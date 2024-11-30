import os
import requests
import numpy as np
import json
import time
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from telegram import Bot
from flask import Flask
from tensorflow.keras import layers, models

# Variables d'environnement
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
PORT = int(os.getenv("PORT", 8001))  # Port par défaut 8001 si non défini
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY")  # Clé API pour Alpha Vantage

# Vérification des variables d'environnement
if not TELEGRAM_TOKEN or not CHAT_ID or not ALPHA_VANTAGE_API_KEY:
    raise ValueError("Les variables d'environnement TELEGRAM_TOKEN, CHAT_ID ou ALPHA_VANTAGE_API_KEY ne sont pas définies.")

# Initialisation du bot Telegram
bot = Bot(token=TELEGRAM_TOKEN)

# Initialisation de l'application Flask
app = Flask(__name__)

# Variables globales
CACHE_FILE = "alpha_vantage_cache.json"
CALL_LIMIT = 50  # Limite des appels API par jour
calls_today = 0  # Compteur des appels API
CRYPTO_LIST = ["bitcoin", "ethereum", "cardano"]  # Liste des cryptomonnaies à surveiller

# Fonction pour récupérer les données de CoinGecko
def fetch_crypto_data_coingecko(crypto_id, retries=3):
    url = f"https://api.coingecko.com/api/v3/coins/{crypto_id}/market_chart"
    params = {
        "vs_currency": "usd",
        "days": "1",
        "interval": "minute"
    }
    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            prices = [item[1] for item in data["prices"]]
            return np.array(prices)
        except requests.exceptions.RequestException as err:
            print(f"Erreur pour {crypto_id} via CoinGecko : {err}")
            time.sleep(5) if attempt < retries - 1 else None
    return None

# Fonction pour créer un réseau de neurones
def create_neural_network(input_shape):
    model = models.Sequential([
        layers.Dense(64, activation='relu', input_shape=input_shape),
        layers.Dense(64, activation='relu'),
        layers.Dense(1, activation='sigmoid')  # Classification binaire (Achat/Vente)
    ])
    model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])
    return model

# Fonction d'entraînement du modèle
def train_ml_model(prices):
    features, target = [], []
    for i in range(20, len(prices)):
        features.append(prices[i-20:i])
        target.append(1 if prices[i] > prices[i-1] else 0)  # Achat si prix monte
    features, target = np.array(features), np.array(target)

    scaler = StandardScaler()
    features = scaler.fit_transform(features.reshape(-1, 1)).reshape(features.shape)

    X_train, X_test, y_train, y_test = train_test_split(features, target, test_size=0.2, random_state=42)

    model = create_neural_network((X_train.shape[1],))
    model.fit(X_train, y_train, epochs=5, batch_size=32, validation_data=(X_test, y_test))
    return model

# Fonction pour envoyer un message via Telegram
def send_telegram_message(message):
    try:
        bot.send_message(chat_id=CHAT_ID, text=message)
    except Exception as e:
        print(f"Erreur d'envoi de message Telegram: {e}")

# Fonction pour envoyer un signal de trading (Achat/Vente)
def send_trading_signal(prediction):
    if prediction == 1:
        message = "Signal d'achat : Le modèle prédit que le prix va augmenter."
    else:
        message = "Signal de vente : Le modèle prédit que le prix va diminuer."
    
    send_telegram_message(message)

# Fonction Flask pour vérifier l'état du bot
@app.route("/")
def status():
    return "Bot opérationnel et serveur en cours d'exécution."

# Fonction de surveillance des prix en continu
def monitor_prices():
    while True:
        for crypto_id in CRYPTO_LIST:
            prices = fetch_crypto_data_coingecko(crypto_id)
            if prices is not None:
                model = train_ml_model(prices)
                prediction = model.predict(prices[-1].reshape(1, -1))  # Dernière valeur pour prédiction
                send_trading_signal(int(prediction[0]))  # Envoie du message
        time.sleep(60)  # Attendre 60 secondes avant de vérifier à nouveau

# Lancer Flask et surveillance des prix en parallèle
if __name__ == "__main__":
    # Lancer le serveur Flask
    from threading import Thread
    thread = Thread(target=app.run, kwargs={'debug': False, 'host': '0.0.0.0', 'port': PORT})
    thread.start()

    # Démarre la surveillance des prix
    monitor_prices()