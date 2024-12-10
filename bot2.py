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
CRYPTO_LIST = ["BTC", "ETH"]
MAX_POSITION_PERCENTAGE = 0.1
CAPITAL = 100
PERFORMANCE_LOG = "trading_performance.csv"
SIGNAL_LOG = "signal_log.csv"

# Récupération des données historiques pour les cryptomonnaies
def fetch_historical_data(crypto_symbol, currency="USD", interval="hour", limit=300):
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

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        if data["Response"] == "Success":
            prices = [item["close"] for item in data["Data"]["Data"]]
            logging.debug(f"Prix récupérés pour {crypto_symbol}/{currency}: {prices}")
            return prices
        else:
            logging.error(f"Erreur API pour {crypto_symbol}: {data.get('Message', 'Erreur inconnue')}")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Erreur lors de la récupération des données pour {crypto_symbol}: {e}")
        return None

# Fonction de calcul des indicateurs
def calculate_indicators(prices):
    if len(prices) < 26:
        raise ValueError("Pas assez de données pour calculer les indicateurs.")
    
    # Moyennes Mobiles (SMA et EMA)
    sma_short = np.mean(prices[-10:])  # Moyenne mobile simple sur 10 périodes
    sma_long = np.mean(prices[-20:])   # Moyenne mobile simple sur 20 périodes
    
    # Calcul de l'EMA avec une méthode exponentielle correcte
    def ema(prices, period):
        multiplier = 2 / (period + 1)
        ema_values = [np.mean(prices[:period])]
        for price in prices[period:]:
            ema_values.append((price - ema_values[-1]) * multiplier + ema_values[-1])
        return ema_values[-1]

    ema_short = ema(prices[-12:], 12)  # EMA sur 12 périodes
    ema_long = ema(prices[-26:], 26)   # EMA sur 26 périodes
    
    # MACD : Différence entre les EMA à court terme et à long terme
    macd = ema_short - ema_long
    
    # ATR (Average True Range) pour la volatilité
    high_prices = np.array(prices[-20:])  # Plages hautes
    low_prices = np.array(prices[-20:])   # Plages basses
    close_prices = np.array(prices[-20:]) # Clôtures
    tr = np.maximum(high_prices - low_prices, 
                    np.maximum(abs(high_prices - close_prices[1:]), abs(low_prices - close_prices[:-1])))
    atr = np.mean(tr)  # ATR sur 20 périodes
    
    # Bandes de Bollinger : Calculées en fonction de la SMA et de l'ATR
    upper_band = sma_short + (2 * atr)  # Bande supérieure
    lower_band = sma_short - (2 * atr)  # Bande inférieure
    
    # RSI (Relative Strength Index) sur 14 périodes
    gains = [prices[i] - prices[i-1] for i in range(1, 14) if prices[i] > prices[i-1]]
    losses = [prices[i-1] - prices[i] for i in range(1, 14) if prices[i] < prices[i-1]]
    average_gain = np.mean(gains) if gains else 0
    average_loss = np.mean(losses) if losses else 0
    rs = average_gain / average_loss if average_loss != 0 else 0
    rsi = 100 - (100 / (1 + rs))
    
    # Stochastique : Calculs classiques avec %K et %D
    lowest_low = min(prices[-14:])
    highest_high = max(prices[-14:])
    stochastic_k = ((prices[-1] - lowest_low) / (highest_high - lowest_low)) * 100 if highest_high != lowest_low else 0
    
    # Calcul du %D (moyenne mobile de %K sur 3 périodes)
    if len(prices) >= 17:  # Il faut au moins 17 données pour calculer le %D
        stochastic_d = np.mean([((prices[i] - min(prices[i-14:i])) / (max(prices[i-14:i]) - min(prices[i-14:i]))) * 100 for i in range(-3, 0)])
    else:
        stochastic_d = stochastic_k  # Si pas assez de données, utiliser %K
    
    logging.debug(f"Indicateurs calculés : SMA_short={sma_short}, SMA_long={sma_long}, EMA_short={ema_short}, EMA_long={ema_long}, MACD={macd}, ATR={atr}, Upper_Band={upper_band}, Lower_Band={lower_band}, RSI={rsi}, Stochastic_K={stochastic_k}, Stochastic_D={stochastic_d}")
    
    return {
        "SMA_short": sma_short,
        "SMA_long": sma_long,
        "EMA_short": ema_short,
        "EMA_long": ema_long,
        "MACD": macd,
        "ATR": atr,
        "Upper_Band": upper_band,
        "Lower_Band": lower_band,
        "RSI": rsi,
        "Stochastic_K": stochastic_k,
        "Stochastic_D": stochastic_d,
    }

# Calcul du Stop Loss et Take Profit en pourcentage du prix d'entrée
def calculate_sl_tp(entry_price, sl_percent=0.02, tp_percent=0.05):
    """
    Calcule le Stop Loss (SL) et Take Profit (TP) en fonction du prix d'entrée.
    Le SL est défini à 2% du prix d'entrée, le TP à 5%.
    """
    # Calcul du Stop Loss et Take Profit en pourcentage du prix d'entrée
    sl_price = entry_price - (sl_percent * entry_price)  # Stop Loss à 2% en dessous du prix d'entrée
    tp_price = entry_price + (tp_percent * entry_price)  # Take Profit à 5% au-dessus du prix d'entrée

    # Retourner les prix calculés
    logging.debug(f"Stop Loss calculé à : {sl_price}, Take Profit calculé à : {tp_price} (Prix d'entrée : {entry_price})")

    return sl_price, tp_price

# Fonction de décision d'achat/vente basée sur les indicateurs
def analyze_signals(prices):
    indicators = calculate_indicators(prices)
    
    # Logique de décision d'achat/vente (exemple simplifié)
    if indicators['RSI'] < 30 and indicators['Stochastic_K'] < 20:
        decision = "Acheter"  # Condition de survente
    elif indicators['RSI'] > 70 and indicators['Stochastic_K'] > 80:
        decision = "Vendre"   # Condition de surachat
    elif indicators['MACD'] > 0 and indicators['EMA_short'] > indicators['EMA_long']:
        decision = "Acheter"  # Si le MACD est positif et l'EMA court terme est au-dessus de l'EMA long terme
    elif indicators['MACD'] < 0 and indicators['EMA_short'] < indicators['EMA_long']:
        decision = "Vendre"   # Si le MACD est négatif et l'EMA court terme est en dessous de l'EMA long terme
    else:
        decision = "Ne rien faire"  # Aucune condition claire d'achat ou de vente

    logging.debug(f"Décision d'action : {decision}")
    return decision

# Fonction principale de vérification périodique
def periodic_price_check(symbol, currency):
    while True:
        prices = fetch_historical_data(symbol, currency)
        if prices:
            signal, indicators = analyze_signals(prices)
            logging.info(f"Signal généré pour {symbol}/{currency}: {signal}")
        else:
            logging.error("Impossible d'analyser les données, données non disponibles.")
        time.sleep(900)  # Attendre 15 minutes  avant la prochaine vérification

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
        
# Tâche périodique
async def trading_task():
    while True:
        logging.info("Début d'une nouvelle itération de trading.")
        tasks = [analyze_signals(prices) for crypto in CRYPTO_LIST]
        await asyncio.gather(*tasks)
        log_memory_usage()
        await asyncio.sleep(900)

# Fonction pour surveiller l'utilisation de la mémoire
def log_memory_usage():
    current, peak = tracemalloc.get_traced_memory()
    logging.info(f"Utilisation de la mémoire - Actuelle: {current / 10**6} MB, Pic: {peak / 10**6} MB")
    tracemalloc.clear_traces()

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

from flask import Flask, jsonify
from threading import Thread

app = Flask(__name__)

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
        asyncio.run(run_flask())
        asyncio.run(safe_trading_task())
    except KeyboardInterrupt:
        logging.info("Exécution interrompue manuellement.")
        sys.exit(0)