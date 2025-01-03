# Utilisation de Python 3.11 basé sur Debian
FROM python:3.11-slim

# Mettre à jour apt-get et installer les dépendances système nécessaires
RUN apt-get update && apt-get install -y \
    build-essential \
    wget \
    gcc \
    g++ \
    make \
    libtool \
    autoconf \
    automake \
    pkg-config \
    libc6-dev \
    libssl-dev \
    libsqlite3-dev \
    libffi-dev \
    python3-dev \
    curl \
    git \
    libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Télécharger et compiler TA-Lib depuis la source
RUN wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz && \
    tar -xzvf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib && \
    ./configure --prefix=/usr/local && \
    make && \
    make install && \
    cd .. && \
    rm -rf ta-lib-0.4.0-src.tar.gz ta-lib

# Ajouter TA-Lib aux chemins d'installations du système
ENV LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH

# Recharger la configuration des bibliothèques
RUN ldconfig

# Vérifier que TA-Lib est installé correctement
RUN python -c "import talib; print(talib.get_functions())"

# Définir le dossier de travail
WORKDIR /app

# Copier les fichiers nécessaires
COPY requirements.txt /app/requirements.txt
COPY bot2.py /app/bot2.py

# Ajouter les variables d'environnement
ENV DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/1321239629084627004/ryXqQGg0oeIxoiAHh21FMhCrUGLo1BOynDHtR3A-mtptklpbocJmL_-W8f2Ews3xHkXY
ENV PORT=8002

# Mettre à jour pip et installer les dépendances Python
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Exposer le port
EXPOSE 8002

# Lancer l'application
CMD ["python", "bot2.py"]