import asyncio
from playwright.async_api import async_playwright

URL = "https://app.powerbi.com/view?r=eyJrIjoiZWQ1YWNiYjctNWNiNC00MTNlLThjOGEtNjE1NDc2NTI4NWU2IiwidCI6ImE4MzE3NzZjLWM0ZTUtNDNhMC04ZmZhLTFkNjIxZWNlZDAzNiIsImMiOjl9"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            headless=True
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = await context.new_page()
        try:
            await page.goto(URL, wait_until="networkidle", timeout=30000)
        except Exception:
            pass
        
        await page.wait_for_timeout(15000)
        
        # Guardar todo el innerHTML
        html = await page.content()
        with open("d:\\agente-powerbi\\dom_dump.html", "w", encoding="utf-8") as f:
            f.write(html)
            
        # Además frame html
        for i, frame in enumerate(page.frames):
            html = await frame.content()
            with open(f"d:\\agente-powerbi\\dom_dump_frame_{i}.html", "w", encoding="utf-8") as f:
                f.write(html)
                
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
