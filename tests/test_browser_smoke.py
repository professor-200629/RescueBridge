"""Reproducible real-browser smoke test (Microsoft Edge via Playwright; fixture OS, no Windows changes).

Two browser contexts: the laptop host console (127.0.0.1) and a phone-sized "device" (localhost, separate
cookie jar). Drives the actual UI: pairing, the combined interview utterance, the focused mouse question, three
exact approvals, the test tone, the person's confirmations, and Stop.
"""

from __future__ import annotations

import pytest

from rescuebridge.host.fixture_ops import make_fixture
from tests.harness import running_backend

pytestmark = [pytest.mark.anyio, pytest.mark.browser]


async def test_browser_combined_recovery_flow(tmp_path):
    pw = pytest.importorskip("playwright.async_api")
    ops = make_fixture("interview")
    async with running_backend(tmp_path, ops) as be, pw.async_playwright() as p:
        try:
            browser = await p.chromium.launch(channel="msedge", headless=True)
        except Exception as exc:  # noqa: BLE001 - environment without Edge
            pytest.skip(f"Microsoft Edge not available for Playwright: {exc}")
        host = await (await browser.new_context()).new_page()
        phone_ctx = await browser.new_context(viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True)
        phone = await phone_ctx.new_page()
        phone.set_default_timeout(15_000)
        host.set_default_timeout(15_000)

        # --- pairing (host console bootstrap code travels only in the URL fragment)
        await host.goto(f"{be.bff_url}/host#b={be.auth.create_host_bootstrap()}")
        assert "#b=" not in host.url
        await host.get_by_role("button", name="Create pairing code").click()
        code = (await host.locator(".pair-code .code").inner_text()).strip()
        phone_base = be.bff_url.replace("127.0.0.1", "localhost")
        await phone.goto(f"{phone_base}/#pair={code}")
        await phone.get_by_role("button", name="Request pairing").click()
        await host.get_by_role("button", name="Accept this device").click()
        await phone.get_by_role("button", name="Tap to talk").wait_for()
        assert "Fixture Simulation" in await phone.locator("header").inner_text()

        # --- combined report
        await phone.locator("#say").fill("My clicks are wrong, I can't hear anything, and my notes disappeared")
        await phone.get_by_role("button", name="Send").click()

        def card(title: str):  # noqa: ANN202
            return phone.locator("article.issue", has=phone.get_by_role("heading", name=title, exact=True))

        await card("Mouse buttons").get_by_text("Question for you").wait_for()
        await card("Mouse buttons").get_by_role("button", name="Left button for normal clicks").click()

        # --- sound: exact approval, observed result, approved tone, person confirms
        await card("Sound").get_by_role("button", name="Approve and apply").click()
        await card("Sound").get_by_text("Change made and the new state was observed").wait_for()
        await card("Sound").get_by_role("button", name="Approve and play").click()
        await card("Sound").get_by_text("only your answer shows whether it was audible").wait_for()
        await card("Sound").get_by_role("button", name="Yes, it works").click()
        await card("Sound").get_by_text("Resolved — you confirmed").wait_for()

        # --- window: document fingerprint unchanged
        await card("Missing window").get_by_role("button", name="Approve and apply").click()
        await card("Missing window").get_by_text("WorkPad's unsaved text: unchanged").wait_for()
        await card("Missing window").get_by_role("button", name="Yes, it works").click()

        # --- mouse: approval, then the simulated person clicks the click-test target
        await card("Mouse buttons").get_by_role("button", name="Approve and apply").click()
        await card("Mouse buttons").get_by_text("Change made and the new state was observed").wait_for()
        assert ops.state.click_tests, "click-test target was not requested"
        for test_id in ops.state.click_tests:
            ops.state.click_tests[test_id] = {"status": "primary_click_received", "primary_clicks": 1, "secondary_clicks": 0}
        await card("Mouse buttons").get_by_role("button", name="Yes, it works").click()
        await phone.get_by_text("All 3 reported issue(s) confirmed resolved by the person.").wait_for()

        # --- MCP App: the server-declared card renders in its sandboxed frame after the ui/initialize handshake
        await phone.locator("details.appcard summary").click()
        card_frame = phone.frame_locator("iframe.app-frame")
        await card_frame.get_by_text("3/3 confirmed").wait_for()
        await card_frame.get_by_text("Fixture Simulation").wait_for()
        await card_frame.get_by_role("button", name="Refresh").click()  # view -> host tools/call -> MCP
        await card_frame.get_by_text("All 3 reported issue(s) confirmed resolved by the person.").wait_for()
        assert await phone.locator("iframe.app-frame").get_attribute("sandbox") == "allow-scripts"

        # --- Stop is direct and acknowledged by the helper fence
        await phone.get_by_role("button", name="STOP all changes").click()
        await phone.get_by_text("Stopped — the laptop helper confirmed").first.wait_for()

        mutations = [c[0] for c in ops.calls if c[0] in {"set_mouse_swap", "set_audio", "play_tone", "move_window",
                                                         "show_click_test"}]
        assert sorted(mutations) == sorted(["set_audio", "play_tone", "move_window", "set_mouse_swap", "show_click_test"])
        await browser.close()
