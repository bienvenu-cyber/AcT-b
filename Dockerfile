# Utiliser une image de base Python
FROM python:3.10-slim

# Installer les dépendances système nécessaires
RUN apt-get update && apt-get install -y \
    build-essential \
    wget \
    curl \
    pkg-config \
    git \
    libblas-dev \
    liblapack-dev \
    libhdf5-dev \
    gfortran \
    postgresql \
    postgresql-contrib \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Installation de TA-Lib
RUN cd /tmp && \
    wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz && \
    tar -xzf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib/ && \
    ./configure && \
    make && \
    make install && \
    cd .. && \
    rm -rf ta-lib-0.4.0-src.tar.gz ta-lib/ && \
    ldconfig

# Définir le répertoire de travail
WORKDIR /app

# Mettre à jour pip
RUN pip install --no-cache-dir --upgrade pip

# Copier les fichiers nécessaires dans l'image Docker
COPY requirements.txt .
COPY bot2.py .

# Modifier le requirements.txt
RUN sed -i 's/tensorflow==2.18.0/tensorflow==2.15.0/' requirements.txt && \
    sed -i 's/psycopg2==2.9.7/psycopg2-binary==2.9.7/' requirements.txt

# Installer les dépendances Python
RUN pip install --no-cache-dir numpy && \
    pip install --no-cache-dir TA-Lib && \
    pip install --no-cache-dir -r requirements.txt

# Ajouter les variables d'environnement
ENV DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/1321239629084627004/ryXqQGg0oeIxoiAHh21FMhCrUGLo1BOynDHtR3A-mtptklpbocJmL_-W
