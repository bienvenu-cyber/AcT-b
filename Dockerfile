# Utilisation de Python 3.11 basé sur Debian
FROM python:3.11

# Vérifier les sources avant modification
RUN cat /etc/apt/sources.list

# Mettre à jour les sources apt-get et forcer l'utilisation d'un miroir différent
RUN echo "deb http://mirrors.kernel.org/debian/ stable main" > /etc/apt/sources.list

# Mettre à jour apt-get et installer les dépendances nécessaires
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
    libpq-dev \
    libta-lib0-dev \
    && rm -rf /var/lib/apt/lists/*

# Installer TA-Lib Python via pip (le module Python pour interagir avec la bibliothèque native)
RUN pip install --no-cache-dir TA-Lib

# Définir le dossier de travail
WORKDIR /app

# Copier les fichiers nécessaires
COPY requirements.txt /app/requirements.txt
COPY bot2.py /app/bot2.py

# Installer les dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# Ajouter les variables d'environnement
ENV DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/1321239629084627004/ryXqQGg0oeIxoiAHh21FMhCrUGLo1BOynDHtR3A-mtptklpbocJmL_-W8f2Ews3xHkXY
ENV PORT=8002

# Exposer le port
EXPOSE 8002

# Lancer l'application
CMD ["python", "bot2.py"]