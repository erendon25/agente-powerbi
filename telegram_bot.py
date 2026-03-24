import asyncio
import logging
import os
import re
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
TOKEN   = os.getenv("TELEGRAM_TOKEN", "8759492692:AAHwjW2Lho1wynrFLpct_FxAO4bVFapK3nM")
URL     = ("https://app.powerbi.com/view?r=eyJrIjoiZWQ1YWNiYjctNWNiNC00MTNlLThjOG"
           "EtNjE1NDc2NTI4NWU2IiwidCI6ImE4MzE3NzZjLWM0ZTUtNDNhMC04ZmZhLTFkNjIxZW"
           "NlZDAzNiIsImMiOjl9")

TIENDAS       = ["PORONGOCHE", "MALL PORONGOCHE"]
TIENDA_EMOJIS = {"PORONGOCHE": "🏪", "MALL PORONGOCHE": "🏬"}
MESES_ES      = {
    1:"Ene", 2:"Feb", 3:"Mar", 4:"Abr", 5:"May", 6:"Jun",
    7:"Jul", 8:"Ago", 9:"Set", 10:"Oct", 11:"Nov", 12:"Dic",
}

CHAT_ID     = None
LAST_RECORD = None

# ─── Servidor web dummy (Render plan gratis necesita un puerto abierto) ───────
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot PowerBI OK")
    def log_message(self, *a): pass

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), DummyHandler).serve_forever()

# ─── Utilidades Playwright ────────────────────────────────────────────────────
async def page_text(page) -> str:
    txt = ""
    for f in page.frames:
        try:
            txt += await f.inner_text("body", timeout=5000) + "\n"
        except Exception:
            pass
    return txt

async def click_slicer_option(page, label: str, option: str):
    """Abre el dropdown del slicer 'label' y selecciona 'option'."""
    for frame in page.frames:
        try:
            headers = frame.locator("h3.slicer-header-text").filter(has_text=label)
            if await headers.count() == 0:
                continue
            container = headers.first.locator(
                "xpath=ancestor::div[contains(@class,'slicer-container')]"
            ).first
            box = container.locator(".slicer-restatement")

            # Abrir dropdown
            if await box.count() > 0:
                await box.first.click(force=True)
            else:
                await container.click(force=True)
            await page.wait_for_timeout(1200)

            # Limpiar selección actual si existe botón borrar
            clear = container.locator(
                ".clear-filter, i[title*='Borrar'], i[title*='Clear'], .slicer-clear"
            )
            if await clear.count() > 0 and await clear.first.is_visible():
                await clear.first.click(force=True)
                await page.wait_for_timeout(800)

            # Hacer "Seleccionar todo" primero para deseleccionar todo (toggle)
            for select_all_text in ["Seleccionar todo", "Select all"]:
                items = frame.locator(".slicerItemContainer")
                cnt = await items.count()
                for i in range(cnt):
                    item = items.nth(i)
                    t = await item.inner_text()
                    if select_all_text.lower() in t.lower() and await item.is_visible():
                        await item.click(force=True)
                        await page.wait_for_timeout(500)
                        await item.click(force=True)  # segunda vez para deseleccionar todo
                        await page.wait_for_timeout(500)
                        break

            # Seleccionar la opción deseada
            items = frame.locator(".slicerItemContainer")
            cnt = await items.count()
            for i in range(cnt):
                item = items.nth(i)
                t = await item.inner_text()
                if option.lower() in t.lower() and await item.is_visible():
                    await item.click(force=True)
                    await page.wait_for_timeout(500)
                    logger.info(f"Slicer '{label}' → '{option}' ✅")
                    # Cerrar dropdown
                    if await box.count() > 0:
                        await box.first.click(force=True)
                    else:
                        await container.click(force=True)
                    await page.wait_for_timeout(800)
                    return True

            # Cerrar aunque no se encontró
            if await box.count() > 0:
                await box.first.click(force=True)
            else:
                await container.click(force=True)
            await page.wait_for_timeout(500)
        except Exception as e:
            logger.warning(f"click_slicer_option('{label}','{option}'): {e}")
    logger.warning(f"Slicer '{label}' → '{option}' ❌ no encontrado")
    return False

async def click_table_row(page, tienda: str) -> bool:
    """Hace clic en la fila de la tabla que contiene el nombre de tienda."""
    tienda_up = tienda.upper()
    row_selectors = ["tr", "div[role='row']", "[class*='tableRow']", "[class*='row']"]
    for frame in page.frames:
        for sel in row_selectors:
            try:
                rows = frame.locator(sel)
                cnt = await rows.count()
                if cnt < 2:
                    continue
                for i in range(cnt):
                    row = rows.nth(i)
                    try:
                        rt = (await row.inner_text(timeout=400)).upper().strip()
                        if tienda_up in rt:
                            logger.info(f"Fila '{tienda}' encontrada: {rt[:80]!r}")
                            await row.click(force=True)
                            return True
                    except Exception:
                        pass
            except Exception:
                pass
    logger.warning(f"No se encontró fila para '{tienda}'")
    return False

def parse_success_rate(text: str):
    """Extrae el porcentaje del 'Sucess Rate' del texto completo de la página."""
    
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    normalized = " ".join(text.split())

    # Estrategia 1: buscar después de "Success Rate" o "Sucess Rate" (PRIORIDAD)
    # Este es el patrón más confiable porque busca específicamente el donut
    m = re.search(r"Suce?ss\s*Rat[^%]{0,200}?(\d{1,3})\s*%", normalized, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        if 0 < val <= 100:
            logger.info(f"parse_success_rate → {val}% (patrón SR)")
            return str(val) + "%"

    # Estrategia 2: buscar línea que sea solo un porcentaje (XX% o XX %)
    # PowerBI renderiza el valor de la métrica en una línea propia
    # Pero solo si no encontramos Success Rate
    valid_pcts = []
    for line in lines[-80:]:
        if 'ampliado' in line.lower() or 'microsoft' in line.lower():
            continue
        m = re.fullmatch(r"(\d{1,3})\s*%", line)
        if m:
            val = int(m.group(1))
            if 0 < val <= 100:
                valid_pcts.append(val)
    
    if valid_pcts:
        logger.info(f"parse_success_rate → {valid_pcts[-1]}% (línea aislada)")
        return f"{valid_pcts[-1]}%"

    # Estrategia 3: buscar en sección Resumen General
    m = re.search(r"Resumen General[^%]{0,200}?(\d{1,3})\s*%", normalized, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        if 0 < val <= 100:
            logger.info(f"parse_success_rate → {val}% (patrón Resumen)")
            return str(val) + "%"

    # Estrategia 4: buscar el número inmediatamente antes o después de "Nota"
    m = re.search(r"Nota\D{0,30}?(\d{1,3})\s*%", normalized, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        if 0 < val <= 100:
            logger.info(f"parse_success_rate → {val}% (patrón Nota)")
            return str(val) + "%"

    # Estrategia 5: buscar "Items con nota" seguido de un porcentaje
    m = re.search(r"Items\s+con\s+nota[^%]{0,100}?(\d{1,3})\s*%", normalized, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        if 0 < val <= 100:
            logger.info(f"parse_success_rate → {val}% (patrón Items)")
            return str(val) + "%"
                
    logger.warning("No se encontró Success Rate válido en el DOM.")
    return None

# ─── Extracción principal ─────────────────────────────────────────────────────
async def extract_full_report() -> dict:
    now = datetime.utcnow()
    # Ajustar a hora Perú (UTC-5)
    mes_idx = now.month if (now.hour - 5) >= 0 else (now.month - 1 or 12)
    mes_actual = MESES_ES[mes_idx]
    logger.info(f"Mes inicial: {mes_actual}")

    result = {
        "record_update": None,
        "mes": mes_actual,
        "tiendas": {t: {} for t in TIENDAS},
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            headless=True,
        )
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="es-PE",
        )
        page = await ctx.new_page()

        # ── Cargar página ────────────────────────────────────────────────────
        logger.info("⏳ Cargando PowerBI (máx 60s)...")
        try:
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            logger.warning(f"⚠️ Timeout en carga: {e}, continuando...")

        # Aceptar cookies si aparecen
        for sel in ["button:has-text('Accept')", "button:has-text('Aceptar')", "button:has-text('OK')"]:
            try:
                b = page.locator(sel).first
                if await b.is_visible(timeout=1000):
                    await b.click()
                    await page.wait_for_timeout(500)
            except Exception:
                pass

        logger.info("⏳ Esperando render (8s)...")
        await page.wait_for_timeout(8000)

        # ── RecordUpdate ─────────────────────────────────────────────────────
        raw = await page_text(page)
        norm_ru = re.sub(r"RecordUpdat\s*e", "RecordUpdate", raw, flags=re.IGNORECASE)
        m = re.search(
            r"RecordUpdate\s*([\d]{1,2}\s*-\s*([A-Za-z]{3})\s*[\d]{1,2}\s*:\s*[\d]{2})",
            norm_ru, re.IGNORECASE,
        )
        if not m:
            m = re.search(
                r"([\d]{1,2}\s*-\s*([A-Za-z]{3})\s*[\d]{1,2}\s*:\s*[\d]{2})",
                norm_ru, re.IGNORECASE,
            )
        if m:
            result["record_update"] = m.group(1).strip()
            mes_actual = m.group(2).strip().capitalize()
            result["mes"] = mes_actual
            logger.info(f"RecordUpdate: {result['record_update']}  |  Mes: {mes_actual}")
        else:
            logger.warning("No se encontró RecordUpdate")

        # ── Filtros globales ─────────────────────────────────────────────────
        logger.info(f"Aplicando filtro Mes = {mes_actual}")
        await click_slicer_option(page, "Mes", mes_actual)
        await page.wait_for_timeout(1500)

        logger.info("Aplicando filtro Supervisor = YOHN")
        await click_slicer_option(page, "Supervisor", "YOHN")
        await page.wait_for_timeout(1500)

        # ── Extraer scores por visita / tienda ───────────────────────────────
        for visita in ["Visita 1", "Visita 2"]:
            logger.info(f"\n{'='*40}\nProcesando {visita}")
            await click_slicer_option(page, "Nro. Visita", visita)
            await page.wait_for_timeout(2500)

            for tienda in TIENDAS:
                logger.info(f"  Buscando {tienda}...")
                score = "Sin visita"
                try:
                    clicked = await click_table_row(page, tienda)
                    if clicked:
                        await page.wait_for_timeout(2500)
                        full_text = await page_text(page)
                        
                        # DEBUG: guardar el texto para diagnosticar
                        debug_file = Path(__file__).parent / f"debug_{tienda.replace(' ', '_')}_{visita.replace(' ', '_')}.txt"
                        try:
                            debug_file.write_text(full_text, encoding="utf-8")
                            logger.info(f"💾 Debug guardado en: {debug_file}")
                        except Exception as e:
                            logger.error(f"❌ Error guardando debug: {e}")
                        
                        # Log de diagnóstico: primeros 500 chars normalizados
                        norm_dbg = " ".join(full_text.split())
                        logger.info(f"[{tienda}|{visita}] Texto (500c): {norm_dbg[:500]}")
                        parsed = parse_success_rate(full_text)
                        if parsed:
                            score = parsed
                            logger.info(f"  ✅ {tienda} | {visita} = {score}")
                        else:
                            logger.warning(f"  ⚠️ No se encontró score para {tienda} | {visita}")
                        # Deseleccionar fila
                        try:
                            await page.mouse.click(960, 30)
                            await page.wait_for_timeout(600)
                        except Exception:
                            pass
                    else:
                        logger.warning(f"  ⚠️ Fila no encontrada: {tienda}")
                except Exception as e:
                    logger.error(f"  ❌ Error en {tienda}: {e}", exc_info=True)

                result["tiendas"][tienda][visita] = score
                logger.info(f"  RESULTADO {tienda} | {visita}: {score}")

        await ctx.close()
        await browser.close()

    return result

# ─── Formateo de mensaje ──────────────────────────────────────────────────────
def format_report_message(report: dict) -> str:
    year = datetime.now().year
    mes    = report.get("mes", "?")
    record = report.get("record_update", "?")
    lines  = [
        f"✅ *Consulta Manual — {mes} {year}*",
        f"🕐 RecordUpdate: `{record}`",
        "",
    ]
    for tienda, visitas in report.get("tiendas", {}).items():
        emoji = TIENDA_EMOJIS.get(tienda, "🏪")
        lines.append(f"{emoji} *{tienda}*")
        if visitas:
            for nro, nota in visitas.items():
                lines.append(f"   • {nro}: `{nota}`")
        else:
            lines.append("   • Sin datos disponibles")
        lines.append("")
    lines.append(f"[Ver PowerBI]({URL})")
    return "\n".join(lines)

# ─── Extracción solo RecordUpdate (para el check_job) ────────────────────────
async def extract_record_update():
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
                headless=True,
            )
            page = await browser.new_page()
            await page.goto(URL, wait_until="networkidle", timeout=60000)
            await page.wait_for_timeout(15000)
            raw = await page_text(page)
            await browser.close()
            norm = re.sub(r"RecordUpdat\s*e", "RecordUpdate", raw, flags=re.IGNORECASE)
            m = re.search(
                r"RecordUpdate\s*([\d]{1,2}\s*-\s*[A-Za-z]{3}\s*\d{1,2}\s*:\s*\d{2})",
                norm, re.IGNORECASE,
            )
            return m.group(1).strip() if m else None
    except Exception as e:
        logger.error(f"extract_record_update: {e}")
        return None

# ─── Handlers Telegram ────────────────────────────────────────────────────────
async def check_job(context: ContextTypes.DEFAULT_TYPE):
    global LAST_RECORD, CHAT_ID
    if not CHAT_ID:
        return
    current = await extract_record_update()
    if current and current != LAST_RECORD:
        LAST_RECORD = current
        report = await extract_full_report()
        report["record_update"] = current
        await context.bot.send_message(
            chat_id=CHAT_ID,
            text=format_report_message(report),
            parse_mode="Markdown",
        )
    else:
        logger.info(f"check_job: sin cambios ({current})")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CHAT_ID
    CHAT_ID = update.effective_chat.id
    if context.job_queue:
        if not context.job_queue.get_jobs_by_name("powerbi_checker"):
            context.job_queue.run_repeating(
                check_job, interval=3600, first=10, name="powerbi_checker"
            )
    await update.message.reply_text(
        "✅ *Bot iniciado!*\n\n"
        "Revisaré tu PowerBI cada hora.\n\n"
        "• /reporte → Ver notas del mes actual\n"
        "• /intervalo 60 → Cambiar frecuencia",
        parse_mode="Markdown",
    )

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Consultando PowerBI... (máx 3 minutos, por favor espera).")
    try:
        # Timeout de 3 minutos para toda la operación
        report = await asyncio.wait_for(extract_full_report(), timeout=180)
        if report.get("record_update"):
            await update.message.reply_text(format_report_message(report), parse_mode="Markdown")
        else:
            await update.message.reply_text(
                "⚠️ No pude leer el RecordUpdate. El dashboard puede estar cargando lento.\n"
                "Intenta de nuevo en 1 minuto."
            )
    except asyncio.TimeoutError:
        logger.error("report_command: Timeout después de 3 minutos")
        await update.message.reply_text(
            "⏱️ Timeout: PowerBI tardó demasiado en cargar.\n"
            "Intenta de nuevo en 1 minuto."
        )
    except Exception as e:
        logger.error(f"report_command error: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Error interno:\n`{e}`", parse_mode="Markdown")

async def set_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        minutes = int(context.args[0])
        if minutes < 1:
            await update.message.reply_text("⛔ Mínimo 1 minuto.")
            return
        if context.job_queue:
            for job in context.job_queue.get_jobs_by_name("powerbi_checker"):
                job.schedule_removal()
            context.job_queue.run_repeating(
                check_job, interval=minutes * 60, first=5, name="powerbi_checker"
            )
            await update.message.reply_text(
                f"⏱️ Revisaré cada *{minutes} min*.", parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ job_queue no disponible.")
    except (IndexError, ValueError):
        await update.message.reply_text("Uso: /intervalo <minutos>  Ej: /intervalo 60")

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    if not TOKEN:
        logger.error("TELEGRAM_TOKEN no definido.")
        return
    threading.Thread(target=run_dummy_server, daemon=True).start()
    logger.info("Servidor web dummy iniciado.")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",     start_command))
    app.add_handler(CommandHandler("reporte",   report_command))
    app.add_handler(CommandHandler("intervalo", set_interval))

    logger.info("🤖 Bot activo...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
