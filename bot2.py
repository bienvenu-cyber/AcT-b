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
import talib
import psutil
import random
import logging
from logging.handlers import RotatingFileHandler
from threading import Thread
import aiohttp
import functools

# Activer la surveillance de la mémoire
tracemalloc.start()

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Configuration du gestionnaire de logs avec rotation des fichiers
handler = RotatingFileHandler('bot_trading.log', maxBytes=5*1024*1024, backupCount=3)  # Taille max de 5 Mo et 3 backups
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(handler)

# Création du logger
logger = logging.getLogger(__name__)

# Exemple de log de démarrage
logger.debug("Démarrage de l'application.")

# Variables d'environnement
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
PORT = int(os.getenv("PORT", 8002))

if not TELEGRAM_TOKEN:
    logging.error("La variable d'environnement TELEGRAM_TOKEN est manquante. Veuillez la définir.")
    sys.exit(1)

if not CHAT_ID:
    logging.error("La variable d'environnement CHAT_ID est manquante. Veuillez la définir.")
    sys.exit(1)
    
bot = Bot(token=TELEGRAM_TOKEN)

# Initialisation de Flask
app = Flask(__name__)

# Constantes
CURRENCY = "USD"
CRYPTO_LIST = ["BTC", "ETH", "XRP"]
MAX_POSITION_PERCENTAGE = 0.1
CAPITAL = 100
PERFORMANCE_LOG = "trading_performance.csv"
SIGNAL_LOG = "signal_log.csv"

logging.basicConfig(level=logging.DEBUG)

# Récupération des données historiques pour les cryptomonnaies de manière asynchrone
async def fetch_historical_data(crypto_symbol, currency="USD", interval="hour", limit=2000, max_retries=5, backoff_factor=2):
    """
    Récupère les données historiques pour une cryptomonnaie donnée.
    Utilise aiohttp pour effectuer des appels API asynchrones.
    """
    base_url = "https://min-api.cryptocompare.com/data/v2/"

    # Déterminer le bon endpoint en fonction de l'intervalle
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
    async with aiohttp.ClientSession() as session:
        while attempt < max_retries:
            try:
                async with session.get(url, params=params) as response:
                    response.raise_for_status()
                    data = await response.json()

                    # Validation des données
                    if data.get("Response") == "Success" and "Data" in data:
                        prices = []
                        for item in data["Data"].get("Data", []):
                            # Vérifie que toutes les clés nécessaires sont présentes
                            if all(key in item for key in ["time", "open", "high", "low", "close", "volumeto"]):
                                prices.append({
                                    "time": item["time"],
                                    "open": item["open"],
                                    "high": item["high"],
                                    "low": item["low"],
                                    "close": item["close"],
                                    "volume": item["volumeto"]
                                })

                        # Extraire les valeurs pour les indicateurs
                        opens = np.array([item["open"] for item in prices])
                        highs = np.array([item["high"] for item in prices])
                        lows = np.array([item["low"] for item in prices])
                        closes = np.array([item["close"] for item in prices])
                        volumes = np.array([item["volume"] for item in prices])

                        logging.debug(f"Données récupérées pour {crypto_symbol}: {len(prices)} éléments.")
                        return prices, opens, highs, lows, closes, volumes

                    else:
                        logging.error(f"Erreur API : {data.get('Message', 'Données invalides.')}")
                        return [], [], [], [], [], []

            except aiohttp.ClientError as e:
                attempt += 1
                if attempt >= max_retries:
                    logging.error(f"Échec après {max_retries} tentatives : {e}")
                    return [], [], [], [], [], []
                logging.warning(f"Tentative {attempt}/{max_retries} échouée, nouvelle tentative dans {backoff_factor ** attempt} secondes.")
                await asyncio.sleep(backoff_factor ** attempt)

            except Exception as e:
                logging.error(f"Erreur inattendue : {e}")
                return [], [], [], [], [], []

    logging.error(f"Échec définitif pour {crypto_symbol}.")
    return [], [], [], [], [], []

# Fonction principale pour récupérer les données de plusieurs cryptomonnaies de manière asynchrone
async def main():
    crypto_symbols = ["BTC", "ETH", "EUR"]
    tasks = [fetch_historical_data(symbol) for symbol in crypto_symbols]

    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for symbol, result in zip(crypto_symbols, results):
        if result:
            prices, opens, highs, lows, closes, volumes = result
            logging.info(f"Données pour {symbol} récupérées: {len(prices)} éléments")
        else:
            logging.error(f"Aucune donnée récupérée pour {symbol}.")

# Fonction de calcul des indicateurs avec TA-Lib
def calculate_indicators(prices):
    if len(prices) < 26:
        raise ValueError("Pas assez de données pour calculer les indicateurs.")
    
    # Convertir les prix en tableau numpy pour TA-Lib
    opens = np.array([price["open"] for price in prices])
    highs = np.array([price["high"] for price in prices])
    lows = np.array([price["low"] for price in prices])
    closes = np.array([price["close"] for price in prices])
    
    # Moyennes Mobiles (SMA et EMA)
    sma_short = talib.SMA(closes, timeperiod=10)[-1]  # SMA sur 10 périodes
    sma_long = talib.SMA(closes, timeperiod=20)[-1]   # SMA sur 20 périodes
    
    # EMA
    ema_short = talib.EMA(closes, timeperiod=12)[-1]  # EMA sur 12 périodes
    ema_long = talib.EMA(closes, timeperiod=26)[-1]   # EMA sur 26 périodes
    
    # MACD : Différence entre les EMA à court terme et à long terme
    macd, macd_signal, macd_hist = talib.MACD(closes, fastperiod=12, slowperiod=26, signalperiod=9)
    
    # ATR (Average True Range) pour la volatilité
    atr = talib.ATR(highs, lows, closes, timeperiod=14)[-1]  # ATR sur 14 périodes
    
    # Bandes de Bollinger : Calculées en fonction de la SMA et de l'ATR
    upper_band, middle_band, lower_band = talib.BBANDS(closes, timeperiod=20, nbdevup=2, nbdevdn=2, matype=0)
    
    # RSI (Relative Strength Index) sur 14 périodes
    rsi = talib.RSI(closes, timeperiod=14)[-1]
    
    # Stochastique : Calculs classiques avec %K et %D
    slowk, slowd = talib.STOCH(highs, lows, closes, fastk_period=14, slowk_period=3, slowd_period=3)
    
    logging.debug(f"Indicateurs calculés : SMA_short={sma_short}, SMA_long={sma_long}, EMA_short={ema_short}, EMA_long={ema_long}, MACD={macd[-1]}, ATR={atr}, Upper_Band={upper_band[-1]}, Lower_Band={lower_band[-1]}, RSI={rsi}, Stochastic_K={slowk[-1]}, Stochastic_D={slowd[-1]}")
    
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
    sl_price = entry_price - (sl_percent * entry_price)  # Stop Loss à 2% en dessous du prix d'entrée
    tp_price = entry_price + (tp_percent * entry_price)  # Take Profit à 5% au-dessus du prix d'entrée

    logging.debug(f"Stop Loss calculé à : {sl_price}, Take Profit calculé à : {tp_price} (Prix d'entrée : {entry_price})")

    return sl_price, tp_price

# Fonction de décision d'achat/vente basée sur les indicateurs
def analyze_signals(prices):
    indicators = calculate_indicators(prices)
    
    # Logique de décision d'achat/vente
    if indicators['RSI'] < 30 and indicators['Stochastic_K'] < 20:
        decision = "Acheter"
    elif indicators['RSI'] > 70 and indicators['Stochastic_K'] > 80:
        decision = "Vendre"
    elif indicators['MACD'] > 0 and indicators['EMA_short'] > indicators['EMA_long']:
        decision = "Acheter"
    elif indicators['MACD'] < 0 and indicators['EMA_short'] < indicators['EMA_long']:
        decision = "Vendre"
    else:
        decision = "Ne rien faire"

    logging.debug(f"Décision d'action : {decision}")
    return decision

# Fonction asynchrone d'envoi de message Telegram
async def send_telegram_message(chat_id, message):
    try:
        logging.debug(f"Envoi du message à Telegram pour le chat {chat_id}: {message}")
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params={"chat_id": chat_id, "text": message}) as response:
                response.raise_for_status()
                logging.debug(f"Message envoyé avec succès. Réponse: {await response.json()}")
    except aiohttp.ClientError as e:
        logging.error(f"Erreur lors de l'envoi du message à Telegram: {e}")

# Fonction de démarrage pour exécuter le trading périodique
async def trading_task():
    while True:
        for crypto in CRYPTO_LIST:
            prices = await fetch_historical_data(crypto)  # Supposez que vous avez une fonction fetch_historical_data asynchrone
            if prices:
                signal = analyze_signals(prices)
                logging.info(f"Signal généré pour {crypto}: {signal}")
                
                # Calcul du SL et TP et envoi du message
                entry_price = prices[-1]['close']
                sl_price, tp_price = calculate_sl_tp(entry_price)
                
                message = f"Signal de trading pour {crypto}: {signal}\n"
                message += f"Prix d'entrée: {entry_price}\n"
                message += f"Stop Loss: {sl_price}\n"
                message += f"Take Profit: {tp_price}\n"
                
                await send_telegram_message(CHAT_ID, message)
        await asyncio.sleep(900)  # Attendre 15 minutes avant de recommencer

# Point d'entrée principal
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    async def main():
        await asyncio.gather(
            trading_task(),  # Lancer la tâche de trading
        )

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Exécution interrompue par l'utilisateur.")
    except Exception as e:
        logging.error(f"Erreur inattendue : {e}")
    finally:
        logging.info("Arrêt complet.")