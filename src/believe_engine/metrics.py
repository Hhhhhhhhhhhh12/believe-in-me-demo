from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any

from .runner import RunResult


def summarize_results(results: Iterable[RunResult]) -> dict[str, Any]:
    runs = list(results)
    winners = Counter(run.winner_id for run in runs if run.winner_id is not None)
    return {
        "games": len(runs),
        "finished_games": sum(run.status == "finished" for run in runs),
        "turn_limited_games": sum(run.status == "turn_limit" for run in runs),
        "winner_counts": dict(sorted(winners.items())),
        "average_turns": round(sum(run.turn_count for run in runs) / len(runs), 2) if runs else 0.0,
    }
