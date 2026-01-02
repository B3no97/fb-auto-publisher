#!/usr/bin/env python3
"""
Facebook Auto Publisher
Pubblica automaticamente annunci di auto da MySQL su pagina Facebook
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

# Carica variabili d'ambiente
load_dotenv()

# ========================================
# CONFIGURAZIONE LOGGING
# ========================================
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
    
    # Limiti
    MAX_POSTS_PER_RUN: int = int(os.getenv("MAX_POSTS", "1"))
    MAX_IMAGES_PER_POST: int = 10
    REQUEST_TIMEOUT: int = 30
    
    @property
    def graph_api_base(self) -> str:
        return f"https://graph.facebook.com/{self.GRAPH_API_VERSION}"
    
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
            
            # 1. Verifica totale auto in vetrina
            cursor.execute("SELECT COUNT(*) as total FROM auto_vetrina")
            total_vetrina = cursor.fetchone()['total']
            logger.info(f"🔍 Totale auto in vetrina: {total_vetrina}")
            
            # 2. Verifica auto NON pubblicate
            cursor.execute("SELECT COUNT(*) as total FROM auto_vetrina WHERE pubblicata_fb = 0")
            non_pubblicate = cursor.fetchone()['total']
            logger.info(f"🔍 Auto NON pubblicate (pubblicata_fb=0): {non_pubblicate}")
            
            # 3. Verifica totale auto disponibili
            cursor.execute("SELECT COUNT(*) as total FROM auto WHERE stato = 'Disponibile'")
            disponibili = cursor.fetchone()['total']
            logger.info(f"🔍 Auto con stato 'Disponibile': {disponibili}")
            
            # 4. Verifica join completo
            cursor.execute("""
                SELECT COUNT(*) as total 
                FROM auto_vetrina v
                JOIN auto a ON v.auto_id = a.id
                WHERE v.pubblicata_fb = 0 AND a.stato = 'Disponibile'
            """)
            match_query = cursor.fetchone()['total']
            logger.info(f"🔍 Auto che matchano i criteri (pubblicata_fb=0 + Disponibile): {match_query}")
            
            # 5. Se ci sono auto, mostra dettagli
            if non_pubblicate > 0:
                cursor.execute("""
                    SELECT v.auto_id, a.marca, a.modello, a.stato, v.pubblicata_fb
                    FROM auto_vetrina v
                    JOIN auto a ON v.auto_id = a.id
                    WHERE v.pubblicata_fb = 0
                    LIMIT 5
                """)
                sample = cursor.fetchall()
                logger.info(f"📋 Esempio auto non pubblicate:")
                for s in sample:
                    logger.info(f"   - ID:{s['auto_id']} {s['marca']} {s['modello']} | Stato:{s['stato']} | pubblicata_fb:{s['pubblicata_fb']}")
            
            # 6. Query principale
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
            
            # Carica le immagini aggiuntive per ogni auto
            for auto in autos:
                cursor.execute("""
                    SELECT url_immagine
                    FROM auto_vetrina_immagini
                    WHERE auto_id = %s
                    ORDER BY ordine ASC
                """, (auto['auto_id'],))
                imgs = cursor.fetchall()
                auto['immagini_aggiuntive'] = [i['url_immagine'] for i in imgs] if imgs else []
            
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
    
    def publish_post(self, text: str, image_urls: Optional[List[str]] = None, link: Optional[str] = None) -> Dict:
        """
        Pubblica un post su Facebook con CTA button
        
        Args:
            text: Testo del post
            image_urls: Lista di URL delle immagini (opzionale)
            link: URL del link da allegare (opzionale)
            
        Returns:
            Dizionario con la risposta di Facebook
        """
        if not image_urls or len(image_urls) == 0:
            return self._publish_text_with_link(text, link)
        elif len(image_urls) == 1:
            return self._publish_single_image(text, image_urls[0], link)
        else:
            return self._publish_carousel(text, image_urls[:self.config.MAX_IMAGES_PER_POST], link)
    
    def _publish_text_with_link(self, text: str, link: Optional[str] = None) -> Dict:
        """Pubblica testo con link"""
        endpoint = f"{self.config.graph_api_base}/{self.config.FACEBOOK_PAGE_ID}/feed"
        payload = {
            "message": text,
            "access_token": self.config.FACEBOOK_ACCESS_TOKEN
        }
        if link:
            payload["link"] = link
        return self._make_request('POST', endpoint, data=payload)
    
    def _publish_single_image(self, text: str, image_url: str, link: Optional[str] = None) -> Dict:
        """Pubblica un post con singola immagine e link"""
        endpoint = f"{self.config.graph_api_base}/{self.config.FACEBOOK_PAGE_ID}/photos"
        payload = {
            "url": image_url,
            "caption": text,
            "access_token": self.config.FACEBOOK_ACCESS_TOKEN
        }
        # Nota: con single photo non si può aggiungere link diretto
        # Il link va nel testo del caption
        return self._make_request('POST', endpoint, data=payload)
    
    def _publish_carousel(self, text: str, image_urls: List[str], link: Optional[str] = None) -> Dict:
        """Pubblica un post con carousel di immagini"""
        import json
        
        # Upload delle immagini non pubblicate
        media_ids = []
        for idx, url in enumerate(image_urls, 1):
            logger.info(f"  📸 Upload immagine {idx}/{len(image_urls)}")
            endpoint = f"{self.config.graph_api_base}/{self.config.FACEBOOK_PAGE_ID}/photos"
            payload = {
                "url": url,
                "published": "false",
                "access_token": self.config.FACEBOOK_ACCESS_TOKEN
            }
            result = self._make_request('POST', endpoint, data=payload)
            media_ids.append({"media_fbid": result["id"]})
        
        # Pubblica il post con le immagini
        endpoint = f"{self.config.graph_api_base}/{self.config.FACEBOOK_PAGE_ID}/feed"
        payload = {
            "message": text,
            "attached_media": json.dumps(media_ids),
            "access_token": self.config.FACEBOOK_ACCESS_TOKEN
        }
        # Nota: con carousel + immagini non si può aggiungere link
        # Il link va nel testo del messaggio
        return self._make_request('POST', endpoint, data=payload)

# ========================================
# POST GENERATOR - ULTRA COMPACT
# ========================================
class PostGenerator:
    """Genera il contenuto testuale dei post in formato ultra-compatto"""
    
    # Configurazione aziendale (PERSONALIZZA QUESTI VALORI)
    COMPANY_PHONE = "+39 123 456 7890"
    COMPANY_WHATSAPP = "391234567890"  # Senza + o spazi
    COMPANY_WEBSITE = "https://www.tuazienda.it"
    COMPANY_NAME = "Auto Srl"
    
    @staticmethod
    def generate_text(auto: Dict) -> str:
        """
        Genera testo ULTRA-COMPATTO - Solo info essenziali
        Massimo 80-90 caratteri per restare visibile sopra le immagini
        
        STRATEGIA:
        - Riga 1: Marca Modello Anno (max 40 char)
        - Riga 2: KM | Carburante | Prezzo (max 50 char)
        
        Args:
            auto: Dizionario con i dati dell'auto
            
        Returns:
            Testo formattato ultra-compatto
        """
        # Formatta i dati essenziali
        marca = auto['marca']
        modello = auto['modello']
        anno = auto.get('anno_immatricolazione', '')
        
        km = auto.get('chilometraggio', 0)
        # Formato ultra-compatto: 14525 -> 14.5k
        if km >= 1000:
            km_str = f"{km/1000:.0f}k"
        else:
            km_str = str(km)
        
        carburante = auto.get('carburante', '').upper()
        # Abbrevia carburante: Diesel->D, Benzina->B, GPL->G, Metano->M
        carb_map = {'DIESEL': 'D', 'BENZINA': 'B', 'GPL': 'G', 'METANO': 'M', 'IBRIDO': 'HYB', 'ELETTRICO': 'EV'}
        carb_short = carb_map.get(carburante, carburante[:3]) if carburante else ''
        
        prezzo = float(auto['prezzo_vendita'])
        # Formato compatto: 9000 -> 9k, 14500 -> 14.5k
        if prezzo >= 1000:
            prezzo_str = f"{prezzo/1000:.1f}k".replace('.0k', 'k')
        else:
            prezzo_str = f"{prezzo:.0f}"
        
        # COSTRUZIONE TESTO ULTRA-COMPATTO
        # Riga 1: 🚗 VW Golf 2000
        line1 = f"🚗 {marca} {modello}"
        if anno:
            line1 += f" {anno}"
        
        # Riga 2: 14k km • GPL • € 9k
        parts = []
        parts.append(f"{km_str} km")
        if carb_short:
            parts.append(carb_short)
        parts.append(f"€ {prezzo_str}")
        line2 = " • ".join(parts)
        
        # Assemblaggio finale (target: 80-90 caratteri totali)
        text = f"{line1}\n{line2}"
        
        return text
    
    @staticmethod
    def generate_whatsapp_link(auto: Dict) -> str:
        """Genera link WhatsApp con messaggio pre-compilato"""
        marca = auto['marca']
        modello = auto['modello']
        anno = auto.get('anno_immatricolazione', '')
        
        # Messaggio pre-compilato
        message = f"Ciao! Sono interessato alla {marca} {modello}"
        if anno:
            message += f" {anno}"
        message += ". Potete darmi maggiori informazioni?"
        
        # Encode per URL
        import urllib.parse
        message_encoded = urllib.parse.quote(message)
        
        return f"https://wa.me/{PostGenerator.COMPANY_WHATSAPP}?text={message_encoded}"
    
    @staticmethod
    def generate_website_link(auto: Dict) -> str:
        """
        Genera link al sito web (se hai pagina dedicata per l'auto)
        Altrimenti usa homepage
        """
        # OPZIONE 1: Link diretto all'auto (se il tuo sito supporta URL specifici)
        # auto_id = auto['auto_id']
        # return f"{PostGenerator.COMPANY_WEBSITE}/auto/{auto_id}"
        
        # OPZIONE 2: Homepage con parametro di tracking
        auto_id = auto['auto_id']
        return f"{PostGenerator.COMPANY_WEBSITE}?utm_source=facebook&utm_medium=post&utm_campaign=auto_{auto_id}"

# ========================================
# ORCHESTRATORE PRINCIPALE
# ========================================
class AutoPublisher:
    """Orchestratore principale dell'applicazione"""
    
    def __init__(self, config: Config):
        self.config = config
        self.db = DatabaseManager(config)
        self.fb = FacebookPublisher(config)
        self.post_gen = PostGenerator()
    
    def run(self) -> int:
        """
        Esegue il processo di pubblicazione
        
        Returns:
            Numero di post pubblicati con successo
        """
        logger.info("🚀 Avvio Facebook Auto Publisher")
        logger.info("📝 Formato: ULTRA-COMPACT + LINK")
        
        # Carica auto da pubblicare
        autos = self.db.load_autos_to_publish(self.config.MAX_POSTS_PER_RUN)
        
        if not autos:
            logger.info("ℹ️ Nessuna auto da pubblicare")
            return 0
        
        published_count = 0
        
        # Pubblica ogni auto
        for idx, auto in enumerate(autos, 1):
            logger.info(f"\n{'='*60}")
            logger.info(f"📌 [{idx}/{len(autos)}] Pubblicazione: {auto['marca']} {auto['modello']}")
            logger.info(f"{'='*60}")
            
            try:
                # Genera testo ultra-compatto (solo info essenziali)
                post_text = self.post_gen.generate_text(auto)
                
                # Genera link WhatsApp con messaggio pre-compilato
                wa_link = self.post_gen.generate_whatsapp_link(auto)
                
                # AGGIUNGI call-to-action al testo
                post_text += f"\n\n💬 WhatsApp: {wa_link}"
                
                # Prepara lista immagini
                images = []
                if auto.get('immagine_principale'):
                    images.append(auto['immagine_principale'])
                if auto.get('immagini_aggiuntive'):
                    images.extend(auto['immagini_aggiuntive'])
                
                # Filtra immagini vuote o None
                images = [img for img in images if img and img.strip()]
                
                logger.info(f"📝 Lunghezza testo base: {len(post_text.split(wa_link)[0])} caratteri")
                logger.info(f"📝 Lunghezza testo totale: {len(post_text)} caratteri")
                logger.info(f"🖼️ Numero immagini: {len(images)}")
                logger.info(f"🔗 Link WhatsApp: {wa_link}")
                
                # Mostra preview
                logger.info(f"👁️ Preview completa:\n{post_text}\n")
                
                # Pubblica su Facebook
                # Nota: il link WhatsApp è nel testo, Facebook lo renderà cliccabile automaticamente
                result = self.fb.publish_post(post_text, images if images else None)
                post_id = result.get('id', result.get('post_id', 'N/A'))
                
                logger.info(f"✅ Post pubblicato con successo! ID: {post_id}")
                
                # Aggiorna stato nel database
                if self.db.update_publication_status(auto['auto_id'], post_id):
                    published_count += 1
                
            except Exception as e:
                logger.error(f"❌ Errore durante la pubblicazione: {e}")
                logger.exception(e)
                continue
        
        logger.info(f"\n{'='*60}")
        logger.info(f"🎉 Pubblicazione completata: {published_count}/{len(autos)} post pubblicati")
        logger.info(f"{'='*60}\n")
        
        return published_count

# ========================================
# MAIN
# ========================================
def main() -> int:
    """Funzione principale"""
    try:
        # Carica e valida configurazione
        config = Config()
        is_valid, errors = config.validate()
        
        if not is_valid:
            logger.error("❌ Errori di configurazione:")
            for error in errors:
                logger.error(f"  - {error}")
            return 1
        
        # Esegui pubblicazione
        publisher = AutoPublisher(config)
        published_count = publisher.run()
        
        return 0 if published_count > 0 else 1
        
    except KeyboardInterrupt:
        logger.info("\n⚠️ Processo interrotto dall'utente")
        return 130
    except Exception as e:
        logger.error(f"❌ Errore fatale: {e}")
        logger.exception(e)
        return 1

if __name__ == "__main__":
    sys.exit(main())
