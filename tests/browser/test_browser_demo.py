"""Real Chromium smoke test for the published BiM demo.

Run separately from the standard library-only unit suite because Playwright is
an optional CI dependency. No account, external server or test artwork is used.
"""
from __future__ import annotations

import subprocess
import sys
import time
import unittest
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
PORT = 18780
BASE_URL = f"http://127.0.0.1:{PORT}/"


class BrowserDemoSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = subprocess.Popen(
            [
                sys.executable, "-m", "http.server", str(PORT),
                "--bind", "127.0.0.1", "--directory", str(DOCS),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(100):
                if cls.server.poll() is not None:
                    raise RuntimeError("Local demo server exited unexpectedly")
                try:
                    with urlopen(BASE_URL, timeout=1) as response:
                        if response.status == 200:
                            return
                except (OSError, URLError):
                    time.sleep(0.1)
            raise RuntimeError("Local demo server did not start")
        except BaseException:
            cls.server.terminate()
            cls.server.wait(timeout=5)
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait(timeout=5)

    def test_start_play_and_reload_mini_match(self) -> None:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(locale="en-US", reduced_motion="reduce")
                page.set_default_timeout(150_000)
                page.goto(BASE_URL + "?lang=en&mini=1", wait_until="domcontentloaded")

                # This is the real Pyodide/wasm browser path, not a mocked engine.
                page.locator(".mini-match").wait_for(state="visible")
                before = page.evaluate("""async () => {
                    const response = await fetch('/api/state');
                    if (!response.ok) throw new Error('Engine state request failed');
                    return response.json();
                }""")
                self.assertEqual(before["stage"], "mini")
                self.assertEqual(before["match"]["phase"], "turn")
                self.assertEqual(before["match"]["actor"], "p1")
                self.assertGreater(page.locator(".mini-hand-card").count(), 0)

                # A real click must reach the Python engine and update the UI.
                page.locator('[data-action="mini_end_turn"]').click()
                page.wait_for_function(
                    """async (previousRevision) => {
                        const response = await fetch('/api/state');
                        return response.ok && (await response.json()).revision > previousRevision;
                    }""",
                    arg=before["revision"],
                )
                after = page.evaluate("async () => (await (await fetch('/api/state')).json())")
                self.assertGreater(after["revision"], before["revision"])
                self.assertTrue(page.locator("#error").is_hidden())

                # Session command replay must restore progress after a reload.
                page.reload(wait_until="domcontentloaded")
                page.locator(".mini-match").wait_for(state="visible")
                restored = page.evaluate("async () => (await (await fetch('/api/state')).json())")
                self.assertEqual(restored["revision"], after["revision"])
                self.assertEqual(restored["stage"], "mini")
                self.assertTrue(page.locator("#error").is_hidden())
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
