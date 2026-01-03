#!/usr/bin/env python3
"""
Facebook Auto Publisher - Multi Images from Separate Table
Pubblica automaticamente annunci di auto da MySQL su pagina Facebook
Carica immagini dalla tabella auto_vetrina_immagini
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
    
    # Link Messenger (mostrato sotto le immagini)
    MESSENGER_LINK: str = os.getenv("MESSENGER_LINK", "https://m.me/875722978961810")
    
    # WhatsApp fallback
    WHATSAPP_NUMBER: str = os.getenv("WHATSAPP_NUMBER", "393407346239")
    
    # Limiti
    MAX_POSTS_PER_RUN: int = int(os.getenv("MAX_POSTS", "1"))
    MAX_IMAGES_PER_POST: int = 4  # Fino a 4 immagini
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
        if not self.MESSENGER_LINK:
            errors.append("MESSENGER_LINK mancante")
        
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
    
    def load_auto_images(self, auto_id: int, max_images: int = 4) -> List[str]:
        """
        Carica le immagini di un'auto dalla tabella auto_vetrina_immagini
        Ordinate per campo 'ordine' ASC
        """
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor(dictionary=True)
            
            query = """
                SELECT url_immagine
                FROM auto_vetrina_immagini
                WHERE auto_id = %s
                ORDER BY ordine ASC
                LIMIT %s
            """
            cursor.execute(query, (auto_id, max_images))
            results = cursor.fetchall()
            cursor.close()
            
            # Estrai solo gli URL
            images = [row['url_immagine'] for row in results if row['url_immagine']]
            
            return images
            
        except MySQLError as e:
            logger.error(f"❌ Errore caricamento immagini per auto_id={auto_id}: {e}")
            return []
        finally:
            if conn and conn.is_connected():
                conn.close()
    
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
                    v.prezzo_vendita
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
            
            # Per ogni auto, carica le sue immagini
            for auto in autos:
                images = self.load_auto_images(
                    auto['auto_id'], 
                    self.config.MAX_IMAGES_PER_POST
                )
                auto['all_images'] = images
                logger.info(f"  📸 {auto['marca']} {auto['modello']}: {len(images)} immagini trovate")
            
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
    
    def _verify_image_url(self, url: str) -> bool:
        """Verifica che l'immagine sia accessibile pubblicamente"""
        try:
            logger.info(f"      🔍 Test accessibilità...")
            response = requests.head(url, timeout=10, allow_redirects=True)
            
            if response.status_code == 200:
                content_type = response.headers.get('content-type', '')
                if 'image' in content_type.lower():
                    logger.info(f"      ✅ Accessibile ({content_type})")
                    return True
                else:
                    logger.warning(f"      ⚠️  Non è un'immagine: {content_type}")
                    return False
            else:
                logger.warning(f"      ⚠️  HTTP {response.status_code}")
                return False
                
        except Exception as e:
            logger.warning(f"      ⚠️  Test fallito: {e}")
            return True
    
    def publish_with_link(self, message: str, image_urls: Optional[List[str]] = None) -> Dict:
        """
        Pubblica post con immagini multiple e link Messenger
        
        STRATEGIA:
        1. Carica fino a 4 immagini come unpublished
        2. Crea post con carousel + link Messenger
        3. Facebook mostrerà: Immagini + Link cliccabile sotto
        """
        import json
        
        endpoint = f"{self.config.graph_api_base}/{self.config.FACEBOOK_PAGE_ID}/feed"
        
        if image_urls and len(image_urls) >= 1:
            # Limita a MAX_IMAGES_PER_POST
            images_to_upload = image_urls[:self.config.MAX_IMAGES_PER_POST]
            logger.info(f"  📸 Upload di {len(images_to_upload)} immagine/i...")
            
            # Step 1: Upload immagini come unpublished photos
            media_ids = []
            for idx, url in enumerate(images_to_upload, 1):
                try:
                    logger.info(f"    📷 [{idx}/{len(images_to_upload)}] Processing...")
                    logger.info(f"       URL: {url[:80]}...")
                    
                    if not url or not url.startswith(('http://', 'https://')):
                        logger.warning(f"       ⚠️  URL non valido, skip")
                        continue
                    
                    # Test accessibilità
                    self._verify_image_url(url)
                    
                    # Upload a Facebook
                    logger.info(f"       📤 Upload a Facebook...")
                    photo_endpoint = f"{self.config.graph_api_base}/{self.config.FACEBOOK_PAGE_ID}/photos"
                    photo_payload = {
                        "url": url,
                        "published": "false",
                        "access_token": self.config.FACEBOOK_ACCESS_TOKEN
                    }
                    
                    try:
                        result = self._make_request('POST', photo_endpoint, data=photo_payload)
                        media_id = result.get("id")
                        
                        if media_id:
                            media_ids.append({"media_fbid": media_id})
                            logger.info(f"       ✅ Upload OK - Media ID: {media_id}")
                        else:
                            logger.warning(f"       ⚠️  Nessun ID ricevuto")
                    
                    except Exception as upload_error:
                        # Fallback: Download + Upload come file
                        logger.warning(f"       ⚠️  Upload URL fallito: {upload_error}")
                        logger.info(f"       🔄 Tentativo download + upload file...")
                        
                        try:
                            img_response = requests.get(url, timeout=30)
                            img_response.raise_for_status()
                            
                            files = {
                                'source': ('image.jpg', img_response.content, 'image/jpeg')
                            }
                            data = {
                                'published': 'false',
                                'access_token': self.config.FACEBOOK_ACCESS_TOKEN
                            }
                            
                            response = requests.post(photo_endpoint, files=files, data=data, timeout=30)
                            response.raise_for_status()
                            result = response.json()
                            
                            media_id = result.get("id")
                            if media_id:
                                media_ids.append({"media_fbid": media_id})
                                logger.info(f"       ✅ Upload file OK - Media ID: {media_id}")
                            else:
                                logger.error(f"       ❌ Upload file fallito: nessun ID")
                        
                        except Exception as file_error:
                            logger.error(f"       ❌ Anche upload file fallito: {file_error}")
                            continue
                
                except Exception as e:
                    logger.error(f"       ❌ Errore: {str(e)[:200]}")
                    continue
            
            if not media_ids:
                logger.error("  ❌ Nessuna immagine caricata con successo!")
                raise Exception("Impossibile caricare le immagini")
            
            logger.info(f"  ✅ {len(media_ids)} immagini caricate correttamente")
            
            # Step 2: Crea post con immagini (link NEL TESTO, non come parametro)
            # IMPORTANTE: Non usiamo "link" parameter perché Facebook darebbe priorità
            # al link preview e ignorerebbe le immagini. Invece, includiamo il link
            # nel testo del messaggio, che Facebook renderà automaticamente cliccabile.
            payload = {
                "message": message,
                "attached_media": json.dumps(media_ids),
                "access_token": self.config.FACEBOOK_ACCESS_TOKEN
            }
            
            logger.info("  📤 Pubblicazione post con carousel...")
            logger.info("  💡 Link Messenger incluso nel testo (auto-cliccabile)")
            
            result = self._make_request('POST', endpoint, data=payload)
            return result
        
        # Nessuna immagine - post testuale
        else:
            logger.info("  📝 Pubblicazione post testuale")
            logger.info("  💡 Link Messenger incluso nel testo (auto-cliccabile)")
            
            payload = {
                "message": message,
                "access_token": self.config.FACEBOOK_ACCESS_TOKEN
            }
            
            logger.info("  📤 Pubblicazione...")
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
        Genera testo ottimizzato per Facebook
        Il link Messenger nel testo diventa automaticamente cliccabile
        """
        parts = []
        
        # RIGA 1: Titolo
        prezzo = float(auto['prezzo_vendita'])
        prezzo_str = f"{prezzo:,.0f}".replace(',', '.')
        
        km = auto.get('chilometraggio', 0)
        km_str = f"{km:,}".replace(',', '.') if km else "N/D"
        
        anno = auto.get('anno_immatricolazione', '')
        anno_str = f"({anno})" if anno else ""
        
        parts.append(f"🚗 {auto['marca']} {auto['modello']} {anno_str}")
        parts.append(f"💰 {prezzo_str} € | 📏 {km_str} km")
        parts.append("")
        
        # Caratteristiche
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
        
        # Descrizione
        if auto.get('descrizione') and auto['descrizione'].strip():
            desc = auto['descrizione'].strip()
            if len(desc) > 150:
                desc = desc[:150] + "..."
            parts.append("")
            parts.append(desc)
        
        # Call to action PROMINENTE con link
        parts.append("")
        parts.append("✅ Auto verificata e pronta alla consegna")
        parts.append("")
        parts.append("💬 CONTATTACI SU MESSENGER:")
        parts.append(f"👉 {self.config.MESSENGER_LINK}")
        
        # WhatsApp alternativo
        whatsapp_text = f"Info su {auto['marca']} {auto['modello']}"
        whatsapp_link = f"{self.config.whatsapp_link}?text={requests.utils.quote(whatsapp_text)}"
        parts.append("")
        parts.append(f"📱 Oppure su WhatsApp:")
        parts.append(f"👉 {whatsapp_link}")
        
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
        logger.info("🚀 Avvio Facebook Auto Publisher (Multi Images)")
        logger.info(f"💬 Link Messenger (nel testo): {self.config.MESSENGER_LINK}")
        logger.info(f"🖼️  Max immagini per post: {self.config.MAX_IMAGES_PER_POST}")
        logger.info("💡 I link nel testo diventano automaticamente cliccabili su Facebook")
        
        # Carica auto da pubblicare
        autos = self.db.load_autos_to_publish(self.config.MAX_POSTS_PER_RUN)
        
        if not autos:
            logger.info("ℹ️  Nessuna auto da pubblicare")
            return 0
        
        published_count = 0
        
        for idx, auto in enumerate(autos, 1):
            logger.info(f"\n{'='*60}")
            logger.info(f"📌 [{idx}/{len(autos)}] Pubblicazione: {auto['marca']} {auto['modello']}")
            logger.info(f"{'='*60}")
            
            try:
                # Genera testo
                post_text = self.post_gen.generate_optimized_text(auto)
                
                # Prepara immagini (dalla tabella auto_vetrina_immagini)
                images = auto.get('all_images', [])
                
                logger.info(f"📝 Lunghezza testo: {len(post_text)} caratteri")
                logger.info(f"🖼️  Immagini da pubblicare: {len(images)}")
                
                if images:
                    for i, img_url in enumerate(images, 1):
                        logger.info(f"  📸 Immagine {i}: {img_url[:80]}...")
                else:
                    logger.warning("  ⚠️  Nessuna immagine trovata per questa auto!")
                
                logger.info(f"\n👁️  Preview (prime 3 righe):")
                preview_lines = post_text.split('\n')[:3]
                logger.info('\n'.join(preview_lines))
                logger.info(f"[...]\n")
                
                # Pubblica su Facebook
                result = self.fb.publish_with_link(
                    message=post_text,
                    image_urls=images if images else None
                )
                
                post_id = result.get('id', result.get('post_id', 'N/A'))
                logger.info(f"✅ Post pubblicato! ID: {post_id}")
                logger.info(f"   📸 {len(images)} immagini | 💬 Link cliccabile nel testo")
                
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
        logger.info("\n⚠️  Processo interrotto")
        return 130
    except Exception as e:
        logger.error(f"❌ Errore fatale: {e}")
        logger.exception(e)
        return 1

if __name__ == "__main__":
    sys.exit(main())
