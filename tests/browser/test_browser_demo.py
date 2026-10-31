"""Exercise the published UI and real Pyodide worker, without API mocks.

Run separately: python -m unittest discover -s tests/browser -v
Requires playwright==1.64.1 and its Chromium installation. Failure evidence is
written to test-results/browser/ for the CI artifact upload.
"""
from __future__ import annotations

import json
import time
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
ARTIFACTS = ROOT / "test-results" / "browser"
STORAGE_KEY = "bim-private-browser-preview-v1"
# The production bridge allows 150 seconds for a cold worker request. Ordinary
# controls have a shorter deadline; startup/replay get an explicit larger one.
WORKER_TIMEOUT = 180_000


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        pass


class BrowserDemoSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Bind before serving, using an OS-assigned port: no collision, startup
        # sleeps or risk of accidentally testing an unrelated localhost server.
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), partial(QuietHandler, directory=str(DOCS))
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

    def read_state(self, page) -> dict:
        # /api/state is intercepted by browser-bridge.js. Playwright's request
        # client would bypass that bridge and only receive an HTTP 404.
        return page.evaluate("""async () => {
            const response = await fetch('/api/state');
            const state = await response.json();
            if (!response.ok) throw new Error(JSON.stringify(state));
            return state;
        }""")

    def assert_rendered(self, page, state) -> None:
        expect(page.locator('.mini-match')).to_be_visible(timeout=WORKER_TIMEOUT)
        expect(page.locator('#app')).to_have_attribute(
            'aria-busy', 'false', timeout=WORKER_TIMEOUT
        )
        expect(page.locator('#error')).to_be_hidden()
        expect(page.locator('.mini-hand-card')).to_have_count(len(state['match']['hand']))
        self.assertEqual(
            page.locator('[data-mini-select]').evaluate_all(
                '(nodes) => nodes.map(node => node.dataset.miniSelect)'
            ),
            [card['id'] for card in state['match']['hand']],
        )
        own = next(player for player in state['players'] if player['id'] == 'p1')
        expect(page.locator('.mini-flock strong')).to_have_text(str(own['believers']))

    def click_command(self, page, selector, before) -> dict:
        page.locator(selector).click()
        # Revision alone can advance before act() has rendered its response.
        # Wait for UI completion before checking state or reloading the page.
        expect(page.locator('#app')).to_have_attribute(
            'aria-busy', 'false', timeout=WORKER_TIMEOUT
        )
        expect(page.locator('#error')).to_be_hidden()
        after = self.read_state(page)
        self.assertEqual(after['revision'], before['revision'] + 1)
        self.assert_rendered(page, after)
        return after

    def assert_reloaded(self, page, expected) -> None:
        history = page.evaluate('(key) => sessionStorage.getItem(key)', STORAGE_KEY)
        commands = json.loads(history)
        self.assertEqual(len(commands), expected['revision'])
        page.reload(wait_until='domcontentloaded', timeout=WORKER_TIMEOUT)
        expect(page.locator('.mini-match')).to_be_visible(timeout=WORKER_TIMEOUT)
        restored = self.read_state(page)
        # Compare every exposed field, including hand, players, phase, options,
        # history and trace. Equal revision counters cannot prove restoration.
        self.assertEqual(restored, expected)
        self.assert_rendered(page, restored)
        self.assertEqual(
            page.evaluate('(key) => sessionStorage.getItem(key)', STORAGE_KEY), history
        )

    def exercise_match(self, *, delay_worker=False) -> None:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(locale='en-US', reduced_motion='reduce')
            context.set_default_timeout(15_000)
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
            page = context.new_page()
            diagnostics = []
            page_errors = []
            page.on('pageerror', lambda error: page_errors.append(str(error)))
            page.on('console', lambda message: diagnostics.append(f'{message.type}: {message.text}'))
            page.on('requestfailed', lambda request: diagnostics.append(
                f'Failed request: {request.url}: {request.failure}'
            ))
            delayed_requests = []
            if delay_worker:
                def slow_worker(route):
                    delayed_requests.append(route.request.url)
                    # Deliberate fault injection, never a readiness wait. Serve
                    # the unmodified worker after delaying each cold startup.
                    time.sleep(1)
                    route.continue_()
                context.route('**/worker.mjs', slow_worker)
            failed = False
            try:
                page.goto(self.base_url + '?lang=en&mini=1',
                          wait_until='domcontentloaded', timeout=WORKER_TIMEOUT)
                expect(page.locator('.mini-match')).to_be_visible(timeout=WORKER_TIMEOUT)
                before = self.read_state(page)
                self.assertEqual(before['revision'], 1)
                self.assertEqual(before['stage'], 'mini')
                self.assertEqual(before['match']['phase'], 'turn')
                self.assertEqual(before['match']['actor'], 'p1')
                self.assertEqual({p['id'] for p in before['players']}, {'p1', 'p2', 'p3'})
                self.assertEqual(before['players'][0]['believers'], 6)
                self.assertGreater(len(before['match']['hand']), 0)
                self.assert_rendered(page, before)
                expect(page.locator('[data-action="mini_end_turn"]')).to_have_text('End turn & draw')

                # Play the prepared Chaos blessing through its real card button.
                option = next(opt for opt in before['match']['options']
                              if opt.get('art') == 'song' and opt['kind'] == 'play')
                after = self.click_command(page,
                    f'[data-action="mini_move"][data-move-index="{option["index"]}"]', before)
                self.assertEqual(after['match']['actions'], before['match']['actions'] - 1)
                self.assertEqual(after['players'][0]['believers'], 10)
                self.assertNotIn(option['card_id'], [c['id'] for c in after['match']['hand']])
                self.assert_reloaded(page, after)

                # Continue playing from the restored state, enter the draw phase,
                # draw a real Truth card and restore this intermediate phase too.
                drawn = self.click_command(page, '[data-action="mini_end_turn"]', after)
                self.assertEqual(drawn['match']['phase'], 'draw')
                self.assertEqual(drawn['match']['actor'], 'p1')
                value = drawn['match']['truth_choices'][0]
                selected = self.click_command(page,
                    f'[data-action="mini_draw"][data-value="{value}"]', drawn)
                self.assertEqual(len(selected['match']['hand']), len(drawn['match']['hand']) + 1)
                self.assertEqual(selected['match']['draws_left'], drawn['match']['draws_left'] - 1)
                self.assert_reloaded(page, selected)
                ended = self.click_command(page, '[data-action="mini_draw_rest"]', selected)
                self.assertEqual(ended['match']['actor'], 'p2')
                advanced = self.click_command(page, '[data-action="mini_advance"]', ended)
                self.assertEqual(advanced['match']['last_move']['player'], 'p2')
                self.assertEqual(advanced['match']['actions'], ended['match']['actions'] - 1)
                self.assertEqual(page_errors, [], 'Uncaught browser errors')
                if delay_worker:
                    self.assertEqual(len(delayed_requests), 3, 'Initial load and two reloads must start real workers')
            except BaseException:
                failed = True
                directory = ARTIFACTS / self._testMethodName
                directory.mkdir(parents=True, exist_ok=True)
                # Diagnostics must never hide the original assertion failure.
                try:
                    (directory / 'browser.log').write_text(
                        '\n'.join(diagnostics + page_errors), encoding='utf-8')
                    page.screenshot(path=str(directory / 'failure.png'), timeout=5000)
                    (directory / 'page.html').write_text(page.content(), encoding='utf-8')
                    context.tracing.stop(path=str(directory / 'trace.zip'))
                except Exception:
                    pass
                raise
            finally:
                if not failed:
                    context.tracing.stop()
                context.close()
                browser.close()

    def test_start_play_and_reload_mini_match(self) -> None:
        self.exercise_match()

    def test_slow_worker_initialization_and_replay(self) -> None:
        self.exercise_match(delay_worker=True)


if __name__ == '__main__':
    unittest.main()
