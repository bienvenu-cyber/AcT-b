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
import gc
import objgraph
import platform
import subprocess

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

def get_crypto_data(crypto_symbol, limit=2000, retries=5):
    url = "https://min-api.cryptocompare.com/data/v2/histoday"
    params = {
        "fsym": crypto_symbol,  
        "tsym": "USD",  
        "limit": limit,  
        "toTs": int(time.time()),  
        "api_key": "70001b698e6a3d349e68ba1b03e7489153644e38c5026b4a33d55c8e460c7a3c" 
    }

    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, timeout=45)
            if response.status_code == 429:
                logging.warning("Limite API atteinte. Pause de 60 secondes.")
                time.sleep(60)
                continue
            response.raise_for_status()
            data = response.json()
            if "Data" in data:
                return data['Data']['Data']
            else:
                logging.error("Erreur : Données manquantes dans la réponse.")
                return None
        except requests.exceptions.RequestException as e:
            logging.warning(f"Tentative {attempt + 1} échouée pour {crypto_symbol} : {e}")
            time.sleep(2)
    
    logging.error(f"Impossible de récupérer les données pour {crypto_symbol} après {retries} tentatives.")
    return None

# Exemple d'utilisation
btc_data = get_crypto_data("BTC")
if btc_data:
    logging.debug("Données historiques récupérées pour Bitcoin.")
else:
    logging.error("Aucune donnée récupérée pour Bitcoin.")

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

# Fonction pour analyser une cryptomonnaie
async def analyze_crypto(crypto_id):
    try:
        logging.debug(f"Début de l'analyse pour {crypto_id}.")
        prices = get_crypto_data(crypto_id)
        
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

@app.route("/")
def home():
    return jsonify({"status": "Bot de trading opérationnel."})

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
    periodic_price_check()