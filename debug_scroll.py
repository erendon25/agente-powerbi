import asyncio
import re
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

async def click_filter(page, filter_label, option_text):
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
                
                # Clear existing
                clear_btn = container.locator(".clear-filter, i[title*='Borrar'], i[title*='Clear'], .slicer-clear")
                if await clear_btn.count() > 0 and await clear_btn.first.is_visible():
                    try:
                        await clear_btn.first.click(force=True)
                        await page.wait_for_timeout(1000)
                    except: pass
                
                await click_option_in_frames(page, option_text)
                if await box.count() > 0:
                    await box.first.click(force=True)
                else:
                    await container.click(force=True)
                await page.wait_for_timeout(1500)
                return
        except Exception:
            pass

async def text_exists(page, txt):
    # Check if text exists anywhere in the frames
    for f in page.frames:
        loc = f.locator(f"text='{txt}'")
        if await loc.count() > 0:
            for i in range(await loc.count()):
                if await loc.nth(i).is_visible(): return True
    return False

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"], headless=True)
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()
        await page.goto(URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(10000)
        
        await click_filter(page, "Mes", "Feb")
        await click_filter(page, "Supervisor", "YOHN")
        await click_filter(page, "Nro. Visita", "Visita 1")
        
        # Verify if PORONGOCHE is visible
        stores_to_check = ["PORONGOCHE", "MALL PORONGOCHE"]
        for st in stores_to_check:
            found = await text_exists(page, st)
            print(f"[{st}] Before scrolling: Visible={found}")
        
        # Power BI virtual scrolling can sometimes be triggered by mouse wheel in the container
        for frame in page.frames:
            # Let's try to locate the scrolling elements
            scrollables = frame.locator(".scrollbar-inner, .scroll-wrapper, .visual-tableEx, .rowHeaders")
            count = await scrollables.count()
            if count > 0:
                print(f"Found {count} scrollable containers. Simulating scrolls...")
                for i in range(count):
                    try:
                        await scrollables.nth(i).hover()
                        # Wheel down heavily
                        await page.mouse.wheel(0, 10000)
                        await page.wait_for_timeout(1000)
                    except: pass

        for st in stores_to_check:
            found = await text_exists(page, st)
            print(f"[{st}] After scrolling: Visible={found}")

        await page.screenshot(path="d:\\agente-powerbi\\log_debug_scroll.png")
        await browser.close()
if __name__ == "__main__": asyncio.run(main())
