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
        # Simular un navegador real con user-agent de Windows Chrome
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="es-PE"
        )
        page = await context.new_page()

        print("⏳ Cargando PowerBI...")
        try:
            await page.goto(URL_POWERBI, wait_until="networkidle", timeout=90000)
        except Exception as e:
            print(f"⚠️ networkidle timeout ({e}), continuando con domcontentloaded...")
            try:
                await page.goto(URL_POWERBI, wait_until="domcontentloaded", timeout=90000)
            except Exception as e2:
                print(f"❌ Error cargando página: {e2}")

        # Intentar aceptar diálogos de cookies / consentimiento
        print("🍪 Buscando diálogos de consentimiento...")
        consent_selectors = [
            "button:has-text('Accept')",
            "button:has-text('Aceptar')",
            "button:has-text('I accept')",
            "button:has-text('Continue')",
            "button:has-text('OK')",
            "[id*='accept']",
            "[class*='accept']",
            "[class*='consent']",
        ]
        for sel in consent_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    print(f"  ✅ Hice clic en: {sel}")
                    await page.wait_for_timeout(2000)
            except Exception:
                pass

        # Guardar screenshot de diagnóstico ANTES de esperar (para ver qué hay)
        print("📸 Guardando screenshot inicial...")
        await page.screenshot(path="screenshot_inicio.png", full_page=False)

        # Esperar 45 segundos para renderizado completo
        print("⏳ Esperando 45 segundos para renderizado completo...")
        await page.wait_for_timeout(45000)

        # Screenshot después de esperar
        print("📸 Guardando screenshot final...")
        await page.screenshot(path="screenshot_final.png", full_page=False)

        text_content = ""
        for frame in page.frames:
            try:
                text = await frame.inner_text("body", timeout=5000)
                text_content += text + "\n"
            except Exception:
                pass

        await context.close()
        await browser.close()

    print(f"📄 Texto total extraído: {len(text_content)} caracteres")
    print("=== INICIO TEXTO EXTRAÍDO ===")
    print(text_content[:3000])  # Imprimir más texto para diagnóstico
    print("=== FIN TEXTO EXTRAÍDO ===")

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
