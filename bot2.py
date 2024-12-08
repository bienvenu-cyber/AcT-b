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
CRYPTO_LIST = ["BTC", "ADA"]
MAX_POSITION_PERCENTAGE = 0.1
CAPITAL = 10000
PERFORMANCE_LOG = "trading_performance.csv"
SIGNAL_LOG = "signal_log.csv"
API_KEY = "70001b698e6a3d349e68ba1b03e7489153644e38c5026b4a33d55c8e460c7a3c"

# Fonction pour récupérer l'historique des prix
def fetch_historical_data(crypto_symbol, limit=2000):
    logging.debug(f"Récupération des données historiques pour {crypto_symbol}")
    url = f"https://min-api.cryptocompare.com/data/v2/histoday"
    params = {
        "fsym": crypto_symbol,
        "tsym": "USD",
        "limit": limit,
        "api_key": API_KEY
    }
    try:
        response = requests.get(url, params=params, timeout=45)
        response.raise_for_status()
        data = response.json()
        if data.get("Response") != "Success":
            raise ValueError(f"Erreur dans la réponse de l'API : {data.get('Message', 'Inconnue')}")
        prices = [entry["close"] for entry in data["Data"]["Data"]]
        logging.debug(f"Récupéré {len(prices)} jours de données pour {crypto_symbol}.")
        return np.array(prices, dtype=np.float32)
    except requests.exceptions.RequestException as e:
        logging.error(f"Erreur lors de la récupération des données historiques : {e}")
        return None

# Fonction pour calculer les indicateurs
def calculate_indicators(prices):
    if len(prices) < 26:
        raise ValueError("Pas assez de données pour calculer les indicateurs.")
    sma_short = prices[-10:].mean()
    sma_long = prices[-20:].mean()
    ema_short = prices[-12:].mean()
    ema_long = prices[-26:].mean()
    macd = ema_short - ema_long
    atr = np.mean(np.abs(np.diff(prices[-20:])))
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

# Envoi de message Telegram
async def send_telegram_message(chat_id, message):
    try:
        await bot.send_message(chat_id=chat_id, text=message)
        logging.info(f"Message Telegram envoyé : {message}")
    except Exception as e:
        logging.error(f"Erreur d'envoi Telegram : {e}")

# Analyse d'une cryptomonnaie
async def analyze_crypto(crypto_symbol):
    try:
        logging.info(f"Analyse de {crypto_symbol}")
        prices = fetch_historical_data(crypto_symbol)
        if prices is None or len(prices) < 26:
            logging.warning(f"Données insuffisantes pour {crypto_symbol}.")
            await send_telegram_message(CHAT_ID, f"Données insuffisantes pour {crypto_symbol}.")
            return
        
        signal, indicators = analyze_signals(prices)
        log_signal(signal, indicators, prices)
        await send_telegram_message(CHAT_ID, f"Signal {signal} pour {crypto_symbol}: {prices[-1]:.2f} USD")
    except Exception as e:
        logging.error(f"Erreur lors de l'analyse de {crypto_symbol}: {e}")
        await send_telegram_message(CHAT_ID, f"Erreur détectée pour {crypto_symbol}: {e}")

# Lancer les tâches de trading
async def trading_task():
    while True:
        tasks = [analyze_crypto(crypto) for crypto in CRYPTO_LIST]
        await asyncio.gather(*tasks)
        await asyncio.sleep(900)

# Application Flask
@app.route("/")
def home():
    return jsonify({"status": "Bot actif."})

# Démarrage
if __name__ == "__main__":
    logging.info("Démarrage du bot de trading.")
    asyncio.run(trading_task())