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
        m = re.search(r"RecordUpdate\s*([\d]{1,2}\s*-\s*[A-Za-z]{3}\s*[\d]{1,2}\s*:\s*[\d]{2})", text_norm, re.IGNORECASE)
        if m:
            result["record_update"] = m.group(1).strip()

        visitas = ["Visita 1", "Visita 2"]

        for tienda in TIENDAS:
            for visita in visitas:
                try:
                    try:
                        await page.goto(URL, wait_until="networkidle", timeout=90000)
                    except Exception:
                        await page.goto(URL, wait_until="domcontentloaded", timeout=90000)
                    await page.wait_for_timeout(10000)

                    for sel in consent_selectors:
                        try:
                            btn = page.locator(sel).first
                            if await btn.is_visible(timeout=1000):
                                await btn.click()
                                await page.wait_for_timeout(500)
                        except Exception:
                            pass

                    await click_filter_option(page, "Mes", mes_actual, deselect_all_first=True)
                    await page.wait_for_timeout(1500)
                    await click_filter_option(page, "Supervisor", "YOHN", deselect_all_first=True)
                    await page.wait_for_timeout(1500)
                    await click_filter_option(page, "Nro. Visita", visita, deselect_all_first=True)
                    await page.wait_for_timeout(1500)

                    # Filtrar por tienda haciendo clic en "Top Places"
                    try:
                        tienda_label = page.locator(f"text={tienda}").last
                        if await tienda_label.is_visible(timeout=3000):
                            await tienda_label.click()
                            await page.wait_for_timeout(2000)
                    except Exception:
                        pass

                    text = await get_page_text(page)

                    # Buscar Success Rate
                    score = None
                    sr_match = re.search(r"Suce?ss\s+Rate\s*\n?\s*(\d{1,3})\s*%", text, re.IGNORECASE)
                    if sr_match:
                        score = sr_match.group(1) + "%"
                    else:
                        matches = re.findall(r"(\d{1,3})\s*%", text)
                        non_100 = [m for m in matches if m != "100"]
                        if non_100:
                            score = non_100[0] + "%"
                        elif matches:
                            score = matches[0] + "%"

                    result["tiendas"][tienda][visita] = score or "N/D"
                except Exception as e:
                    result["tiendas"][tienda][visita] = "Error"
                    print(f"Error {tienda} {visita}: {e}")

        await context.close()
        await browser.close()

    return result

def format_report_message(report: dict) -> str:
    mes = report.get("mes", "?")
    record = report.get("record_update", "?")
    tiendas = report.get("tiendas", {})
    lineas = [
        f"📊 *Reporte Mystery Client — {mes} 2026*",
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
    await update.message.reply_text("🔍 Revisando PowerBI... (espera ~60 segundos).")

    report = await extract_full_report()

    if report.get("record_update"):
        mensaje = format_report_message(report)
        await update.message.reply_text(mensaje, parse_mode="Markdown")
    else:
        await update.message.reply_text(
            "⚠️ No pude leer los datos del PowerBI en este momento. Puede ser un error de carga."
        )

async def set_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cambia el intervalo de revisión automática."""
    try:
        minutes = int(context.args[0])
        if minutes < 1:
            await update.message.reply_text("⛔ El mínimo es 1 minuto.")
            return

        current_jobs = context.job_queue.get_jobs_by_name("powerbi_checker")
        for job in current_jobs:
            job.schedule_removal()

        context.job_queue.run_repeating(check_job, interval=minutes * 60, first=5, name="powerbi_checker")
        await update.message.reply_text(f"⏱️ Listo! Revisaré PowerBI cada *{minutes} minuto(s)*.", parse_mode="Markdown")
    except (IndexError, ValueError):
        await update.message.reply_text("Uso: /intervalo <minutos>\nEjemplo: /intervalo 60")

def main():
    if not TOKEN:
        print("ERROR: Falta el TELEGRAM_TOKEN.")
        return

    # Inicia el servidor web en un hilo paralelo (requerido por Render)
    threading.Thread(target=run_dummy_server, daemon=True).start()
    print(f"Servidor web iniciado.")

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("reporte", report_command))
    application.add_handler(CommandHandler("intervalo", set_interval))

    print("🤖 Bot de Telegram activo, esperando /start...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
