import asyncio
from playwright.async_api import async_playwright

URL = "https://app.powerbi.com/view?r=eyJrIjoiZWQ1YWNiYjctNWNiNC00MTNlLThjOGEtNjE1NDc2NTI4NWU2IiwidCI6ImE4MzE3NzZjLWM0ZTUtNDNhMC04ZmZhLTFkNjIxZWNlZDAzNiIsImMiOjl9"
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
        except Exception: pass
    return False

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"], headless=True)
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()
        await page.goto(URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(10000)

        html = ""
        for frame in page.frames:
            try:
                if await frame.locator("text='Top Places'").count() > 0:
                    tp = frame.locator("text='Top Places'").first
                    container = tp.locator("xpath=ancestor::visual-container").first
                    html = await container.inner_html()
                    break
            except: pass
        
        with open("d:\\agente-powerbi\\top_places_dom.html", "w", encoding="utf-8") as f:
            f.write(html)
        
        await browser.close()
if __name__ == "__main__": asyncio.run(main())
