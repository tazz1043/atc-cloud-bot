FROM python:3.10-slim

# Install Google Chrome
RUN apt-get update && apt-get install -y wget gnupg unzip \
    && wget -q -O chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt install -y ./chrome.deb \
    && rm chrome.deb \
    && rm -rf /var/lib/apt/lists/*

# Set up the bot files
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app.py .

# Expose the web port and boot the server
ENV PORT=5000
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
