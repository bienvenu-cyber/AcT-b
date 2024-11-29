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
import asyncio
import tensorflow as tf
from tensorflow.keras import layers, models
import json

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

# Fichier de cache pour les données économiques
CACHE_FILE = "trading_economics_cache.json"
CALL_LIMIT = 50  # Limite des appels API par jour
calls_today = 0  # Compteur des appels API

# Fonction pour récupérer les données économiques via Trading Economics avec cache
def fetch_economic_data_trading_economics():
    global calls_today
    
    # Vérifier si le cache existe et est encore valide
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            cache = json.load(f)
        
        # Vérifier si les données sont encore valides (cache expiré après 24 heures)
        if time.time() - cache.get('timestamp', 0) < 86400:
            print("Utilisation des données en cache.")
            return cache.get('data', None)
    
    # Si le cache est expiré ou inexistant, faire un appel à l'API
    if calls_today >= CALL_LIMIT:
        print("Limite d'appels API atteinte pour la journée.")
        return None  # Retourner None si la limite d'appels est atteinte
    
    url = "https://api.tradingeconomics.com/economic-calendar"
    params = {"c": "your_api_key_here", "country": "US"}  # Exemple pour les États-Unis
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Mettre à jour le cache avec les nouvelles données
        with open(CACHE_FILE, 'w') as f:
            json.dump({"timestamp": time.time(), "data": data}, f)
        
        calls_today += 1  # Incrémenter le compteur d'appels
        
        return data
    except requests.exceptions.RequestException as err:
        print(f"Erreur dans la récupération des données économiques: {err}")
        return None

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
                asyncio.run(bot.send_message(chat_id=CHAT_ID, text=f"Erreur lors de la récupération des données pour {crypto_id}."))
    return None

# Fonction pour vérifier l'état du bot et envoyer une notification
async def monitor_bot_status():
    try:
        # Tester l'envoi d'un message
        await bot.send_message(chat_id=CHAT_ID, text="Le bot fonctionne correctement")
    except Exception as e:
        await bot.send_message(chat_id=CHAT_ID, text=f"Erreur dans le bot: {str(e)}")
        raise  # Propager l'exception pour plus de visibilité

# Fonction pour gérer l'équilibre des positions
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

# Fonction pour prédire les signaux de trading
def predict_signal(model, data):
    return model.predict(data)

# Main loop pour exécuter les opérations de trading toutes les 5 minutes
async def trading_loop():
    while True:
        # Fetch des données crypto
        crypto_data = fetch_crypto_data_coingecko("bitcoin")
        
        # Entraîner et prédire le signal
        if crypto_data is not None:
            model = train_ml_model(crypto_data)
            signal = predict_signal(model, crypto_data[-20:])
            print("Signal de trading:", signal)
        
        await asyncio.sleep(300)  # Attendre 5 minutes avant le prochain trade

# Lancer le serveur Flask
def run_flask_app():
    app.run(host="0.0.0.0", port=PORT)

# Lancer le monitoring du bot dans un thread
monitor_thread = threading.Thread(target=lambda: asyncio.run(monitor_bot_status()))
monitor_thread.start()

# Lancer Flask dans un thread séparé
flask_thread = threading.Thread(target=run_flask_app)
flask_thread.start()

# Démarrer le bot de trading dans la boucle
asyncio.run(trading_loop())