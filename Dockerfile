# Imagen oficial de Playwright con Python y Chromium ya instalado
# Esto evita todos los problemas de permisos de sistema
FROM mcr.microsoft.com/playwright/python:v1.50.0-jammy

# Directorio de trabajo
WORKDIR /app

# Copiamos los archivos
COPY requirements.txt .
COPY telegram_bot.py .

# Instalamos las dependencias de Python (playwright ya está instalado en la imagen)
RUN pip install --no-cache-dir python-telegram-bot

# Puerto para que Render lo detecte como Web Service
ENV PORT=10000

# Comando de arranque
CMD ["python", "telegram_bot.py"]
