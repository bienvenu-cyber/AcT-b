import os
import requests
import numpy as np
import pandas as pd
import time
import logging
from sklearn.preprocessing import StandardScaler
from telegram import Bot
from flask import Flask, jsonify
from threading import Thread
from concurrent.futures import ThreadPoolExecutor
import asyncio
import signal
import sys
import tracemalloc
import gc  # Garbage collector pour optimiser la mémoire

# Activer la surveillance de la mémoire
tracemalloc.start()

# Configuration des logs
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logging.info("Démarrage de l'application.")

# Variables d'environnement
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
PORT = int(os.getenv("PORT", 8001))
CG_API_KEY = os.getenv("CG_API_KEY")

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
executor = ThreadPoolExecutor(max_workers=8)  # Pool de threads pour optimisation

# Fonction pour surveiller la mémoire
def log_memory_usage():
    snapshot = tracemalloc.take_snapshot()
    top_stats = snapshot.statistics("lineno")
    logging.debug("[TOP 10 Mémoire]")
    for stat in top_stats[:10]:
        logging.debug(stat)

# Fonction pour récupérer les données de l'API
def fetch_crypto_data(crypto_id, retries=3):
    url = f"https://api.coingecko.com/api/v3/coins/{crypto_id}/market_chart"
    params = {"vs_currency": "usd", "days": "1", "interval": "minute"}
    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            prices = [item[1] for item in response.json().get("prices", [])]
            if not prices:
                raise ValueError(f"Pas de données pour {crypto_id}.")
            logging.debug(f"Données reçues pour {crypto_id}: {prices}")
            return np.array(prices, dtype=np.float32)
        except requests.exceptions.RequestException as e:
            logging.warning(f"Tentative {attempt + 1} échouée pour {crypto_id} : {e}")
            time.sleep(2)
    logging.error(f"Impossible de récupérer les données pour {crypto_id} après {retries} tentatives.")
    return None

# Calcul des indicateurs techniques
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
    return {
        "SMA_short": sma_short,
        "SMA_long": sma_long,
        "MACD": macd,
        "ATR": atr,
        "Upper_Band": upper_band,
        "Lower_Band": lower_band,
    }

# Analyse des signaux avec logs supplémentaires
def analyze_signals(prices):
    indicators = calculate_indicators(prices)
    logging.debug(f"Indicateurs calculés : {indicators}")
    
    # Log des prix et des indicateurs avant la décision
    logging.debug(f"Prix actuel : {prices[-1]}, Indicateurs : {indicators}")

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

# Fonction pour analyser une cryptomonnaie avec vérification des données et notification d'erreur
async def analyze_crypto(crypto_id):
    try:
        logging.debug(f"Début de l'analyse pour {crypto_id}.")
        prices = fetch_crypto_data(crypto_id)
        
        # Vérification des données avant analyse
        if prices is None or len(prices) < 20:
            logging.warning(f"Données insuffisantes pour {crypto_id}.")
            await notify_error(f"Données insuffisantes pour {crypto_id}.")
            return
        
        signal, indicators = analyze_signals(prices)
        
        # Log du signal avant l'envoi
        logging.debug(f"Signal généré pour {crypto_id}: {signal} à {prices[-1]:.2f}")
        
        log_signal(signal, indicators, prices)
        
        await send_telegram_message(CHAT_ID, f"{crypto_id.upper()} Signal: {signal} à {prices[-1]:.2f}")
        
        gc.collect()  # Libérer les ressources inutilisées
        
    except Exception as e:
        logging.error(f"Erreur lors de l'analyse de {crypto_id} : {e}")
        await notify_error(f"Erreur détectée dans le bot pour {crypto_id}: {e}")

# Tâche périodique pour analyser toutes les cryptos
async def trading_task():
    while True:
        logging.info("Début d'une nouvelle itération de trading.")
        
        tasks = [analyze_crypto(crypto) for crypto in CRYPTO_LIST]
        
        await asyncio.gather(*tasks)
        
        log_memory_usage()  # Journaliser l'usage mémoire
        
        await asyncio.sleep(900)

# Gestion des signaux d'arrêt
def handle_shutdown_signal(signum, frame):
    logging.info("Arrêt de l'application (Signal: %s)", signum)
    executor.shutdown(wait=True)  # Attendre la fin des threads
    logging.info("Pool de threads arrêté.")
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_shutdown_signal)
signal.signal(signal.SIGINT, handle_shutdown_signal)

# Route Flask
@app.route("/")
def home():
    return jsonify({"status": "Bot de trading opérationnel."})

# Lancer Flask sur un thread séparé
def run_flask():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8001)))

# Test manuel au démarrage du bot 
if TELEGRAM_TOKEN and CHAT_ID:
    try:
        asyncio.run(send_telegram_message(CHAT_ID, "Test manuel de connexion Telegram : Bot actif."))
    except Exception as e:
        logging.error(f"Échec du test manuel Telegram : {e}")

if __name__ == "__main__":
    logging.info("Démarrage du bot de trading.")
    
    Thread(target=run_flask, daemon=True).start()
    
    asyncio.run(trading_task())