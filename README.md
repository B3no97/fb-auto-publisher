# ==========================================
# README.md
# ==========================================

# Facebook Auto Publisher

Script Python per pubblicare automaticamente annunci di auto da database MySQL su pagina Facebook.

## Requisiti

- Python 3.8+
- MySQL 8.0+ (Aiven)
- Pagina Facebook con accesso API

## Installazione

1. Clona il repository
2. Installa le dipendenze:
   ```bash
   pip install -r requirements.txt
   ```

3. Copia `.env.example` in `.env` e compila i dati:
   ```bash
   cp .env.example .env
   ```

4. Modifica `.env` con le tue credenziali

## Configurazione Facebook

### Come ottenere il Page Access Token:

1. Vai su [Facebook Developers](https://developers.facebook.com/)
2. Crea un'app (o usa una esistente)
3. Aggiungi il prodotto "Facebook Login for Business"
4. Vai in "Tools" > "Access Token Tool"
5. Genera un token per la tua pagina
6. **IMPORTANTE**: Estendi il token per renderlo permanente:
   ```
   https://graph.facebook.com/v18.0/oauth/access_token?grant_type=fb_exchange_token&client_id=YOUR_APP_ID&client_secret=YOUR_APP_SECRET&fb_exchange_token=YOUR_SHORT_TOKEN
   ```

### Permessi necessari:
- `pages_manage_posts`
- `pages_read_engagement`
- `pages_show_list`

## Uso

### Esecuzione manuale:
```bash
python fb_auto_publisher.py
```

### Schedulazione con cron (Linux/Mac):
```bash
# Modifica crontab
crontab -e

# Pubblica 1 auto ogni giorno alle 10:00
0 10 * * * cd /path/to/script && /usr/bin/python3 fb_auto_publisher.py

# Pubblica 3 auto ogni lunedì, mercoledì e venerdì alle 14:00
0 14 * * 1,3,5 cd /path/to/script && MAX_POSTS=3 /usr/bin/python3 fb_auto_publisher.py
```

### Schedulazione con Task Scheduler (Windows):
1. Apri "Task Scheduler"
2. Crea un nuovo task
3. Trigger: imposta quando eseguire
4. Action: `python.exe C:\path\to\fb_auto_publisher.py`

## Struttura Database

Lo script utilizza 3 tabelle:
- `auto`: dati principali delle auto
- `auto_vetrina`: auto in vendita con flag pubblicazione
- `auto_vetrina_immagini`: immagini aggiuntive

## Log

I log vengono salvati in `fb_publisher.log` e mostrati anche a console.

## Troubleshooting

### Errore "Token is invalid"
- Verifica che il token non sia scaduto
- Rigenera un token permanente seguendo la guida sopra

### Errore connessione database
- Verifica host, porta e credenziali in `.env`
- Controlla che l'IP del server sia autorizzato su Aiven

### Nessuna auto pubblicata
- Verifica che ci siano auto con `pubblicata = 0` in `auto_vetrina`
- Verifica che lo `stato` in `auto` sia 'Disponibile'

## Licenza

MIT