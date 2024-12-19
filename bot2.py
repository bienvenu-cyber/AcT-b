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
import objgraph
import talib
from logging.handlers import RotatingFileHandler
import aiohttp

# Activer la surveillance de la mémoire
tracemalloc.start()

# Configuration du gestionnaire de logs avec rotation des fichiers
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
handler = RotatingFileHandler('bot_trading.log', maxBytes=5*1024*1024, backupCount=3)
handler.setFormatter(logging.Formatter('%(asctime)s - %(levellevel)s - %(message)s'))
logging.getLogger().addHandler(handler)
logger = logging.getLogger(__name__)
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

# Récupération des données historiques pour les cryptomonnaies
async def fetch_historical_data(crypto_symbol, currency="USD", interval="hour", limit=2000, max_retries=5, backoff_factor=2):
    base_url = "https://min-api.cryptocompare.com/data/v2/"

    # Déterminer le bon endpoint en fonction de l'intervalle
    endpoint = "histohour" if interval == "hour" else "histoday"
    url = f"{base_url}{endpoint}"
    params = {
        "fsym": crypto_symbol.upper(),
        "tsym": currency.upper(),
        "limit": limit,
        "api_key": "70001b698e6a3d349e68ba1b03e7489153644e38c5026b4a33d55c8e460c7a3c"
    }

    attempt = 0
    while attempt < max_retries:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    response.raise_for_status()
                    data = await response.json()

            if data.get("Response") == "Success" and "Data" in data:
                prices = []
                for item in data["Data"].get("Data", []):
                    if all(key in item for key in ["time", "open", "high", "low", "close", "volumeto"]):
                        prices.append({
                            "time": item["time"],
                            "open": item["open"],
                            "high": item["high"],
                            "low": item["low"],
                            "close": item["close"],
                            "volume": item["volumeto"]
                        })

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

# Fonction de calcul des indicateurs avec TA-Lib
def calculate_indicators(prices):
    if len(prices) < 26:
        raise ValueError("Pas assez de données pour calculer les indicateurs.")

    opens = np.array([price["open"] for price in prices])
    highs = np.array([price["high"] for price in prices])
    lows = np.array([price["low"] for price in prices])
    closes = np.array([price["close"] for price in prices])

    sma_short = talib.SMA(closes, timeperiod=10)[-1]
    sma_long = talib.SMA(closes, timeperiod=20)[-1]
    ema_short = talib.EMA(closes, timeperiod=12)[-1]
    ema_long = talib.EMA(closes, timeperiod=26)[-1]
    macd, macd_signal, macd_hist = talib.MACD(closes, fastperiod=12, slowperiod=26, signalperiod=9)
    atr = talib.ATR(highs, lows, closes, timeperiod=14)[-1]
    upper_band, middle_band, lower_band = talib.BBANDS(closes, timeperiod=20, nbdevup=2, nbdevdn=2, matype=0)
    rsi = talib.RSI(closes, timeperiod=14)[-1]
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

def calculate_sl_tp(entry_price, sl_percent=0.02, tp_percent=0.05):
    sl_price = entry_price - (sl_percent * entry_price)
    tp_price = entry_price + (tp_percent * entry_price)
    logging.debug(f"Stop Loss calculé à : {sl_price}, Take Profit calculé à : {tp_price} (Prix d'entrée : {entry_price})")
    return sl_price, tp_price

def analyze_signals(prices):
    indicators = calculate_indicators(prices)

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

async def send_telegram_message(chat_id, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params={"chat_id": chat_id, "text": message}) as response:
                response.raise_for_status()
                logging.debug(f"Message envoyé avec succès. Réponse: {await response.json()}")
    except aiohttp.ClientError as e:
        logging.error(f"Erreur lors de l'envoi du message à Telegram : {e}")

async def periodic_price_check():
    while True:
        for symbol in CRYPTO_LIST:
            prices = await fetch_historical_data(symbol, CURRENCY)
            if prices:
                signal = analyze_signals(prices)
                logging.info(f"Signal généré pour {symbol}/{CURRENCY}: {signal}")
                if signal:
                    message = f"Signal de trading pour {symbol}/{CURRENCY}: {signal}"
                    await send_telegram_message(CHAT_ID, message)
            else:
                logging.error(f"Impossible d'analyser les données pour {symbol}, données non disponibles.")
        await asyncio.sleep(900)

def log_memory_usage():
    current, peak = tracemalloc.get_traced_memory()
    logging.info(f"Utilisation de la mémoire - Actuelle: {current / 10**6} MB, Pic: {peak / 10**6} MB")
    tracemalloc.clear_traces()

async def trading_task():
    last_sent_signals = {}
    while True:
        logging.info("Début d'une nouvelle itération de trading.")
        tasks = []
        for crypto in CRYPTO_LIST:
            prices = await fetch_historical_data(crypto, CURRENCY)
            if prices:
                signal = analyze_signals(prices)
                if signal:
                    if last_sent_signals.get(crypto) == signal:
                        logging.info(f"Signal déjà envoyé pour {crypto}. Ignoré.")
                        continue
                    last_sent_signals[crypto] = signal
                    entry_price = prices[-1]["close"]
                    sl_price, tp_price = calculate_sl_tp(entry_price)
                    message = f"Signal de trading pour {crypto}/{CURRENCY}: {signal}\n"
                    message += f"Prix d'entrée: {entry_price}\n"
                    message += f"Stop Loss: {sl_price}\n"
                    message += f"Take Profit: {tp_price}\n"
                    await send_telegram_message(CHAT_ID, message)
                logging.info(f"Signal généré pour {crypto}/{CURRENCY}: {signal}")
            else:
                logging.error(f"Impossible d'analyser les données pour {crypto}, données non disponibles.")
        await asyncio.sleep(600)

async def handle_shutdown_signal(signum, frame):
    logging.info(f"Signal d'arrêt reçu : {signum}")
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    logging.info("Arrêt propre du bot.")
    sys.exit(0)

def configure_signal_handlers(loop):
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda sig=sig: asyncio.create_task(handle_shutdown_signal(sig, None)))

@app.route("/")
def home():
    logging.info("Requête reçue sur '/'")
    return jsonify({"status": "Bot de trading opérationnel."})

async def run_flask():
    await asyncio.to_thread(app.run, host='0.0.0.0', port=PORT, threaded=True, use_reloader=False, debug=True)

async def main():
    await asyncio.gather(
        trading_task(),
        run_flask()
    )

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Exécution interrompue par l'utilisateur.")
    except Exception as e:
        logging.error(f"Erreur inattendue : {e}")
    finally:
        logging.info("Arrêt complet.")