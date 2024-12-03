import os
import requests
import numpy as np
import pandas as pd
import time
import asyncio
from sklearn.preprocessing import StandardScaler
from telegram import Bot
from flask import Flask, jsonify
from threading import Lock

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
FILE_LOCK = Lock()  # Verrou pour les accès aux fichiers

# Fonction pour récupérer les données d'une API
def fetch_crypto_data(crypto_id, retries=3):
    url = f"https://api.coingecko.com/api/v3/coins/{crypto_id}/market_chart"
params = {
    "vs_currency": "usd", 
    "days": "1", 
    "interval": "minute",
    "x_cg_demo_api_key": 
    "CG-JL3PvcpDM8bFWUF5wmNHZ8iA"  # La clé API doit être complète et entre guillemets.
}
    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            prices = [item[1] for item in response.json()["prices"]]
            return np.array(prices)
        except requests.exceptions.RequestException as e:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Erreur pour {crypto_id} : {e}")
            time.sleep(5)
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

# Analyse des signaux
def analyze_signals(prices):
    indicators = calculate_indicators(prices)
    if prices[-1] > indicators["Upper_Band"]:
        return "SELL", indicators
    elif prices[-1] < indicators["Lower_Band"]:
        return "BUY", indicators
    else:
        return "HOLD", indicators

# Envoi synchrone d'un message Telegram
def send_telegram_message_sync(chat_id, message):
    try:
        bot.send_message(chat_id=chat_id, text=message)
    except Exception as e:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Erreur d'envoi Telegram : {e}")

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
    with FILE_LOCK:  # Empêche les conflits d'écriture
        if not os.path.exists(SIGNAL_LOG):
            df.to_csv(SIGNAL_LOG, index=False)
        else:
            df.to_csv(SIGNAL_LOG, mode="a", header=False, index=False)

# Fonction principale pour analyser une cryptomonnaie
def analyze_crypto(crypto_id):
    prices = fetch_crypto_data(crypto_id)
    if prices is None or len(prices) < 20:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Données insuffisantes pour {crypto_id}.")
        return
    signal, indicators = analyze_signals(prices)
    log_signal(signal, indicators, prices)
    send_telegram_message_sync(CHAT_ID, f"{crypto_id.upper()} Signal: {signal} à {prices[-1]:.2f}")

# Tâche périodique pour analyser toutes les cryptos
def trading_task():
    while True:
        for crypto in CRYPTO_LIST:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Analyse de {crypto}...")
            analyze_crypto(crypto)
        time.sleep(900)  # Intervalle de 15 minutes

# Route Flask
@app.route("/")
def home():
    return jsonify({"status": "Bot de trading opérationnel."})

# Lancement de l'application
if __name__ == "__main__":
    from threading import Thread

    # Exécuter la tâche de trading dans un thread séparé
    trading_thread = Thread(target=trading_task, daemon=True)
    trading_thread.start()

    # Démarrer Flask en mode debug
    app.run(host="0.0.0.0", port=8001)