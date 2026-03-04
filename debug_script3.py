import asyncio
import os
import re
from datetime import datetime
from playwright.async_api import async_playwright

URL = "https://app.powerbi.com/view?r=eyJrIjoiZWQ1YWNiYjctNWNiNC00MTNlLThjOGEtNjE1NDc2NTI4NWU2IiwidCI6ImE4MzE3NzZjLWM0ZTUtNDNhMC04ZmZhLTFkNjIxZWNlZDAzNiIsImMiOjl9"
TIENDAS = ["PORONGOCHE", "MALL PORONGOCHE"]

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
    slicers = page.locator("visual-container")
    count = await slicers.count()
    for i in range(count):
        slicer = slicers.nth(i)
        try:
            slicer_text = await slicer.inner_text(timeout=3000)
            if filter_label.lower() in slicer_text.lower():
                try:
                    await slicer.click(position={"x": 10, "y": 10})
                except Exception:
                    await slicer.click()
                await page.wait_for_timeout(1000)

                if deselect_all_first:
                    await deselect_all_in_frames(page)
                    await page.wait_for_timeout(800)

                clicked = await click_option_in_frames(page, option_text)
                
                try:
                    await slicer.click(position={"x": 10, "y": 10})
                except Exception:
                    await slicer.click()
                await page.wait_for_timeout(1000)
                
                return clicked
        except Exception:
            continue
    return False

async def main():
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

        print("Loading...")
        try:
            await page.goto(URL, wait_until="networkidle", timeout=30000)
        except Exception:
            print("Fallback to domcontentloaded")
            await page.goto(URL, wait_until="domcontentloaded", timeout=10000)

        await page.wait_for_timeout(5000)
        
        # Aceptar cookies
        for sel in ["button:has-text('Accept')", "button:has-text('Aceptar')", "button:has-text('OK')", "[id*='accept']"]:
            try:
                b = page.locator(sel).first
                if await b.is_visible(timeout=1000):
                    await b.click()
            except Exception:
                pass

        print("Filtering Mes=Feb...")
        await click_filter_option(page, "Mes", "Feb", deselect_all_first=True)
        print("Filtering Supervisor=YOHN...")
        await click_filter_option(page, "Supervisor", "YOHN", deselect_all_first=True)
        print("Filtering Visita 1...")
        await click_filter_option(page, "Nro. Visita", "Visita 1", deselect_all_first=True)

        print("Dumping state and screenshot...")
        text = await get_page_text(page)
        with open("d:\\agente-powerbi\\log_final.txt", "w", encoding="utf-8") as f:
            f.write(text)
        await page.screenshot(path="d:\\agente-powerbi\\log_final.png")
        print("Done!")
        
        await context.close()
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
