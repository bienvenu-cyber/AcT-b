# Utiliser une image de base Python
FROM python:3.11-slim

# Mettre à jour pip et installer les dépendances système
RUN apt-get update && apt-get install -y \
    build-essential \
    wget \
    libpq-dev \
    libtool \
    autoconf && \
    rm -rf /var/lib/apt/lists/*

# Télécharger et installer TA-Lib
RUN wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz && \
    tar -xzvf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib && \
    ./configure --prefix=/usr && \
    make && \
    make install && \
    cd .. && \
    rm -rf ta-lib-0.4.0-src.tar.gz ta-lib

# Définir le répertoire de travail
WORKDIR /app

# Copier les fichiers nécessaires dans l'image Docker
COPY requirements.txt /app/requirements.txt
COPY bot2.py /app/bot2.py

# Ajouter les variables d'environnement
ENV DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/1321239629084627004/ryXqQGg0oeIxoiAHh21FMhCrUGLo1BOynDHtR3A-mtptklpbocJmL_-W8f2Ews3xHkXY
ENV PORT=8002

# Installer les dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# Exposer le port sur lequel l'application écoute
EXPOSE 8002

# Commande de démarrage pour python
CMD ["python", "bot2.py"]