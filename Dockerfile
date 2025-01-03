# Use a base Python image
FROM python:3.11-slim

# Update apt-get and install necessary system dependencies
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
    git && \
    rm -rf /var/lib/apt/lists/*

# Download and install TA-Lib from source
RUN wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz && \
    tar -xzvf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib && \
    ./configure --prefix=/usr/local && \
    make && \
    make install && \
    cd .. && \
    rm -rf ta-lib-0.4.0-src.tar.gz ta-lib

# Verify that the TA-Lib library is correctly installed
RUN ls -l /usr/local/lib | grep ta_lib

# Set library path environment variable
ENV LD_LIBRARY_PATH=/usr/local/lib

# Define the working directory
WORKDIR /app

# Copy requirements.txt and bot2.py into the Docker image
COPY requirements.txt /app/requirements.txt
COPY bot2.py /app/bot2.py

# Add environment variables
ENV DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/1321239629084627004/ryXqQGg0oeIxoiAHh21FMhCrUGLo1BOynDHtR3A-mtptklpbocJmL_-W8f2Ews3xHkXY
ENV PORT=8002

# Upgrade pip and install Python dependencies
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Expose the port on which the application listens
EXPOSE 8002

# Command to start the application
CMD ["python", "bot2.py"]