import asyncio
from playwright.async_api import async_playwright

URL = "https://app.powerbi.com/view?r=eyJrIjoiZWQ1YWNiYjctNWNiNC00MTNlLThjOGEtNjE1NDc2NTI4NWU2IiwidCI6ImE4MzE3NzZjLWM0ZTUtNDNhMC04ZmZhLTFkNjIxZWNlZDAzNiIsImMiOjl9"

async def main():
    async with async_playwright() as p:
         browser = await p.chromium.launch(headless=True)
         page = await browser.new_page()
         await page.goto(URL, wait_until="networkidle", timeout=60000)
         await page.wait_for_timeout(15000)
         
         text_content = ""
         for frame in page.frames:
             try:
                 text = await frame.inner_text("body", timeout=5000)
                 text_content += f"\n--- FRAME {frame.name} ---\n" + text + "\n"
             except Exception as e:
                 text_content += f"\n--- FRAME Error ---\n{e}\n"
         
         with open("d:\\agente-powerbi\\debug_scraping.txt", "w", encoding="utf-8") as f:
             f.write(text_content)
             
         await browser.close()

asyncio.run(main())
