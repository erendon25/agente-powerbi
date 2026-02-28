"""
check_and_notify.py
-------------------
Script ejecutado por GitHub Actions cada hora.
- Abre el PowerBI con Playwright
- Compara con el último valor guardado en 'last_record.txt'
- Si cambió, envía un mensaje a Telegram
"""

import asyncio
import os
import re
import sys
import urllib.request
import urllib.parse
import json
from playwright.async_api import async_playwright

# ─────────────────────────────────────────────
# Configuración (se leen desde variables de entorno de GitHub Actions)
# ─────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
URL_POWERBI = (
    "https://app.powerbi.com/view?r=eyJrIjoiZWQ1YWNiYjctNWNiNC00MTNlLThjOGEtNjE1N"
    "Dc2NTI4NWU2IiwidCI6ImE4MzE3NzZjLWM0ZTUtNDNhMC04ZmZhLTFkNjIxZWNlZDAzNiIsImMiOjl9"
)
STATE_FILE = "last_record.txt"

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def send_telegram(message: str):
    """Envía un mensaje de Telegram usando urllib (sin dependencias extra)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read())
        if not result.get("ok"):
            print(f"Error enviando mensaje: {result}")
        else:
            print("✅ Mensaje de Telegram enviado")

def read_last_record() -> str:
    """Lee el último valor guardado."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return f.read().strip()
    return ""

def save_record(value: str):
    """Guarda el nuevo valor."""
    with open(STATE_FILE, "w") as f:
        f.write(value)
    print(f"💾 Guardado: {value}")

# ─────────────────────────────────────────────
# Extracción desde PowerBI
# ─────────────────────────────────────────────
async def extract_record_update() -> str | None:
    """Abre el PowerBI con Playwright y extrae el valor de RecordUpdate."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            headless=True
        )
        page = await browser.new_page()
        print(f"Cargando PowerBI...")
        await page.goto(URL_POWERBI, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(15000)

        text_content = ""
        for frame in page.frames:
            try:
                text = await frame.inner_text("body", timeout=5000)
                text_content += text + "\n"
            except Exception:
                pass

        await browser.close()

    match = re.search(
        r"RecordUpdate\s*([\d]{1,2}\s*-\s*[A-Za-z]{3}\s*\d{1,2}\s*:\s*\d{2})",
        text_content,
        re.IGNORECASE
    )
    if match:
        value = match.group(1).strip()
        print(f"✅ RecordUpdate encontrado: {value}")
        return value
    else:
        print("⚠️ RecordUpdate NO encontrado en esta revisión.")
        print("Fragmento de texto extraído:")
        print(text_content[:600])
        return None

# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
async def main():
    print("=== Agente PowerBI — GitHub Actions ===")
    current = await extract_record_update()

    if not current:
        print("No se pudo leer el valor actual. Saliendo sin cambios.")
        sys.exit(0)

    last = read_last_record()
    print(f"Último guardado: '{last}'  |  Actual: '{current}'")

    if current != last:
        print("🔴 ¡CAMBIO DETECTADO!")
        mensaje = (
            f"🔴 *¡El puntaje Mystery Client se actualizó!*\n\n"
            f"📊 Nuevo RecordUpdate: `{current}`\n"
            f"📌 Anterior: `{last or 'Ninguno'}`\n\n"
            f"[Ver PowerBI](https://app.powerbi.com/view?r=eyJrIjoiZWQ1YWNiYjctNWNiNC00MTNlLThjOGEtNjE1NDc2NTI4NWU2IiwidCI6ImE4MzE3NzZjLWM0ZTUtNDNhMC04ZmZhLTFkNjIxZWNlZDAzNiIsImMiOjl9)"
        )
        send_telegram(mensaje)
        save_record(current)
    else:
        print("✅ Sin cambios. No se envía notificación.")

if __name__ == "__main__":
    asyncio.run(main())
