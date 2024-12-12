# Utilise une image de base Python
FROM python:3.11-slim

# Définir le répertoire de travail
WORKDIR /app

# Copier les fichiers nécessaires dans l'image Docker
COPY requirements.txt /app/requirements.txt
COPY bot2.py /app/bot2.py

# Ajouter les variables d'environnement (TOKEN et CHAT_ID)
ENV TOKEN=8052620219:AAEnP3ksiFUV3dEPf7Fpzyu3W_-Kg4jfXQ0
ENV CHAT_ID=1963161645

# Installer les dépendances
RUN pip install --no-cache-dir -r requirements.txt

# Exposer le port sur lequel l'application écoute
EXPOSE 8001

# Commande de démarrage pour Gunicorn
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8001", "--keep-alive", "120", "--log-level", "debug", "bot2:app"]