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
        # The terminal screen hides the hand while the engine retains its cards.
        finished = state['match']['phase'] == 'finished'
        expect(page.locator('.mini-hand-card')).to_have_count(
            0 if finished else len(state['match']['hand'])
        )
        self.assertEqual(
            page.locator('[data-mini-select]').evaluate_all(
                '(nodes) => nodes.map(node => node.dataset.miniSelect)'
            ),
            [] if finished else [card['id'] for card in state['match']['hand']],
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

    def finish_match_through_controls(self, page, state) -> None:
        transitions = []
        for _ in range(150):
            match = state['match']
            phase = match['phase']
            if phase == 'finished':
                break
            self.assertFalse(match['game_over'])
            self.assertEqual(match['winner_ids'], [])
            if phase == 'round_end':
                selector = '[data-action="mini_next_round"]'
            elif phase == 'claim':
                manifest = 'true' if match['can_manifest'] else 'false'
                selector = f'[data-action="mini_claim"][data-manifest="{manifest}"]'
            elif phase == 'nun':
                selector = '[data-action="mini_nun"][data-sacrifice="true"]'
            elif match['actor'] in {'p2', 'p3'}:
                selector = '[data-action="mini_advance"]'
            elif phase == 'turn':
                selector = '[data-action="mini_end_turn"]'
            elif phase == 'draw':
                selector = '[data-action="mini_draw_rest"]'
            elif phase == 'contest':
                desired = 'truth_p1_4' if match['own_bid_total'] == 0 else 'truth_p1_6'
                bid = next((card for card in match['hand']
                            if card['art'] == desired and card['can_bid']), None) if state['round'] == 1 else None
                if bid is None and match['can_pass']:
                    selector = '[data-action="mini_pass"]'
                else:
                    bid = bid or next(card for card in match['hand'] if card['can_bid'])
                    selector = f'[data-action="mini_bid"][data-card-id="{bid["id"]}"]'
            else:
                self.fail(f'Unexpected mini-match phase: {phase}')
            before = state
            state = self.click_command(page, selector, before)
            if phase == 'claim' and before['round'] == 1:
                self.assertEqual(state['body_count'], 3)
                self.assertTrue(state['revealed'])
                self.assertEqual(state['match']['rounds_left'], 3)
                expect(page.locator('.board-legs')).to_be_visible()
                expect(page.locator('.prophet-slot')).to_have_attribute('data-occupied', 'true')
                expect(page.locator('.prophet-slot img')).to_be_visible()
                expect(page.locator('.mini-prophet-supply')).to_have_count(0)
                directory = ARTIFACTS / 'layout'
                directory.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(directory / 'special-chips-prophet-claimed.png'), full_page=True)
            if phase == 'nun' and before['round'] == 1:
                self.assertEqual(state['match']['nun_ready'], 0)
                expect(page.locator('.nun-slot')).to_have_attribute('data-ready', '0')
                expect(page.locator('.nun-slot img')).to_have_count(0)
            if state['endgame']:
                expect(page.locator('.mini-round-status')).to_contain_text(
                    f'Twilight: {state["match"]["rounds_left"]} final rounds'
                )
            if phase == 'round_end':
                transitions.append((before['round'], match['rounds_left'], state['match']['rounds_left']))
        else:
            self.fail('The browser mini-match did not finish within 150 commands')
        self.assertEqual(transitions, [(1, 3, 3), (2, 3, 2), (3, 2, 1), (4, 1, 0)])
        self.assertTrue(state['match']['game_over'])
        self.assertEqual(state['match']['end_reason'], 'game_over_endgame')
        self.assertEqual(state['match']['winner_ids'], ['p1'])
        expect(page.locator('.mini-finished h2')).to_have_text('The Heavenly Realm has spoken.')
        expect(page.locator('.mini-finished .mini-result')).to_have_text('You')
        expect(page.locator('[data-action="mini_next_round"]')).to_have_count(0)
        expect(page.locator('[data-action="mini_bid"]')).to_have_count(0)
        self.assert_reloaded(page, state)
        expect(page.locator('.mini-finished .mini-result')).to_have_text('You')
        expect(page.locator('.mini-finished [data-action="restart"]')).to_be_visible()

    def exercise_match(self, *, delay_worker=False, complete_match=False) -> None:
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
                self.assertEqual(before['match']['nun_ready'], 1)
                self.assertTrue(before['match']['nun_active'])
                self.assertIsNone(before['match']['prophet_holder'])
                expect(page.locator('.nun-slot')).to_have_attribute('data-ready', '1')
                expect(page.locator('.nun-slot img')).to_be_visible()
                expect(page.locator('.prophet-slot')).to_have_attribute('data-occupied', 'false')
                expect(page.locator('.mini-prophet-supply')).to_contain_text('In reserve')
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
                if complete_match:
                    self.finish_match_through_controls(page, advanced)
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

    def test_complete_mini_match_manifest_countdown_winner_and_reload(self) -> None:
        self.exercise_match(complete_match=True)


if __name__ == '__main__':
    unittest.main()
