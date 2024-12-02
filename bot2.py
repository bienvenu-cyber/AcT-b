import tracemalloc
import os
import requests
import numpy as np
import pandas as pd
import time
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from telegram import Bot
from concurrent.futures import ThreadPoolExecutor
from flask import Flask
from tensorflow.keras import layers, models

# Variables d'environnement
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
PORT = int(os.getenv("PORT", 8001))

# Vérification des variables d'environnement
if not TELEGRAM_TOKEN or not CHAT_ID:
    raise ValueError("Les variables d'environnement TELEGRAM_TOKEN ou CHAT_ID ne sont pas définies.")

# Initialisation du bot Telegram
bot = Bot(token=TELEGRAM_TOKEN)

# Liste des cryptomonnaies à surveiller
CRYPTO_LIST = ["bitcoin","cardano"]

# Capital initial et gestion des positions
MAX_POSITION_PERCENTAGE = 0.1
CAPITAL = 10000

# Journalisation
PERFORMANCE_LOG = "trading_performance.csv"
SIGNAL_LOG = "signal_log.csv"

# Initialisation de l'application Flask
app = Flask(__name__)

# Fonction générique pour récupérer les données d'une API
def fetch_crypto_data(api_name, crypto_id, retries=3):
    api_config = {
        "CoinGecko": {
            "url": f"https://api.coingecko.com/api/v3/coins/{crypto_id}/market_chart",
            "params": {"vs_currency": "usd", "days": "1", "interval": "minute"},
            "parse": lambda data: [item[1] for item in data["prices"]]
        },
        "Binance": {
            "url": f"https://api.binance.com/api/v3/klines",
            "params": {"symbol": f"{crypto_id.upper()}USDT", "interval": "1m", "limit": 1000},
            "parse": lambda data: [float(item[4]) for item in data]
        }
    }
    api = api_config.get(api_name)
    if not api:
        raise ValueError(f"API '{api_name}' non supportée.")
    
    for attempt in range(retries):
        try:
            response = requests.get(api["url"], params=api["params"], timeout=10)
            response.raise_for_status()
            data = response.json()
            return np.array(api["parse"](data))
        except requests.exceptions.RequestException as err:
            print(f"Erreur {api_name} pour {crypto_id}: {err}")
            if attempt < retries - 1:
                time.sleep(5)
            else:
 
import asyncio  # Ensure asyncio is imported

# Updated function for sending a message
async def send_async_telegram_message(chat_id, message):
    try:
        # Ensure this is your async bot instance
        await bot.send_message(chat_id=chat_id, text=message)
    except Exception as e:
        logger.error(f"Failed to send async message: {e}")

# Replace all calls to `bot.send_message` with `await send_async_telegram_message`# Fonction pour calculer les indicateurs techniques
def calculate_indicators(prices):
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
        "Lower_Band": lower_band
    }

# Fonction pour analyser les signaux
def analyze_signals(prices):
    indicators = calculate_indicators(prices)
    if prices[-1] > indicators["Upper_Band"]:
        return "SELL", indicators
    elif prices[-1] < indicators["Lower_Band"]:
        return "BUY", indicators
    else:
        return "HOLD", indicators

# Fonction de gestion des positions
def manage_position(signal, current_position, capital):
    position_size = capital * MAX_POSITION_PERCENTAGE
    if signal == "BUY" and current_position < position_size:
        return position_size
    elif signal == "SELL" and current_position > 0:
        return 0
    return current_position

# Fonction de journalisation des signaux
def log_signal(signal, indicators, prices):
    df = pd.DataFrame([{
        "Signal": signal,
        "Price": prices[-1],
        "SMA_short": indicators["SMA_short"],
        "SMA_long": indicators["SMA_long"],
        "MACD": indicators["MACD"],
        "ATR": indicators["ATR"],
        "Time": time.strftime("%Y-%m-%d %H:%M:%S")
    }])
    if not os.path.exists(SIGNAL_LOG):
        df.to_csv(SIGNAL_LOG, index=False)
    else:
        df.to_csv(SIGNAL_LOG, mode="a", header=False, index=False)

# Fonction principale pour chaque crypto
def run_trading_bot(crypto_id):
    print(f"Analyse de {crypto_id}")
    prices = fetch_crypto_data("CoinGecko", crypto_id)
    if prices is None or len(prices) < 20:
        print(f"Données insuffisantes pour {crypto_id}")
        return
    signal, indicators = analyze_signals(prices)
    current_position = manage_position(signal, 0, CAPITAL)
    log_signal(signal, indicators, prices)
    bot.send_message(chat_id=CHAT_ID, text=f"{crypto_id.upper()} Signal: {signal} à {prices[-1]:.2f}")

# Application Flask
@app.route("/")
def home():
    return "Bot de trading opérationnel."

# Fonction pour exécuter le bot de manière répétée
def start_bot():
    while True:
        for crypto in CRYPTO_LIST:
            run_trading_bot(crypto)
        time.sleep(60)  # Intervalle d'analyse (1 minute)

# Exécution
if __name__ == "__main__":
    with ThreadPoolExecutor() as executor:
        executor.submit(start_bot)
        executor.submit(app.run, host="0.0.0.0", port=PORT)