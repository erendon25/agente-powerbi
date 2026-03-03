import asyncio
import os
import re
from datetime import datetime
from playwright.async_api import async_playwright

URL = "https://app.powerbi.com/view?r=eyJrIjoiZWQ1YWNiYjctNWNiNC00MTNlLThjOGEtNjE1NDc2NTI4NWU2IiwidCI6ImE4MzE3NzZjLWM0ZTUtNDNhMC04ZmZhLTFkNjIxZWNlZDAzNiIsImMiOjl9"
TIENDAS = ["PORONGOCHE", "MALL PORONGOCHE"]

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

async def main():
    now = datetime.utcnow()
    mes_actual = MESES_ES[now.month]
    consent_selectors = [
        "button:has-text('Accept')", "button:has-text('Aceptar')",
        "button:has-text('I accept')", "button:has-text('Continue')",
        "button:has-text('OK')", "[id*='accept']", "[class*='consent']",
    ]

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
        
        visitas = ["Visita 1", "Visita 2"]
        tienda = "PORONGOCHE"
        for visita in visitas:
            print(f"Buscando {tienda} - {visita}")
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

            try:
                tienda_label = page.locator(f"text={tienda}").last
                if await tienda_label.is_visible(timeout=3000):
                    await tienda_label.click()
                    await page.wait_for_timeout(2000)
            except Exception:
                pass

            text = await get_page_text(page)
            with open(f"d:\\agente-powerbi\\debug_{visita.replace(' ', '')}.txt", "w", encoding="utf-8") as f:
                f.write(text)
            
            await page.screenshot(path=f"d:\\agente-powerbi\\debug_{visita.replace(' ', '')}.png")
            print(f"Dumped para {visita}")

        await context.close()
        await browser.close()

try:
    asyncio.run(main())
except Exception as e:
    with open("d:\\agente-powerbi\\debug_error.txt", "w", encoding="utf-8") as f:
        import traceback
        f.write(traceback.format_exc())
