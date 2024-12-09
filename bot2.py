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
CRYPTO_LIST = ["bitcoin", "cardano"]
MAX_POSITION_PERCENTAGE = 0.1
CAPITAL = 10000
PERFORMANCE_LOG = "trading_performance.csv"
SIGNAL_LOG = "signal_log.csv"

# Fonction pour récupérer les données de l'API avec votre clé API
def fetch_historical_data(crypto_symbol, interval="hour", limit=50):
    base_url = "https://min-api.cryptocompare.com/data/v2/"
    if interval == "hour":
        endpoint = "histohour"
    elif interval == "day":
        endpoint = "histoday"
    else:
        raise ValueError("Intervalle non supporté. Utilisez 'hour' ou 'day'.")
    
    url = f"{base_url}{endpoint}"
    params = {
        "fsym": crypto_symbol.upper(),  # Assurer que le symbole est en majuscule
        "tsym": "USD",
        "limit": 50,
        "api_key": "70001b698e6a3d349e68ba1b03e7489153644e38c5026b4a33d55c8e460c7a3c"  # Votre clé API ici
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        # Vérifier si l'API a renvoyé un succès
        if data["Response"] == "Success":
            # Récupérer les prix de clôture
            return [item["close"] for item in data["Data"]["Data"]]
        else:
            # Gestion d'erreurs plus détaillée
            logging.error(f"Erreur de l'API pour {crypto_symbol}: {data['Message']}")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Erreur lors de la récupération des données historiques pour {crypto_symbol}: {e}")
        return None

# Exemple d'utilisation pour Bitcoin et Cardano
btc_price = fetch_historical_data("BTC")
ada_price = fetch_historical_data("ADA")

if btc_price is not None:
    print(f"Le prix du Bitcoin (BTC) en USD est {btc_price[0]}")
else:
    print("Impossible de récupérer le prix du Bitcoin.")

if ada_price is not None:
    print(f"Le prix de Cardano (ADA) en USD est {ada_price[0]}")
else:
    print("Impossible de récupérer le prix de Cardano.")

# Fonction pour récupérer les données historiques
def fetch_historical_data(symbol, currency, limit=50):
    url = f"https://min-api.cryptocompare.com/data/v2/histohour"
    params = {
        "fsym": symbol,
        "tsym": currency,
        "limit": limit,
        "api_key": 70001b698e6a3d349e68ba1b03e7489153644e38c5026b4a33d55c8e460c7a3c
    }
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        if data.get("Response") == "Success":
            # Extraire les prix de clôture
            prices = [item["close"] for item in data["Data"]["Data"]]
            logging.debug(f"Prix récupérés pour {symbol}/{currency}: {prices}")
            return prices
        else:
            logging.error(f"Erreur dans la réponse de l'API : {data}")
            return None
    except Exception as e:
        logging.error(f"Erreur lors de la récupération des données : {e}")
        return None

# Fonction de calcul des indicateurs techniques
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

# Fonction principale de vérification périodique
def periodic_price_check(symbol, currency):
    while True:
        prices = fetch_historical_data(symbol, currency)
        if prices:
            signal, indicators = analyze_signals(prices)
            logging.info(f"Signal généré pour {symbol}/{currency}: {signal}")
        else:
            logging.error("Impossible d'analyser les données, données non disponibles.")
        time.sleep(3600)  # Attendre 1 heure avant la prochaine vérification

# Exemple d'utilisation
if __name__ == "__main__":
    # Lancer la vérification pour BTC/USD
    try:
        periodic_price_check("BTC", "USD")
    except KeyboardInterrupt:
        logging.info("Arrêt manuel du script.")

# Envoi asynchrone d'un message Telegram
async def send_telegram_message(chat_id, message):
    try:
        await bot.send_message(chat_id=chat_id, text=message)
        logging.info(f"Message Telegram envoyé : {message}")
    except Exception as e:
        logging.error(f"Erreur d'envoi Telegram : {e.__class__.__name__} - {e}")

# Notification d'erreur en cas d'exception
async def notify_error(message):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=message)
        logging.info(f"Notification d'erreur envoyée : {message}")
    except Exception as e:
        logging.error(f"Erreur lors de l'envoi de la notification d'erreur : {e}")

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

# Fonction pour analyser une cryptomonnaie
async def analyze_crypto(crypto_id):
    try:
        logging.debug(f"Début de l'analyse pour {crypto_id}.")
        prices = fetch_historical_data(crypto_id)
        
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

# Tâche périodique
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

# Gestion des signaux d'arrêt et redémarrage automatique
def handle_shutdown_signal(signum, frame):
    logging.info("Arrêt de l'application (Signal: %s)", signum)
    logging.info("Redémarrage de l'application...")
    
    if platform.system() == "Darwin":  # Si macOS
        subprocess.call(["osascript", "-e", "tell application \"Terminal\" to quit"])
    
    time.sleep(2)
    sys.exit(0)

# Log des performances
def log_performance():
    pass

# Ajout du gestionnaire de signaux
signal.signal(signal.SIGTERM, handle_shutdown_signal)

# Route Flask
@app.route("/")
def home():
    return jsonify({"status": "Bot de trading opérationnel."})

# Lancer Flask sur un thread séparé
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
    # Démarrage de l'application Flask
    app.run(debug=True, host="127.0.0.1", port=PORT)