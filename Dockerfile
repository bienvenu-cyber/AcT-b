# Utiliser une image de base Python
FROM python:3.11-slim

# Mettre à jour pip
RUN pip install --upgrade pip

# Installer les dépendances système nécessaires pour psycopg2 et TA-Lib
RUN apt-get update && apt-get install -y \
    build-essential \
    wget \
    libpq-dev \
    libtool \
    autoconf \
    && rm -rf /var/lib/apt/lists/*

# Télécharger et installer TA-Lib à partir des sources
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

# Ajouter les variables d'environnement (TOKEN et CHAT_ID)
ENV TELEGRAM_TOKEN=8052620219:AAEnP3ksiFUV3dEPf7Fpzyu3W_-Kg4jfXQ0
ENV CHAT_ID=1963161645
ENV PORT=8001

# Installer les dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# Exposer le port sur lequel l'application écoute
EXPOSE 8001

# Commande de démarrage pour python
CMD ["python", "bot2.py"]