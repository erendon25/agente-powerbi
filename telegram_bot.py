import asyncio
import os
import re
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Servidor web falso para que Render (plan gratis) permita alojarlo
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot de PowerBI funcionando!")
    def log_message(self, format, *args):
        pass  # Silenciar logs de HTTP

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), DummyHandler)
    server.serve_forever()

# URL del PowerBI
URL = "https://app.powerbi.com/view?r=eyJrIjoiZWQ1YWNiYjctNWNiNC00MTNlLThjOGEtNjE1NDc2NTI4NWU2IiwidCI6ImE4MzE3NzZjLWM0ZTUtNDNhMC04ZmZhLTFkNjIxZWNlZDAzNiIsImMiOjl9"

# Token del bot de Telegram (desde variable de entorno o valor por defecto)
TOKEN = os.getenv("TELEGRAM_TOKEN", "8759492692:AAHwjW2Lho1wynrFLpct_FxAO4bVFapK3nM")
CHAT_ID = None   # Se guarda automáticamente cuando haces /start
LAST_RECORD = None

# Tiendas a reportar
TIENDAS = ["PORONGOCHE", "MALL PORONGOCHE"]
TIENDA_EMOJIS = {"PORONGOCHE": "🏪", "MALL PORONGOCHE": "🏬"}

# Meses en español
MESES_ES = {
    1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr",
    5: "May", 6: "Jun", 7: "Jul", 8: "Ago",
    9: "Set", 10: "Oct", 11: "Nov", 12: "Dic"
}

async def get_page_text(page) -> str:
    text_content = ""
    for frame in page.frames:
        try:
            text = await frame.inner_text("body", timeout=5000)
            text_content += text + "\n"
        except Exception:
            pass
    return text_content

async def click_option_in_frames(page, option_text: str, wait_ms: int = 1000) -> bool:
    for frame in page.frames:
        try:
            slicer_items = frame.locator(".slicerItemContainer")
            count = await slicer_items.count()
            if count > 0:
                for i in range(count):
                    item = slicer_items.nth(i)
                    if await item.is_visible():
                        text = await item.inner_text()
                        if option_text.lower() in text.lower():
                            await item.click(force=True)
                            await page.wait_for_timeout(wait_ms)
                            return True
            
            for loc_expr in [
                lambda f: f.get_by_text(option_text, exact=True),
                lambda f: f.locator(f"span:has-text('{option_text}')"),
            ]:
                loc = loc_expr(frame)
                cnt = await loc.count()
                for i in range(cnt):
                    el = loc.nth(i)
                    if await el.is_visible():
                        await el.click(force=True)
                        await page.wait_for_timeout(wait_ms)
                        return True
        except Exception:
            pass
    return False

async def deselect_all_in_frames(page) -> bool:
    for text in ["Seleccionar todo", "Select all"]:
        if await click_option_in_frames(page, text, wait_ms=600):
            return True
    return False

async def click_filter_option(page, filter_label: str, option_text: str, deselect_all_first: bool = False):
    for frame in page.frames:
        try:
            headers = frame.locator("h3.slicer-header-text").filter(has_text=filter_label)
            if await headers.count() > 0:
                container = headers.first.locator("xpath=ancestor::div[contains(@class, 'slicer-container')]").first
                box = container.locator(".slicer-restatement")
                
                if await box.count() > 0:
                    await box.first.click(force=True)
                else:
                    await container.click(force=True)
                
                await page.wait_for_timeout(1500)

                clear_btn = container.locator(".clear-filter, i[title*='Borrar'], i[title*='Clear'], .slicer-clear")
                if await clear_btn.count() > 0 and await clear_btn.first.is_visible():
                    try:
                        await clear_btn.first.click(force=True)
                        await page.wait_for_timeout(1000)
                    except:
                        pass

                if deselect_all_first:
                    try:
                        # Optional double toggle
                        await deselect_all_in_frames(page)
                        await page.wait_for_timeout(800)
                        await deselect_all_in_frames(page)
                    except: pass
                    await page.wait_for_timeout(1000)

                clicked = await click_option_in_frames(page, option_text)
                
                if await box.count() > 0:
                    await box.first.click(force=True)
                else:
                    await container.click(force=True)
                    
                await page.wait_for_timeout(1000)
                return clicked
        except Exception:
            pass
    return False

def parse_score_from_row(row_text: str) -> str:
    matches = re.findall(r"(\d{1,3})\s*%", row_text)
    valid = [int(x) for x in matches if 0 < int(x) <= 100]
    if valid: return str(valid[0]) + "%"
    matches_dec = re.findall(r"(\d{1,3})[.,]\d+", row_text)
    valid_dec = [int(x) for x in matches_dec if 0 < int(x) <= 100]
    if valid_dec: return str(valid_dec[0]) + "%"
    return None

async def find_score_in_table(page, tienda: str, visita: str):
    tienda_norm = tienda.upper().strip()
    visita_norm = visita.upper().strip()
    row_selectors = ["tr", "div[role='row']", "[class*='row']", "[class*='tableRow']"]
    for frame in page.frames:
        for sel in row_selectors:
            try:
                rows = frame.locator(sel)
                count = await rows.count()
                for i in range(count):
                    row = rows.nth(i)
                    try:
                        rt_peek = await row.inner_text(timeout=500)
                        rt_norm = rt_peek.upper().strip()
                        if tienda_norm in rt_norm and visita_norm in rt_norm:
                            score = parse_score_from_row(rt_peek)
                            if score: return score
                        # También si solo está la tienda y un número (por slicer Nro. Visita)
                        elif tienda_norm in rt_norm and re.search(r'\d', rt_norm):
                            score = parse_score_from_row(rt_peek)
                            if score: return score
                    except Exception:
                        pass
            except Exception:
                pass
    return None

async def extract_full_report() -> dict:
    """
    Extrae notas por Nro. de Visita para el mes actual
    para Porongoche y Mall Porongoche bajo supervisor YOHN.
    """
    now = datetime.utcnow()
    mes_actual = MESES_ES[now.month]
    consent_selectors = [
        "button:has-text('Accept')", "button:has-text('Aceptar')",
        "button:has-text('I accept')", "button:has-text('Continue')",
        "button:has-text('OK')", "[id*='accept']", "[class*='consent']",
    ]

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

        # Carga inicial para sacar RecordUpdate
        try:
            await page.goto(URL, wait_until="networkidle", timeout=90000)
        except Exception:
            await page.goto(URL, wait_until="domcontentloaded", timeout=90000)

        for sel in consent_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    await page.wait_for_timeout(1000)
            except Exception:
                pass

        await page.wait_for_timeout(12000)
        text_inicial = await get_page_text(page)

        # Extraer RecordUpdate
        text_norm = re.sub(r'RecordUpdat\s*e', 'RecordUpdate', text_inicial, flags=re.IGNORECASE)
        m = re.search(r"RecordUpdate\s*([\d]{1,2}\s*-\s*([A-Za-z]{3})\s*[\d]{1,2}\s*:\s*[\d]{2})", text_norm, re.IGNORECASE)
        if m:
            result["record_update"] = m.group(1).strip()
            mes_actual = m.group(2).strip().capitalize()
            result["mes"] = mes_actual
        else:
            m = re.search(r"([\d]{1,2}\s*-\s*([A-Za-z]{3})\s*[\d]{1,2}\s*:\s*[\d]{2})", text_norm, re.IGNORECASE)
            if m:
                result["record_update"] = m.group(1).strip()
                mes_actual = m.group(2).strip().capitalize()
                result["mes"] = mes_actual

        visitas = ["Visita 1", "Visita 2"]

        # Filtros globales (Mes, Supervisor) se aplican una sola vez
        print("Aplicando filtros globales...")
        await click_filter_option(page, "Mes", mes_actual, deselect_all_first=True)
        await page.wait_for_timeout(1000)
        
        await click_filter_option(page, "Supervisor", "YOHN", deselect_all_first=True)
        await page.wait_for_timeout(1000)



        for visita in visitas:
            print(f"Filtrando {visita}...")
            await click_filter_option(page, "Nro. Visita", visita, deselect_all_first=True)
            await page.wait_for_timeout(2500)
            
            for tienda in TIENDAS:
                score_table = await find_score_in_table(page, tienda, visita)
                if score_table:
                    score = score_table
                    print(f" -> {tienda} (tabla): {score}")
                else:
                    score = "Sin visita"
                    try:
                        clicked = False
                        for frame in page.frames:
                            tienda_labels = frame.get_by_text(tienda, exact=True)
                            count = await tienda_labels.count()
                            for i in range(count):
                                lbl = tienda_labels.nth(i)
                                if await lbl.is_visible():
                                    try:
                                        await lbl.scroll_into_view_if_needed()
                                        await lbl.click(force=True)
                                        clicked = True
                                        await page.wait_for_timeout(3500) # Un poco más de tiempo para que cargue
                                        text = await get_page_text(page)
                                        
                                        # Normalizar texto (cambiar saltos de línea por espacios)
                                        norm_text = " ".join(text.split())
                                        if 'logger' in globals(): logger.info(f"[{tienda} - {visita}] Texto extraido: {norm_text[:200]}...")
                                        
                                        score = None
                                        
                                        # Estrategias de parseo mejoradas
                                        m = re.search(r"(\d{1,3})\s*%\s*.*Suce?ss\s+Rat", norm_text, re.IGNORECASE)
                                        if m:
                                            score = m.group(1) + "%"
                                        if not score:
                                            m = re.search(r"Suce?ss\s*Rat[^%]{0,200}?(\d{1,3})\s*%", norm_text, re.IGNORECASE)
                                            if m:
                                                score = m.group(1) + "%"
                                        
                                        if not score:
                                            m = re.search(r"Resumen General[^%]{0,200}?(\d{1,3})\s*%", norm_text, re.IGNORECASE)
                                            if m:
                                                score = m.group(1) + "%"
                                                
                                        if not score:
                                            m = re.search(r"Nota\D{0,30}?(\d{1,3})\s*%", norm_text, re.IGNORECASE)
                                            if m:
                                                score = m.group(1) + "%"
                                                
                                        score = score if score else "Sin visita"
                                        if 'logger' in globals(): logger.info(f"[{tienda} - {visita}] Score final: {score}")
                                        
                                        # Deseleccionar la tienda actual
                                        await lbl.click(force=True)
                                        await page.wait_for_timeout(1000)
                                        break
                                    except Exception as e:
                                        if 'logger' in globals(): logger.warning(f"Error parseando {tienda}: {e}")
                            if clicked:
                                break
                    except Exception as e:
                        if 'logger' in globals(): logger.warning(f"Error general en {tienda}: {e}")
                
                    print(f" -> {tienda}: {score}")
                    result["tiendas"][tienda][visita] = score

        await context.close()
        await browser.close()

    return result

def format_report_message(report: dict) -> str:
    from datetime import datetime
    year = datetime.now().year

    mes = report.get("mes", "?")
    record = report.get("record_update", "?")
    tiendas = report.get("tiendas", {})

    lineas  = [
        f"✅ *Consulta Manual — {mes} {year}*",
        f"🕐 RecordUpdate: `{record}`",
        "",
    ]
    for tienda, visitas in tiendas.items():
        emoji = TIENDA_EMOJIS.get(tienda, "🏪")
        lineas.append(f"{emoji} *{tienda}*")
        if visitas:
            for nro_visita, nota in visitas.items():
                lineas.append(f"   • {nro_visita}: `{nota}`")
        else:
            lineas.append("   • Sin datos disponibles")
        lineas.append("")
    lineas.append(f"[Ver PowerBI]({URL})")
    return "\n".join(lineas)

async def extract_record_update():
    """Para compatibilidad con el check_job (solo el RecordUpdate)."""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
                headless=True
            )
            page = await browser.new_page()
            await page.goto(URL, wait_until="networkidle", timeout=60000)
            await page.wait_for_timeout(15000)

            text_content = ""
            for frame in page.frames:
                try:
                    text = await frame.inner_text("body", timeout=5000)
                    text_content += text + "\n"
                except Exception:
                    pass

            await browser.close()

            text_norm = re.sub(r'RecordUpdat\s*e', 'RecordUpdate', text_content, flags=re.IGNORECASE)
            match = re.search(
                r"RecordUpdate\s*([\d]{1,2}\s*-\s*[A-Za-z]{3}\s*\d{1,2}\s*:\s*\d{2})",
                text_norm, re.IGNORECASE
            )
            return match.group(1).strip() if match else None
    except Exception as e:
        print(f"Error extrayendo RecordUpdate: {e}")
        return None

async def check_job(context: ContextTypes.DEFAULT_TYPE):
    """Job periódico: revisa PowerBI y avisa si cambió con reporte detallado."""
    global LAST_RECORD, CHAT_ID
    if not CHAT_ID:
        return

    current_record = await extract_record_update()

    if current_record and current_record != LAST_RECORD:
        LAST_RECORD = current_record
        # Generar reporte detallado
        report = await extract_full_report()
        report["record_update"] = current_record
        mensaje = format_report_message(report)
        await context.bot.send_message(
            chat_id=CHAT_ID,
            text=mensaje,
            parse_mode="Markdown"
        )
    else:
        print(f"Sin cambios. Valor actual: {current_record}")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia el bot y guarda el chat ID del usuario."""
    global CHAT_ID
    CHAT_ID = update.effective_chat.id

    if context.job_queue:
        current_jobs = context.job_queue.get_jobs_by_name("powerbi_checker")
        if not current_jobs:
            context.job_queue.run_repeating(check_job, interval=3600, first=10, name="powerbi_checker")

    await update.message.reply_text(
        "✅ *Bot iniciado correctamente!*\n\n"
        "Revisaré tu PowerBI cada hora y te avisaré si cambia.\n\n"
        "Comandos disponibles:\n"
        "• /reporte → Ver notas por visita del mes actual\n"
        "• /intervalo 60 → Revisar cada 60 minutos\n"
        "• /intervalo 1 → Revisar cada 1 minuto",
        parse_mode="Markdown"
    )

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Revisión inmediata con reporte detallado por visita y tienda."""
    try:
        await update.message.reply_text("🔍 Revisando PowerBI... (espera ~60 segundos).")

        report = await extract_full_report()

        if report.get("record_update"):
            mensaje = format_report_message(report)
            await update.message.reply_text(mensaje, parse_mode="Markdown")
        else:
            await update.message.reply_text(
                "⚠️ No pude leer los datos del PowerBI en este momento. Puede ser un error de carga."
            )
    except Exception as e:
        if 'logger' in globals():
            logger.error(f"Error en /reporte: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ocurrió un error interno: {str(e)}")

async def set_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cambia el intervalo de revisión automática."""
    try:
        minutes = int(context.args[0])
        if minutes < 1:
            await update.message.reply_text("⛔ El mínimo es 1 minuto.")
            return

        if context.job_queue:
            current_jobs = context.job_queue.get_jobs_by_name("powerbi_checker")
            for job in current_jobs:
                job.schedule_removal()

            context.job_queue.run_repeating(check_job, interval=minutes * 60, first=5, name="powerbi_checker")
            await update.message.reply_text(f"⏱️ Listo! Revisaré PowerBI cada *{minutes} minuto(s)*.", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ No está habilitado el planificador (job_queue).")
    except (IndexError, ValueError):
        await update.message.reply_text("Uso: /intervalo <minutos>\nEjemplo: /intervalo 60")

import logging

# Habilitar logs detallados para ver errores, muy útil
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def main():
    if not TOKEN:
        print("ERROR: Falta el TELEGRAM_TOKEN.")
        return

    # Inicia el servidor web en un hilo paralelo (requerido por Render)
    try:
        threading.Thread(target=run_dummy_server, daemon=True).start()
        print(f"Servidor web iniciado.")
    except Exception as e:
        logger.error(f"No se pudo iniciar servidor web: {e}")

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("reporte", report_command))
    application.add_handler(CommandHandler("intervalo", set_interval))

    print("🤖 Bot de Telegram activo, esperando comandos...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
