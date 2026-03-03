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

# Coordenadas de los HEADERS de los slicers (posición fija, no cambia)
# Viewport 767×730 verificado en sesión real
MES_HEADER    = (65, 163)   # abrir/cerrar dropdown Mes
SUP_HEADER    = (65, 210)   # abrir/cerrar dropdown Supervisor
VIS_HEADER    = (65, 249)   # abrir/cerrar dropdown Nro. Visita
AREA_NEUTRAL  = (500, 20)   # clic neutro para deseleccionar row de tabla

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
    """
    En Power BI, el donut de 'Sucess Rate' tiene el LABEL primero en el DOM
    y el VALOR porcentual aparece varias lineas despues.
    Normalizamos el texto y buscamos el primer % despues del label.
    """
    normalized = " ".join(text.split())

    # Estrategia 1: primer % despues del label 'Sucess Rate' (hasta 400 chars)
    m = re.search(r"Suce?ss\s*Rat[^%]{0,400}?(\d{1,3})\s*%", normalized, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        if 0 < val <= 100:
            print(f"    📊 Score (patrón 1): {val}%")
            return str(val) + "%"

    # Estrategia 2: buscar en sección Resumen General
    m = re.search(r"Resumen General[^%]{0,400}?(\d{1,3})\s*%", normalized, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        if 0 < val <= 100:
            print(f"    📊 Score (patrón 2 Resumen): {val}%")
            return str(val) + "%"

    # Fallback: primer % razonable en el texto (excluye 100 y 0)
    all_pct = re.findall(r"(\d{1,3})\s*%", normalized)
    non_100 = [int(x) for x in all_pct if 0 < int(x) < 100]
    if non_100:
        print(f"    ⚠️ Fallback: {non_100[0]}% (encontrados: {all_pct[:8]})")
        return str(non_100[0]) + "%"

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

# ── Búsqueda automática de opciones en los frames de Power BI ────────────────
async def click_option_in_frames(page, option_text: str, wait_ms: int = 1000) -> bool:
    """
    Busca 'option_text' en todos los frames y hace clic.
    Usa exact=False para tolerar espacios extra o texto parcial.
    """
    for frame in page.frames:
        for loc_expr in [
            lambda f: f.get_by_text(option_text, exact=False),
            lambda f: f.locator(f"span:text-is('{option_text}')"),
            lambda f: f.locator(f"div:text-is('{option_text}')"),
            lambda f: f.locator(f"[title='{option_text}']"),
            lambda f: f.locator(f"[aria-label*='{option_text}']"),
        ]:
            try:
                loc = loc_expr(frame)
                cnt = await loc.count()
                if cnt > 0:
                    await loc.first.click()
                    await page.wait_for_timeout(wait_ms)
                    print(f"    ✅ Clic en '{option_text}'")
                    return True
            except Exception:
                pass
    print(f"    ⚠️ No se encontró '{option_text}' en ningún frame")
    return False

async def deselect_all_in_frames(page) -> bool:
    """Hace clic en 'Seleccionar todo' / 'Select all'."""
    for text in ["Seleccionar todo", "Select all"]:
        if await click_option_in_frames(page, text, wait_ms=600):
            return True
    return False

# ── Clic en fila de tabla por texto (no depende de coordenadas) ───────────────
async def click_table_row(page, tienda: str, visita: str) -> bool:
    """
    Busca la fila de la tabla que contiene 'tienda' y 'visita' y hace clic.
    Estrategia escalonada:
      1. Fila con tienda + visita (texto exacto)
      2. Fila con solo tienda (si el slicer ya filtra la visita)
      3. Elemento con texto de tienda en cualquier parte del DOM (Top Places / visual)
    """
    tienda_norm  = tienda.upper().strip()
    visita_norm  = visita.upper().strip()
    row_selectors = ["tr", "div[role='row']", "[class*='row']", "[class*='tableRow']"]

    # ── Intento 1: fila con tienda + visita ──────────────────────────────────
    for frame in page.frames:
        for sel in row_selectors:
            try:
                rows = frame.locator(sel)
                count = await rows.count()
                for i in range(count):
                    row = rows.nth(i)
                    try:
                        row_text = await row.inner_text(timeout=1000)
                        rt_norm  = row_text.upper().strip()
                        if tienda_norm in rt_norm and visita_norm in rt_norm:
                            await row.click()
                            await page.wait_for_timeout(2000)
                            print(f"    ✅ [1] Fila tienda+visita clickeada: {tienda} / {visita}")
                            return True
                    except Exception:
                        continue
            except Exception:
                continue

    # ── Intento 2: fila con solo tienda (el slicer de visita ya está activo) ──
    print(f"    ⚠️ No encontré fila '{tienda}+{visita}', intentando solo '{tienda}'...")
    for frame in page.frames:
        for sel in row_selectors:
            try:
                rows = frame.locator(sel)
                count = await rows.count()
                # Log de primeras filas para diagnóstico
                if count > 0 and sel == "tr":
                    sample_texts = []
                    for j in range(min(5, count)):
                        try:
                            t = await rows.nth(j).inner_text(timeout=800)
                            sample_texts.append(repr(t[:80]))
                        except Exception:
                            pass
                    if sample_texts:
                        print(f"    📋 Primeras filas ({frame.name or 'main'}/{sel}): {sample_texts}")
                for i in range(count):
                    row = rows.nth(i)
                    try:
                        row_text = await row.inner_text(timeout=1000)
                        rt_norm  = row_text.upper().strip()
                        if tienda_norm in rt_norm:
                            await row.click()
                            await page.wait_for_timeout(2000)
                            print(f"    ✅ [2] Fila (solo tienda) clickeada: {tienda}")
                            return True
                    except Exception:
                        continue
            except Exception:
                continue

    # ── Intento 3: clic en cualquier elemento con el texto de la tienda ──────
    print(f"    ⚠️ No encontré fila solo '{tienda}', intentando clic por texto en DOM...")
    for frame in page.frames:
        for loc_expr in [
            lambda f: f.get_by_text(tienda, exact=False),
            lambda f: f.locator(f"[title*='{tienda}']"),
            lambda f: f.locator(f"[aria-label*='{tienda}']"),
        ]:
            try:
                loc   = loc_expr(frame)
                count = await loc.count()
                if count > 0:
                    await loc.first.click()
                    await page.wait_for_timeout(2000)
                    print(f"    ✅ [3] Clic por texto/atributo: {tienda}")
                    return True
            except Exception:
                pass

    print(f"    ❌ Sin fila para: {tienda} / {visita}")
    return False

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

        # ── Aplicar filtro Mes = mes_actual (automático) ─────────────────────
        print(f"🗓️  Aplicando filtro Mes = {mes_actual}...")
        await px(page, *MES_HEADER)           # abrir dropdown
        await page.wait_for_timeout(800)
        await deselect_all_in_frames(page)    # deseleccionar todo
        await deselect_all_in_frames(page)    # doble click por si es toggle
        await click_option_in_frames(page, mes_actual)  # seleccionar mes actual
        await px(page, *MES_HEADER)           # cerrar dropdown
        await page.wait_for_timeout(2000)

        # ── Aplicar filtro Supervisor = YOHN (automático) ─────────────────────
        print("👤 Aplicando filtro Supervisor = YOHN...")
        await px(page, *SUP_HEADER)
        await page.wait_for_timeout(800)
        await click_option_in_frames(page, "YOHN")
        await px(page, *SUP_HEADER)
        await page.wait_for_timeout(2000)
        await page.screenshot(path="screenshot_filtros.png")

        # ── Extraer scores por tienda × visita ───────────────────────────────
        combos = [
            ("Visita 1", "PORONGOCHE"),
            ("Visita 2", "PORONGOCHE"),
            ("Visita 1", "MALL PORONGOCHE"),
            ("Visita 2", "MALL PORONGOCHE"),
        ]

        for visita, tienda in combos:
            print(f"  → {tienda} | {visita}")
            try:
                # 1. Seleccionar solo esta visita en el filtro
                await px(page, *VIS_HEADER)
                await page.wait_for_timeout(600)
                await deselect_all_in_frames(page)
                await click_option_in_frames(page, visita)
                await px(page, *VIS_HEADER)
                await page.wait_for_timeout(1000)

                # 2. Clic en la fila de la tabla (por texto de tienda+visita)
                #    NO usamos coordenadas del grafico Top Places porque
                #    las barras cambian de posicion segun el ranking de notas.
                found_row = await click_table_row(page, tienda, visita)

                # 3. Leer Success Rate
                #    Si found_row es False, el slicer de visita ya está activo;
                #    intentamos leer el score del estado actual del dashboard.
                text  = await page_text(page)
                excerpt = " ".join(text.split())[:600]
                print(f"    📄 Texto (600c): {excerpt}")
                score = parse_success_rate(text)

                if score:
                    result["tiendas"][tienda][visita] = score
                    if not found_row:
                        print(f"    ℹ️ Score leído sin clic en fila ({tienda}/{visita}): {score}")
                else:
                    result["tiendas"][tienda][visita] = "Sin visita" if not found_row else "N/D"

                # 4. Clic neutro para deseleccionar la fila
                await px(page, *AREA_NEUTRAL, wait_ms=800)

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
