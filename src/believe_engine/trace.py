from __future__ import annotations

import json
from typing import Any

from .runner import RunResult


def trace_payload(result: RunResult) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "seed": result.seed,
        "status": result.status,
        "turn_count": result.turn_count,
        "winner_id": result.winner_id,
        "events": [
            {
                "round": event.round_number,
                "turn_index": event.turn_index,
                "player_id": event.player_id,
                "type": event.event_type,
                **dict(event.data),
            }
            for event in result.final_state.events
        ],
        "players": [
            {
                "player_id": player.player_id,
                "resources": player.resources,
                "progress": player.progress,
                "discard_count": player.discard_count,
            }
            for player in result.final_state.players
        ],
    }


def trace_json(result: RunResult) -> str:
    return json.dumps(trace_payload(result), indent=2, sort_keys=True)
