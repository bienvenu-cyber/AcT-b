import os
import requests
import numpy as np
import pandas as pd
import time
import logging
from telegram import Bot
from flask import Flask, jsonify
from threading import Thread
from concurrent.futures import ThreadPoolExecutor
import asyncio
import signal
import sys

# Configuration des logs
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logging.info("Démarrage de l'application.")

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
CAPITAL = 10000
SIGNAL_LOG = "signal_log.csv"

# Fonction pour récupérer les données de l'API
def fetch_crypto_data(crypto_id, retries=3):
    url = f"https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": crypto_id,
        "vs_currencies": "usd"
    }
    
    for attempt in range(retries):
        try:
            logging.debug(f"Envoi de la requête à l'API pour {crypto_id} (Tentative {attempt + 1}).")
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            logging.debug(f"Réponse API reçue : {data}")
            
            if crypto_id in data:
                price = data[crypto_id]['usd']
                return np.array([price], dtype=np.float32)
            else:
                logging.warning(f"Pas de données valides pour {crypto_id}. Réponse : {data}")
        except requests.exceptions.RequestException as e:
            logging.warning(f"Erreur API pour {crypto_id} : {e}")
            time.sleep(2)
    
    logging.error(f"Échec de récupération des données pour {crypto_id} après {retries} tentatives.")
    return None

# Calcul des indicateurs techniques
def calculate_indicators(prices):
    if len(prices) < 26:
        raise ValueError("Pas assez de données pour calculer les indicateurs.")
    sma_short = prices[-10:].mean()
    sma_long = prices[-20:].mean()
    macd = prices[-12:].mean() - prices[-26:].mean()
    atr = prices[-20:].std()
    return {
        "SMA_short": sma_short,
        "SMA_long": sma_long,
        "MACD": macd,
        "ATR": atr
    }

# Analyse des signaux
def analyze_signals(prices):
    indicators = calculate_indicators(prices)
    if prices[-1] > indicators["SMA_short"] + (2 * indicators["ATR"]):
        return "SELL", indicators
    elif prices[-1] < indicators["SMA_short"] - (2 * indicators["ATR"]):
        return "BUY", indicators
    return "HOLD", indicators

# Notification Telegram
async def send_telegram_message(message):
    try:
        bot.send_message(chat_id=CHAT_ID, text=message)
        logging.info(f"Message Telegram envoyé : {message}")
    except Exception as e:
        logging.error(f"Erreur d'envoi Telegram : {e}")

# Analyse d'une cryptomonnaie
async def analyze_crypto(crypto_id):
    try:
        prices = fetch_crypto_data(crypto_id)
        if prices is None:
            await send_telegram_message(f"Échec de récupération des données pour {crypto_id}.")
            return
        
        signal, indicators = analyze_signals(prices)
        await send_telegram_message(f"{crypto_id.upper()} Signal: {signal} à {prices[-1]:.2f}")
    except Exception as e:
        logging.error(f"Erreur pour {crypto_id} : {e}")
        await send_telegram_message(f"Erreur pour {crypto_id} : {e}")

# Tâche principale
async def trading_task():
    while True:
        tasks = [analyze_crypto(crypto) for crypto in CRYPTO_LIST]
        await asyncio.gather(*tasks)
        await asyncio.sleep(900)

# Route Flask
@app.route("/")
def home():
    return jsonify({"status": "Bot opérationnel."})

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=PORT), daemon=True).start()
    asyncio.run(trading_task())