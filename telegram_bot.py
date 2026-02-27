import asyncio
import os
import re
import threading
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

async def extract_record_update():
    """Abre el PowerBI de forma invisible y extrae el RecordUpdate."""
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

            match = re.search(
                r"RecordUpdate\s*([\d]{1,2}\s*-\s*[A-Za-z]{3}\s*\d{1,2}\s*:\s*\d{2})",
                text_content,
                re.IGNORECASE
            )

            if match:
                return match.group(1).strip()
            else:
                return None
    except Exception as e:
        print(f"Error extrayendo datos: {e}")
        return None

async def check_job(context: ContextTypes.DEFAULT_TYPE):
    """Job periódico: revisa PowerBI y avisa si cambió."""
    global LAST_RECORD, CHAT_ID
    if not CHAT_ID:
        return

    current_record = await extract_record_update()

    if current_record and current_record != LAST_RECORD:
        LAST_RECORD = current_record
        await context.bot.send_message(
            chat_id=CHAT_ID,
            text=f"🔴 *¡RecordUpdate cambió!*\nNuevo valor: `{LAST_RECORD}`",
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
        "• /reporte → Ver la nota ahora mismo\n"
        "• /intervalo 60 → Revisar cada 60 minutos\n"
        "• /intervalo 1 → Revisar cada 1 minuto",
        parse_mode="Markdown"
    )

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Revisión inmediata a pedido."""
    await update.message.reply_text("🔍 Revisando PowerBI... (espera ~20 segundos).")
    current_record = await extract_record_update()

    if current_record:
        await update.message.reply_text(
            f"📊 *RecordUpdate actual:*\n`{current_record}`",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("⚠️ No encontré el RecordUpdate en este momento. Puede ser un error de carga.")

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
