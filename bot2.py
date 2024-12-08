import os
import requests
import numpy as np
import pandas as pd
import time
import logging
from telegram import Bot
from flask import Flask, jsonify
import asyncio
import signal
import sys
import tracemalloc
import gc  # Garbage collector pour optimiser la mémoire
import objgraph  # Pour la détection des fuites de mémoire

# Activer la surveillance de la mémoire
tracemalloc.start()

# Configuration des logs
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logging.debug("Démarrage de l'application.")

# Variables d'environnement
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
PORT = int(os.getenv("PORT", 8001))

if not TELEGRAM_TOKEN or not CHAT_ID:
    raise ValueError("Les variables d'environnement TELEGRAM_TOKEN ou CHAT_ID ne sont pas définies.")

bot = Bot(token=TELEGRAM_TOKEN)

# Initialisation de Flask
app = Flask(__name__)

# Constantes
CRYPTO_LIST = ["bitcoin", "cardano"]
MAX_POSITION_PERCENTAGE = 0.1
CAPITAL = 10000
PERFORMANCE_LOG = "trading_performance.csv"
SIGNAL_LOG = "signal_log.csv"

# Fonction pour récupérer les données de l'API avec votre clé API
def fetch_crypto_data(crypto_symbol, retries=3):
    logging.debug(f"Récupération des données pour {crypto_symbol}")
    url = "https://min-api.cryptocompare.com/data/price"
    params = {
        "fsym": crypto_symbol,  # Symbole de la crypto-monnaie (ex: "BTC" ou "ADA")
        "tsyms": "USD",  # Devise cible (USD)
        "api_key": "70001b698e6a3d349e68ba1b03e7489153644e38c5026b4a33d55c8e460c7a3c"  # Votre clé API
    }
    
    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, timeout=45)  # Timeout augmenté
            if response.status_code == 429:  # Trop de requêtes
                logging.warning("Limite API atteinte. Pause de 60 secondes.")
                time.sleep(60)
                continue
            response.raise_for_status()
            data = response.json()
            if "USD" not in data:
                raise ValueError(f"Pas de données pour {crypto_symbol}.")
            price = data["USD"]
            logging.debug(f"Données reçues pour {crypto_symbol}: {price}")
            return np.array([price], dtype=np.float32)
        except requests.exceptions.RequestException as e:
            logging.warning(f"Tentative {attempt + 1} échouée pour {crypto_symbol} : {e}")
            time.sleep(2)
    logging.error(f"Impossible de récupérer les données pour {crypto_symbol} après {retries} tentatives.")
    return None

# Exemple d'utilisation pour Bitcoin et Cardano
btc_price = fetch_crypto_data("BTC")
ada_price = fetch_crypto_data("ADA")

if btc_price is not None:
    print(f"Le prix du Bitcoin (BTC) en USD est {btc_price[0]}")
else:
    print("Impossible de récupérer le prix du Bitcoin.")

if ada_price is not None:
    print(f"Le prix de Cardano (ADA) en USD est {ada_price[0]}")
else:
    print("Impossible de récupérer le prix de Cardano.")

# Fonction pour récupérer périodiquement les prix du Bitcoin et Cardano
def periodic_price_check():
    while True:
        bitcoin_price = fetch_crypto_data("BTC")
        cardano_price = fetch_crypto_data("ADA")
        
        if bitcoin_price is not None and cardano_price is not None:
            print(f"Le prix du Bitcoin (BTC) en USD est {bitcoin_price[0]}")
            print(f"Le prix de Cardano (ADA) en USD est {cardano_price[0]}")
        
        # Attente de 5 minutes avant le prochain cycle
        time.sleep(300)

# Fonction de calcul des indicateurs techniques
def calculate_indicators(prices):
    if len(prices) < 26:
        raise ValueError("Pas assez de données pour calculer les indicateurs.")
    sma_short = prices[-10:].mean()
    sma_long = prices[-20:].mean()
    ema_short = prices[-12:].mean()
    ema_long = prices[-26:].mean()
    macd = ema_short - ema_long
    atr = prices[-20:].std()
    upper_band = sma_short + (2 * atr)
    lower_band = sma_short - (2 * atr)
    logging.debug(f"Indicateurs calculés : SMA_short={sma_short}, SMA_long={sma_long}, MACD={macd}, ATR={atr}, Upper_Band={upper_band}, Lower_Band={lower_band}")
    return {
        "SMA_short": sma_short,
        "SMA_long": sma_long,
        "MACD": macd,
        "ATR": atr,
        "Upper_Band": upper_band,
        "Lower_Band": lower_band,
    }

# Analyse des signaux
def analyze_signals(prices):
    indicators = calculate_indicators(prices)
    logging.debug(f"Indicateurs calculés : {indicators}")

    if prices[-1] > indicators["Upper_Band"]:
        logging.info("Signal de vente généré.")
        return "SELL", indicators
    elif prices[-1] < indicators["Lower_Band"]:
        logging.info("Signal d'achat généré.")
        return "BUY", indicators
    
    logging.info("Aucun signal, maintien de la position.")
    return "HOLD", indicators

# Envoi asynchrone d'un message Telegram
async def send_telegram_message(chat_id, message):
    try:
        await bot.send_message(chat_id=chat_id, text=message)
        logging.info(f"Message Telegram envoyé : {message}")
    except Exception as e:
        logging.error(f"Erreur d'envoi Telegram : {e.__class__.__name__} - {e}")

# Notification d'erreur en cas d'exception
async def notify_error(message):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=message)
        logging.info(f"Notification d'erreur envoyée : {message}")
    except Exception as e:
        logging.error(f"Erreur lors de l'envoi de la notification d'erreur : {e}")

# Journalisation des signaux
def log_signal(signal, indicators, prices):
    df = pd.DataFrame([{
        "Signal": signal,
        "Price": prices[-1],
        "SMA_short": indicators["SMA_short"],
        "SMA_long": indicators["SMA_long"],
        "MACD": indicators["MACD"],
        "ATR": indicators["ATR"],
        "Time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }])
    
    if not os.path.exists(SIGNAL_LOG):
        df.to_csv(SIGNAL_LOG, index=False)
    else:
        df.to_csv(SIGNAL_LOG, mode="a", header=False, index=False)
    
    logging.debug(f"Signal logué : {signal} à {prices[-1]}")

# Fonction pour analyser une cryptomonnaie
async def analyze_crypto(crypto_id):
    try:
        logging.debug(f"Début de l'analyse pour {crypto_id}.")
        prices = fetch_crypto_data(crypto_id)
        
        if prices is None or len(prices) < 20:
            logging.warning(f"Données insuffisantes pour {crypto_id}.")
            await notify_error(f"Données insuffisantes pour {crypto_id}.")
            return
        
        signal, indicators = analyze_signals(prices)
        logging.debug(f"Signal généré pour {crypto_id}: {signal} à {prices[-1]:.2f}")
        
        log_signal(signal, indicators, prices)
        await send_telegram_message(CHAT_ID, f"{crypto_id.upper()} Signal: {signal} à {prices[-1]:.2f}")
        
        # Analyser les fuites de mémoire
        objgraph.show_most_common_types(limit=10)
        gc.collect()
        
    except Exception as e:
        logging.error(f"Erreur lors de l'analyse de {crypto_id} : {e}")
        await notify_error(f"Erreur détectée dans le bot pour {crypto_id}: {e}")

# Tâche périodique
async def trading_task():
    while True:
        logging.info("Début d'une nouvelle itération de trading.")
        tasks = [analyze_crypto(crypto) for crypto in CRYPTO_LIST]
        await asyncio.gather(*tasks)
        log_memory_usage()
        await asyncio.sleep(900)

# Fonction de sécurité pour le trading task
async def safe_trading_task():
    try:
        await trading_task()
    except Exception as e:
        logging.error(f"Erreur globale dans trading_task: {e}")
        await notify_error(f"Erreur critique détectée : {e}")
        sys.exit(1)  # Arrêt propre

# Gestion des signaux d'arrêt et redémarrage automatique
def handle_shutdown_signal(signum, frame):
    logging.info("Arrêt de l'application (Signal: %s)", signum)
    logging.info("Redémarrage de l'application...")
    
    if platform.system() == "Windows":
        subprocess.Popen([sys.executable] + sys.argv)
    else:
        os.execv(sys.executable, ['python'] + sys.argv)
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_shutdown_signal)
signal.signal(signal.SIGINT, handle_shutdown_signal)

# Route Flask
@app.route("/")
def home():
    return jsonify({"status": "Bot de trading opérationnel."})

# Lancer Flask sur un thread séparé
async def run_flask():
    from threading import Thread
    Thread(target=app.run, kwargs={'host': '0.0.0.0', 'port': PORT, 'threaded': True, 'use_reloader': False}).start()

# Test manuel au démarrage du bot
if TELEGRAM_TOKEN and CHAT_ID:
    try:
        asyncio.run(send_telegram_message(CHAT_ID, "Test manuel de connexion Telegram : Bot actif."))
    except Exception as e:
        logging.error(f"Échec du test manuel Telegram : {e}")

if __name__ == "__main__":
    logging.info("Démarrage du bot de trading.")
    asyncio.run(run_flask())
    asyncio.run(safe_trading_task())
    periodic_price_check()  # Lancer la récupération des prix toutes les 5 minutes