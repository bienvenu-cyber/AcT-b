# Utilisation de Python 3.11 basé sur Debian
FROM python:3.11

# Installer les dépendances système
RUN apt-get update && apt-get install -y \
    build-essential \
    wget \
    libpq-dev \
    libtool \
    autoconf \
    automake \
    pkg-config \
    libffi-dev \
    python3-dev \
    curl \
    git \
    gcc \
    make \
    cmake \
    libc6-dev \
    libssl-dev \
    libsqlite3-dev && \
    rm -rf /var/lib/apt/lists/*

# Télécharger et compiler TA-Lib
RUN wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz && \
    tar -xzvf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib && \
    ./configure --prefix=/usr/local && \
    make && \
    make install && \
    cd .. && \
    rm -rf ta-lib-0.4.0-src.tar.gz ta-lib

# Vérifier si TA-Lib est bien installé
RUN ls /usr/local/lib/ | grep libta_lib || echo "TA-Lib not found"

# Copier la bibliothèque pour que pip puisse la trouver
RUN cp /usr/local/lib/libta_lib.so* /usr/lib/

# Ajouter TA-Lib aux bibliothèques système
ENV LD_LIBRARY_PATH=/usr/local/lib
RUN echo "/usr/local/lib" > /etc/ld.so.conf.d/ta-lib.conf && ldconfig

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

# Vérifier que TA-Lib fonctionne
RUN python -c "import talib; print(talib.get_functions())"

# Exposer le port
EXPOSE 8002

# Lancer l'application
CMD ["python", "bot2.py"]