# Believe in Me Demo

**[Play in your browser](https://hhhhhhhhhhhh12.github.io/believe-in-me-demo/)**

Play a prepared mini-match of Believe in Me with the original card artwork and
the Python rules engine running locally in a Pyodide Web Worker. New matches
start with six believers. Opponent steps wait for Continue, so results remain
available to read. No account, Python server or installation is required.

Display settings and local progress stay in your browser. There is no password
protection; opponent hands are concealed by the interface, not against developer
tools. Keyboard controls, readable card effects, larger text, contrast and
reduced-motion options are included. VoiceOver and physical-phone review remain
in progress; this is not an accessibility certification.

- [About Accessibility](https://hhhhhhhhhhhh12.github.io/believe-in-me-demo/accessibility.html?lang=en)
- [Under the surface](https://hhhhhhhhhhhh12.github.io/believe-in-me-demo/under-the-surface.html?lang=en)
- [Readable rules-engine sources](docs/source/)
- [Third-party notices and source references](docs/THIRD_PARTY_NOTICES.md)
- [Earlier resource-game browser demo](https://hhhhhhhhhhhh12.github.io/believe-in-me-demo/legacy-index.html)

The static site is in `docs/`; `docs/EXPORT-MANIFEST.json` records its exported
file hashes. Only selected demo cards, artwork and runtime modules are included.
The private development repository and its history are not part of this export.

## Earlier Resource-Engine Example

The original small resource-game engine and its tests are preserved below.
It is a separate earlier example, not the rules for the new BiM mini-match.

## Run

Requires Python 3.11 or newer. The engine and tests use only the standard library.
Run these commands from the repository root:

```sh
PYTHONPATH=src python3 -m believe_engine --seed 7
PYTHONPATH=src python3 -m believe_engine --seed 7 --json
```

With Make installed, `make demo` runs the same example. `make trace` prints its
JSON event log. Neither command writes files or contacts external services.

## Game

Two to eight players start with one resource and one card each. The seed controls
the initial deck shuffle. Each turn allows one action:

| Action | Effect |
| --- | --- |
| Gather | Gain one resource. |
| Draw | Take one card from the deck, up to a hand of three. |
| Play card | Pay its cost, gain its progress, and discard it. |
| Convert | Spend three resources to gain two progress. |
| Pass | End the turn without spending resources. |

The runner uses a simple greedy policy: take an immediate win, otherwise play
the highest-progress affordable card, draw when empty-handed, convert, or gather. It stops at a winner
or a configurable turn limit. A limit is reported as `turn_limit`, not a draw.

```sh
PYTHONPATH=src python3 -m believe_engine --players 4 --seed 12 --max-turns 100
PYTHONPATH=src python3 examples/run_demo.py
```

## Python API

```python
from believe_engine.legal_moves import legal_moves
from believe_engine.rules import apply_move, create_game

state = create_game(player_count=3)
next_state = apply_move(state, legal_moves(state)[0])
assert state.players[0].resources == 1
assert next_state.players[0].resources == 2
```

Actions produce new states and immutable event records. JSON exports are detached
copies, so editing a trace cannot change a match. Trace schema version 1 includes
the seed, completion status, turn count, winner, events, and final player totals.
It is an event log, not a save-game format.

Identical inputs reproduce the same trace with the same engine and Python version.
Randomness is local to each run. Cross-version trace compatibility is not promised.

The earlier browser game at `docs/legacy-index.html` implements that small set of actions in JavaScript
so GitHub Pages can run it without a Python server. Its seeded shuffle is separate
from Python's, so the same seed need not produce the same card order across them.

## Tests

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

`make test` is equivalent. Tests cover action legality, state isolation, victory,
turn limits, reproducibility, trace exports, and aggregate results.

Browser rules can be checked with Node.js 20 or newer:

```sh
make test-web
```

## License

All rights reserved. See [LICENSE](LICENSE) for reuse terms.
