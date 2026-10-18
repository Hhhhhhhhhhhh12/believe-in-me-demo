from __future__ import annotations

from .constants import PHENOMENON_REMOVAL_REASON_ACTION_PLAYED
from .logging import append_event
from .state import GameState


def play_stored_phenomenon_action(
    state: GameState,
    *,
    player_id: str,
    phenomenon_id: str | None = None,
    action_name: str = "stored_phenomenon_action",
    decision_source: str | None = None,
) -> str:
    player = state.players[player_id]
    if not player.stored_phenomena:
        raise ValueError(f"Player {player_id} has no stored phenomena to play.")

    resolved_phenomenon_id = phenomenon_id
    if resolved_phenomenon_id is None:
        resolved_phenomenon_id = player.stored_phenomena[-1]
    elif resolved_phenomenon_id not in player.stored_phenomena:
        raise ValueError(f"Player {player_id} cannot play unknown stored phenomenon {resolved_phenomenon_id}.")

    stored_before = list(player.stored_phenomena)
    player.stored_phenomena.remove(resolved_phenomenon_id)
    state.phenomenon_discard.append(resolved_phenomenon_id)
    stored_after = list(player.stored_phenomena)

    append_event(
        state.event_log,
        "phenomenon_action_played",
        player_id=player_id,
        action_name=action_name,
        phenomenon_id=resolved_phenomenon_id,
        card_id=resolved_phenomenon_id,
        selected_default_lifo=phenomenon_id is None,
        stored_before=stored_before,
        stored_after=stored_after,
        decision_source=decision_source,
    )
    append_event(
        state.event_log,
        "phenomenon_discarded_after_action",
        player_id=player_id,
        phenomenon_id=resolved_phenomenon_id,
        card_id=resolved_phenomenon_id,
        stored_before=stored_before,
        stored_after=stored_after,
        reason=PHENOMENON_REMOVAL_REASON_ACTION_PLAYED,
        action_name=action_name,
        decision_source=decision_source,
        phenomenon_discard_size=len(state.phenomenon_discard),
    )
    return resolved_phenomenon_id
