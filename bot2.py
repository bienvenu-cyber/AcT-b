import os
import requests
import numpy as np
import pandas as pd
import time
import logging
import asyncio
import signal
import sys
import tracemalloc
import gc  # Garbage collector pour optimiser la mémoire
import objgraph  # Pour la détection des fuites de mémoire
import platform
import subprocess
import talib
import psutil
from telegram import Bot
from flask import Flask, jsonify
from threading import Thread
import random

# Démarrage de la surveillance de la mémoire
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
CRYPTO_LIST = ["BTC", "ETH", "XRP"]
CURRENCY = "USD"
MAX_POSITION_PERCENTAGE = 0.1
CAPITAL = 100
PERFORMANCE_LOG = "trading_performance.csv"
SIGNAL_LOG = "signal_log.csv"

# Fonction pour récupérer les données historiques des cryptomonnaies
def fetch_historical_data(crypto_symbol, currency="USD", interval="hour", limit=2000, max_retries=5, backoff_factor=2):
    """
    Récupère les données historiques pour une cryptomonnaie donnée.
    """
    base_url = "https://min-api.cryptocompare.com/data/v2/"

    if interval == "hour":
        endpoint = "histohour"
    elif interval == "day":
        endpoint = "histoday"
    else:
        raise ValueError("Intervalle non supporté. Utilisez 'hour' ou 'day'.")

    url = f"{base_url}{endpoint}"
    params = {
        "fsym": crypto_symbol.upper(),
        "tsym": currency.upper(),
        "limit": limit,
        "api_key": "70001b698e6a3d349e68ba1b03e7489153644e38c5026b4a33d55c8e460c7a3c"
    }
    
    attempt = 0  # Compteur de tentatives
    while attempt < max_retries:
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            if data["Response"] == "Success" and "Data" in data:
                prices = [{
                    "time": item["time"],
                    "open": item["open"],
                    "high": item["high"],
                    "low": item["low"],
                    "close": item["close"],
                    "volume": item["volumeto"]
                } for item in data["Data"]["Data"]]

                opens = np.array([item["open"] for item in prices])
                highs = np.array([item["high"] for item in prices])
                lows = np.array([item["low"] for item in prices])
                closes = np.array([item["close"] for item in prices])
                volumes = np.array([item["volume"] for item in prices])
                
                return prices, opens, highs, lows, closes, volumes

            else:
                logging.error(f"Erreur API: {data.get('Message', 'Erreur inconnue')}")
                return None

        except requests.exceptions.RequestException as e:
            attempt += 1
            if attempt >= max_retries:
                logging.error(f"Échec après {max_retries} tentatives : {e}")
                return None
            time.sleep(backoff_factor ** attempt)
            
        except Exception as e:
            logging.error(f"Erreur inattendue : {e}")
            return None

    logging.error(f"Échec définitif pour {crypto_symbol}.")
    return None

# Fonction de calcul des indicateurs avec TA-Lib
def calculate_indicators(prices):
    if len(prices) < 26:
        raise ValueError("Pas assez de données pour calculer les indicateurs.")
    
    opens = np.array([price["open"] for price in prices])
    highs = np.array([price["high"] for price in prices])
    lows = np.array([price["low"] for price in prices])
    closes = np.array([price["close"] for price in prices])
    
    sma_short = talib.SMA(closes, timeperiod=14)[-1]
    sma_long = talib.SMA(closes, timeperiod=50)[-1]
    ema_short = talib.EMA(closes, timeperiod=14)[-1]
    ema_long = talib.EMA(closes, timeperiod=50)[-1]
    macd, macdsignal, macdhist = talib.MACD(closes, fastperiod=12, slowperiod=26, signalperiod=9)
    atr = talib.ATR(highs, lows, closes, timeperiod=14)[-1]
    upper_band, middle_band, lower_band = talib.BBANDS(closes, timeperiod=20, nbdevup=2, nbdevdn=2, matype=0)
    rsi = talib.RSI(closes, timeperiod=14)[-1]
    slowk, slowd = talib.STOCH(highs, lows, closes, fastk_period=5, slowk_period=3, slowd_period=3, slowk_matype=0, slowd_matype=0)
    
    logging.debug(f"Indicateurs calculés : {sma_short}, {sma_long}, {ema_short}, {ema_long}, MACD={macd[-1]}, ATR={atr}, RSI={rsi}, Stochastic_K={slowk[-1]}")
    
    return {
        "SMA_short": sma_short,
        "SMA_long": sma_long,
        "EMA_short": ema_short,
        "EMA_long": ema_long,
        "MACD": macd[-1],
        "ATR": atr,
        "Upper_Band": upper_band[-1],
        "Lower_Band": lower_band[-1],
        "RSI": rsi,
        "Stochastic_K": slowk[-1],
        "Stochastic_D": slowd[-1],
    }

# Calcul du Stop Loss et Take Profit en pourcentage du prix d'entrée
def calculate_sl_tp(entry_price, sl_percent=0.02, tp_percent=0.05):
    sl_price = entry_price - (sl_percent * entry_price)
    tp_price = entry_price + (tp_percent * entry_price)

    logging.debug(f"Stop Loss calculé à : {sl_price}, Take Profit calculé à : {tp_price} (Prix d'entrée : {entry_price})")

    return sl_price, tp_price

# Fonction de décision d'achat/vente basée sur les indicateurs
def analyze_signals(prices):
    if not prices or len(prices) < 26:
        raise ValueError("Données invalides ou insuffisantes pour l'analyse des signaux.")
    
    indicators = calculate_indicators(prices)
    
    if indicators['RSI'] < 30 and indicators['Stochastic_K'] < 20:
        return "BUY"
    elif indicators['RSI'] > 70 and indicators['Stochastic_K'] > 80:
        return "SELL"
    else:
        return "HOLD"

# Envoi d'un message sur Telegram
def send_telegram_message(message):
    try:
        bot.send_message(chat_id=CHAT_ID, text=message)
    except Exception as e:
        logging.error(f"Erreur d'envoi de message Telegram : {e}")

# Démarrage des tâches périodiques
async def start_periodic_task():
    while True:
        try:
            # Récupération des données
            prices_data = await asyncio.to_thread(fetch_historical_data, "BTC", "USD")
            if prices_data:
                prices, opens, highs, lows, closes, volumes = prices_data
                signal = analyze_signals(prices)
                send_telegram_message(f"Signal détecté : {signal}")
            
            await asyncio.sleep(60 * 15)  # Attente de 15 minutes avant la prochaine requête
        except Exception as e:
            logging.error(f"Erreur lors de l'exécution de la tâche périodique : {e}")
            await asyncio.sleep(60)

# Lancer la tâche principale dans un thread
def run_async_task():
    asyncio.run(start_periodic_task())

# Démarrer Flask et les tâches asynchrones
def start_flask():
    app.run(host="0.0.0.0", port=PORT)

# Endpoint Flask pour vérifier que le serveur fonctionne
@app.route("/status")
def status():
    return jsonify({"status": "Server is running"}), 200

if __name__ == "__main__":
    flask_thread = Thread(target=start_flask)
    flask_thread.start()

    # Lancer les tâches périodiques
    run_async_task()