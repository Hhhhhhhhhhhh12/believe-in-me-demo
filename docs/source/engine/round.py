from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, fields
from typing import Any

from .contest import normalize_manifest_requests, register_known_phenomenon_metadata, resolve_contest
from .logging import append_event
from .state import GameState


@dataclass(slots=True)
class RoundFrame:
    completed_round: int
    player_count: int
    turn_order: list[str]


def _resolve_claim_card_name(state: GameState, *, card_id: str) -> str | None:
    for event in reversed(state.event_log):
        if event.get("type") != "phenomenon_drawn_for_contest":
            continue
        if event.get("card_id") != card_id:
            continue
        card_name = event.get("card_name")
        return card_name if isinstance(card_name, str) and card_name else None
    return None


def _restore_game_state(target: GameState, snapshot: GameState) -> None:
    for state_field in fields(GameState):
        setattr(target, state_field.name, deepcopy(getattr(snapshot, state_field.name)))


def _validate_turn_intents_by_player(
    state: GameState,
    *,
    turn_intents_by_player: dict[str, dict[str, Any]] | None,
) -> None:
    if not turn_intents_by_player:
        return
    for player_id, payload in turn_intents_by_player.items():
        if player_id not in state.players:
            raise ValueError(f"Unknown player in turn_intents_by_player: {player_id}")
        if not isinstance(payload, dict):
            raise ValueError(f"turn_intents_by_player[{player_id}] must be a dict payload.")
        if "role_action_intents" in payload:
            raise ValueError(
                "Legacy turn intent key role_action_intents is not supported in play_round; "
                "use action_intents instead."
            )


def _validate_contest_options(contest_options: dict[str, Any] | None) -> None:
    if contest_options is None:
        return
    if not isinstance(contest_options, dict):
        raise ValueError("contest_options must be a dict payload.")
    allowed_option_keys = {
        "contested_card_id",
        "contested_card_name",
        "contested_card_alignment",
        "manifest_requests",
        "tie_manifest_requests",
        "nun_sacrifice_decisions",
        "contest_turn_intents",
        "phenomenon_prediction_guesses",
        "require_explicit_turn_intents",
    }
    unknown_keys = sorted(key for key in contest_options if key not in allowed_option_keys)
    if unknown_keys:
        raise ValueError(f"Unknown contest_options keys: {unknown_keys}")


def begin_round(state: GameState) -> RoundFrame | None:
    if state.game_over:
        from .core import validate_state

        validate_state(state)
        append_event(
            state.event_log,
            "round_skipped_game_over",
            round_number=state.round_number,
            start_player_idx=state.start_player_idx,
        )
        state.validation_cursor = len(state.event_log)
        return None

    if state.endgame_active and state.endgame_rounds_left == 0:
        from .core import validate_state

        validate_state(state)
        append_event(
            state.event_log,
            "round_skipped_final_rounds_exhausted",
            round_number=state.round_number,
            start_player_idx=state.start_player_idx,
        )
        state.validation_cursor = len(state.event_log)
        return None

    player_count = len(state.player_order)
    turn_order = [
        state.player_order[(state.start_player_idx + offset) % player_count]
        for offset in range(player_count)
    ]
    completed_round = state.round_number
    append_event(
        state.event_log,
        "round_started",
        round_number=completed_round,
        start_player_idx=state.start_player_idx,
        turn_order=turn_order,
    )
    return RoundFrame(
        completed_round=completed_round,
        player_count=player_count,
        turn_order=turn_order,
    )


def finalize_round(state: GameState, *, frame: RoundFrame) -> GameState:
    from .core import (
        advance_endgame_countdown_after_round,
        finalize_round_terminal_state,
        validate_state,
    )

    state.start_player_idx = (state.start_player_idx + 1) % frame.player_count
    state.current_player_index = state.start_player_idx
    state.round_number += 1
    append_event(
        state.event_log,
        "round_completed",
        completed_round=frame.completed_round,
        next_round_number=state.round_number,
        next_start_player_idx=state.start_player_idx,
    )
    advance_endgame_countdown_after_round(state, completed_round=frame.completed_round)
    finalize_round_terminal_state(state, completed_round=frame.completed_round)
    validate_state(state)
    return state


def play_round(
    state: GameState,
    *,
    turn_intents_by_player: dict[str, dict[str, Any]] | None = None,
    contest_options: dict[str, Any] | None = None,
) -> GameState:
    if not state.game_over:
        _validate_turn_intents_by_player(state, turn_intents_by_player=turn_intents_by_player)
        _validate_contest_options(contest_options)

    frame = begin_round(state)
    if frame is None:
        return state

    from .core import (
        maybe_start_endgame_countdown,
        play_turn,
    )

    for player_id in frame.turn_order:
        turn_intents = {} if turn_intents_by_player is None else turn_intents_by_player.get(player_id, {})
        play_turn(
            state,
            player_id=player_id,
            prophet_target_player_id=turn_intents.get("prophet_target_player_id"),
            prophet_payment_choice=turn_intents.get("prophet_payment_choice"),
            prophet_transfer_payment_choice=turn_intents.get("prophet_transfer_payment_choice"),
            tableau_effect_intents=turn_intents.get("tableau_effect_intents"),
            action_intents=turn_intents.get("action_intents"),
            require_explicit_action_intents=turn_intents.get("require_explicit_action_intents"),
        )

    play_phenomenon_contest(state, **(contest_options or {}))
    maybe_start_endgame_countdown(state, trigger_source="round_end_post_contest")
    return finalize_round(state, frame=frame)


def play_phenomenon_contest(
    state: GameState,
    *,
    contested_card_id: str | None = None,
    contested_card_name: str | None = None,
    contested_card_alignment: str | None = None,
    manifest_requests: dict[str, bool | str | dict[str, Any]] | None = None,
    tie_manifest_requests: dict[str, str | dict[str, Any]] | None = None,
    nun_sacrifice_decisions: dict[str, bool] | None = None,
    contest_turn_intents: dict[str, list[dict[str, object] | str] | dict[str, object] | str] | None = None,
    phenomenon_prediction_guesses: dict[str, str] | None = None,
    require_explicit_turn_intents: bool | None = None,
) -> GameState:
    state_snapshot = deepcopy(state)
    try:
        explicit_turn_intents_required = (
            state.require_explicit_contest_turn_intents
            if require_explicit_turn_intents is None
            else require_explicit_turn_intents
        )
        register_known_phenomenon_metadata(
            state,
            card_id=contested_card_id,
            card_name=contested_card_name,
            card_alignment=contested_card_alignment,
        )
        normalized_manifest_requests = normalize_manifest_requests(
            state,
            manifest_requests=manifest_requests,
        )
        contest = resolve_contest(
            state,
            contested_card_id=contested_card_id,
            tie_manifest_requests=tie_manifest_requests,
            nun_sacrifice_decisions=nun_sacrifice_decisions,
            contest_turn_intents=contest_turn_intents,
            prediction_guesses=phenomenon_prediction_guesses,
            require_explicit_turn_intents=explicit_turn_intents_required,
        )
        from .core import (
            claim_phenomenon,
            has_free_phenomenon_slot,
            maybe_start_endgame_countdown,
            validate_state,
        )

        if contest.winner_id is None or contest.contested_card_id is None:
            maybe_start_endgame_countdown(state, trigger_source="contest_end_no_winner")
            validate_state(state)
            return state

        winner = state.players[contest.winner_id]

        if not has_free_phenomenon_slot(state, player_id=contest.winner_id):
            append_event(
                state.event_log,
                "contest_winner_cannot_claim_phenomenon_due_to_full_slots",
                current_round=state.round_number,
                player_id=contest.winner_id,
                contested_card_id=contest.contested_card_id,
                stored_phenomena_count=len(winner.stored_phenomena),
                phenomena_slots=winner.phenomena_slots,
            )
            maybe_start_endgame_countdown(
                state,
                trigger_source="contest_end_winner_no_claim",
                preferred_player_id=contest.winner_id,
            )
            validate_state(state)
            return state

        claim_phenomenon(
            state,
            player_id=contest.winner_id,
            card_id=contest.contested_card_id,
            card_name=_resolve_claim_card_name(state, card_id=contest.contested_card_id),
            manifest_requested=normalized_manifest_requests.get(contest.winner_id, (False, None))[0],
            manifest_body_part_category=normalized_manifest_requests.get(contest.winner_id, (False, None))[1],
        )
        maybe_start_endgame_countdown(
            state,
            trigger_source="contest_end_claim",
            preferred_player_id=contest.winner_id,
        )
        validate_state(state)
        return state
    except Exception:
        _restore_game_state(state, state_snapshot)
        raise
