#!/usr/bin/env python3
"""
Facebook Auto Publisher - Optimized with CTA
Pubblica annunci auto con CTA visibile e informazioni strategiche
"""
import os
import sys
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

import mysql.connector
from mysql.connector import Error as MySQLError
from mysql.connector.pooling import MySQLConnectionPool
import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('fb_publisher.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ========================================
# CONFIGURAZIONE
# ========================================
@dataclass
class Config:
    """Configurazione dell'applicazione"""
    # Database
    DB_HOST: str = os.getenv("DB_HOST", "")
    DB_PORT: int = int(os.getenv("DB_PORT", "19352"))
    DB_NAME: str = os.getenv("DB_NAME", "")
    DB_USER: str = os.getenv("DB_USER", "")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
    
    # Facebook
    FACEBOOK_PAGE_ID: str = os.getenv("FB_PAGE_ID", "")
    FACEBOOK_ACCESS_TOKEN: str = os.getenv("FB_ACCESS_TOKEN", "")
    GRAPH_API_VERSION: str = "v18.0"
    
    # CTA Configuration
    # Opzioni: "MESSAGE_PAGE" (Messenger) o "LEARN_MORE" (link sito)
    CTA_TYPE: str = os.getenv("CTA_TYPE", "MESSAGE_PAGE")
    CTA_LINK: str = os.getenv("CTA_LINK", "https://www.mc-auto.it")
    
    # WhatsApp fallback (per inserire nel testo)
    WHATSAPP_NUMBER: str = os.getenv("WHATSAPP_NUMBER", "393407346239")
    
    # Limiti
    MAX_POSTS_PER_RUN: int = int(os.getenv("MAX_POSTS", "1"))
    MAX_IMAGES_PER_POST: int = 10
    REQUEST_TIMEOUT: int = 30
    
    @property
    def graph_api_base(self) -> str:
        return f"https://graph.facebook.com/{self.GRAPH_API_VERSION}"
    
    @property
    def whatsapp_link(self) -> str:
        return f"https://wa.me/{self.WHATSAPP_NUMBER}"
    
    def validate(self) -> Tuple[bool, List[str]]:
        """Valida la configurazione"""
        errors = []
        if not self.DB_HOST:
            errors.append("DB_HOST mancante")
        if not self.DB_NAME:
            errors.append("DB_NAME mancante")
        if not self.DB_USER:
            errors.append("DB_USER mancante")
        if not self.DB_PASSWORD:
            errors.append("DB_PASSWORD mancante")
        if not self.FACEBOOK_PAGE_ID:
            errors.append("FB_PAGE_ID mancante")
        if not self.FACEBOOK_ACCESS_TOKEN:
            errors.append("FB_ACCESS_TOKEN mancante")
        
        # Valida CTA_TYPE
        valid_cta_types = ["MESSAGE_PAGE", "LEARN_MORE", "SHOP_NOW", "CONTACT_US", "SIGN_UP"]
        if self.CTA_TYPE not in valid_cta_types:
            errors.append(f"CTA_TYPE non valido. Usa uno di: {', '.join(valid_cta_types)}")
        
        return len(errors) == 0, errors

# ========================================
# DATABASE MANAGER
# ========================================
class DatabaseManager:
    """Gestisce le connessioni e le query al database"""
    
    def __init__(self, config: Config):
        self.config = config
        self.pool = None
        self._init_connection_pool()
    
    def _init_connection_pool(self):
        """Inizializza il connection pool"""
        try:
            self.pool = MySQLConnectionPool(
                pool_name="fb_publisher_pool",
                pool_size=3,
                host=self.config.DB_HOST,
                port=self.config.DB_PORT,
                database=self.config.DB_NAME,
                user=self.config.DB_USER,
                password=self.config.DB_PASSWORD,
                charset='utf8mb4',
                collation='utf8mb4_unicode_ci'
            )
            logger.info("✅ Connection pool creato con successo")
        except MySQLError as e:
            logger.error(f"❌ Errore creazione connection pool: {e}")
            raise
    
    def get_connection(self):
        """Ottiene una connessione dal pool"""
        try:
            return self.pool.get_connection()
        except MySQLError as e:
            logger.error(f"❌ Errore ottenimento connessione: {e}")
            raise
    
    def load_autos_to_publish(self, max_posts: int) -> List[Dict]:
        """Carica le auto non ancora pubblicate"""
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor(dictionary=True)
            
            query = """
                SELECT 
                    v.auto_id, 
                    a.marca, 
                    a.modello, 
                    a.targa,
                    a.anno_immatricolazione, 
                    a.chilometraggio,
                    a.carburante, 
                    a.cambio, 
                    a.colore,
                    a.potenza_kw,
                    a.cilindrata_cc,
                    v.descrizione, 
                    v.prezzo_vendita,
                    v.immagine_principale
                FROM auto_vetrina v
                JOIN auto a ON v.auto_id = a.id
                WHERE v.pubblicata_fb = 0 
                    AND a.stato = 'Disponibile'
                ORDER BY v.data_pubblicazione ASC
                LIMIT %s
            """
            cursor.execute(query, (max_posts,))
            autos = cursor.fetchall()
            cursor.close()
            logger.info(f"📊 Caricate {len(autos)} auto da pubblicare")
            return autos
            
        except MySQLError as e:
            logger.error(f"❌ Errore caricamento auto: {e}")
            raise
        finally:
            if conn and conn.is_connected():
                conn.close()
    
    def update_publication_status(self, auto_id: int, fb_post_id: Optional[str] = None) -> bool:
        """Aggiorna lo stato di pubblicazione dell'auto"""
        query = """
            UPDATE auto_vetrina 
            SET pubblicata_fb = 1, 
                data_modifica = NOW()
            WHERE auto_id = %s
        """
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(query, (auto_id,))
            conn.commit()
            cursor.close()
            logger.info(f"✅ Stato pubblicazione aggiornato per auto_id={auto_id}")
            return True
        except MySQLError as e:
            logger.error(f"❌ Errore aggiornamento stato: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn and conn.is_connected():
                conn.close()

# ========================================
# FACEBOOK PUBLISHER
# ========================================
class FacebookPublisher:
    """Gestisce la pubblicazione su Facebook"""
    
    def __init__(self, config: Config):
        self.config = config
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict:
        """Esegue una richiesta HTTP con gestione errori"""
        try:
            kwargs.setdefault('timeout', self.config.REQUEST_TIMEOUT)
            response = requests.request(method, endpoint, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Errore richiesta HTTP: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            raise
    
    def publish_with_cta(self, message: str, image_urls: Optional[List[str]] = None) -> Dict:
        """
        Pubblica post con immagini e CTA button
        
        STRATEGIA CORRETTA per CTA + Immagini:
        1. Se c'è UN'immagine: usa link post con picture (mostra immagine + CTA)
        2. Se ci sono PIÙ immagini: pubblica carousel senza CTA (Facebook non supporta CTA su carousel)
        3. Se non ci sono immagini: post testuale con CTA
        
        IMPORTANTE: Facebook mostra CTA solo su link posts, non su photo posts con attached_media
        """
        import json
        
        endpoint = f"{self.config.graph_api_base}/{self.config.FACEBOOK_PAGE_ID}/feed"
        
        # CASO 1: Una singola immagine - usa link post con picture
        if image_urls and len(image_urls) == 1:
            logger.info("  📸 Pubblicazione con immagine singola + CTA")
            
            payload = {
                "message": message,
                "link": self.config.CTA_LINK,  # Link è obbligatorio per CTA
                "picture": image_urls[0],      # Immagine come preview del link
                "access_token": self.config.FACEBOOK_ACCESS_TOKEN
            }
            
            # Aggiungi CTA button
            cta_config = {
                "type": self.config.CTA_TYPE,
                "value": {
                    "link": self.config.CTA_LINK
                }
            }
            payload["call_to_action"] = json.dumps(cta_config)
            
            logger.info(f"  🔘 CTA: {self.config.CTA_TYPE} → {self.config.CTA_LINK}")
            logger.info("  📤 Pubblicazione link post con immagine e CTA...")
            
            result = self._make_request('POST', endpoint, data=payload)
            return result
        
        # CASO 2: Più immagini - carousel SENZA CTA (Facebook non supporta CTA su carousel)
        elif image_urls and len(image_urls) > 1:
            logger.info(f"  📸 Pubblicazione carousel con {len(image_urls)} immagini (no CTA)")
            logger.warning("  ⚠️ Facebook non supporta CTA su carousel - pubblico solo immagini")
            
            # Upload immagini come unpublished
            media_ids = []
            for idx, url in enumerate(image_urls[:self.config.MAX_IMAGES_PER_POST], 1):
                logger.info(f"    📷 Upload immagine {idx}/{len(image_urls)}")
                photo_endpoint = f"{self.config.graph_api_base}/{self.config.FACEBOOK_PAGE_ID}/photos"
                photo_payload = {
                    "url": url,
                    "published": "false",
                    "access_token": self.config.FACEBOOK_ACCESS_TOKEN
                }
                result = self._make_request('POST', photo_endpoint, data=photo_payload)
                media_ids.append({"media_fbid": result["id"]})
            
            # Pubblica carousel
            payload = {
                "message": message,
                "attached_media": json.dumps(media_ids),
                "access_token": self.config.FACEBOOK_ACCESS_TOKEN
            }
            
            logger.info("  📤 Pubblicazione carousel...")
            result = self._make_request('POST', endpoint, data=payload)
            return result
        
        # CASO 3: Nessuna immagine - solo testo con CTA
        else:
            logger.info("  📝 Pubblicazione solo testo con CTA")
            
            payload = {
                "message": message,
                "link": self.config.CTA_LINK,
                "access_token": self.config.FACEBOOK_ACCESS_TOKEN
            }
            
            # Aggiungi CTA button
            cta_config = {
                "type": self.config.CTA_TYPE,
                "value": {
                    "link": self.config.CTA_LINK
                }
            }
            payload["call_to_action"] = json.dumps(cta_config)
            
            logger.info(f"  🔘 CTA: {self.config.CTA_TYPE} → {self.config.CTA_LINK}")
            logger.info("  📤 Pubblicazione post testuale con CTA...")
            
            result = self._make_request('POST', endpoint, data=payload)
            return result

# ========================================
# POST GENERATOR
# ========================================
class PostGenerator:
    """Genera il contenuto testuale dei post"""
    
    def __init__(self, config: Config):
        self.config = config
    
    def generate_optimized_text(self, auto: Dict) -> str:
        """
        Genera testo BREVE e STRATEGICO per Facebook
        
        STRATEGIA FACEBOOK:
        - Testo breve (massimo 2-3 righe iniziali visibili)
        - Prezzo e info chiave ALL'INIZIO (prima del "...Altro")
        - Resto nascosto ma disponibile
        - CTA button fa il lavoro pesante
        
        FORMATO:
        [EMOJI] Marca Modello Anno | Prezzo € | Km
        [Caratteristiche chiave in 1-2 righe]
        """
        parts = []
        
        # RIGA 1: Titolo compatto con PREZZO e KM
        # Questo DEVE essere visibile prima del "...Altro"
        prezzo = float(auto['prezzo_vendita'])
        prezzo_str = f"{prezzo:,.0f}".replace(',', '.')
        
        km = auto.get('chilometraggio', 0)
        km_str = f"{km:,}".replace(',', '.') if km else "N/D"
        
        anno = auto.get('anno_immatricolazione', '')
        anno_str = f"({anno})" if anno else ""
        
        # Linea 1: TUTTO ciò che è ESSENZIALE
        line1 = f"🚗 {auto['marca']} {auto['modello']} {anno_str}"
        parts.append(line1)
        
        # Linea 2: PREZZO e KM - MOLTO VISIBILI
        line2 = f"💰 {prezzo_str} € | 📏 {km_str} km"
        parts.append(line2)
        parts.append("")
        
        # RIGA 3-4: Caratteristiche chiave COMPATTE
        specs_line = []
        
        if auto.get('carburante'):
            specs_line.append(f"⛽ {auto['carburante']}")
        
        if auto.get('cambio'):
            specs_line.append(f"⚙️ {auto['cambio']}")
        
        if auto.get('potenza_kw'):
            kw = auto['potenza_kw']
            cv = int(kw * 1.36)
            specs_line.append(f"⚡ {cv} CV")
        
        if specs_line:
            parts.append(" • ".join(specs_line))
        
        # DESCRIZIONE (opzionale, andrà sotto "...Altro")
        if auto.get('descrizione') and auto['descrizione'].strip():
            desc = auto['descrizione'].strip()
            if len(desc) > 150:
                desc = desc[:150] + "..."
            parts.append("")
            parts.append(desc)
        
        # CALL TO ACTION testuale (opzionale, per chi espande)
        parts.append("")
        parts.append("✅ Auto verificata e pronta alla consegna")
        
        # WhatsApp come alternativa (sotto "Altro")
        whatsapp_text = f"Info su {auto['marca']} {auto['modello']}"
        whatsapp_link = f"{self.config.whatsapp_link}?text={requests.utils.quote(whatsapp_text)}"
        parts.append("")
        parts.append(f"📱 WhatsApp: {whatsapp_link}")
        
        return "\n".join(parts)

# ========================================
# ORCHESTRATORE PRINCIPALE
# ========================================
class AutoPublisher:
    """Orchestratore principale dell'applicazione"""
    
    def __init__(self, config: Config):
        self.config = config
        self.db = DatabaseManager(config)
        self.fb = FacebookPublisher(config)
        self.post_gen = PostGenerator(config)
    
    def run(self) -> int:
        """Esegue il processo di pubblicazione"""
        logger.info("🚀 Avvio Facebook Auto Publisher (CTA Optimized)")
        logger.info(f"🔘 CTA Type: {self.config.CTA_TYPE}")
        logger.info(f"🔗 CTA Link: {self.config.CTA_LINK}")
        
        # Carica auto da pubblicare
        autos = self.db.load_autos_to_publish(self.config.MAX_POSTS_PER_RUN)
        
        if not autos:
            logger.info("ℹ️ Nessuna auto da pubblicare")
            return 0
        
        published_count = 0
        
        for idx, auto in enumerate(autos, 1):
            logger.info(f"\n{'='*60}")
            logger.info(f"📌 [{idx}/{len(autos)}] Pubblicazione: {auto['marca']} {auto['modello']}")
            logger.info(f"{'='*60}")
            
            try:
                # Genera testo ottimizzato per Facebook
                post_text = self.post_gen.generate_optimized_text(auto)
                
                # Prepara immagine
                image_url = auto.get('immagine_principale')
                images = [image_url] if image_url and image_url.strip() else None
                
                logger.info(f"📝 Lunghezza testo: {len(post_text)} caratteri")
                logger.info(f"🖼️ Immagini: {len(images) if images else 0}")
                logger.info(f"\n👁️ Preview (prime 3 righe visibili):")
                preview_lines = post_text.split('\n')[:3]
                logger.info('\n'.join(preview_lines))
                logger.info(f"[...Altro]\n")
                
                # Pubblica su Facebook con CTA
                result = self.fb.publish_with_cta(
                    message=post_text,
                    image_urls=images
                )
                
                post_id = result.get('id', result.get('post_id', 'N/A'))
                logger.info(f"✅ Post pubblicato con CTA! ID: {post_id}")
                
                # Aggiorna database
                if self.db.update_publication_status(auto['auto_id'], post_id):
                    published_count += 1
                
            except Exception as e:
                logger.error(f"❌ Errore pubblicazione: {e}")
                logger.exception(e)
                continue
        
        logger.info(f"\n{'='*60}")
        logger.info(f"🎉 Completato: {published_count}/{len(autos)} post pubblicati")
        logger.info(f"{'='*60}\n")
        
        return published_count

# ========================================
# MAIN
# ========================================
def main() -> int:
    """Funzione principale"""
    try:
        config = Config()
        is_valid, errors = config.validate()
        
        if not is_valid:
            logger.error("❌ Errori di configurazione:")
            for error in errors:
                logger.error(f"  - {error}")
            return 1
        
        publisher = AutoPublisher(config)
        published_count = publisher.run()
        
        return 0 if published_count > 0 else 1
        
    except KeyboardInterrupt:
        logger.info("\n⚠️ Processo interrotto")
        return 130
    except Exception as e:
        logger.error(f"❌ Errore fatale: {e}")
        logger.exception(e)
        return 1

if __name__ == "__main__":
    sys.exit(main())
