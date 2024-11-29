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
from gunicorn.app.base import BaseApplication
import threading
import tensorflow as tf
from tensorflow.keras import layers, models

# Variables d'environnement
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
PORT = int(os.getenv("PORT", 8000))  # Port par défaut 8000 si non défini

# Vérification des variables d'environnement
if not TELEGRAM_TOKEN or not CHAT_ID:
    raise ValueError("Les variables d'environnement TELEGRAM_TOKEN ou CHAT_ID ne sont pas définies.")

# Initialisation du bot Telegram
bot = Bot(token=TELEGRAM_TOKEN)

# Liste des cryptomonnaies à surveiller
CRYPTO_LIST = ["bitcoin", "ethereum", "cardano"]
PERFORMANCE_LOG = "trading_performance.csv"  # Log de performances

# Capital initial et gestion des positions
MAX_POSITION_PERCENTAGE = 0.1  # Investir un maximum de 10% du capital par position

# Initialisation de l'application Flask
app = Flask(__name__)

# Fonction pour récupérer les données de l'API CoinGecko
def fetch_crypto_data_coingecko(crypto_id, retries=3):
    url = f"https://api.coingecko.com/api/v3/coins/{crypto_id}/market_chart"
    params = {"vs_currency": "usd", "days": "1", "interval": "minute"}
    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            prices = [item[1] for item in data["prices"]]
            return np.array(prices)
        except requests.exceptions.RequestException as err:
            print(f"Erreur pour {crypto_id} via CoinGecko: {err}")
            if attempt < retries - 1:
                time.sleep(5)  # Attendre avant de réessayer
            else:
                bot.send_message(chat_id=CHAT_ID, text=f"Erreur lors de la récupération des données pour {crypto_id}.")
    return None

# Fonction pour récupérer les données de Binance
def fetch_crypto_data_binance(crypto_id, retries=3):
    url = f"https://api.binance.com/api/v3/klines"
    params = {"symbol": f"{crypto_id}USDT", "interval": "1m", "limit": 1000}
    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            prices = [float(item[4]) for item in data]  # Close prices
            return np.array(prices)
        except requests.exceptions.RequestException as err:
            print(f"Erreur pour {crypto_id} via Binance: {err}")
            if attempt < retries - 1:
                time.sleep(5)
            else:
                bot.send_message(chat_id=CHAT_ID, text=f"Erreur lors de la récupération des données pour {crypto_id} sur Binance.")
    return None

# Fonction pour récupérer les données de Kraken
def fetch_crypto_data_kraken(crypto_id, retries=3):
    url = f"https://api.kraken.com/0/public/OHLC"
    params = {"pair": f"{crypto_id}USD", "interval": 1, "since": int(time.time() - 86400)}
    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            prices = [float(item[4]) for item in data['result'][f"{crypto_id}USD"]]
            return np.array(prices)
        except requests.exceptions.RequestException as err:
            print(f"Erreur pour {crypto_id} via Kraken: {err}")
            if attempt < retries - 1:
                time.sleep(5)
            else:
                bot.send_message(chat_id=CHAT_ID, text=f"Erreur lors de la récupération des données pour {crypto_id} sur Kraken.")
    return None

# Fonction pour récupérer les données de KuCoin
def fetch_crypto_data_kucoin(crypto_id, retries=3):
    url = f"https://api.kucoin.com/api/v1/market/candles"
    params = {"symbol": f"{crypto_id}-USDT", "type": "1min", "limit": 1000}
    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            prices = [float(item[4]) for item in data['data']]  # Close prices
            return np.array(prices)
        except requests.exceptions.RequestException as err:
            print(f"Erreur pour {crypto_id} via KuCoin: {err}")
            if attempt < retries - 1:
                time.sleep(5)
            else:
                bot.send_message(chat_id=CHAT_ID, text=f"Erreur lors de la récupération des données pour {crypto_id} sur KuCoin.")
    return None

# Fonction pour récupérer des données financières via Yahoo Finance
def fetch_financial_data_yahoo(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": "1d", "interval": "1m"}
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        prices = [item[1] for item in data['chart']['result'][0]['indicators']['quote'][0]['close']]
        return np.array(prices)
    except requests.exceptions.RequestException as err:
        print(f"Erreur pour {symbol} via Yahoo Finance: {err}")
        return None

# Fonction pour récupérer des données économiques via Trading Economics
def fetch_economic_data_trading_economics():
    url = f"https://api.tradingeconomics.com/economic-calendar"
    params = {"c": "your_api_key_here", "country": "US"}  # Exemple pour les États-Unis
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data
    except requests.exceptions.RequestException as err:
        print(f"Erreur dans la récupération des données économiques: {err}")
        return None

# Fonction pour vérifier l'état du bot et envoyer une notification
def monitor_bot_status():
    try:
        # Tester l'envoi d'un message
        bot.send_message(chat_id=CHAT_ID, text="Le bot fonctionne correctement")
    except Exception as e:
        bot.send_message(chat_id=CHAT_ID, text=f"Erreur dans le bot: {str(e)}")
        raise  # Propager l'exception pour plus de visibilité

# Fonction de gestion de l'équilibre des positions
def balance_positions(current_position, capital):
    if current_position > capital * MAX_POSITION_PERCENTAGE:
        return capital * MAX_POSITION_PERCENTAGE  # Limiter la position
    return current_position

# Fonction pour créer un modèle de réseau de neurones (ML)
def create_neural_network(input_shape):
    model = models.Sequential([
        layers.Dense(64, activation='relu', input_shape=input_shape),
        layers.Dense(64, activation='relu'),
        layers.Dense(1, activation='sigmoid')  # Classification binaire (Achat / Vente)
    ])
    model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])
    return model

# Fonction pour entraîner le modèle de réseau de neurones
def train_ml_model(prices):
    # Préparation des données pour l'entraînement du modèle
    features = []
    target = []
    for i in range(20, len(prices)):
        features.append(prices[i-20:i])
        target.append(1 if prices[i] > prices[i-1] else 0)  # Signal d'achat si le prix monte
    features = np.array(features)
    target = np.array(target)
    
    # Normalisation des données
    scaler = StandardScaler()
    features = scaler.fit_transform(features.reshape(-1, 20))
    
    # Split des données en entrainement et test
    X_train, X_test, y_train, y_test = train_test_split(features, target, test_size=0.2, random_state=42)
    
    # Création du modèle
    model = create_neural_network((20,))
    
    # Entraînement du modèle
    model.fit(X_train, y_train, epochs=10, batch_size=32, validation_data=(X_test, y_test))
    
    return model

# Fonction pour analyser les signaux avec un modèle ML
def analyze_signals(prices, model):
    sma_short = prices[-10:].mean()
    sma_long = prices[-20:].mean()
    ema_short = prices[-12:].mean()
    ema_long = prices[-26:].mean()
    macd = ema_short - ema_long
    atr = prices[-20:].std()
    upper_band = sma_short + (2 * atr)
    lower_band = sma_short - (2 * atr)
    
    if prices[-1] > upper_band:
        return "SELL"
    elif prices[-1] < lower_band:
        return "BUY"
    else:
        return "HOLD"

# Thread pour lancer l'application Flask et la surveillance du bot simultanément
def run_flask_app():
    app.run(host='0.0.0.0', port=PORT)

def run_bot_monitoring():
    monitor_bot_status()

# Lance les threads pour Flask et Telegram
if __name__ == "__main__":
    with ThreadPoolExecutor() as executor:
        executor.submit(run_flask_app)
        executor.submit(run_bot_monitoring)