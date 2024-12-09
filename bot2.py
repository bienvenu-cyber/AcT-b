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

logging.basicConfig(level=logging.DEBUG)
# Récupération des données historiques pour les cryptomonnaies
def fetch_historical_data(crypto_symbol, currency="USD", interval="hour", limit=2000):
    base_url = "https://min-api.cryptocompare.com/data/v2/"
    
    # Déterminer le bon endpoint en fonction de l'intervalle
    if interval == "minute":
        endpoint = "histominute"
    elif interval == "hour":
        endpoint = "histohour"
    elif interval == "day":
        endpoint = "histoday"
    else:
        raise ValueError("Intervalle non supporté. Utilisez 'minute', 'hour' ou 'day'.")
    
    url = f"{base_url}{endpoint}"
    params = {
        "fsym": crypto_symbol.upper(),
        "tsym": currency.upper(),
        "limit": limit,
        "api_key": "70001b698e6a3d349e68ba1b03e7489153644e38c5026b4a33d55c8e460c7a3c"
    }

    try:
        # Faire la requête
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        # Vérification de la réponse de l'API
        if data["Response"] == "Success" and "Data" in data and "Data" in data["Data"]:
            prices = [{
                "time": item["time"],
                "open": item["open"],
                "high": item["high"],
                "low": item["low"],
                "close": item["close"],
                "volume": item["volumeto"]
            } for item in data["Data"]["Data"]]
            
            # Conversion en arrays NumPy pour TA-Lib
            opens = np.array([item["open"] for item in prices])
            highs = np.array([item["high"] for item in prices])
            lows = np.array([item["low"] for item in prices])
            closes = np.array([item["close"] for item in prices])
            volumes = np.array([item["volume"] for item in prices])

            # Exemple d'utilisation de TA-Lib pour le calcul de l'Indicateur Technique
            # Calcul de la moyenne mobile simple (SMA) sur 50 périodes
            sma = talib.SMA(closes, timeperiod=50)
            logging.debug(f"SMA calculée: {sma[-5:]}")  # Affichage des 5 derniers SMA calculés
            
            # Vous pouvez calculer d'autres indicateurs techniques ici (RSI, MACD, etc.)
            
            return prices
        else:
            logging.error(f"Erreur API pour {crypto_symbol}: {data.get('Message', 'Erreur inconnue')}")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Erreur lors de la récupération des données pour {crypto_symbol}: {e}")
        return None

# Fonction de calcul des indicateurs avec TA-Lib
def calculate_indicators(prices):
    if len(prices) < 26:
        raise ValueError("Pas assez de données pour calculer les indicateurs.")
    
    # Convertir les prix en tableau numpy pour TA-Lib
    prices_array = np.array(prices)
    
    # Moyennes Mobiles (SMA et EMA)
    sma_short = talib.SMA(prices_array, timeperiod=10)[-1]  # SMA sur 10 périodes
    sma_long = talib.SMA(prices_array, timeperiod=20)[-1]   # SMA sur 20 périodes
    
    # EMA
    ema_short = talib.EMA(prices_array, timeperiod=12)[-1]  # EMA sur 12 périodes
    ema_long = talib.EMA(prices_array, timeperiod=26)[-1]   # EMA sur 26 périodes
    
    # MACD : Différence entre les EMA à court terme et à long terme
    macd, macd_signal, macd_hist = talib.MACD(prices_array, fastperiod=12, slowperiod=26, signalperiod=9)
    
    # ATR (Average True Range) pour la volatilité
    atr = talib.ATR(prices_array, prices_array, prices_array, timeperiod=14)[-1]  # ATR sur 14 périodes
    
    # Bandes de Bollinger : Calculées en fonction de la SMA et de l'ATR
    upper_band, middle_band, lower_band = talib.BBANDS(prices_array, timeperiod=20, nbdevup=2, nbdevdn=2, matype=0)
    
    # RSI (Relative Strength Index) sur 14 périodes
    rsi = talib.RSI(prices_array, timeperiod=14)[-1]
    
    # Stochastique : Calculs classiques avec %K et %D
    slowk, slowd = talib.STOCH(prices_array, prices_array, prices_array, fastk_period=14, slowk_period=3, slowd_period=3)
    
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

# Exemple pour récupérer les prix réels (exemple fictif, remplacer par vos méthodes réelles)
prices = get_crypto_prices()  # Remplacer par votre méthode pour obtenir les prix du marché

# Appel de la fonction d'analyse
signal = analyze_signals(prices)
print(signal)

# Appeler la fonction analyze_signals avec la variable prices définie
decision = analyze_signals(prices)
print(decision)  # Affichera la décision d'achat/vente

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