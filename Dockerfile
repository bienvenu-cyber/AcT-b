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

# Installation de TA-Lib depuis les sources
RUN cd /tmp && \
    wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz && \
    tar -xvf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib/ && \
    ./configure && \
    make && \
    make install && \
    rm -rf /tmp/ta-lib-0.4.0-src.tar.gz && \
    rm -rf /tmp/ta-lib && \
    ln -s /usr/local/lib/libta_lib.so.0 /usr/lib/libta_lib.so.0 && \
    ldconfig

# Définir le répertoire de travail
WORKDIR /app

# Mettre à jour pip
RUN pip install --no-cache-dir --upgrade pip

# Copier les fichiers nécessaires dans l'image Docker
COPY requirements.txt .
COPY bot2.py .

# Modifier le requirements.txt pour adapter les versions
RUN sed -i 's/tensorflow==2.18.0/tensorflow==2.15.0/' requirements.txt && \
    sed -i 's/psycopg2==2.9.7/psycopg2-binary==2.9.7/' requirements.txt && \
    sed -i '/TA-Lib/d' requirements.txt

# Installer TA-Lib et autres dépendances Python
RUN pip install --no-cache-dir numpy && \
    pip install --no-cache-dir TA-Lib==0.4.24 && \
    pip install --no-cache-dir -r requirements.txt

# Ajouter les variables d'environnement
ENV DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/1321239629084627004/ryXqQGg0oeIxoiAHh21FMhCrUGLo1BOynDHtR3A-mtptklpbocJmL_-W8f2Ews3xHkXY
ENV PORT=8002

# Exposer le port
EXPOSE 8002

# Lancer l'application
CMD ["python", "bot2.py"]
