# Published browser smoke tests

These tests serve the actual `docs/` export and exercise Chromium, the fetch
bridge, the Pyodide Web Worker and its bundled Python game engine together.
They do not use Playwright API-request fixtures or replace engine responses.

## Run

```sh
python -m pip install 'playwright==1.64.1'
python -m playwright install --with-deps chromium
python -m unittest discover -s tests/browser -p 'test_*.py' -v
make verify
make demo
```

Keep this directory without `__init__.py`: the standard-library-only `make test`
job must not discover the optional Playwright tests recursively.

## Assertions and timing

Both tests start with an isolated browser context and empty session storage.
They check English controls, the three players, six starting believers, and the
rendered hand against the worker state. A real Chaos blessing consumes an action
and its card, raising the flock from six to ten. The test reloads and compares
every field returned by `/api/state`, including hand, players, phase, legal
options, history and trace, while ensuring replay did not append commands.
It then ends the turn, draws a Truth card, reloads that intermediate draw phase,
finishes drawing and advances an opponent via the visible Continue command.
The second test delays the unmodified worker script by one second on the initial
load and both reloads, exercising readiness and replay under slower startup.

The bridge's `ready` promise gates requests until worker initialization/replay
completes; the worker serializes requests on a promise queue. No production
initialization defect was established during this review. The original test's
revision-only wait could observe engine progress before the UI finished rendering.
The updated test waits for `#app[aria-busy=false]` and checks the rendered hand,
flock and error status after each command. Startup/replay allow 180 seconds,
covering the bridge's 150-second request budget; normal controls allow 15 seconds.
The one-second delay is fault injection, not a substitute for readiness assertions.

On failure, best-effort screenshots, DOM, browser diagnostics and a Playwright
trace are saved under `test-results/browser/`; CI uploads them for seven days.
There are no retries that could turn a failing test green.

## Review evidence and merge gate (31 October 2026)

The original PR head `575cfb4c961ed396a4d321c4f4b79044a840b1fe` passed
[Browser Smoke run 41033355343](https://github.com/Hhhhhhhhhhhh12/believe-in-me-demo/actions/runs/41033355343)
(one test, 4.556 seconds) and
[Verify run 41033355294](https://github.com/Hhhhhhhhhhhh12/believe-in-me-demo/actions/runs/41033355294).
These results do not validate subsequent review changes.

Local review environment: 36 Python tests, seven Node tests and the CLI demo
passed. Playwright 1.64.1 installed, but Chromium and headless-shell downloads
returned invalid/truncated ZIP archives. No system Chromium was available.
The browser suite consequently failed at launch, before executing the scenarios.
The updated suite must pass on GitHub Actions (both normal and delayed startup),
alongside the unchanged five Verify job names, on the exact final PR head.

The active `Protect main – PR + CI` ruleset requires `python (3.11)`,
`python (3.12)`, `python (3.13)`, `python (3.14)` and `browser-rules`, with strict
up-to-date checking and no bypass actors. It does **not** currently require
`browser-smoke`; its required approving review count is **zero**. The separate
legacy branch-protection endpoint was inaccessible to the GitHub integration
(403); the ruleset itself was readable. No protection setting was changed.
Before merge, obtain a review and successful checks; consider making
`browser-smoke` required once its final-head CI result is green. An independent
review can be technically enforced by requiring one approving review if a
separate eligible reviewer is available. The PR stays draft in this review.

Verify previously ran on every push and every PR event, duplicating all five jobs
for updates to an open PR. Both workflows now validate PRs targeting main plus
post-merge main pushes, cancel superseded runs within the same workflow/PR, and
keep existing required job names. Feature branches without PRs should use local
checks or open a draft PR for CI. No path filters or draft skips can strand a
required check in Pending. Personal notification settings were not accessed or
changed; genuine failures still fail CI.

## Scope limits

This is an opening-flow and persistence smoke test, not full game qualification.
It does not cover a complete match, all bidding/claim/nun branches, invalid-command
UI recovery, corrupted storage, the 2,000-command history limit, another browser,
mobile layout or an accessibility audit. Reload restores the same-tab session;
closing the tab and starting a new session is not a persistence guarantee.
