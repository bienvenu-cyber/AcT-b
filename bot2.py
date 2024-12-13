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

# Exécution du programme asynchrone
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(main())

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

# Appel de la fonction d'analyse
async def main():
    # Appel de la fonction d'analyse
    for crypto in CRYPTO_LIST:
        prices, opens, highs, lows, closes, volumes = await fetch_historical_data(crypto)
        
        if prices:
            signal = analyze_signals(prices)
            print(f"Signal pour {crypto}: {signal}")
        else:
            print(f"Erreur de récupération des données pour {crypto}.")

# Appeler la fonction analyze_signals avec la variable prices définie
async def main():
    for crypto in CRYPTO_LIST:  # CRYPTO_LIST contient les cryptomonnaies à analyser
        try:
            # Récupérer les données
            prices, opens, highs, lows, closes, volumes = await fetch_historical_data(crypto)
            
            if prices:  # Vérifiez si des données ont été récupérées
                # Afficher les 5 premiers éléments des prix pour validation
                print(f"Premiers 5 éléments de données pour {crypto}: {prices[:5]}")  
                
                # Appeler la fonction analyze_signals avec la variable prices définie
                decision = analyze_signals(prices)
                print(f"Décision pour {crypto}: {decision}")  # Affichera la décision d'achat/vente
            else:
                print(f"Les données pour {crypto} sont vides ou invalides.")
        except Exception as e:
            print(f"Erreur lors du traitement pour {crypto}: {e}")

# Événement global pour gérer l'arrêt des tâches
STOP_EVENT = asyncio.Event()

# Fonction principale de vérification périodique
async def periodic_price_check():
    while not STOP_EVENT.is_set():  # Vérifie si STOP_EVENT est activé
        for symbol in CRYPTO_LIST:
            prices = fetch_historical_data(symbol, CURRENCY)
            if prices:
                signal, indicators = analyze_signals(prices)
                logging.info(f"Signal généré pour {symbol}/{CURRENCY}: {signal}")
                
                if signal:
                    message = f"Signal de trading pour {symbol}/{CURRENCY}: {signal}"
                    await send_telegram_message(CHAT_ID, message)
            else:
                logging.error(f"Impossible d'analyser les données pour {symbol}, données non disponibles.")
        
        await asyncio.sleep(900)  # Pause de 15 minutes

# Appel de la fonction périodique avec gestion de l'arrêt
async def start_periodic_task():
    try:
        # Crée une liste de tâches asyncio
        tasks = [
            asyncio.create_task(periodic_price_check())
        ]

        # Attend que toutes les tâches s'exécutent jusqu'à l'arrêt
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logging.info("Tâches asyncio annulées.")
    finally:
        STOP_EVENT.set()  # Déclenche l'arrêt propre

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
    
    # Vérification si le fichier existe ou non avant de l'écrire
    if not os.path.exists(SIGNAL_LOG):
        df.to_csv(SIGNAL_LOG, index=False)
    else:
        df.to_csv(SIGNAL_LOG, mode="a", header=False, index=False)

    logging.debug(f"Signal logué : {signal} à {prices[-1]}")

# Fonction asynchrone d'envoi de message Telegram
async def send_telegram_message(chat_id, message):
    try:
        logging.debug(f"Envoi du message à Telegram pour le chat {chat_id}: {message}")
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        
        # Utilisation d'aiohttp pour envoyer des messages de manière non-bloquante
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params={"chat_id": chat_id, "text": message}) as response:
                response.raise_for_status()  # Vérifie si la requête a échoué
                logging.debug(f"Message envoyé avec succès. Réponse: {await response.json()}")
    except aiohttp.ClientResponseError as e:
        logging.error(f"Erreur HTTP lors de l'envoi du message à Telegram: {e}")
    except aiohttp.ClientConnectionError as e:
        logging.error(f"Erreur de connexion lors de l'envoi du message à Telegram: {e}")
    except aiohttp.ClientError as e:
        logging.error(f"Erreur générale lors de l'envoi du message à Telegram: {e}")
    except Exception as e:
        logging.error(f"Erreur inattendue lors de l'envoi du message à Telegram: {e}")
    finally:
        # Log de la mémoire et des performances
        log_memory_usage()
        # Attendre avant la prochaine itération (900 secondes = 15 minutes) en cas d'erreur
        await asyncio.sleep(900)

# Tâche périodique de trading
async def trading_task():
    last_sent_signals = {}  # Dictionnaire pour suivre les signaux envoyés
    
    while True:
        logging.info("Début d'une nouvelle itération de trading.")
        
        # Récupérer les prix pour chaque crypto
        tasks = []
        for crypto in CRYPTO_LIST:
            prices = fetch_historical_data(crypto, CURRENCY)
            if prices:
                # Analyser les signaux de trading pour la crypto
                signal, indicators = analyze_signals(prices)
                
                # Si un signal est généré (Achat/Vente)
                if signal:
                    # Vérifier si ce signal a déjà été envoyé récemment
                    if last_sent_signals.get(crypto) == signal:
                        logging.info(f"Signal déjà envoyé pour {crypto}. Ignoré.")
                        continue  # Ignorer si signal déjà envoyé
                    
                    # Mettre à jour le signal envoyé
                    last_sent_signals[crypto] = signal
                    
                    # Calcul du Stop Loss et Take Profit pour le dernier prix (prix d'entrée)
                    entry_price = prices[-1]["close"]  # On utilise ici le dernier prix de clôture
                    sl_price, tp_price = calculate_sl_tp(entry_price)

                    # Créer le message Telegram avec le signal, le prix d'entrée, le SL et TP
                    message = f"Signal de trading pour {crypto}/{CURRENCY}: {signal}\n"
                    message += f"Prix d'entrée: {entry_price}\n"
                    message += f"Stop Loss: {sl_price}\n"
                    message += f"Take Profit: {tp_price}\n"
                    
                    # Envoi du message Telegram avec toutes les informations
                    await send_telegram_message(CHAT_ID, message)

                logging.info(f"Signal généré pour {crypto}/{CURRENCY}: {signal}")
            else:
                logging.error(f"Impossible d'analyser les données pour {crypto}, données non disponibles.")
        
        # Attendre un certain délai avant la prochaine itération (par exemple, 10 minutes)
        await asyncio.sleep(600)  # 900 secondes = 15 minutes

# Fonction pour surveiller l'utilisation de la mémoire
def log_memory_usage():
    current, peak = tracemalloc.get_traced_memory()
    logging.info(f"Utilisation de la mémoire - Actuelle: {current / 10**6} MB, Pic: {peak / 10**6} MB")
    tracemalloc.clear_traces()

# Fonction de sécurité pour le trading task
async def safe_trading_task():
    while True:  # Essaye de redémarrer la tâche tant que cela échoue
        try:
            await trading_task()
            break  # Sort de la boucle si tout fonctionne
        except Exception as e:
            logging.error(f"Erreur globale dans trading_task: {str(e)}", exc_info=True)
            await notify_error(f"Erreur critique détectée : {str(e)}")  # Notification d'erreur
            await asyncio.sleep(10)  # Attends un peu avant de réessayer

# Log des performances
def log_performance():
    # Exemple simple pour loguer l'utilisation du CPU et de la mémoire
    cpu_usage = psutil.cpu_percent(interval=1)  # Utilisation du CPU sur 1 seconde
    memory_info = psutil.virtual_memory()  # Informations sur la mémoire

    # Log des performances
    logging.info(f"Utilisation CPU: {cpu_usage}%")
    logging.info(f"Utilisation mémoire: {memory_info.percent}%")
    logging.info(f"RAM totale: {memory_info.total / (1024 * 1024)} MB")
    logging.info(f"RAM disponible: {memory_info.available / (1024 * 1024)} MB")

# Fonction pour gérer l'arrêt propre des tâches asynchrones
async def handle_shutdown_signal(signum, frame):
    logging.info(f"Signal d'arrêt reçu : {signum}")
    
    # Annuler toutes les tâches en cours, sauf la tâche courante
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    
    for task in tasks:
        task.cancel()
    
    # Attendre la fin des tâches annulées
    await asyncio.gather(*tasks, return_exceptions=True)
    
    logging.info("Arrêt propre du bot.")
    sys.exit(0)

# Fonction pour configurer les gestionnaires de signaux
def configure_signal_handlers(loop):
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda sig=sig: asyncio.create_task(handle_shutdown_signal(sig, None)))

app = Flask(__name__)

# Route Flask
@app.route("/")
def home():
    logging.info("Requête reçue sur '/'")
    return jsonify({"status": "Bot de trading opérationnel."})

# Lancer Flask dans un thread séparé
async def run_flask():
    """Exécute Flask dans un thread séparé via asyncio."""
    await asyncio.to_thread(app.run, host='0.0.0.0', port=PORT, threaded=True, use_reloader=False, debug=True)

# Démarrer les tâches asyncio et Flask en parallèle
async def main():
    # Lancer les tâches asyncio
    await asyncio.gather(
        trading_task(),  # Ta tâche principale
        run_flask()      # Flask
    )

# Point d'entrée principal
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Envoi du message de test au démarrage
    async def startup():
        try:
            # Envoi du message de démarrage
            await send_telegram_message(CHAT_ID, "Le bot de trading a démarré avec succès.")
        except Exception as e:
            logging.error(f"Erreur lors de l'envoi du message de démarrage : {e}")

    # Lancer la fonction de démarrage avant d'exécuter la tâche principale
    asyncio.run(startup())  # Envoi du message de test
    try:
        asyncio.run(main())  # Démarrage de la boucle principale de trading
    except KeyboardInterrupt:
        logging.info("Exécution interrompue par l'utilisateur.")
    except Exception as e:
        logging.error(f"Erreur inattendue : {e}")
    finally:
        logging.info("Arrêt complet.")