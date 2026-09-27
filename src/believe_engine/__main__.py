from __future__ import annotations

import argparse

from .runner import run_match
from .trace import trace_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a Believe in Me resource match.")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--players", type=int, choices=range(2, 9), default=3)
    parser.add_argument("--max-turns", type=int, default=200)
    parser.add_argument("--json", action="store_true", help="Print the complete event trace.")
    args = parser.parse_args()
    try:
        result = run_match(seed=args.seed, player_count=args.players, max_turns=args.max_turns)
    except ValueError as error:
        parser.error(str(error))
    if args.json:
        print(trace_json(result))
    else:
        print("Believe in Me Demo")
        print(f"Seed: {result.seed}")
        print(f"Status: {result.status}")
        print(f"Winner: {result.winner_id or 'none'}")
        print(f"Turns: {result.turn_count}")
        print(f"Events: {len(result.final_state.events)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
