"""Record an end-to-end HIVEMIND demo as a .webm video using Playwright.

Prerequisites (one-time):
    C:\\Python313\\python.exe -m pip install playwright
    C:\\Python313\\python.exe -m playwright install chromium

Both the FastAPI backend (`http://127.0.0.1:8000`) and the Vite dev server
(`http://localhost:5173`) must already be running. The two AXL sidecar nodes
on ports 7001/7002 must be up if you want `run_mode=live_axl+live_0g` instead
of degraded mode.

Drives the live React dashboard (`http://localhost:5173/`) backed by the live
FastAPI/AXL/0G/Uniswap stack and captures the full flow:

    1.  Set the agent slider to N (default 200)
    2.  Replace the scenario prompt
    3.  Click EXECUTE SCENARIO and wait for the run to settle
    4.  Click the rank-1 leaderboard row to surface the AgentDetailPanel
    5.  Hold so the panel is visible in the recording
    6.  Click MINT WINNER and wait for the `★ MINTED` success card
    7.  Stop recording and report the saved .webm path

Usage:
    C:\\Python313\\python.exe docs\\scripts\\record_e2e_demo.py \\
        --url http://localhost:5173 \\
        --agents 200 \\
        --mint-timeout 300 \\
        --output docs/demo/e2e-200-agents.webm

The mint timeout is in seconds; iNFT minting on 0G Galileo is real and can take
30s-2m+ in practice, so be generous.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import time
from pathlib import Path

from playwright.async_api import (
    Locator,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)


DEFAULT_PROMPT = (
    "Block builders signal a massive MEV opportunity; gas spikes 8x; mempool "
    "floods with sandwich bots; pending swaps revert."
)


def _log(message: str) -> None:
    elapsed = time.monotonic() - _log.start  # type: ignore[attr-defined]
    safe = message.encode("ascii", errors="replace").decode("ascii")
    print(f"[{elapsed:7.2f}s] {safe}", flush=True)


_log.start = time.monotonic()  # type: ignore[attr-defined]


async def _set_range_value(page: Page, selector: str, value: int) -> None:
    """Set <input type='range'> + dispatch input/change so React sees it.

    Playwright's `fill()` does not work on range inputs, and `evaluate` with the
    React-internal value setter is the only reliable way to trigger the
    component's onChange handler.
    """
    await page.evaluate(
        """({selector, value}) => {
            const el = document.querySelector(selector);
            if (!el) throw new Error(`range not found: ${selector}`);
            const proto = Object.getPrototypeOf(el);
            const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
            setter.call(el, String(value));
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        }""",
        {"selector": selector, "value": value},
    )


async def _wait_visible(locator: Locator, timeout_ms: int, label: str) -> None:
    try:
        await locator.wait_for(state="visible", timeout=timeout_ms)
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(f"timed out waiting for {label}") from exc


async def _hold(page: Page, seconds: float, reason: str) -> None:
    _log(f"  hold {seconds:.1f}s ({reason})")
    await page.wait_for_timeout(int(seconds * 1000))


async def run_demo(args: argparse.Namespace) -> Path:
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    # Playwright records to a tmp dir at context level; we move/rename after.
    video_dir = output.parent / "_recordings_tmp"
    if video_dir.exists():
        shutil.rmtree(video_dir)
    video_dir.mkdir(parents=True)

    viewport = {"width": args.width, "height": args.height}

    async with async_playwright() as pw:
        _log("launching chromium (headed)")
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport=viewport,
            record_video_dir=str(video_dir),
            record_video_size=viewport,
        )
        page = await context.new_page()

        _log(f"navigating to {args.url}")
        await page.goto(args.url, wait_until="domcontentloaded")

        # Wait for the React shell to mount.
        await _wait_visible(
            page.locator('textarea[aria-label="Scenario text"]'),
            timeout_ms=15_000,
            label="scenario textarea (app shell)",
        )
        await _hold(page, 1.5, "let the HUD breathe")

        # 1) Set agent count.
        _log(f"setting agents -> {args.agents}")
        await _set_range_value(page, "#agent-count", args.agents)
        await _hold(page, 0.6, "show new agent count")

        # 2) Replace the prompt.
        _log("typing scenario prompt")
        textarea = page.locator('textarea[aria-label="Scenario text"]')
        await textarea.click()
        await textarea.press("Control+A")
        await textarea.press("Delete")
        # `type()` simulates real keystrokes so the recording shows it being
        # entered, not pasted in one frame.
        await textarea.type(args.prompt, delay=12)
        await _hold(page, 1.2, "let viewer read the prompt")

        # 3) Click EXECUTE SCENARIO.
        _log("clicking EXECUTE SCENARIO")
        run_btn = page.get_by_role("button", name="EXECUTE SCENARIO", exact=False)
        await run_btn.click()

        # Wait for the button to flip to "RUNNING..." (proof the click landed)
        running_btn = page.get_by_role("button", name="RUNNING", exact=False)
        try:
            await running_btn.wait_for(state="visible", timeout=8_000)
            _log("  scenario started (RUNNING...)")
        except PlaywrightTimeoutError:
            _log("  warning: did not see RUNNING... state — scenario may have completed instantly")

        # Wait until the button returns to EXECUTE SCENARIO (run finished),
        # or until the scenario settle timeout fires.
        _log(f"waiting up to {args.scenario_timeout}s for scenario to settle")
        try:
            await page.get_by_role("button", name="EXECUTE SCENARIO", exact=False).wait_for(
                state="visible", timeout=args.scenario_timeout * 1000
            )
            _log("  scenario settled")
        except PlaywrightTimeoutError:
            _log("  scenario did not settle in time; continuing anyway")

        await _hold(page, 2.0, "pause on settled HUD")

        # 4) Click the rank-1 leaderboard row to open the AgentDetailPanel.
        _log("clicking rank-1 leaderboard row")
        rank_one = page.locator(".table-row.rank-one").first
        await _wait_visible(rank_one, timeout_ms=10_000, label="rank-1 row")
        await rank_one.click()
        # Wait for the panel to slide in (the .visible class flips).
        try:
            await page.locator(".agent-detail-panel.visible").wait_for(
                state="visible", timeout=5_000
            )
            _log("  agent detail panel visible")
        except PlaywrightTimeoutError:
            _log("  warning: agent-detail-panel.visible not found; continuing")

        await _hold(page, 4.0, "let viewer read the rationale + telemetry")

        # 5) Click MINT WINNER.
        _log("scrolling mint section into view")
        mint_btn = page.get_by_role("button", name="MINT WINNER", exact=False)
        await _wait_visible(mint_btn, timeout_ms=10_000, label="MINT WINNER button")
        await mint_btn.scroll_into_view_if_needed()
        await _hold(page, 1.0, "show MINT button")
        _log("clicking MINT WINNER")
        await mint_btn.click()

        # Wait for ★ MINTED success card.
        _log(f"waiting up to {args.mint_timeout}s for ★ MINTED")
        try:
            await page.locator(".minted-badge").wait_for(
                state="visible", timeout=args.mint_timeout * 1000
            )
            _log("  ★ MINTED!")
        except PlaywrightTimeoutError:
            _log(f"  WARNING: mint did not complete within {args.mint_timeout}s; ending recording anyway")

        # Hold the success card on screen so the recording captures it.
        await _hold(page, 5.0, "show ★ MINTED card")

        _log("closing context (this finalizes the .webm)")
        # We need the page video handle BEFORE close() so we can move it.
        video = page.video
        await context.close()
        await browser.close()

        if video is None:
            raise RuntimeError("no video handle on page; recording did not start")

        recorded_path = Path(await video.path()).resolve()

    # Move/rename the .webm to the requested output path.
    if output.exists():
        output.unlink()
    shutil.move(str(recorded_path), str(output))

    # Clean up tmp dir.
    if video_dir.exists():
        try:
            shutil.rmtree(video_dir)
        except OSError:
            pass

    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:5173/")
    parser.add_argument("--agents", type=int, default=200)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument(
        "--scenario-timeout",
        type=int,
        default=180,
        help="Max seconds to wait for the scenario run to settle.",
    )
    parser.add_argument(
        "--mint-timeout",
        type=int,
        default=300,
        help="Max seconds to wait for the ★ MINTED success card.",
    )
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=1000)
    parser.add_argument("--output", default="docs/demo/e2e-200-agents.webm")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        path = asyncio.run(run_demo(args))
    except Exception as exc:
        msg = str(exc).encode("ascii", errors="replace").decode("ascii")
        print(f"FAILED: {msg}", file=sys.stderr)
        return 1
    size_mb = path.stat().st_size / (1024 * 1024)
    print(f"\nDONE — saved {size_mb:.1f} MB to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
