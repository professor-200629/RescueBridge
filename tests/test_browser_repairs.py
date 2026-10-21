"""Real-browser regression tests (Microsoft Edge via Playwright, fixture OS, no Windows changes) for the review
findings: persistent Send errors with Retry, first-reply speech without replays, stale snapshots after Stop and
overlapping polls, pairing-code validation, duplicate approvals and timeout reconciliation, the simulated preview's
isolation, keyboard reachability and phone-width layout.

Speech synthesis is replaced by a recording substitute (no audio). Network faults are injected with Playwright
routing; the backend is the real in-process BFF + MCP server with the fixture adapter.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

import pytest

from rescuebridge.host.fixture_ops import make_fixture
from tests.harness import pair_device, running_backend

pytestmark = [pytest.mark.anyio, pytest.mark.browser]

FAKE_SPEECH = """
window.__spoken = [];
const fakeSynth = { speaking: false, pending: false, paused: false,
  speak(u) { window.__spoken.push(u.text); setTimeout(() => { u.onstart && u.onstart(); u.onend && u.onend(); }, 5); },
  cancel() {}, pause() {}, resume() {}, getVoices() { return []; }, addEventListener() {}, removeEventListener() {} };
Object.defineProperty(window, "speechSynthesis", { configurable: true, get: () => fakeSynth });
if (!window.SpeechSynthesisUtterance) { window.SpeechSynthesisUtterance = function (t) { this.text = t; }; }
"""


@asynccontextmanager
async def edge():  # noqa: ANN201
    pw = pytest.importorskip("playwright.async_api")
    async with pw.async_playwright() as p:
        try:
            browser = await p.chromium.launch(channel="msedge", headless=True)
        except Exception as exc:  # noqa: BLE001 - environment without Edge
            pytest.skip(f"Microsoft Edge not available for Playwright: {exc}")
        try:
            yield browser
        finally:
            await browser.close()


async def phone_page(browser: Any, be: Any, *, paired: bool = True, speech: bool = True) -> tuple[Any, Any]:
    """A phone-sized page; when paired, it reuses a session created through the real pairing flow."""
    ctx = await browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    if speech:
        await ctx.add_init_script(FAKE_SPEECH)
    http = None
    if paired:
        http, _ = await pair_device(be)
        await ctx.add_cookies([{"name": "rb_session", "value": http.cookies.get("rb_session"), "url": be.bff_url}])
    page = await ctx.new_page()
    page.set_default_timeout(15_000)
    return page, http


def api_requests(page: Any, fragment: str) -> list[str]:
    seen: list[str] = []
    page.on("request", lambda r: seen.append(f"{r.method} {r.url}") if fragment in r.url else None)
    return seen


async def test_send_error_stays_visible_through_polling_and_retry_keeps_the_text(tmp_path):
    async with running_backend(tmp_path, make_fixture("muted")) as be, edge() as browser:
        page, http = await phone_page(browser, be)
        await page.goto(be.bff_url)
        await page.get_by_role("button", name="Tap to talk").wait_for()
        fail = {"on": True}

        async def utterance(route):  # noqa: ANN001, ANN202
            if fail["on"]:
                await route.fulfill(status=500, content_type="application/json",
                                    body='{"error":{"code":"INTERNAL","message":"Server error"}}')
            else:
                await route.continue_()

        await page.route("**/api/utterance", utterance)
        await page.locator("#say").fill("I can't hear anything")
        await page.get_by_role("button", name="Send", exact=True).click()
        alert = page.get_by_role("alert")
        await alert.locator(".err-title").get_by_text("server error", exact=False).wait_for()
        await page.wait_for_timeout(4500)  # two polling cycles and re-renders
        assert await alert.is_visible(), "the error was overwritten by a re-render"
        assert await page.locator("#say").input_value() == "I can't hear anything"  # transcript preserved
        fail["on"] = False
        await alert.get_by_role("button", name="Retry").click()
        await page.locator("article.issue").get_by_text("Waiting for your approval").wait_for()
        assert await page.get_by_role("alert").count() == 0
        assert await page.locator("#say").input_value() == ""
        await http.aclose()


async def test_first_reply_is_spoken_once_and_history_is_not_replayed(tmp_path):
    async with running_backend(tmp_path, make_fixture("muted")) as be, edge() as browser:
        page, http = await phone_page(browser, be)
        await page.goto(be.bff_url)
        await page.get_by_role("button", name="Tap to talk").wait_for()
        await page.wait_for_timeout(2500)  # initial history (empty) loaded by polling
        assert await page.evaluate("window.__spoken.length") == 0
        await page.locator("#say").fill("I can't hear anything")
        await page.get_by_role("button", name="Send", exact=True).click()
        await page.locator("article.issue").get_by_text("Waiting for your approval").wait_for()
        await page.wait_for_timeout(4500)  # Send response and polling overlap with the same reply
        spoken = await page.evaluate("window.__spoken")
        assert len(spoken) == 1 and "speaker is muted" in spoken[0], spoken
        await page.reload()  # history must not be replayed
        await page.get_by_role("button", name="Tap to talk").wait_for()
        await page.wait_for_timeout(3000)
        assert await page.evaluate("window.__spoken.length") == 0
        await page.locator("#speak").uncheck()  # toggle off: a new reply is captioned but not spoken
        await page.locator("article.issue button.approve").first.click()
        await page.get_by_text("Done, and observed").first.wait_for()
        await page.wait_for_timeout(2500)
        assert await page.evaluate("window.__spoken.length") == 0
        assert "Done, and observed" in await page.locator(".caption").inner_text()
        await http.aclose()


async def test_old_active_snapshot_after_confirmed_stop_is_ignored_and_polls_do_not_overlap(tmp_path):
    async with running_backend(tmp_path, make_fixture("muted")) as be, edge() as browser:
        page, http = await phone_page(browser, be, speech=False)
        await http.post("/api/utterance", json={"text": "I can't hear anything"})  # ACTIVE mission with a proposal
        await page.goto(be.bff_url)
        await page.locator("article.issue button.approve").first.wait_for()
        held: list[Any] = []
        release = asyncio.Event()
        state_requests = api_requests(page, "/api/state")

        async def hold_one(route):  # noqa: ANN001, ANN202
            if held:
                await route.continue_()
                return
            response = await route.fetch()  # the server answers now: mission ACTIVE
            held.append(response)
            await release.wait()
            await route.fulfill(response=response)  # ... but the browser gets it only after Stop

        await page.route("**/api/state", hold_one)
        for _ in range(50):
            if held:
                break
            await page.wait_for_timeout(100)
        assert held, "no poll was intercepted"
        before = len(state_requests)
        await page.wait_for_timeout(4500)
        assert len(state_requests) == before, "a new poll started while the previous one was still pending"
        await page.get_by_role("button", name="STOP all changes").click()
        await page.get_by_text("Stopped — the laptop helper confirmed").first.wait_for()
        await page.locator("#continue-btn").wait_for()
        release.set()
        await page.wait_for_timeout(600)
        assert await page.locator("#continue-btn").count() == 1, "an old ACTIVE snapshot replaced the stopped state"
        assert await page.locator("article.issue button.approve").count() == 0
        await http.aclose()


async def test_pairing_code_is_validated_before_any_request(tmp_path):
    async with running_backend(tmp_path) as be, edge() as browser:
        page, _ = await phone_page(browser, be, paired=False, speech=False)
        pair_calls = api_requests(page, "/api/pair/request")
        await page.goto(be.bff_url)
        await page.get_by_role("button", name="Request pairing").click()
        await page.locator("#code-error").get_by_text("8 digits", exact=False).wait_for()
        assert pair_calls == [], "an empty code reached the backend"
        assert await page.evaluate("document.activeElement.id") == "code"  # focus returns to the field
        await page.locator("#code").fill("12ab")
        await page.get_by_role("button", name="Request pairing").click()
        await page.wait_for_timeout(300)
        assert pair_calls == []
        assert await page.locator("#code").get_attribute("aria-invalid") == "true"
        await page.locator("#code").fill("1234 5678")  # valid format, but no code was created on the laptop
        await page.get_by_role("button", name="Request pairing").click()
        await page.get_by_text("No pairing code is active", exact=False).wait_for()
        assert len(pair_calls) == 1


async def test_double_tapped_approval_sends_one_request_and_timeout_is_reconciled(tmp_path):
    async with running_backend(tmp_path, make_fixture("muted")) as be, edge() as browser:
        page, http = await phone_page(browser, be, speech=False)
        await http.post("/api/utterance", json={"text": "I can't hear anything"})
        await page.goto(be.bff_url)
        approve = page.locator("article.issue button.approve").first
        await approve.wait_for()
        calls = api_requests(page, "/approve")

        async def applied_but_lost(route):  # noqa: ANN001, ANN202
            await route.fetch()  # the laptop applies the change ...
            await route.abort("timedout")  # ... but the answer never reaches the phone

        await page.route("**/approve", applied_but_lost)
        await approve.dblclick()
        alert = page.get_by_role("alert")
        await alert.wait_for()
        assert "may or may not" in (await alert.inner_text())
        await page.get_by_text("Change made and the new state was observed").first.wait_for()  # reconciled
        await page.wait_for_timeout(1000)
        assert len(calls) == 1, calls
        assert be.ops.state.endpoints[0].muted is False
        assert len([c for c in be.ops.calls if c[0] == "set_audio"]) == 1
        await http.aclose()


async def test_lost_connection_after_delivery_does_not_resend_the_message(tmp_path):
    async with running_backend(tmp_path, make_fixture("muted")) as be, edge() as browser:
        page, http = await phone_page(browser, be, speech=False)
        await page.goto(be.bff_url)
        await page.get_by_role("button", name="Tap to talk").wait_for()
        calls = api_requests(page, "/api/utterance")

        async def delivered_but_lost(route):  # noqa: ANN001, ANN202
            await route.fetch()  # the laptop receives and handles the message ...
            await route.abort("connectionreset")  # ... but the phone never sees the answer

        await page.route("**/api/utterance", delivered_but_lost)
        await page.locator("#say").fill("I can't hear anything")
        await page.get_by_role("button", name="Send", exact=True).click()
        alert = page.get_by_role("alert")
        await alert.get_by_text("did reach the laptop", exact=False).wait_for()
        assert await alert.get_by_role("button", name="Retry").count() == 0  # nothing to resend
        await page.locator("article.issue").get_by_text("Waiting for your approval").wait_for()
        assert len(calls) == 1
        users = be.ctx.store.all("SELECT text FROM messages WHERE role = 'user'")
        assert [u["text"] for u in users] == ["I can't hear anything"]
        await http.aclose()


async def test_simulated_preview_is_labelled_complete_and_never_contacts_the_laptop(tmp_path):
    async with running_backend(tmp_path) as be, edge() as browser:
        page, _ = await phone_page(browser, be, paired=False)
        await page.goto(be.bff_url)
        await page.get_by_role("button", name="Try a simulated recovery").click()
        await page.get_by_text("Simulated preview", exact=False).first.wait_for()
        api_calls = api_requests(page, "/api/")
        mcp_calls = api_requests(page, "/mcp")
        assert "nothing on any laptop is read or changed" in (await page.locator(".preview-banner").inner_text()).lower()
        await page.get_by_role("button", name="My clicks are wrong").click()
        await page.get_by_role("button", name="Send", exact=True).click()
        await page.get_by_role("alert").get_by_text("one recorded conversation", exact=False).wait_for()
        await page.get_by_role("button", name="I can't hear anything").click()
        await page.get_by_role("button", name="Send", exact=True).click()
        card = page.locator("article.issue")
        await card.get_by_role("button", name="Approve and apply").click()
        await card.get_by_text("Change made and the new state was observed").wait_for()
        await card.get_by_role("button", name="Approve and play").click()
        await card.get_by_role("button", name="Yes, it works").click()
        await card.get_by_text("Resolved — you confirmed").wait_for()
        assert "Fixture Simulation" in await card.inner_text()  # the recorded evidence keeps its label
        await page.get_by_role("button", name="STOP all changes").click()
        await page.get_by_text("Nothing is running here", exact=False).wait_for()
        assert await page.locator("details.appcard").count() == 0 and await page.locator("details.diag").count() == 0
        assert api_calls == [] and mcp_calls == [], (api_calls, mcp_calls)
        assert await page.evaluate("window.__spoken.length") >= 1  # replies are spoken in the preview too


async def test_keyboard_reaches_every_control_and_nothing_overflows_a_phone_screen(tmp_path):
    async with running_backend(tmp_path, make_fixture("muted")) as be, edge() as browser:
        async def check(page, must_reach: list[str]) -> None:  # noqa: ANN001
            assert await page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), \
                "horizontal overflow at phone width"
            assert await page.evaluate("[...document.querySelectorAll('[tabindex]')].every(e => e.tabIndex <= 0)")
            reached: list[str] = []
            await page.evaluate("document.activeElement && document.activeElement.blur()")
            for _ in range(60):
                await page.keyboard.press("Tab")
                reached.append(await page.evaluate(
                    "(() => { const e = document.activeElement; return (e.id || '') + '|' + (e.textContent || e.getAttribute('aria-label') || '').trim().slice(0, 40); })()"))
            for want in must_reach:
                assert any(want in r for r in reached), (want, reached)

        page, _ = await phone_page(browser, be, paired=False, speech=False)
        await page.goto(be.bff_url)
        await page.locator("#code").wait_for()
        await check(page, ["code|", "Request pairing", "Try a simulated recovery"])
        page2, http = await phone_page(browser, be, speech=False)
        await http.post("/api/utterance", json={"text": "I can't hear anything"})
        await page2.goto(be.bff_url)
        await page2.locator("article.issue button.approve").first.wait_for()
        await check(page2, ["Tap to talk", "say|", "Send", "Approve and apply", "Decline", "STOP all changes"])
        await page2.keyboard.press("Shift+Tab")
        assert await page2.evaluate("getComputedStyle(document.activeElement).outlineStyle") != "none"  # visible focus
        await http.aclose()


async def test_host_console_without_a_valid_link_explains_the_launcher(tmp_path):
    async with running_backend(tmp_path) as be, edge() as browser:
        page = await (await browser.new_context()).new_page()
        await page.goto(f"{be.bff_url}/host")
        await page.get_by_text("host-console.ps1", exact=False).first.wait_for()
        link = be.auth.create_host_bootstrap()
        await page.goto(f"{be.bff_url}/host#b={link}")
        await page.get_by_role("button", name="Create pairing code").wait_for()  # a valid link opens the console
        page2 = await (await browser.new_context()).new_page()
        await page2.goto(f"{be.bff_url}/host#b={link}")
        await page2.get_by_role("alert").get_by_text("already used", exact=False).wait_for()
