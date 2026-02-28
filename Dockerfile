# Imagen oficial de Playwright con Python y Chromium ya instalado
FROM mcr.microsoft.com/playwright/python:v1.50.0-jammy

WORKDIR /app

COPY requirements.txt .
COPY telegram_bot.py .

# Instala todas las dependencias de Python (incluyendo playwright)
RUN pip install --no-cache-dir -r requirements.txt

# Instala el navegador Chromium (ya viene en la imagen base, pero lo forzamos por si acaso)
RUN playwright install chromium

ENV PORT=10000

CMD ["python", "telegram_bot.py"]
