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

async def deselect_all_in_frames(page) -> bool:
    for text in ["Seleccionar todo", "Select all"]:
        if await click_option_in_frames(page, text, wait_ms=600):
            return True
    return False

async def click_filter_option(page, filter_label, option_text, deselect_all_first=False):
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
                    except: pass

                if deselect_all_first:
                    try:
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
                await page.wait_for_timeout(1500)
                return clicked
        except Exception:
            pass
    return False

async def page_text(page):
    txt = ""
    for f in page.frames:
        try:
            txt += await f.locator("body").inner_text() + "\n"
        except: pass
    return txt

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"], headless=True)
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()
        await page.goto(URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(10000)

        # Filters from check_and_notify
        print("Filtering Mes=Feb")
        await click_filter_option(page, "Mes", "Feb", deselect_all_first=True)
        
        print("Filtering Supervisor=YOHN")
        await click_filter_option(page, "Supervisor", "YOHN", deselect_all_first=True)
        
        print("Filtering Visita 1")
        await click_filter_option(page, "Nro. Visita", "Visita 1", deselect_all_first=True)

        tienda = "PORONGOCHE"
        print(f"Looking for Tienda = {tienda}")
        
        # Capture screenshot for debug
        await page.screenshot(path="d:\\agente-powerbi\\log_debug_before_click.png")

        tienda_label = page.locator(f"text={tienda}").last
        if await tienda_label.is_visible(timeout=3000):
            print(f"Label '{tienda}' IS VISIBLE! Clicking...")
            await tienda_label.click(force=True)
            await page.wait_for_timeout(2500)
            
            await page.screenshot(path="d:\\agente-powerbi\\log_debug_after_click.png")
            txt = await page_text(page)
            print("Extracted page text after clicking:")
            print(txt[:500]) # just show a bit
        else:
            print(f"Label '{tienda}' IS NOT VISIBLE!")
            
            # Let's see what IS visible
            txt = await page_text(page)
            with open("d:\\agente-powerbi\\log_debug_fail.txt", "w", encoding="utf-8") as f:
                f.write(txt)
            print("Wrote log_debug_fail.txt to check what is shown!")


        await browser.close()
if __name__ == "__main__": asyncio.run(main())
