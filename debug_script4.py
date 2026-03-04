import asyncio
import os
import re
from datetime import datetime
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

async def click_filter_debug(page, filter_label, option_text):
    for frame in page.frames:
        try:
            headers = frame.locator("h3.slicer-header-text").filter(has_text=filter_label)
            if await headers.count() > 0:
                print(f"[{filter_label}] Found header")
                container = headers.first.locator("xpath=ancestor::div[contains(@class, 'slicer-container')]").first
                box = container.locator(".slicer-restatement")
                
                # Check status
                print(f"[{filter_label}] Initial status: ", await box.inner_text())

                # Open dropdown
                if await box.count() > 0:
                    await box.first.click(force=True)
                else:
                    await container.click(force=True)
                await page.wait_for_timeout(1500)
                
                await page.screenshot(path=f"d:\\agente-powerbi\\log_debug_{filter_label}_opened.png")

                clear_btn = container.locator(".clear-filter, i[title*='Borrar'], i[title*='Clear'], .slicer-clear")
                if await clear_btn.count() > 0 and await clear_btn.first.is_visible():
                    print(f"[{filter_label}] Found eraser, clicking")
                    await clear_btn.first.click(force=True)
                    await page.wait_for_timeout(1000)

                # Now click the option
                print(f"[{filter_label}] Clicking option {option_text}")
                await click_option_in_frames(page, option_text)
                await page.screenshot(path=f"d:\\agente-powerbi\\log_debug_{filter_label}_selected.png")
                
                # Close dropdown
                if await box.count() > 0:
                    await box.first.click(force=True)
                else:
                    await container.click(force=True)
                await page.wait_for_timeout(1000)

                print(f"[{filter_label}] Final status: ", await box.inner_text())
                return
        except Exception as e:
            print(e)
            pass

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
        await page.goto(URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(10000)

        # Aceptar cookies
        for sel in ["button:has-text('Accept')", "button:has-text('Aceptar')", "button:has-text('OK')", "[id*='accept']"]:
            try:
                b = page.locator(sel).first
                if await b.is_visible(timeout=1000):
                    await b.click()
            except Exception:
                pass


        await click_filter_debug(page, "Mes", "Feb")
        await click_filter_debug(page, "Supervisor", "YOHN")
        await click_filter_debug(page, "Nro. Visita", "Visita 1")
        
        await page.screenshot(path="d:\\agente-powerbi\\log_debug_final.png")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
