# Believe in Me Demo

A small Python engine for a turn-based resource game. Players gather resources,
play cards, and convert resources into progress. The first to reach 10 progress wins.

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
the initial deck shuffle; undealt cards stay out of play. Each turn allows one action:

| Action | Effect |
| --- | --- |
| Gather | Gain one resource. |
| Play card | Pay its cost, gain its progress, and discard it. |
| Convert | Spend three resources to gain two progress. |
| Pass | End the turn without spending resources. |

The runner uses a simple greedy policy: take an immediate win, otherwise play
the highest-progress affordable card, convert, or gather. It stops at a winner
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

## Tests

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

`make test` is equivalent. Tests cover action legality, state isolation, victory,
turn limits, reproducibility, trace exports, and aggregate results.

## License

All rights reserved. See [LICENSE](LICENSE) for reuse terms.
