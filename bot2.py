import os
import requests
import numpy as np
import pandas as pd
import time
import asyncio
import logging
from sklearn.preprocessing import StandardScaler
from telegram import Bot
from flask import Flask, jsonify
from threading import Lock

# Configuration des logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.info("Démarrage de l'application.")

# Variables d'environnement
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
PORT = int(os.getenv("PORT", 8001))
CG_API_KEY = os.getenv("CG_API_KEY")

logging.info(f"Variables récupérées : TELEGRAM_TOKEN défini : {bool(TELEGRAM_TOKEN)}, CHAT_ID : {CHAT_ID}, PORT : {PORT}")

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
        "x_cg_demo_api_key": CG_API_KEY  # Clé API
    }
    logging.info(f"Récupération des données pour {crypto_id} avec la clé API : {CG_API_KEY}")
    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()  # Vérifie si la requête a échoué
            prices = [item[1] for item in response.json().get("prices", [])]
            logging.info(f"Données récupérées pour {crypto_id}. Longueur des prix : {len(prices)}")
            return np.array(prices)
        except requests.exceptions.RequestException as e:
            logging.error(f"Erreur pour {crypto_id} : {e}")
            time.sleep(5)
    return None

# Calcul des indicateurs techniques
def calculate_indicators(prices):
    logging.info("Calcul des indicateurs techniques...")
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
    logging.info(f"Indicateurs calculés : SMA_short={sma_short}, SMA_long={sma_long}, MACD={macd}, ATR={atr}, Upper_Band={upper_band}, Lower_Band={lower_band}")
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
    logging.info("Analyse des signaux...")
    indicators = calculate_indicators(prices)
    if prices[-1] > indicators["Upper_Band"]:
        logging.info(f"Signal SELL généré : Prix actuel ({prices[-1]}) au-dessus de la bande supérieure.")
        return "SELL", indicators
    elif prices[-1] < indicators["Lower_Band"]:
        logging.info(f"Signal BUY généré : Prix actuel ({prices[-1]}) en dessous de la bande inférieure.")
        return "BUY", indicators
    else:
        logging.info(f"Signal HOLD généré : Prix actuel ({prices[-1]}) dans la plage.")
        return "HOLD", indicators

# Envoi synchrone d'un message Telegram
def send_telegram_message_sync(chat_id, message):
    try:
        bot.send_message(chat_id=chat_id, text=message)
        logging.info(f"Message Telegram envoyé : {message}")
    except Exception as e:
        logging.error(f"Erreur d'envoi Telegram : {e}")

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
    logging.info(f"Signal journalisé : {signal}")

# Fonction principale pour analyser une cryptomonnaie
def analyze_crypto(crypto_id):
    logging.info(f"Début de l'analyse pour {crypto_id}.")
    try:
        prices = fetch_crypto_data(crypto_id)
        if prices is None or len(prices) < 20:
            logging.warning(f"Données insuffisantes pour {crypto_id}.")
            return
        signal, indicators = analyze_signals(prices)
        log_signal(signal, indicators, prices)
        send_telegram_message_sync(CHAT_ID, f"{crypto_id.upper()} Signal: {signal} à {prices[-1]:.2f}")
    except Exception as e:
        logging.error(f"Erreur lors de l'analyse de {crypto_id} : {e}")

# Tâche périodique pour analyser toutes les cryptos
def trading_task():
    logging.info("Démarrage de la tâche de trading.")
    while True:
        for crypto in CRYPTO_LIST:
            logging.info(f"Analyse de {crypto}...")
            analyze_crypto(crypto)
        logging.info("Attente de 15 minutes avant la prochaine analyse.")
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
    logging.info("Thread de trading démarré.")

    # Démarrer Flask en mode debug
  app.run(host="0.0.0.0", port=PORT, debug=True)