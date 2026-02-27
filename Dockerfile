# Imagen oficial de Playwright con Python y Chromium ya instalado
# playwright ya está disponible en esta imagen, NO lo reinstalamos
FROM mcr.microsoft.com/playwright/python:v1.50.0-jammy

WORKDIR /app

COPY requirements.txt .
COPY telegram_bot.py .

# Solo instalamos python-telegram-bot con soporte de job-queue
RUN pip install --no-cache-dir "python-telegram-bot[job-queue]"

ENV PORT=10000

CMD ["python", "telegram_bot.py"]
