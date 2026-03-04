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

async def extract_full_report() -> dict:
    now = datetime.utcnow()
    mes_actual = MESES_ES[now.month]
    print(f"Mes actual: {mes_actual}")
    consent_selectors = [
        "button:has-text('Accept')", "button:has-text('Aceptar')",
        "button:has-text('I accept')", "button:has-text('Continue')",
        "button:has-text('OK')", "[id*='accept']", "[class*='consent']",
    ]

    result = {
        "record_update": None,
        "mes": mes_actual,
        "tiendas": {t: {} for t in TIENDAS}
    }

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

        await page.wait_for_timeout(12000)
        
        visitas = ["Visita 1", "Visita 2"]

        for tienda in TIENDAS:
            for visita in visitas:
                print(f"Scrapeando {tienda} - {visita}")
                try:
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

                    print("Applying filters...")
                    await click_filter_option(page, "Mes", mes_actual, deselect_all_first=True)
                    await page.wait_for_timeout(1500)
                    await click_filter_option(page, "Supervisor", "YOHN", deselect_all_first=True)
                    await page.wait_for_timeout(1500)
                    await click_filter_option(page, "Nro. Visita", visita, deselect_all_first=True)
                    await page.wait_for_timeout(1500)

                    # Filtrar por tienda haciendo clic en "Top Places"
                    score = "Sin visita"
                    try:
                        print(f"Clicking on {tienda} label...")
                        tienda_label = page.locator(f"text={tienda}").last
                        if await tienda_label.is_visible(timeout=3000):
                            await tienda_label.click()
                            await page.wait_for_timeout(2500)
                            
                            # GENERATE LOGS HERE!
                            safe_name = f"{tienda}_{visita}".replace(" ", "_").lower()
                            await page.screenshot(path=f"d:\\agente-powerbi\\log_screen_{safe_name}.png")
                            text = await get_page_text(page)
                            with open(f"d:\\agente-powerbi\\log_text_{safe_name}.txt", "w", encoding="utf-8") as f:
                                f.write(text)
                            
                            m = re.search(r"(\d{1,3})\s*%\s*\n*.*Suce?ss\s+Rate", text, re.IGNORECASE)
                            if m:
                                score = m.group(1) + "%"
                            else:
                                m2 = re.search(r"Suce?ss\s+Rate\s*\n?\s*(\d{1,3})\s*%", text, re.IGNORECASE)
                                if m2:
                                    score = m2.group(1) + "%"
                                else:
                                    rg = re.search(r"Resumen General[^%]{0,150}?(\d{1,3})\s*%", text, re.IGNORECASE)
                                    score = rg.group(1) + "%" if rg else "Sin visita"
                            print(f"{tienda} - {visita} result: {score}")
                        else:
                            print(f"Label {tienda} not visible.")
                    except Exception as e:
                        print(f"Error accessing label {tienda}: {e}")

                    result["tiendas"][tienda][visita] = score
                except Exception as e:
                    result["tiendas"][tienda][visita] = "Error"
                    print(f"Error general {tienda} {visita}: {e}")

        await context.close()
        await browser.close()
    return result

if __name__ == "__main__":
    report = asyncio.run(extract_full_report())
    print("FINISHED REPORT:")
    print(report)
