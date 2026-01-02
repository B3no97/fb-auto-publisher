# ========================================
# POST GENERATOR - VERSIONE PROFESSIONALE
# ========================================
class PostGenerator:
    """Genera il contenuto testuale dei post in modo professionale"""
    
    # Configurazione aziendale (da personalizzare)
    COMPANY_PHONE = "+39 123 456 7890"
    COMPANY_WHATSAPP = "391234567890"  # Senza + o spazi
    COMPANY_WEBSITE = "https://www.tuazienda.it"
    COMPANY_NAME = "Auto Srl"
    
    # Hashtag (max 3-5)
    HASHTAGS = ["#AutoUsate", "#Concessionaria", "#ProvaSubito"]
    
    @staticmethod
    def generate_text(auto: Dict) -> str:
        """
        Genera il testo del post per un'auto con struttura professionale
        
        Struttura:
        1. Headline accattivante (Marca + Modello + Anno + Tag)
        2. Descrizione breve personalizzata o punti chiave
        3. Specifiche tecniche con emoji
        4. Prezzo evidenziato
        5. Call to Action cliccabili
        6. Hashtag e branding
        
        Args:
            auto: Dizionario con i dati dell'auto
            
        Returns:
            Testo formattato per il post Facebook
        """
        text_parts = []
        
        # ==========================================
        # 1. HEADLINE - Marca + Modello + Anno + Tag accattivante
        # ==========================================
        anno = auto.get('anno_immatricolazione', '')
        headline = f"🚗 {auto['marca']} {auto['modello']}"
        if anno:
            headline += f" {anno}"
        headline += " – Pronta Consegna!"  # Tag accattivante
        
        text_parts.append(headline)
        text_parts.append("")
        
        # ==========================================
        # 2. DESCRIZIONE BREVE
        # ==========================================
        # Se esiste una descrizione personalizzata nel DB, usala
        if auto.get('descrizione'):
            text_parts.append(auto['descrizione'])
        else:
            # Altrimenti genera una descrizione automatica professionale
            desc_parts = []
            
            # Stato e chilometraggio
            if auto.get('chilometraggio'):
                km = auto['chilometraggio']
                if km < 20000:
                    desc_parts.append("bassissimo chilometraggio")
                elif km < 50000:
                    desc_parts.append("basso chilometraggio")
            
            # Altre caratteristiche
            desc_parts.append("ottime condizioni")
            desc_parts.append("pronta consegna")
            
            desc_text = "Auto con " + ", ".join(desc_parts) + "."
            text_parts.append(desc_text.capitalize())
        
        text_parts.append("")
        
        # ==========================================
        # 3. SPECIFICHE TECNICHE
        # ==========================================
        text_parts.append("📋 Specifiche:")
        
        if auto.get('anno_immatricolazione'):
            text_parts.append(f"📅 Anno: {auto['anno_immatricolazione']}")
        
        if auto.get('chilometraggio'):
            km_formatted = f"{auto['chilometraggio']:,}".replace(',', '.')
            text_parts.append(f"🛣️ Km: {km_formatted}")
        
        if auto.get('carburante'):
            text_parts.append(f"⛽ {auto['carburante']}")
        
        if auto.get('cambio'):
            text_parts.append(f"⚙️ Cambio {auto['cambio']}")
        
        if auto.get('potenza_kw'):
            text_parts.append(f"🔋 Potenza: {auto['potenza_kw']} kW")
        
        if auto.get('cilindrata_cc'):
            text_parts.append(f"🏎️ Cilindrata: {auto['cilindrata_cc']} cc")
        
        if auto.get('colore'):
            text_parts.append(f"🎨 {auto['colore']}")
        
        # ==========================================
        # 4. PREZZO
        # ==========================================
        text_parts.append("")
        prezzo_formatted = f"{float(auto['prezzo_vendita']):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        text_parts.append(f"💰 Prezzo: € {prezzo_formatted}")
        
        # ==========================================
        # 5. CALL TO ACTION (Cliccabili)
        # ==========================================
        text_parts.append("")
        text_parts.append(f"📞 Chiama ora: {PostGenerator.COMPANY_PHONE}")
        
        # WhatsApp link cliccabile
        wa_link = f"https://wa.me/{PostGenerator.COMPANY_WHATSAPP}"
        text_parts.append(f"💬 WhatsApp: {wa_link}")
        
        # Sito web
        text_parts.append(f"🌐 Scopri di più: {PostGenerator.COMPANY_WEBSITE}")
        
        # ==========================================
        # 6. HASHTAG E BRANDING
        # ==========================================
        text_parts.append("")
        
        # Aggiungi hashtag con marca
        marca_hashtag = f"#{auto['marca'].replace(' ', '')}"
        all_hashtags = [marca_hashtag] + PostGenerator.HASHTAGS
        text_parts.append(" ".join(all_hashtags))
        
        # Branding finale (opzionale)
        # text_parts.append("")
        # text_parts.append(f"— {PostGenerator.COMPANY_NAME}")
        
        return "\n".join(text_parts)
    
    @staticmethod
    def generate_text_compact(auto: Dict) -> str:
        """
        Versione compatta del post (per limite caratteri o test A/B)
        
        Args:
            auto: Dizionario con i dati dell'auto
            
        Returns:
            Testo compatto formattato
        """
        anno = auto.get('anno_immatricolazione', '')
        km = auto.get('chilometraggio', 0)
        km_formatted = f"{km:,}".replace(',', '.') if km else "N/D"
        prezzo_formatted = f"{float(auto['prezzo_vendita']):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        
        parts = [
            f"🚗 {auto['marca']} {auto['modello']} {anno}",
            f"🛣️ {km_formatted} km | ⛽ {auto.get('carburante', 'N/D')} | ⚙️ {auto.get('cambio', 'N/D')}",
            f"💰 € {prezzo_formatted}",
            "",
            f"📞 {PostGenerator.COMPANY_PHONE}",
            f"💬 https://wa.me/{PostGenerator.COMPANY_WHATSAPP}",
        ]
        
        return "\n".join(parts)


# ========================================
# ESEMPIO DI OUTPUT
# ========================================
if __name__ == "__main__":
    # Dati di esempio
    auto_esempio = {
        'marca': 'Volkswagen',
        'modello': 'Golf',
        'anno_immatricolazione': 2021,
        'chilometraggio': 45000,
        'carburante': 'Benzina',
        'cambio': 'Manuale',
        'potenza_kw': 110,
        'cilindrata_cc': 1498,
        'colore': 'Nero metallizzato',
        'prezzo_vendita': 18900.00,
        'descrizione': 'Auto in ottime condizioni, manutenzione certificata, unico proprietario.'
    }
    
    generator = PostGenerator()
    
    print("=" * 70)
    print("VERSIONE COMPLETA:")
    print("=" * 70)
    print(generator.generate_text(auto_esempio))
    print("\n")
    
    print("=" * 70)
    print("VERSIONE COMPATTA:")
    print("=" * 70)
    print(generator.generate_text_compact(auto_esempio))
