"""
check_and_notify.py — Agente PowerBI
Extrae notas por visita para Porongoche y Mall Porongoche del mes actual.
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

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID        = os.environ["TELEGRAM_CHAT_ID"]
URL_POWERBI    = (
    "https://app.powerbi.com/view?r=eyJrIjoiZWQ1YWNiYjctNWNiNC00MTNlLThjOGEtNjE1N"
    "Dc2NTI4NWU2IiwidCI6ImE4MzE3NzZjLWM0ZTUtNDNhMC04ZmZhLTFkNjIxZWNlZDAzNiIsImMiOjl9"
)
STATE_FILE = "last_record.txt"
MODO_MANUAL = len(sys.argv) > 1 and sys.argv[1] == "check"

MESES_ES = {
    1:"Ene",2:"Feb",3:"Mar",4:"Abr",5:"May",6:"Jun",
    7:"Jul",8:"Ago",9:"Set",10:"Oct",11:"Nov",12:"Dic"
}

# Coordenadas calibradas para viewport 767×730 (verificadas en sesión anterior)
# Filtro Mes
MES_HEADER    = (65, 163)   # clic para abrir/cerrar dropdown Mes
MES_SEL_TODO  = (31, 290)   # "Seleccionar todo"
MES_FEB       = (31, 330)   # opción "Feb"

# Filtro Supervisor
SUP_HEADER    = (65, 210)   # clic para abrir/cerrar dropdown Supervisor
SUP_YOHN      = (31, 465)   # opción "YOHN"

# Filtro Nro. Visita
VIS_HEADER    = (65, 249)   # clic para abrir/cerrar dropdown Nro. Visita
VIS_SEL_TODO  = (31, 270)   # "Seleccionar todo"
VIS_1         = (31, 290)   # opción "Visita 1"
VIS_2         = (31, 310)   # opción "Visita 2"

# Barras "Top Places" (click para filtrar por tienda)
BAR_PORONGOCHE      = (430, 355)
BAR_MALL_PORONGOCHE = (716, 355)
AREA_NEUTRAL        = (500, 20)  # clic neutro para deseleccionar tienda

# ── Telegram ──────────────────────────────────────────────────────────────────
def send_telegram(message: str):
    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"
    }).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data), timeout=15) as r:
            res = json.loads(r.read())
            print("✅ Telegram OK" if res.get("ok") else f"❌ Telegram: {res}")
    except Exception as e:
        print(f"❌ Error Telegram: {e}")

def read_last_record() -> str:
    return open(STATE_FILE).read().strip() if os.path.exists(STATE_FILE) else ""

def save_record(value: str):
    open(STATE_FILE, "w").write(value)
    print(f"💾 Guardado: {value}")

# ── Extracción de texto desde todos los frames ────────────────────────────────
async def page_text(page) -> str:
    txt = ""
    for f in page.frames:
        try:
            txt += await f.inner_text("body", timeout=5000) + "\n"
        except Exception:
            pass
    return txt

# ── Parsear el Success Rate del texto ─────────────────────────────────────────
def parse_success_rate(text: str) -> str | None:
    # Busca "97\n%\nSucess Rate" o "97%\nSucess Rate" o variantes
    for pat in [
        r"(\d{1,3})\s*\n*\s*%\s*\n*\s*Suce?ss\s*Rate",
        r"Suce?ss\s*Rate\s*\n*\s*(\d{1,3})\s*%?",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1) + "%"
    return None

# ── Parsear RecordUpdate ───────────────────────────────────────────────────────
def parse_record_update(text: str) -> str | None:
    t = re.sub(r'RecordUpdat\s*e', 'RecordUpdate', text, flags=re.IGNORECASE)
    m = re.search(
        r"RecordUpdate\s*([\d]{1,2}\s*-\s*[A-Za-z]{3}\s*[\d]{1,2}\s*:\s*[\d]{2})",
        t, re.IGNORECASE
    )
    if m:
        return m.group(1).strip()
    m = re.search(r"([\d]{1,2}\s*-\s*[A-Za-z]{3}\s*[\d]{1,2}\s*:\s*[\d]{2})", t, re.IGNORECASE)
    return m.group(1).strip() if m else None

# ── Pixel click helper ─────────────────────────────────────────────────────────
async def px(page, x, y, wait_ms=1200):
    await page.mouse.click(x, y)
    await page.wait_for_timeout(wait_ms)

# ── Extracción principal (1 sola carga de página) ─────────────────────────────
async def extract_full_report() -> dict:
    # Mes actual en hora Peru (UTC-5)
    now = datetime.utcnow()
    hora_peru = now.hour - 5
    mes_num = now.month if hora_peru >= 0 else (now.month - 1 or 12)
    mes_actual = MESES_ES[mes_num]
    print(f"📅 Mes actual Peru: {mes_actual}")

    result = {
        "record_update": None,
        "mes": mes_actual,
        "tiendas": {
            "PORONGOCHE":      {},
            "MALL PORONGOCHE": {},
        }
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            args=["--no-sandbox","--disable-setuid-sandbox","--disable-dev-shm-usage"],
            headless=True
        )
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 767, "height": 730},
            locale="es-PE"
        )
        page = await ctx.new_page()

        # ── Cargar ────────────────────────────────────────────────────────────
        print("⏳ Cargando PowerBI...")
        try:
            await page.goto(URL_POWERBI, wait_until="networkidle", timeout=90000)
        except Exception:
            await page.goto(URL_POWERBI, wait_until="domcontentloaded", timeout=90000)

        # Aceptar cookies
        for sel in ["button:has-text('Accept')","button:has-text('Aceptar')","button:has-text('OK')"]:
            try:
                b = page.locator(sel).first
                if await b.is_visible(timeout=1500):
                    await b.click()
                    await page.wait_for_timeout(1000)
            except Exception:
                pass

        print("⏳ Esperando render (15s)...")
        await page.wait_for_timeout(15000)
        await page.screenshot(path="screenshot_inicio.png")

        # RecordUpdate desde estado inicial
        result["record_update"] = parse_record_update(await page_text(page))
        print(f"🔖 RecordUpdate: {result['record_update']}")

        # ── Aplicar filtro Mes = mes_actual ───────────────────────────────────
        print(f"🗓️  Aplicando filtro Mes = {mes_actual}...")
        await px(page, *MES_HEADER)           # abrir dropdown
        await px(page, *MES_SEL_TODO)         # deseleccionar todo
        await px(page, *MES_SEL_TODO)         # click extra por si toggle
        # Buscar la posición correcta del mes (depende de qué meses existen)
        # Feb suele ser el 2° item; ajustar si el mes cambia
        await px(page, *MES_FEB, wait_ms=800) # seleccionar mes actual (Feb)
        await px(page, *MES_HEADER)           # cerrar dropdown
        await page.wait_for_timeout(2000)

        # ── Aplicar filtro Supervisor = YOHN ──────────────────────────────────
        print("👤 Aplicando filtro Supervisor = YOHN...")
        await px(page, *SUP_HEADER)
        await px(page, *SUP_YOHN)
        await px(page, *SUP_HEADER)
        await page.wait_for_timeout(2000)
        await page.screenshot(path="screenshot_filtros.png")

        # ── Extraer scores por tienda × visita ───────────────────────────────
        combos = [
            ("Visita 1", VIS_1,  BAR_PORONGOCHE,      "PORONGOCHE"),
            ("Visita 2", VIS_2,  BAR_PORONGOCHE,      "PORONGOCHE"),
            ("Visita 1", VIS_1,  BAR_MALL_PORONGOCHE, "MALL PORONGOCHE"),
            ("Visita 2", VIS_2,  BAR_MALL_PORONGOCHE, "MALL PORONGOCHE"),
        ]

        for visita, vis_coord, bar_coord, tienda in combos:
            print(f"  → {tienda} | {visita}")
            try:
                # Seleccionar solo esta visita
                await px(page, *VIS_HEADER)
                await px(page, *VIS_SEL_TODO)   # deselect all
                await px(page, *vis_coord)       # select visita N
                await px(page, *VIS_HEADER)      # cerrar
                await page.wait_for_timeout(1000)

                # Clic en la barra de la tienda en Top Places
                await px(page, *bar_coord, wait_ms=2000)

                # Leer score
                text = await page_text(page)
                score = parse_success_rate(text)
                result["tiendas"][tienda][visita] = score or "N/D"
                print(f"     ✅ {score}")

                # Clic neutro para deseleccionar tienda
                await px(page, *AREA_NEUTRAL, wait_ms=1000)

            except Exception as e:
                print(f"     ❌ Error: {e}")
                result["tiendas"][tienda][visita] = "Error"

        await ctx.close()
        await browser.close()

    return result

# ── Formato Telegram ──────────────────────────────────────────────────────────
def format_message(report: dict, es_primero: bool = False, last: str = "") -> str:
    mes    = report.get("mes", "?")
    record = report.get("record_update", "?")
    titulo = "🆕 *Primer registro*" if es_primero else "🔴 *¡Puntaje actualizado!*"
    lines  = [
        f"{titulo}",
        f"📊 *Reporte Mystery Client — {mes} 2026*",
        f"🕐 RecordUpdate: `{record}`",
    ]
    if last and not es_primero:
        lines.append(f"📌 Anterior: `{last}`")
    lines.append("")

    emojis = {"PORONGOCHE": "🏪", "MALL PORONGOCHE": "🏬"}
    for tienda, visitas in report["tiendas"].items():
        lines.append(f"{emojis.get(tienda,'🏪')} *{tienda}*")
        for v, nota in visitas.items():
            lines.append(f"   • {v}: `{nota}`")
        lines.append("")

    lines.append(f"[Ver PowerBI]({URL_POWERBI})")
    return "\n".join(lines)

def format_manual_message(report: dict) -> str:
    mes    = report.get("mes", "?")
    record = report.get("record_update", "?")
    lines  = [
        f"✅ *Consulta Manual — {mes} 2026*",
        f"🕐 RecordUpdate: `{record}`",
        "",
    ]
    emojis = {"PORONGOCHE": "🏪", "MALL PORONGOCHE": "🏬"}
    for tienda, visitas in report["tiendas"].items():
        lines.append(f"{emojis.get(tienda,'🏪')} *{tienda}*")
        for v, nota in visitas.items():
            lines.append(f"   • {v}: `{nota}`")
        lines.append("")
    lines.append(f"[Ver PowerBI]({URL_POWERBI})")
    return "\n".join(lines)

# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    print(f"=== Agente PowerBI — {'MANUAL' if MODO_MANUAL else 'AUTO'} ===")

    report = await extract_full_report()
    record_update = report.get("record_update")

    if not record_update:
        send_telegram(
            "⚠️ *Revisión PowerBI*\n\n"
            "No pude leer el RecordUpdate. El dashboard tardó en cargar.\n"
            "Reintentaré en la próxima revisión."
        )
        print("❌ Sin RecordUpdate.")
        sys.exit(0)

    last = read_last_record()
    print(f"📌 Último: '{last}' | Actual: '{record_update}'")

    if record_update != last:
        print("🔴 CAMBIO DETECTADO")
        send_telegram(format_message(report, es_primero=(last == ""), last=last))
        save_record(record_update)
    elif MODO_MANUAL:
        print("ℹ️ Modo manual, enviando igual...")
        send_telegram(format_manual_message(report))
    else:
        print("✅ Sin cambios.")

if __name__ == "__main__":
    asyncio.run(main())
