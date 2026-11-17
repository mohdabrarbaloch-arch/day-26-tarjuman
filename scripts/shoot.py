"""Capture real screenshots of the running app.

Run with the server already listening on 127.0.0.1:8000.
"""

from __future__ import annotations

import asyncio
import pathlib

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8000"
OUT = pathlib.Path("docs/screenshots")
OUT.mkdir(parents=True, exist_ok=True)


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])

        # ---- desktop ----
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        await page.goto(BASE, wait_until="networkidle")
        await page.wait_for_timeout(900)
        await page.screenshot(path=str(OUT / "01-translate.png"))
        print("01-translate.png")

        # Fill and translate a real sentence, then capture the verdict panel.
        await page.fill("#sourceText", "Please send the invoice by Friday.")
        await page.select_option("#targetLang", "ur")
        await page.click("#translateBtn")
        await page.wait_for_selector("#verdictPanel:not([hidden])", timeout=45000)
        await page.wait_for_timeout(1200)
        # Scroll so the whole verdict panel is in frame, not just its top.
        await page.evaluate(
            "() => document.getElementById('verdictPanel').scrollIntoView({block: 'center'})"
        )
        await page.wait_for_timeout(600)
        await page.screenshot(path=str(OUT / "02-verdict.png"))
        print("02-verdict.png")

        # ---- conversation (needs an account) ----
        email = "shots@example.com"
        pw = "screenshot-pass-123"
        await page.evaluate(
            """async ([email, pw]) => {
                await fetch('/api/auth/register', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({email, password: pw})
                });
                const r = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({email, password: pw})
                });
                const d = await r.json();
                localStorage.setItem('tarjuman_token', d.access_token);
            }""",
            [email, pw],
        )
        await page.reload(wait_until="networkidle")
        await page.wait_for_timeout(700)

        await page.click('[data-view="conversation"]')
        await page.wait_for_timeout(500)
        await page.click("#startConvBtn")
        await page.wait_for_timeout(2500)
        await page.fill("#convInput", "Where does it hurt?")
        await page.click("#sendTurnBtn")
        await page.wait_for_timeout(4000)
        await page.screenshot(path=str(OUT / "03-conversation.png"))
        print("03-conversation.png")

        # ---- history ----
        # Save a couple of translations while signed in, so the view has real
        # rows instead of an empty state.
        await page.evaluate(
            """async () => {
                const t = localStorage.getItem('tarjuman_token');
                const samples = [
                    ['Please send the invoice by Friday.', 'en', 'ur'],
                    ['The meeting has been moved to Monday morning.', 'en', 'ur'],
                    ['Aaj mausam bohat acha hai', 'ur', 'en']
                ];
                for (const [text, s, tgt] of samples) {
                    await fetch('/api/translate', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': 'Bearer ' + t
                        },
                        body: JSON.stringify({text, source_lang: s, target_lang: tgt, save: true})
                    });
                }
            }"""
        )
        await page.click('[data-view="history"]')
        await page.wait_for_timeout(2500)
        await page.screenshot(path=str(OUT / "04-history.png"))
        print("04-history.png")

        # ---- mobile ----
        m = await browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        await m.goto(BASE, wait_until="networkidle")
        await m.wait_for_timeout(900)
        await m.screenshot(path=str(OUT / "05-mobile.png"))
        print("05-mobile.png")

        # Measure horizontal overflow — a real check, not an assumption.
        overflow = await m.evaluate(
            "() => ({scroll: document.documentElement.scrollWidth,"
            " client: document.documentElement.clientWidth})"
        )
        print(f"mobile overflow: scrollWidth={overflow['scroll']} clientWidth={overflow['client']}")

        await browser.close()


asyncio.run(main())
