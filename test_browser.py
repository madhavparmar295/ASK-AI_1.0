import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        response = await page.goto("https://iitj.ac.in", wait_until="domcontentloaded", timeout=30000)
        print("STATUS:", response.status if response else None)
        print("TITLE:", await page.title())
        print("LENGTH:", len(await page.content()))
        await browser.close()

asyncio.run(main())
