import asyncio
import os
import re
from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

URL = "https://app.powerbi.com/view?r=eyJrIjoiZWQ1YWNiYjctNWNiNC00MTNlLThjOGEtNjE1NDc2NTI4NWU2IiwidCI6ImE4MzE3NzZjLWM0ZTUtNDNhMC04ZmZhLTFkNjIxZWNlZDAzNiIsImMiOjl9"

# Token from BotFather
TOKEN = os.getenv("TELEGRAM_TOKEN", "8759492692:AAHwjW2Lho1wynrFLpct_FxAO4bVFapK3nM")
CHAT_ID = None  # We will save the chat ID when you interact with the bot
LAST_RECORD = None

async def extract_record_update():
    """Extracts the RecordUpdate from the PowerBI page."""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"], headless=True)
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
            
            match = re.search(r"RecordUpdate\s*([\d]{1,2}\s*-\s*[A-Za-z]{3}\s*\d{1,2}\s*:\s*\d{2})", text_content, re.IGNORECASE)
            
            if match:
                return match.group(1).strip()
            else:
                return None
    except Exception as e:
        print(f"Error extracting data: {e}")
        return None

async def check_job(context: ContextTypes.DEFAULT_TYPE):
    """Checks the PowerBI page periodically and sends a message if it changes."""
    global LAST_RECORD, CHAT_ID
    if not CHAT_ID:
        return
    
    current_record = await extract_record_update()
    
    if current_record and current_record != LAST_RECORD:
        LAST_RECORD = current_record
        await context.bot.send_message(
            chat_id=CHAT_ID, 
            text=f"🔴 ¡Actualización detectada!\nEl RecordUpdate ha cambiado a: {LAST_RECORD}"
        )

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts the bot and saves the chat ID."""
    global CHAT_ID
    CHAT_ID = update.effective_chat.id
    
    # Start the default hourly job if not present
    current_jobs = context.job_queue.get_jobs_by_name("powerbi_checker")
    if not current_jobs:
        context.job_queue.run_repeating(check_job, interval=3600, first=10, name="powerbi_checker")
        
    await update.message.reply_text("✅ Bot iniciado. Te enviaré notificaciones cada hora si detecto cambios en tu PowerBI.")

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Forces an immediate check of the PowerBI page."""
    await update.message.reply_text("🔍 Revisando PowerBI en este momento... (tomará unos 20-30 segundos).")
    current_record = await extract_record_update()
    
    if current_record:
        await update.message.reply_text(f"📊 La nota actual de RecordUpdate es: {current_record}")
    else:
        await update.message.reply_text("⚠️ No pude encontrar la nota en este momento (pudo haber un error de carga).")

async def set_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Changes the checking interval."""
    try:
        minutes = int(context.args[0])
        if minutes < 1:
            await update.message.reply_text("⛔ El intervalo mínimo es 1 minuto.")
            return

        current_jobs = context.job_queue.get_jobs_by_name("powerbi_checker")
        for job in current_jobs:
            job.schedule_removal()
            
        context.job_queue.run_repeating(check_job, interval=minutes * 60, first=5, name="powerbi_checker")
        await update.message.reply_text(f"⏱️ Intervalo cambiado. Revisaré PowerBI cada {minutes} minuto(s).")
    except (IndexError, ValueError):
        await update.message.reply_text("Uso correcto: /intervalo <minutos>\nEjemplo: /intervalo 60")

def main():
    if not TOKEN:
        print("ERROR: Por favor, configura tu TELEGRAM_TOKEN antes de iniciar.")
        return

    # Create application
    application = Application.builder().token(TOKEN).build()

    # Commands
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("reporte", report_command))
    application.add_handler(CommandHandler("intervalo", set_interval))

    # Run bot
    print("🤖 Bot de Telegram en línea y esperando por el comando /start...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
