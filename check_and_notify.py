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

# ── Parsear score desde el texto de UNA FILA de tabla ────────────────────────
def parse_score_from_row(row_text: str) -> str | None:
    """
    Intenta extraer el porcentaje desde el texto de una fila de la tabla.
    La tabla suele tener: 'TIENDA  Visita N  85%' o similar.
    """
    matches = re.findall(r"(\d{1,3})\s*%", row_text)
    valid = [int(x) for x in matches if 0 < int(x) <= 100]
    if valid:
        print(f"    📊 Score de fila: {valid[0]}%")
        return str(valid[0]) + "%"
    # A veces viene como número decimal: '85.3' → tomamos el entero
    matches_dec = re.findall(r"(\d{1,3})[.,]\d+", row_text)
    valid_dec = [int(x) for x in matches_dec if 0 < int(x) <= 100]
    if valid_dec:
        print(f"    📊 Score de fila (decimal): {valid_dec[0]}%")
        return str(valid_dec[0]) + "%"
    return None

# ── Parsear el Success Rate del texto de PÁGINA COMPLETA ─────────────────────
def parse_success_rate(text: str) -> str | None:
    """
    Busca el porcentaje del donut 'Sucess Rate' en el texto de la página.
    Solo se usa cuando no se pudo leer de la fila directamente.
    """
    normalized = " ".join(text.split())

    # Estrategia 1: primer % despues del label 'Sucess Rate' (hasta 200 chars)
    m = re.search(r"Suce?ss\s*Rat[^%]{0,200}?(\d{1,3})\s*%", normalized, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        if 0 < val <= 100:
            print(f"    📊 Score (patrón SR): {val}%")
            return str(val) + "%"

    # Estrategia 2: buscar en sección Resumen General
    m = re.search(r"Resumen General[^%]{0,200}?(\d{1,3})\s*%", normalized, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        if 0 < val <= 100:
            print(f"    📊 Score (patrón Resumen): {val}%")
            return str(val) + "%"

    # Estrategia 3: buscar el número inmediatamente antes o despues de "Nota"
    m = re.search(r"Nota\D{0,30}?(\d{1,3})\s*%", normalized, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        if 0 < val <= 100:
            print(f"    📊 Score (patrón Nota): {val}%")
            return str(val) + "%"

    return None


# ── Parsear RecordUpdate ───────────────────────────────────────────────────────
def parse_record_update(text: str) -> tuple[str | None, str | None]:
    t = re.sub(r'RecordUpdat\s*e', 'RecordUpdate', text, flags=re.IGNORECASE)
    m = re.search(
        r"RecordUpdate\s*([\d]{1,2}\s*-\s*([A-Za-z]{3})\s*[\d]{1,2}\s*:\s*[\d]{2})",
        t, re.IGNORECASE
    )
    if m:
        return m.group(1).strip(), m.group(2).strip().capitalize()
    m = re.search(r"([\d]{1,2}\s*-\s*([A-Za-z]{3})\s*[\d]{1,2}\s*:\s*[\d]{2})", t, re.IGNORECASE)
    return (m.group(1).strip(), m.group(2).strip().capitalize()) if m else (None, None)

# ── Búsqueda automática en visual-containers ─────────────────────────────────
async def click_filter_option(page, filter_label: str, option_text: str, deselect_all_first: bool = False):
    """Intenta abrir el slicer con filter_label y seleccionar option_text."""
    slicers = page.locator("visual-container")
    count = await slicers.count()
    for i in range(count):
        slicer = slicers.nth(i)
        try:
            slicer_text = await slicer.inner_text(timeout=3000)
            if filter_label.lower() in slicer_text.lower():
                if deselect_all_first:
                    try:
                        select_all = slicer.locator("span:has-text('Seleccionar todo'), span:has-text('Select all')")
                        if await select_all.count() > 0:
                            await select_all.first.click()
                            await page.wait_for_timeout(500)
                            await select_all.first.click()
                            await page.wait_for_timeout(500)
                    except Exception:
                        pass
                try:
                    option = slicer.locator(f"span:has-text('{option_text}')")
                    if await option.count() > 0:
                        await option.first.click()
                        await page.wait_for_timeout(1000)
                        return True
                except Exception:
                    continue
        except Exception:
            continue
    return False

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

# ── Buscar score directamente en la tabla (sin cross-filter al donut) ────────
async def find_score_in_table(page, tienda: str, visita: str) -> str | None:
    """
    Recorre las filas de la tabla de Power BI buscando la que corresponde
    a (tienda, visita) y extrae el score DIRECTAMENTE del texto de esa fila.

    Estrategia:
      1. Busca fila con tienda+visita → extrae % del texto de la propia fila
      2. Si la fila no tiene %, la clica y lee el donut (Sucess Rate) filtrado
      3. Si no hay fila tienda+visita, busca fila con solo tienda (slicer ya filtra)
         y repite el proceso de leer/clicar
      4. Sin fila → retorna None
    """
    tienda_norm = tienda.upper().strip()
    visita_norm = visita.upper().strip()
    row_selectors = ["tr", "div[role='row']", "[class*='row']", "[class*='tableRow']"]

    async def try_get_score_from_row(row, label: str) -> str | None:
        """Intenta leer el % de la fila; si no tiene, hace clic y lee el donut."""
        try:
            row_text = await row.inner_text(timeout=1000)
            print(f"    📋 Fila encontrada ({label}): {repr(row_text[:120])}")
            # Prioridad 1: el % está en la fila misma
            score = parse_score_from_row(row_text)
            if score:
                return score
            # Prioridad 2: clicar la fila y leer el donut de la página
            print(f"    🖱️ Fila sin %, haciendo clic para filtrar donut...")
            await row.click()
            await page.wait_for_timeout(2500)
            page_txt = await page_text(page)
            score = parse_success_rate(page_txt)
            if score:
                print(f"    📊 Score del donut tras clic: {score}")
            return score
        except Exception as e:
            print(f"    ⚠️ Error procesando fila: {e}")
            return None

    # ── Intento 1: fila con tienda + visita ─────────────────────────────────
    for frame in page.frames:
        for sel in row_selectors:
            try:
                rows = frame.locator(sel)
                count = await rows.count()
                for i in range(count):
                    row = rows.nth(i)
                    try:
                        row_text_peek = await row.inner_text(timeout=800)
                        rt_norm = row_text_peek.upper().strip()
                        if tienda_norm in rt_norm and visita_norm in rt_norm:
                            score = await try_get_score_from_row(row, f"{tienda}/{visita}")
                            if score:
                                return score
                    except Exception:
                        continue
            except Exception:
                continue

    # ── LOG: mostrar primeras filas para diagnóstico ─────────────────────────
    print(f"    ⚠️ Sin fila '{tienda}+{visita}'. Mostrando filas disponibles:")
    for frame in page.frames:
        for sel in ["tr", "div[role='row']"]:
            try:
                rows = frame.locator(sel)
                count = await rows.count()
                if count > 1:
                    for j in range(min(8, count)):
                        try:
                            t = await rows.nth(j).inner_text(timeout=600)
                            if t.strip():
                                print(f"      [{j}] {repr(t.strip()[:100])}")
                        except Exception:
                            pass
                    break
            except Exception:
                continue
        break

    # ── Intento 2: fila con solo tienda (slicer de visita ya activo) ────────
    print(f"    🔄 Buscando fila solo con '{tienda}'...")
    for frame in page.frames:
        for sel in row_selectors:
            try:
                rows = frame.locator(sel)
                count = await rows.count()
                for i in range(count):
                    row = rows.nth(i)
                    try:
                        row_text_peek = await row.inner_text(timeout=800)
                        rt_norm = row_text_peek.upper().strip()
                        # Excluir filas que sean encabezados (no tienen números)
                        if tienda_norm in rt_norm and re.search(r'\d', rt_norm):
                            score = await try_get_score_from_row(row, f"{tienda} (slicer)")
                            if score:
                                return score
                    except Exception:
                        continue
            except Exception:
                continue

    print(f"    ❌ Sin score para: {tienda} / {visita}")
    return None

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
        rd_upd, parsed_mes = parse_record_update(await page_text(page))
        result["record_update"] = rd_upd
        if parsed_mes:
            mes_actual = parsed_mes
            result["mes"] = mes_actual
        print(f"🔖 RecordUpdate: {result['record_update']}")

        # ── Aplicar filtro Mes = mes_actual (automático) ─────────────────────
        print(f"🗓️  Aplicando filtro Mes = {mes_actual}...")
        await click_filter_option(page, "Mes", mes_actual, deselect_all_first=True)
        await page.wait_for_timeout(2000)

        # ── Aplicar filtro Supervisor = YOHN (automático) ─────────────────────
        print("👤 Aplicando filtro Supervisor = YOHN...")
        await click_filter_option(page, "Supervisor", "YOHN", deselect_all_first=True)
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
                # 1. Seleccionar solo esta visita en el filtro de Nro. Visita
                await click_filter_option(page, "Nro. Visita", visita, deselect_all_first=True)
                await page.wait_for_timeout(2000)  # esperar render

                # 2. Leer score HACIENDO CLIC en Top Places / row de Tienda
                score = "Sin visita"
                tienda_label = page.locator(f"text={tienda}").last
                if await tienda_label.is_visible(timeout=3000):
                    await tienda_label.click()
                    await page.wait_for_timeout(2500)
                    
                    page_txt = await page_text(page)
                    m = re.search(r"(\d{1,3})\s*%\s*\n*.*Suce?ss\s+Rate", page_txt, re.IGNORECASE)
                    if m:
                        score = m.group(1) + "%"
                    else:
                        m2 = re.search(r"Suce?ss\s+Rate\s*\n?\s*(\d{1,3})\s*%", page_txt, re.IGNORECASE)
                        if m2:
                            score = m2.group(1) + "%"
                        else:
                            rg = re.search(r"Resumen General[^%]{0,150}?(\d{1,3})\s*%", page_txt, re.IGNORECASE)
                            score = rg.group(1) + "%" if rg else "Sin visita"

                    # 3. Clic neutro para deseleccionar
                    await tienda_label.click()
                    await page.wait_for_timeout(1000)

                result["tiendas"][tienda][visita] = score
                print(f"    🏁 {tienda} | {visita} → {result['tiendas'][tienda][visita]}")

            except Exception as e:
                print(f"     ❌ Error: {e}")
                result["tiendas"][tienda][visita] = "Error"
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
