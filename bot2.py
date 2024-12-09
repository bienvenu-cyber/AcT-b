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
import platform
import subprocess
from threading import Thread

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
def fetch_historical_data(crypto_symbol, interval="hour", limit=50):
    base_url = "https://min-api.cryptocompare.com/data/v2/"
    endpoint = "histohour" if interval == "hour" else "histoday"
    url = f"{base_url}{endpoint}"
    params = {
        "fsym": crypto_symbol.upper(),  # Assurer que le symbole est en majuscule
        "tsym": "USD",
        "limit": limit,
        "api_key": "70001b698e6a3d349e68ba1b03e7489153644e38c5026b4a33d55c8e460c7a3c"
    }
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        if data.get("Response") == "Success":
            prices = [item["close"] for item in data["Data"]["Data"]]
            logging.debug(f"Données récupérées pour {crypto_symbol}: {prices}")
            return prices
        else:
            logging.error(f"Erreur de l'API pour {crypto_symbol}: {data['Message']}")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Erreur lors de la récupération des données pour {crypto_symbol}: {e}")
        return None

# Fonction pour calculer les indicateurs techniques
def calculate_indicators(prices):
    if len(prices) < 26:
        raise ValueError("Pas assez de données pour calculer les indicateurs.")
    sma_short = np.mean(prices[-10:])
    sma_long = np.mean(prices[-20:])
    ema_short = np.mean(prices[-12:])  # EMA simplifiée
    ema_long = np.mean(prices[-26:])  # EMA simplifiée
    macd = ema_short - ema_long
    atr = np.std(prices[-20:])
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
    
    logging.info("Aucun signal détecté.")
    return "HOLD", indicators

# Fonction pour analyser une cryptomonnaie et déclencher les calculs
async def analyze_crypto(crypto_id):
    try:
        logging.debug(f"Début de l'analyse pour {crypto_id}.")
        prices = fetch_historical_data(crypto_id.upper(), interval="hour")
        
        if prices is None or len(prices) < 20:
            logging.warning(f"Données insuffisantes pour {crypto_id}.")
            await send_telegram_message(CHAT_ID, f"Données insuffisantes pour {crypto_id}.")
            return
        
        signal, indicators = analyze_signals(prices)
        log_signal(crypto_id, signal, indicators, prices)
        await send_telegram_message(CHAT_ID, f"{crypto_id.upper()} Signal: {signal} à {prices[-1]:.2f}")
        
        gc.collect()  # Optimisation mémoire après chaque analyse
        
    except Exception as e:
        logging.error(f"Erreur lors de l'analyse de {crypto_id} : {e}")
        await send_telegram_message(CHAT_ID, f"Erreur détectée pour {crypto_id}: {e}")

# Fonction de journalisation des signaux
def log_signal(crypto_id, signal, indicators, prices):
    df = pd.DataFrame([{
        "Crypto": crypto_id,
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
    
    logging.debug(f"Signal logué pour {crypto_id}: {signal} à {prices[-1]}")

# Envoi asynchrone d'un message Telegram
async def send_telegram_message(chat_id, message):
    try:
        await bot.send_message(chat_id=chat_id, text=message)
        logging.info(f"Message Telegram envoyé : {message}")
    except Exception as e:
        logging.error(f"Erreur d'envoi Telegram : {e.__class__.__name__} - {e}")

# Tâche principale de trading
async def trading_task():
    while True:
        logging.info("Début d'une nouvelle itération de trading.")
        tasks = [analyze_crypto(crypto) for crypto in CRYPTO_LIST]
        await asyncio.gather(*tasks)
        await asyncio.sleep(900)

# Démarrage Flask et asyncio ensemble
async def run_bot():
    Thread(target=app.run, kwargs={'host': '0.0.0.0', 'port': PORT, 'threaded': True, 'use_reloader': False}).start()
    await trading_task()

if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logging.info("Arrêt manuel du bot.")