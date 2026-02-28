"""
check_and_notify.py
-------------------
Script ejecutado por GitHub Actions cada hora.
- Abre el PowerBI con Playwright
- Compara con el último valor guardado en 'last_record.txt'
- Si cambió (o es primera vez), envía un mensaje a Telegram
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
# Configuración (variables de entorno de GitHub Actions)
# ─────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
URL_POWERBI = (
    "https://app.powerbi.com/view?r=eyJrIjoiZWQ1YWNiYjctNWNiNC00MTNlLThjOGEtNjE1N"
    "Dc2NTI4NWU2IiwidCI6ImE4MzE3NzZjLWM0ZTUtNDNhMC04ZmZhLTFkNjIxZWNlZDAzNiIsImMiOjl9"
)
STATE_FILE = "last_record.txt"

# Si se pasa el argumento "check" (manual), siempre notifica aunque no haya cambio
MODO_MANUAL = len(sys.argv) > 1 and sys.argv[1] == "check"

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }).encode()
    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            if result.get("ok"):
                print("✅ Mensaje de Telegram enviado")
            else:
                print(f"❌ Error Telegram: {result}")
    except Exception as e:
        print(f"❌ Error enviando Telegram: {e}")

def read_last_record() -> str:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return f.read().strip()
    return ""

def save_record(value: str):
    with open(STATE_FILE, "w") as f:
        f.write(value)
    print(f"💾 Estado guardado: {value}")

# ─────────────────────────────────────────────
# Extracción desde PowerBI (con reintentos)
# ─────────────────────────────────────────────
async def extract_record_update() -> str | None:
    """Abre PowerBI con Playwright, espera más tiempo para renderizado completo."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            headless=True
        )
        page = await browser.new_page()

        print("⏳ Cargando PowerBI (puede tomar hasta 60 segundos)...")
        try:
            # Aumentamos el tiempo de espera a 90 segundos
            await page.goto(URL_POWERBI, wait_until="networkidle", timeout=90000)
        except Exception:
            # Si networkidle falla, igual esperamos el DOM
            print("⚠️ networkidle timeout, esperando domcontentloaded...")
            await page.goto(URL_POWERBI, wait_until="domcontentloaded", timeout=90000)

        # Esperamos 30 segundos para que los gráficos de PowerBI terminen de renderizar
        print("⏳ Esperando 30 segundos para renderizado completo...")
        await page.wait_for_timeout(30000)

        text_content = ""
        for frame in page.frames:
            try:
                text = await frame.inner_text("body", timeout=5000)
                text_content += text + "\n"
            except Exception:
                pass

        await browser.close()

    print(f"📄 Texto extraído ({len(text_content)} chars). Primeros 500:")
    print(text_content[:500])
    print("---")

    match = re.search(
        r"RecordUpdate\s*([\d]{1,2}\s*-\s*[A-Za-z]{3}\s*\d{1,2}\s*:\s*\d{2})",
        text_content,
        re.IGNORECASE
    )
    if match:
        value = match.group(1).strip()
        print(f"✅ RecordUpdate encontrado: '{value}'")
        return value
    else:
        print("⚠️ RecordUpdate NO encontrado en el texto extraído.")
        return None

# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
async def main():
    modo = "MANUAL" if MODO_MANUAL else "AUTOMÁTICO (cada hora)"
    print(f"=== Agente PowerBI — Modo: {modo} ===")

    current = await extract_record_update()

    if not current:
        # Si no encontró el valor, avisar por Telegram para que sepas que hay un problema
        send_telegram(
            "⚠️ *Revisión PowerBI*\n\n"
            "No pude leer el valor de RecordUpdate esta vez.\n"
            "El PowerBI puede haber tardado en cargar. Reintentaré en la próxima revisión."
        )
        print("❌ No se encontró el valor. Notificación de error enviada.")
        sys.exit(0)

    last = read_last_record()
    print(f"📌 Último guardado: '{last}' | Actual: '{current}'")

    if current != last:
        print("🔴 ¡CAMBIO DETECTADO! Enviando notificación...")
        es_primero = last == ""
        mensaje = (
            f"{'🆕 *Primer registro detectado*' if es_primero else '🔴 *¡El puntaje Mystery Client cambió!*'}\n\n"
            f"📊 RecordUpdate: `{current}`\n"
            + (f"📌 Anterior: `{last}`\n" if not es_primero else "")
            + f"\n[Ver PowerBI](https://app.powerbi.com/view?r=eyJrIjoiZWQ1YWNiYjctNWNiNC00MTNlLThjOGEtNjE1NDc2NTI4NWU2IiwidCI6ImE4MzE3NzZjLWM0ZTUtNDNhMC04ZmZhLTFkNjIxZWNlZDAzNiIsImMiOjl9)"
        )
        send_telegram(mensaje)
        save_record(current)
    elif MODO_MANUAL:
        # En modo manual, siempre informa aunque no haya cambio
        print("ℹ️ Sin cambios, pero modo manual: enviando estado actual...")
        send_telegram(
            f"✅ *Consulta Manual PowerBI*\n\n"
            f"📊 RecordUpdate actual: `{current}`\n"
            f"📌 Sin cambios desde la última revisión.\n\n"
            f"[Ver PowerBI](https://app.powerbi.com/view?r=eyJrIjoiZWQ1YWNiYjctNWNiNC00MTNlLThjOGEtNjE1NDc2NTI4NWU2IiwidCI6ImE4MzE3NzZjLWM0ZTUtNDNhMC04ZmZhLTFkNjIxZWNlZDAzNiIsImMiOjl9)"
        )
    else:
        print("✅ Sin cambios. No se envía notificación.")

if __name__ == "__main__":
    asyncio.run(main())
