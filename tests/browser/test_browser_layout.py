"""Check real mini-match layout at desktop, tablet and phone sizes."""
from __future__ import annotations

import json
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from threading import Thread

from playwright.sync_api import expect, sync_playwright

import test_browser_demo as smoke


class MiniMatchLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), partial(smoke.QuietHandler, directory=str(smoke.DOCS))
        )
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}/"
        cls.addClassCleanup(cls.stop_server)

    @classmethod
    def stop_server(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def test_compact_opening_and_aligned_phenomena(self) -> None:
        directory = smoke.ARTIFACTS / "layout"
        directory.mkdir(parents=True, exist_ok=True)
        sizes = [(1363, 936), (1280, 800), (1024, 768), (768, 1024), (390, 844)]
        measurements = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for width, height in sizes:
                with self.subTest(width=width, height=height):
                    context = browser.new_context(
                        viewport={"width": width, "height": height},
                        locale="en-US", reduced_motion="reduce",
                    )
                    page = context.new_page()
                    try:
                        page.goto(self.base_url + "?lang=en&mini=1", wait_until="domcontentloaded")
                        expect(page.locator(".mini-match")).to_be_visible(timeout=smoke.WORKER_TIMEOUT)
                        expect(page.locator("#app")).to_have_attribute("aria-busy", "false")
                        page.wait_for_function("Array.from(document.images).every(img => img.complete && img.naturalWidth > 0)")
                        page.screenshot(path=str(directory / f"opening-{width}x{height}.png"), full_page=True)
                        metrics = page.evaluate("""() => {
                            const toolbar = document.querySelector('.mini-hand-heading').getBoundingClientRect();
                            const cards = [...document.querySelectorAll('.mini-phenomenon-selection .card-art')];
                            return {
                                width: innerWidth, height: innerHeight,
                                pageHeight: document.documentElement.scrollHeight,
                                overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
                                toolbarBottom: toolbar.bottom,
                                angles: cards.map(card => {
                                    const transform = getComputedStyle(card).transform;
                                    const matrix = new DOMMatrixReadOnly(transform === 'none' ? undefined : transform);
                                    return Math.atan2(matrix.b, matrix.a) * 180 / Math.PI;
                                }),
                                tops: cards.map(card => card.getBoundingClientRect().top),
                                commandHeight: document.querySelector('[data-action="mini_end_turn"]').getBoundingClientRect().height
                            };
                        }""")
                        measurements.append(metrics)
                        self.assertLessEqual(metrics["overflow"], 1)
                        self.assertEqual(len(metrics["angles"]), 3)
                        self.assertTrue(all(abs(angle) < 0.01 for angle in metrics["angles"]))
                        self.assertLess(max(metrics["tops"]) - min(metrics["tops"]), 1)
                        self.assertGreaterEqual(metrics["commandHeight"], 44)
                        if width >= 1024:
                            self.assertLessEqual(metrics["toolbarBottom"], height)
                            self.assertLessEqual(metrics["pageHeight"], 1150)
                        # The toolbar stays available while scrolling through the hand.
                        page.locator(".mini-hand-grid").scroll_into_view_if_needed()
                        expect(page.locator('[data-action="mini_end_turn"]')).to_be_in_viewport()
                        if width == 1024:
                            page.get_by_role("button", name="Accessibility", exact=True).click()
                            page.locator('[data-access-pref="textSize"][value="larger"]').check()
                            page.locator('#accessibility-dialog .dialog-close').click()
                            page.screenshot(path=str(directory / "opening-1024-larger-text.png"), full_page=True)
                            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth"), 1)
                    finally:
                        context.close()
            browser.close()
        (directory / "measurements.json").write_text(json.dumps(measurements, indent=2) + "\n")


if __name__ == "__main__":
    unittest.main()
