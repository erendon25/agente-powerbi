"""
check_and_notify.py
-------------------
Script ejecutado por GitHub Actions cada hora.
- Abre el PowerBI con Playwright
- Filtra por el mes actual, supervisor YOHN
- Extrae notas por Nro. de Visita para Porongoche y Mall Porongoche
- Envía un reporte detallado a Telegram
"""

import asyncio
import os
import re
import sys
import urllib.request
import urllib.parse
import json
from datetime import datetime
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

# Meses en español tal como aparecen en el filtro de Power BI
MESES_ES = {
    1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr",
    5: "May", 6: "Jun", 7: "Jul", 8: "Ago",
    9: "Set", 10: "Oct", 11: "Nov", 12: "Dic"
}

# Tiendas a reportar
TIENDAS = ["PORONGOCHE", "MALL PORONGOCHE"]

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
# Extracción del RecordUpdate (para detectar cambios)
# ─────────────────────────────────────────────
def extract_record_update_from_text(text_content: str) -> str | None:
    text_normalizado = re.sub(r'RecordUpdat\s*e', 'RecordUpdate', text_content, flags=re.IGNORECASE)
    match = re.search(
        r"RecordUpdate\s*([\d]{1,2}\s*-\s*[A-Za-z]{3}\s*[\d]{1,2}\s*:\s*[\d]{2})",
        text_normalizado,
        re.IGNORECASE
    )
    if not match:
        match = re.search(
            r"([\d]{1,2}\s*-\s*[A-Za-z]{3}\s*[\d]{1,2}\s*:\s*[\d]{2})",
            text_normalizado,
            re.IGNORECASE
        )
        if match:
            print("⚠️ Encontrado vía regex fallback (sin prefijo RecordUpdate)")
    if match:
        return match.group(1).strip()
    return None

# ─────────────────────────────────────────────
# Helpers de Playwright: Selects/Slicers
# ─────────────────────────────────────────────
async def get_page_text(page) -> str:
    text_content = ""
    for frame in page.frames:
        try:
            text = await frame.inner_text("body", timeout=5000)
            text_content += text + "\n"
        except Exception:
            pass
    return text_content

async def click_filter_option(page, filter_label: str, option_text: str, deselect_all_first: bool = False):
    """
    Intenta abrir el slicer que contiene filter_label y seleccionar option_text.
    Si deselect_all_first=True, primero deselecciona todas las opciones.
    """
    # Buscar el slicer por texto cercano al label
    slicers = page.locator("visual-container")
    count = await slicers.count()
    print(f"  🔍 Buscando filtro '{filter_label}' entre {count} visuales...")

    for i in range(count):
        slicer = slicers.nth(i)
        try:
            slicer_text = await slicer.inner_text(timeout=3000)
            if filter_label.lower() in slicer_text.lower():
                print(f"  ✅ Encontrado slicer '{filter_label}' en índice {i}")

                if deselect_all_first:
                    # Intentar hacer clic en "Seleccionar todo" para deseleccionar todo
                    try:
                        select_all = slicer.locator("span:has-text('Seleccionar todo'), span:has-text('Select all')")
                        if await select_all.count() > 0:
                            await select_all.first.click()
                            await page.wait_for_timeout(500)
                            # Hacer clic de nuevo para deseleccionar
                            await select_all.first.click()
                            await page.wait_for_timeout(500)
                    except Exception:
                        pass

                # Intentar encontrar la opción
                try:
                    option = slicer.locator(f"span:has-text('{option_text}'), div:has-text('{option_text}')")
                    if await option.count() > 0:
                        await option.first.click()
                        await page.wait_for_timeout(1000)
                        print(f"  ✅ Seleccionado '{option_text}' en filtro '{filter_label}'")
                        return True
                except Exception as e:
                    print(f"  ⚠️ Error seleccionando opción: {e}")
        except Exception:
            continue
    print(f"  ⚠️ No se encontró el filtro '{filter_label}'")
    return False

# ─────────────────────────────────────────────
# Función principal de extracción
# ─────────────────────────────────────────────
async def extract_full_report() -> dict:
    """
    Abre PowerBI, filtra por mes actual + YOHN, y extrae notas por visita
    para Porongoche y Mall Porongoche.
    Retorna dict con estructura:
    {
        "record_update": str,
        "mes": str,
        "tiendas": {
            "PORONGOCHE": {"Visita 1": "97%", "Visita 2": "97%"},
            "MALL PORONGOCHE": {"Visita 1": "57%"}
        }
    }
    """
    now = datetime.utcnow()
    mes_actual = MESES_ES[now.month]
    print(f"📅 Mes actual: {mes_actual} ({now.year})")

    result = {
        "record_update": None,
        "mes": mes_actual,
        "tiendas": {t: {} for t in TIENDAS}
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            headless=True
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="es-PE"
        )
        page = await context.new_page()

        # ── Cargar la página ──
        print("⏳ Cargando PowerBI...")
        try:
            await page.goto(URL_POWERBI, wait_until="networkidle", timeout=90000)
        except Exception as e:
            print(f"⚠️ networkidle timeout ({e}), continuando...")
            try:
                await page.goto(URL_POWERBI, wait_until="domcontentloaded", timeout=90000)
            except Exception as e2:
                print(f"❌ Error cargando página: {e2}")

        # ── Aceptar cookies ──
        consent_selectors = [
            "button:has-text('Accept')", "button:has-text('Aceptar')",
            "button:has-text('I accept')", "button:has-text('Continue')",
            "button:has-text('OK')", "[id*='accept']", "[class*='consent']",
        ]
        for sel in consent_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    await page.wait_for_timeout(2000)
            except Exception:
                pass

        # ── Esperar renderizado ──
        print("⏳ Esperando renderizado inicial (12s)...")
        await page.wait_for_timeout(12000)
        await page.screenshot(path="screenshot_inicio.png", full_page=False)

        # ── Extraer RecordUpdate del texto inicial ──
        text_inicial = await get_page_text(page)
        result["record_update"] = extract_record_update_from_text(text_inicial)
        print(f"📊 RecordUpdate: {result['record_update']}")

        # ─────────────────────────────────────────────
        # Estrategia de extracción:
        # Para cada combinación (tienda, visita):
        #   1. Aplicar filtro Mes = mes_actual
        #   2. Aplicar filtro Supervisor = YOHN (ya debería estar)
        #   3. Hacer clic en la tienda en "Top Places" para filtrarla
        #   4. Aplicar filtro Nro. Visita = Visita N
        #   5. Leer "Sucess Rate" del texto
        # ─────────────────────────────────────────────

        visitas = ["Visita 1", "Visita 2"]

        for tienda in TIENDAS:
            print(f"\n🏪 Extrayendo datos para: {tienda}")
            for visita in visitas:
                print(f"  📋 Procesando {visita}...")
                try:
                    # Recargar página para empezar limpio en cada combinación
                    await page.goto(URL_POWERBI, wait_until="networkidle", timeout=90000)
                    await page.wait_for_timeout(10000)

                    # Aceptar posibles diálogos nuevamente
                    for sel in consent_selectors:
                        try:
                            btn = page.locator(sel).first
                            if await btn.is_visible(timeout=1000):
                                await btn.click()
                                await page.wait_for_timeout(1000)
                        except Exception:
                            pass

                    # ── Intentar seleccionar el Mes actual ──
                    await click_filter_option(page, "Mes", mes_actual, deselect_all_first=True)
                    await page.wait_for_timeout(2000)

                    # ── Intentar seleccionar el Supervisor YOHN ──
                    await click_filter_option(page, "Supervisor", "YOHN", deselect_all_first=True)
                    await page.wait_for_timeout(2000)

                    # ── Intentar seleccionar la Visita ──
                    await click_filter_option(page, "Nro. Visita", visita, deselect_all_first=True)
                    await page.wait_for_timeout(2000)

                    # ── Intentar hacer clic en la tienda en "Top Places" ──
                    try:
                        tienda_label = page.locator(f"text={tienda}").last
                        if await tienda_label.is_visible(timeout=3000):
                            await tienda_label.click()
                            await page.wait_for_timeout(2000)
                            print(f"  ✅ Filtrado por tienda: {tienda}")
                    except Exception as e:
                        print(f"  ⚠️ No pude hacer clic en tienda {tienda}: {e}")

                    # ── Leer el porcentaje ──
                    text = await get_page_text(page)

                    # Buscar el Success Rate en el texto
                    # Aparece como "XX %" o "XX%"
                    matches = re.findall(r"(\d{1,3})\s*%", text)
                    # El Success Rate es el primer porcentaje prominente
                    # Filtramos para evitar 100% de criterios individuales
                    # Tomamos el más frecuente o el primero razonable
                    score = None
                    if matches:
                        # Tomar el primer porcentaje que no sea 100 (que suelen ser criterios)
                        # Si todos son 100, tomar el primero
                        non_100 = [m for m in matches if m != "100"]
                        score = non_100[0] + "%" if non_100 else matches[0] + "%"

                    # Busca el patrón "Sucess Rate\nXX%" o "Success Rate XX%"
                    sr_match = re.search(r"Suce?ss\s+Rate\s*\n?\s*(\d{1,3})\s*%", text, re.IGNORECASE)
                    if sr_match:
                        score = sr_match.group(1) + "%"

                    if score:
                        result["tiendas"][tienda][visita] = score
                        print(f"  ✅ {tienda} - {visita}: {score}")
                    else:
                        result["tiendas"][tienda][visita] = "N/D"
                        print(f"  ⚠️ No se encontró score para {tienda} - {visita}")

                except Exception as e:
                    print(f"  ❌ Error procesando {tienda} - {visita}: {e}")
                    result["tiendas"][tienda][visita] = "Error"

        await context.close()
        await browser.close()

    return result

# ─────────────────────────────────────────────
# Formatear el mensaje de Telegram
# ─────────────────────────────────────────────
def format_telegram_message(report: dict) -> str:
    mes = report.get("mes", "?")
    record = report.get("record_update", "?")
    tiendas = report.get("tiendas", {})

    lineas = [
        f"📊 *Reporte Mystery Client — {mes} 2026*",
        f"🕐 RecordUpdate: `{record}`",
        "",
    ]

    tienda_emojis = {
        "PORONGOCHE": "🏪",
        "MALL PORONGOCHE": "🏬"
    }

    for tienda, visitas in tiendas.items():
        emoji = tienda_emojis.get(tienda, "🏪")
        lineas.append(f"{emoji} *{tienda}*")
        if visitas:
            for nro_visita, nota in visitas.items():
                lineas.append(f"   • {nro_visita}: `{nota}`")
        else:
            lineas.append("   • Sin datos disponibles")
        lineas.append("")

    lineas.append(f"[Ver PowerBI]({URL_POWERBI})")

    return "\n".join(lineas)

# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
async def main():
    modo = "MANUAL" if MODO_MANUAL else "AUTOMÁTICO (cada hora)"
    print(f"=== Agente PowerBI — Modo: {modo} ===")

    report = await extract_full_report()

    record_update = report.get("record_update")

    if not record_update:
        send_telegram(
            "⚠️ *Revisión PowerBI*\n\n"
            "No pude leer el valor de RecordUpdate esta vez.\n"
            "El PowerBI puede haber tardado en cargar. Reintentaré en la próxima revisión."
        )
        print("❌ No se encontró el RecordUpdate. Notificación de error enviada.")
        sys.exit(0)

    last = read_last_record()
    print(f"📌 Último guardado: '{last}' | Actual: '{record_update}'")

    if record_update != last or MODO_MANUAL:
        if record_update != last:
            print("🔴 ¡CAMBIO DETECTADO! Enviando reporte detallado...")
        else:
            print("ℹ️ Sin cambios, pero modo manual: enviando reporte...")

        mensaje = format_telegram_message(report)
        send_telegram(mensaje)
        save_record(record_update)
    else:
        print("✅ Sin cambios. No se envía notificación.")

if __name__ == "__main__":
    asyncio.run(main())
