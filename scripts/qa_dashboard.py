"""Validación del dashboard ejecutivo sobre sigap-mcp."""
import asyncio
import os

from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()
TOKEN = os.getenv('API_TOKEN', '')


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel='msedge', headless=True)
        page = await browser.new_page(viewport={'width': 1560, 'height': 1000})
        errs = []
        page.on('pageerror', lambda e: errs.append(str(e)))
        page.on('console', lambda m: errs.append(m.text) if m.type == 'error' else None)

        await page.goto('http://127.0.0.1:8100/dashboard', wait_until='networkidle', timeout=60000)
        await page.wait_for_timeout(1500)

        # 1) Panel de auth visible
        auth_visible = await page.locator('#authPanel').is_visible()
        print('1) auth visible:', auth_visible)

        # 2) Ingresar token
        await page.fill('#tokenInput', TOKEN)
        await page.click('#authPanel button')
        await page.wait_for_timeout(12000)

        # 3) Contenido cargado
        kpis = await page.locator('.kpi').count()
        canvases = await page.locator('.box canvas').count()
        filas_p = await page.locator('#tablaPartidas tbody tr').count()
        filas_d = await page.locator('#tablaDemorados tbody tr').count()
        actualizado = await page.locator('#lastUpdated').text_content()
        print(f'2) KPI cards: {kpis} | canvases: {canvases} | filas partidas: {filas_p} | filas demorados: {filas_d}')
        print('   ', actualizado.strip())

        valores = await page.eval_on_selector_all('.kpi .val', 'els => els.map(e => e.textContent.trim())')
        print('3) valores:', valores)
        mal = [v for v in valores if 'NaN' in v or 'undefined' in v]
        print('   valores inválidos:', mal if mal else 'ninguno')

        overflow = await page.evaluate('() => document.documentElement.scrollWidth > document.documentElement.clientWidth')
        print('4) overflow horizontal:', overflow)
        print('5) errores JS:', errs if errs else 'ninguno')

        await page.screenshot(path='export_dashboard.png', full_page=True)
        print('screenshot: export_dashboard.png')
        await browser.close()


asyncio.run(main())
