from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Any

from .catalog import get_card_record
from .commandments import is_tableau_card_disabled
from .constants import ILLEGAL_STATE_NO_PHENOMENON_AVAILABLE_FOR_CONTEST
from .logging import append_event
from .state import CardRef, GameState, PlayerState, is_pure_alignment


HEAVENLY_BIDDABLE_CATEGORIES = {"Aufklärer", "Heiliges Heer", "Reliquie", "Segen"}
TRUTH_CATEGORY = "Wahrheit"
ENLIGHTENER_TRUTH_SIX_SEVEN_ZERO_TEXT = 'Ab sofort: Deine "Wahrheitskarte 6" und "Wahrheitskarte 7" zählen 0 Wahrheit'
ENLIGHTENER_FORCE_FIRST_CONTEST_CARD_OPEN_TEXT = "Ab sofort: Du musst deine erste Karte beim Stechen offen auslegen."
ENLIGHTENER_DISABLES_RELICS_TEXT = "Ab sofort: Deine Reliquien verlieren"
RELIC_PREDICT_NEXT_PHENOMENON_ALIGNMENT_TEXT = (
    "Du darfst vor dem Aufdecken eines Phänomens die Gesinnung vorhersagen. "
    "Liegst du richtig, darfst du 2 <CULTISTS> taufen"
)
RELIC_TEMPLES_CANNOT_LOSE_ROLE_MEEPLES_TEXT = "Deine Tempel können weder Mönche, Missionare noch Nonnen verlieren."
RELIC_EMPTY_NUN_TEMPLE_TRUTH_BONUS_TEXT = (
    "Jede deiner Wahrheitskarten zählt 1 Punkt mehr, solange dein Nonnen-Tempel keine Nonnen beherbergt."
)


@dataclass(slots=True)
class ContestBidChoice:
    truth_values: list[int] = field(default_factory=list)
    truth_card_ids: list[str] = field(default_factory=list)
    heavenly_card_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CommittedContestBid:
    player_id: str
    truth_values: list[int] = field(default_factory=list)
    truth_cards: list[CardRef] = field(default_factory=list)
    heavenly_cards: list[CardRef] = field(default_factory=list)
    bid_total: int = 0
    is_open: bool = False
    bid_order: int = 0
    player_bid_index: int = 0


@dataclass(slots=True)
class ContestScore:
    bid_totals: dict[str, int]
    winner_id: str | None
    tied_player_ids: list[str]
    tie_breaker: str = "highest_bid_total"


@dataclass(slots=True)
class ContestState:
    player_order: list[str]
    current_player_idx: int
    start_player_idx: int
    current_round: int
    contested_card_id: str | None = None
    played_bids: list[CommittedContestBid] = field(default_factory=list)
    passed_players: set[str] = field(default_factory=set)
    passed_player_ids: list[str] = field(default_factory=list)
    pass_order_by_player: dict[str, int] = field(default_factory=dict)
    total_pass_count: int = 0
    bid_count: int = 0
    hidden_bid_buffers: dict[str, list[CommittedContestBid]] = field(default_factory=dict)
    winner_id: str | None = None
    ended: bool = False
    nuns_used: bool = False
    nun_sacrifice_player_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ContestTurnIntent:
    action: str
    bid_choice: ContestBidChoice | None = None


@dataclass(slots=True)
class ContestOutcomeResolution:
    outcome: str
    manifestation_player_ids: list[str] = field(default_factory=list)
    baptism_player_ids: list[str] = field(default_factory=list)
    phenomenon_discarded_due_to_tie: bool = False
    discarded_phenomenon_card_id: str | None = None


def _count_total_believers(player: PlayerState) -> int:
    assigned_role_meeples = sum(max(0, int(amount)) for amount in player.assigned_role_meeples.values())
    prepared_nuns = max(0, int(player.nunnery_state.prepared_nuns))
    return max(0, int(player.meeples)) + assigned_role_meeples + prepared_nuns


def _normalize_alignment_value(alignment: str | None) -> str | None:
    if not isinstance(alignment, str):
        return None
    normalized = alignment.strip().strip("<>").strip()
    return normalized or None


def _is_pure_unergruendlich(player: PlayerState | None) -> bool:
    if player is None:
        return False
    return player.alignment == "<Unergründlich>" and is_pure_alignment(player, "<Unergründlich>")


def get_phenomenon_believer_reward(
    *,
    player_alignment: str | None,
    phenomenon_alignment: str | None,
    player: PlayerState | None = None,
) -> int | None:
    normalized_phenomenon_alignment = _normalize_alignment_value(phenomenon_alignment)
    normalized_player_alignment = _normalize_alignment_value(player_alignment)
    if normalized_phenomenon_alignment is None:
        return None
    if normalized_player_alignment == "Unergründlich":
        if _is_pure_unergruendlich(player):
            return 10
        return 3
    if normalized_player_alignment == normalized_phenomenon_alignment:
        return 5
    return 8


def get_known_phenomenon_record(state: GameState, card_id: str | None) -> dict[str, Any] | None:
    if not isinstance(card_id, str):
        return None

    _sync_known_phenomena_from_draw_pile(state)
    record = get_card_record(card_id)
    known_record = state.known_phenomena.get(card_id)
    if record is None:
        return dict(known_record) if isinstance(known_record, dict) else None
    if not isinstance(known_record, dict):
        return record

    merged_record = dict(record)
    for key, value in known_record.items():
        if value is not None:
            merged_record[key] = value
    return merged_record


def get_known_phenomenon_alignment(state: GameState, card_id: str | None) -> str | None:
    record = get_known_phenomenon_record(state, card_id)
    if record is None:
        return None
    alignment = record.get("alignment")
    return alignment if isinstance(alignment, str) else None


def register_known_phenomenon_metadata(
    state: GameState,
    *,
    card_id: str | None,
    card_name: str | None = None,
    card_category: str | None = None,
    card_alignment: str | None = None,
) -> None:
    if not isinstance(card_id, str):
        return

    existing_record = get_known_phenomenon_record(state, card_id) or {}
    if (
        not existing_record
        and card_name is None
        and card_category is None
        and card_alignment is None
    ):
        return

    resolved_name = card_name or existing_record.get("name") or card_id
    resolved_category = card_category or existing_record.get("category") or "Phänomene"
    resolved_alignment = card_alignment if isinstance(card_alignment, str) else existing_record.get("alignment")
    resolved_source_row = existing_record.get("source_row")
    state.known_phenomena[card_id] = {
        "card_id": card_id,
        "name": resolved_name,
        "category": resolved_category,
        "alignment": resolved_alignment,
        "source_row": resolved_source_row,
    }


def resolve_contested_phenomenon_card_id(
    state: GameState,
    *,
    contested_card_id: str | None,
) -> str | None:
    return _resolve_contested_phenomenon_card_id(state, contested_card_id=contested_card_id)


def apply_phenomenon_prediction_bonuses(
    state: GameState,
    *,
    contested_card_id: str,
    current_round: int,
    prediction_guesses: dict[str, str] | None,
) -> None:
    phenomenon_alignment = get_known_phenomenon_alignment(state, contested_card_id)
    if not isinstance(phenomenon_alignment, str):
        return

    normalized_guesses = _normalize_prediction_guesses(state, prediction_guesses=prediction_guesses)
    for player_id in state.player_order:
        if not _player_has_active_relic_rule_text(
            state,
            player_id=player_id,
            text=RELIC_PREDICT_NEXT_PHENOMENON_ALIGNMENT_TEXT,
        ):
            continue

        guessed_alignment = normalized_guesses.get(player_id)
        decision_source = "explicit_intent" if player_id in normalized_guesses else "no_guess"
        append_event(
            state.event_log,
            "phenomenon_prediction_decided",
            current_round=current_round,
            player_id=player_id,
            contested_card_id=contested_card_id,
            guessed_alignment=guessed_alignment,
            phenomenon_alignment=phenomenon_alignment,
            decision_source=decision_source,
        )
        if guessed_alignment != phenomenon_alignment:
            append_event(
                state.event_log,
                "phenomenon_prediction_resolved",
                current_round=current_round,
                player_id=player_id,
                contested_card_id=contested_card_id,
                guessed_alignment=guessed_alignment,
                phenomenon_alignment=phenomenon_alignment,
                was_correct=False,
                reward_amount=0,
                meeples_after=state.players[player_id].meeples,
            )
            continue

        state.players[player_id].meeples += 2
        append_event(
            state.event_log,
            "phenomenon_prediction_resolved",
            current_round=current_round,
            player_id=player_id,
            contested_card_id=contested_card_id,
            guessed_alignment=guessed_alignment,
            phenomenon_alignment=phenomenon_alignment,
            was_correct=True,
            reward_amount=2,
            meeples_after=state.players[player_id].meeples,
        )


def _register_known_phenomenon_card(state: GameState, card: CardRef) -> None:
    state.known_phenomena[card.card_id] = {
        "card_id": card.card_id,
        "name": card.name,
        "category": card.category,
        "alignment": card.metadata.get("alignment"),
        "source_row": card.metadata.get("source_row"),
    }


def _sync_known_phenomena_from_draw_pile(state: GameState) -> None:
    for card in state.phenomenon_draw_pile:
        if card.category != "Phänomene":
            continue
        _register_known_phenomenon_card(state, card)


def normalize_bid_choice(bid_choice: ContestBidChoice | dict[str, Any] | list[int]) -> ContestBidChoice:
    if isinstance(bid_choice, ContestBidChoice):
        return ContestBidChoice(
            truth_values=list(bid_choice.truth_values),
            truth_card_ids=list(bid_choice.truth_card_ids),
            heavenly_card_ids=list(bid_choice.heavenly_card_ids),
        )
    if isinstance(bid_choice, list):
        return ContestBidChoice(truth_values=list(bid_choice))
    if isinstance(bid_choice, dict):
        return ContestBidChoice(
            truth_values=list(bid_choice.get("truth", [])),
            truth_card_ids=list(bid_choice.get("truth_card_ids", [])),
            heavenly_card_ids=list(bid_choice.get("heavenly_card_ids", [])),
        )
    raise ValueError(f"Unsupported contest bid payload: {bid_choice!r}")


def serialize_bid_choice(choice: ContestBidChoice) -> dict[str, Any]:
    serialized: dict[str, Any] = {
        "truth": list(choice.truth_values),
        "heavenly_card_ids": list(choice.heavenly_card_ids),
    }
    if choice.truth_card_ids:
        serialized["truth_card_ids"] = list(choice.truth_card_ids)
    return serialized


def get_bid_options(
    state: GameState,
    player_id: str,
    contest_state: ContestState | None = None,
) -> list[ContestBidChoice]:
    if contest_state is not None:
        if contest_state.ended or player_id not in contest_state.player_order:
            return []
        if _player_has_passed(contest_state, player_id):
            return []

    player = state.players[player_id]
    if contest_state is not None and _get_player_committed_contest_card_count(
        contest_state,
        player_id=player_id,
    ) >= _get_contest_card_limit(player):
        return []
    bid_options: list[ContestBidChoice] = []

    for card in player.hand_cards:
        if card.category in HEAVENLY_BIDDABLE_CATEGORIES:
            bid_options.append(ContestBidChoice(heavenly_card_ids=[card.card_id]))

    for card in player.hand_cards:
        if card.category != TRUTH_CATEGORY:
            continue
        if _get_truth_card_pool_value(card) not in player.truth_pool:
            continue
        bid_options.append(
            ContestBidChoice(
                truth_card_ids=[card.card_id],
            )
        )

    return bid_options


def get_legal_bid_options(
    state: GameState,
    player_id: str,
    contest_state: ContestState | None = None,
) -> list[ContestBidChoice]:
    legal_bid_options: list[ContestBidChoice] = []
    for bid_choice in get_bid_options(state, player_id, contest_state):
        try:
            validate_bid_choice(
                state,
                player_id=player_id,
                bid_choice=bid_choice,
                contest_state=contest_state,
            )
        except ValueError:
            continue
        legal_bid_options.append(bid_choice)
    return legal_bid_options


def estimate_bid_choice_total(
    state: GameState,
    player_id: str,
    bid_choice: ContestBidChoice | dict[str, Any] | list[int],
    contest_state: ContestState | None = None,
) -> int:
    normalized_bid = normalize_bid_choice(bid_choice)
    player = state.players[player_id]
    cards_by_id = {str(card.card_id): card for card in player.hand_cards}
    total = 0
    for truth_card_id in normalized_bid.truth_card_ids:
        card = cards_by_id.get(str(truth_card_id))
        if card is not None:
            total += _get_effective_bid_truth_value(state, player_id=player_id, card=card)
    for heavenly_card_id in normalized_bid.heavenly_card_ids:
        card = cards_by_id.get(str(heavenly_card_id))
        if card is not None:
            total += _get_effective_bid_truth_value(state, player_id=player_id, card=card)
    for truth_value in normalized_bid.truth_values:
        total += int(truth_value)
    if contest_state is not None and not _player_has_defined_chest(player):
        already_has_committed_bid = any(
            committed_bid.player_id == player_id
            for committed_bid in list(getattr(contest_state, "played_bids", []) or [])
        )
        if not already_has_committed_bid:
            total += 3
    return total


def commit_bid(
    state: GameState,
    player_id: str,
    bid_choice: ContestBidChoice | dict[str, Any] | list[int],
    *,
    contest_state: ContestState | None = None,
) -> CommittedContestBid:
    normalized_bid = normalize_bid_choice(bid_choice)
    validate_bid_choice(
        state,
        player_id=player_id,
        bid_choice=normalized_bid,
        contest_state=contest_state,
    )
    player = state.players[player_id]

    committed_bid = CommittedContestBid(player_id=player_id)

    for truth_card_id in normalized_bid.truth_card_ids:
        truth_card = _pop_card_from_hand(player, card_id=truth_card_id)
        if truth_card.category != TRUTH_CATEGORY:
            raise ValueError(f"Card {truth_card_id} is not a truth card.")
        truth_pool_value = _get_truth_card_pool_value(truth_card)
        truth_value = _get_effective_bid_truth_value(state, player_id=player_id, card=truth_card)
        counts_as_used_truth = truth_pool_value in player.truth_pool
        truth_card.metadata["counts_as_used_truth"] = counts_as_used_truth
        if counts_as_used_truth:
            _consume_truth_value(
                state,
                player_id=player_id,
                truth_value=truth_pool_value,
                card_id=truth_card.card_id,
            )
        committed_bid.truth_cards.append(truth_card)
        committed_bid.truth_values.append(truth_pool_value)
        committed_bid.bid_total += truth_value

    for heavenly_card_id in normalized_bid.heavenly_card_ids:
        heavenly_card = _pop_card_from_hand(player, card_id=heavenly_card_id)
        if heavenly_card.category not in HEAVENLY_BIDDABLE_CATEGORIES:
            raise ValueError(f"Card {heavenly_card_id} is not a biddable heavenly card.")
        committed_bid.heavenly_cards.append(heavenly_card)
        committed_bid.bid_total += _get_effective_bid_truth_value(
            state,
            player_id=player_id,
            card=heavenly_card,
        )

    truth_card_penalty = player.commandment_state.contest_truth_card_value_modifier_per_card * len(committed_bid.truth_cards)
    committed_bid.bid_total += truth_card_penalty

    return committed_bid


def validate_bid_choice(
    state: GameState,
    *,
    player_id: str,
    bid_choice: ContestBidChoice | dict[str, Any] | list[int],
    contest_state: ContestState | None = None,
) -> ContestBidChoice:
    normalized_bid = normalize_bid_choice(bid_choice)
    player = state.players[player_id]
    _validate_bid_choice_structure(player_id=player_id, bid_choice=normalized_bid)
    _validate_contest_card_limit(
        player,
        bid_choice=normalized_bid,
        existing_card_count=_get_player_committed_contest_card_count(
            contest_state,
            player_id=player_id,
        ),
    )
    _validate_truth_bid_cards(
        state,
        player_id=player_id,
        bid_choice=normalized_bid,
        contest_state=contest_state,
    )
    _validate_heavenly_bid_cards(
        player,
        bid_choice=normalized_bid,
        contest_state=contest_state,
    )
    return normalized_bid


def normalize_manifest_requests(
    state: GameState,
    *,
    manifest_requests: dict[str, bool | str | dict[str, Any]] | None,
    allowed_player_ids: list[str] | None = None,
) -> dict[str, tuple[bool, str | None]]:
    if manifest_requests is None:
        return {}

    allowed_player_id_set = None if allowed_player_ids is None else set(allowed_player_ids)
    normalized_manifest_requests: dict[str, tuple[bool, str | None]] = {}

    for player_id, requested in manifest_requests.items():
        if player_id not in state.players:
            raise ValueError(f"Unknown player in manifest requests: {player_id}.")
        if allowed_player_id_set is not None and player_id not in allowed_player_id_set:
            raise ValueError(f"Player {player_id} cannot submit a manifest request for this contest.")

        normalized_manifest_requests[player_id] = _normalize_single_manifest_request(
            player_id=player_id,
            raw_request=requested,
        )

    return normalized_manifest_requests


def finalize_committed_bids(state: GameState, committed_bids: list[CommittedContestBid]) -> GameState:
    touched_player_ids: set[str] = set()
    for committed_bid in committed_bids:
        if committed_bid.truth_cards:
            for truth_card in committed_bid.truth_cards:
                _append_truth_discard_card(
                    state,
                    player_id=committed_bid.player_id,
                    card=truth_card,
                    counts_as_used_truth=bool(truth_card.metadata.get("counts_as_used_truth", True)),
                )
            touched_player_ids.add(committed_bid.player_id)
        if committed_bid.heavenly_cards:
            state.heavenly_discard_pile.extend(committed_bid.heavenly_cards)
    for player_id in touched_player_ids:
        _maybe_reset_truth_after_exhaustion(state, player_id=player_id)
    return state


def _count_committed_cards_for_player(committed_bids: list[CommittedContestBid], *, player_id: str) -> int:
    total = 0
    for committed_bid in committed_bids:
        if committed_bid.player_id != player_id:
            continue
        total += len(committed_bid.truth_cards) + len(committed_bid.heavenly_cards)
    return total


def _recompute_committed_bid_total(state: GameState, *, player_id: str, committed_bid: CommittedContestBid) -> None:
    player = state.players[player_id]
    bid_total = 0
    for truth_card in committed_bid.truth_cards:
        bid_total += _get_effective_bid_truth_value(state, player_id=player_id, card=truth_card)
    for heavenly_card in committed_bid.heavenly_cards:
        bid_total += _get_effective_bid_truth_value(state, player_id=player_id, card=heavenly_card)
    bid_total += player.commandment_state.contest_truth_card_value_modifier_per_card * len(committed_bid.truth_cards)
    committed_bid.bid_total = bid_total


def _discard_contest_card_for_pure_wrath(
    state: GameState,
    *,
    committed_bids: list[CommittedContestBid],
    target_player_id: str,
) -> tuple[str, str] | None:
    for index in range(len(committed_bids) - 1, -1, -1):
        committed_bid = committed_bids[index]
        if committed_bid.player_id != target_player_id:
            continue
        if committed_bid.heavenly_cards:
            discarded_card = committed_bid.heavenly_cards.pop()
            state.heavenly_discard_pile.append(discarded_card)
            discard_zone = "heavenly_discard_pile"
        elif committed_bid.truth_cards:
            discarded_card = committed_bid.truth_cards.pop()
            if committed_bid.truth_values:
                committed_bid.truth_values.pop()
            _append_truth_discard_card(
                state,
                player_id=target_player_id,
                card=discarded_card,
                counts_as_used_truth=bool(discarded_card.metadata.get("counts_as_used_truth", True)),
            )
            discard_zone = "truth_discard"
            _maybe_reset_truth_after_exhaustion(state, player_id=target_player_id)
        else:
            continue
        _recompute_committed_bid_total(state, player_id=target_player_id, committed_bid=committed_bid)
        if not committed_bid.truth_cards and not committed_bid.heavenly_cards:
            committed_bids.pop(index)
        return discarded_card.card_id, discard_zone
    return None


def apply_pure_wrath_contest_discards(
    state: GameState,
    *,
    committed_bids: list[CommittedContestBid],
    current_round: int,
    contested_card_id: str | None,
    contest: ContestState | None = None,
) -> None:
    pure_wrath_player_ids = [
        player_id
        for player_id in state.player_order
        if player_id in {bid.player_id for bid in committed_bids}
        and state.players[player_id].alignment == "<Zorn>"
        and is_pure_alignment(state.players[player_id], "<Zorn>")
    ]
    if not pure_wrath_player_ids:
        return

    for pure_wrath_player_id in pure_wrath_player_ids:
        target_player_ids = [
            player_id
            for player_id in state.player_order
            if player_id != pure_wrath_player_id and _count_committed_cards_for_player(committed_bids, player_id=player_id) >= 2
        ]
        for target_player_id in target_player_ids:
            cards_before = _count_committed_cards_for_player(committed_bids, player_id=target_player_id)
            discarded = _discard_contest_card_for_pure_wrath(
                state,
                committed_bids=committed_bids,
                target_player_id=target_player_id,
            )
            if discarded is None:
                continue
            discarded_card_id, discard_zone = discarded
            cards_after = _count_committed_cards_for_player(committed_bids, player_id=target_player_id)
            if contest is not None:
                hidden_buffer = contest.hidden_bid_buffers.get(target_player_id, [])
                hidden_buffer[:] = [
                    committed_bid
                    for committed_bid in hidden_buffer
                    if committed_bid in committed_bids
                ]
            append_event(
                state.event_log,
                "pure_alignment_contest_discard_resolved",
                current_round=current_round,
                contested_card_id=contested_card_id,
                player_id=pure_wrath_player_id,
                pure_alignment="<Zorn>",
                target_player_id=target_player_id,
                discarded_card_id=discarded_card_id,
                discard_zone=discard_zone,
                committed_cards_before=cards_before,
                committed_cards_after=cards_after,
            )


def apply_nun_sacrifice_modifiers(
    state: GameState,
    committed_bids: list[CommittedContestBid],
    *,
    player_order: list[str],
    current_round: int,
    nun_sacrifice_decisions: dict[str, bool] | None = None,
) -> list[str]:
    applied_player_ids: list[str] = []
    decisions = dict(nun_sacrifice_decisions or {})
    unknown_decision_player_ids = sorted(
        player_id
        for player_id in decisions
        if player_id not in state.players
    )
    if unknown_decision_player_ids:
        raise ValueError(
            f"Nun sacrifice decisions include unknown player(s): {unknown_decision_player_ids}."
        )

    append_event(
        state.event_log,
        "nun_sacrifice_decision_window_started",
        current_round=current_round,
        player_order=list(player_order),
    )

    for player_id in player_order:
        can_apply = _can_apply_nun_sacrifice(state, player_id=player_id)
        explicit_decision = decisions.get(player_id)
        if explicit_decision and not can_apply:
            raise ValueError(
                f"Player {player_id} cannot sacrifice a nun without an active prepared nun."
            )
        if not can_apply:
            continue

        target = _get_lowest_truth_bid_entry(committed_bids, player_id=player_id)
        decision_source = "explicit" if player_id in decisions else "auto_default"

        if explicit_decision and target is None:
            raise ValueError(
                f"Player {player_id} cannot sacrifice a nun without having a real truth bid in the contest."
            )

        should_sacrifice = (
            explicit_decision
            if player_id in decisions
            else should_auto_sacrifice_nun(state, committed_bids, player_id=player_id)
        )
        append_event(
            state.event_log,
            "nun_sacrifice_decided",
            player_id=player_id,
            current_round=current_round,
            decision=should_sacrifice,
            decision_source=decision_source,
            has_truth_bid=target is not None,
            prepared_nuns=state.players[player_id].nunnery_state.prepared_nuns,
        )

        if not should_sacrifice or target is None:
            continue

        target_bid, truth_card, truth_value = target
        player = state.players[player_id]
        if _player_has_active_relic_rule_text(
            state,
            player_id=player_id,
            text=RELIC_TEMPLES_CANNOT_LOSE_ROLE_MEEPLES_TEXT,
        ):
            append_event(
                state.event_log,
                "nun_sacrifice_blocked_temple_protection",
                player_id=player_id,
                current_round=current_round,
                card_id=truth_card.card_id,
                truth_value=truth_value,
                prepared_nuns_remaining=player.nunnery_state.prepared_nuns,
            )
            continue
        _sacrifice_prepared_nuns(player, 1)
        target_bid.bid_total += truth_value
        applied_player_ids.append(player_id)

        append_event(
            state.event_log,
            "nun_sacrifice_applied",
            player_id=player_id,
            current_round=current_round,
            card_id=truth_card.card_id,
            doubled_truth_value=truth_value,
            prepared_nuns_remaining=player.nunnery_state.prepared_nuns,
            assigned_nuns_remaining=player.assigned_role_meeples.get("Nonnen", 0),
            sacrificed_nuns_total=player.nunnery_state.sacrificed_nuns,
        )

    return applied_player_ids


def score_committed_bids(state: GameState, committed_bids: list[CommittedContestBid]) -> ContestScore:
    bid_totals = _calculate_bid_totals(committed_bids)
    if not bid_totals:
        return ContestScore(
            bid_totals={},
            winner_id=None,
            tied_player_ids=[],
            tie_breaker="no_card_contribution",
        )
    for player_id in list(bid_totals):
        if not _player_has_defined_chest(state.players[player_id]):
            bid_totals[player_id] += 3
    highest_bid_total = max(bid_totals.values())
    winning_player_ids = [
        player_id
        for player_id, bid_total in bid_totals.items()
        if bid_total == highest_bid_total
    ]
    winner_id, tie_breaker = _break_contest_tie(
        state,
        winning_player_ids,
        committed_bids=committed_bids,
    )
    return ContestScore(
        bid_totals=bid_totals,
        winner_id=winner_id,
        tied_player_ids=[],
        tie_breaker=tie_breaker,
    )


def should_auto_sacrifice_nun(
    state: GameState,
    committed_bids: list[CommittedContestBid],
    *,
    player_id: str,
) -> bool:
    """Favor a strong Truth in a close lead; otherwise spend only for a win."""
    if not _can_apply_nun_sacrifice(state, player_id=player_id):
        return False
    target = _get_lowest_truth_bid_entry(committed_bids, player_id=player_id)
    if target is None or target[2] <= 0:
        return False
    if _player_has_active_relic_rule_text(
        state, player_id=player_id, text=RELIC_TEMPLES_CANNOT_LOSE_ROLE_MEEPLES_TEXT,
    ):
        return False
    target_bid, _truth_card, truth_value = target
    current_score = score_committed_bids(state, committed_bids)
    if current_score.winner_id == player_id:
        opponent_totals = [
            total for contender_id, total in current_score.bid_totals.items()
            if contender_id != player_id
        ]
        return (
            truth_value >= 4
            and bool(opponent_totals)
            and current_score.bid_totals[player_id] - max(opponent_totals) <= truth_value
        )

    player = state.players[player_id]
    projected_player = replace(
        player,
        nunnery_state=replace(player.nunnery_state),
        assigned_role_meeples=dict(player.assigned_role_meeples),
    )
    # The sacrificed believer also affects the existing fewest-believers tie-break.
    _sacrifice_prepared_nuns(projected_player, 1)
    projected_state = replace(state, players={**state.players, player_id: projected_player})
    projected_bids = [
        replace(bid, bid_total=bid.bid_total + truth_value) if bid is target_bid else bid
        for bid in committed_bids
    ]
    return score_committed_bids(projected_state, projected_bids).winner_id == player_id


def append_contest_reveal_log(
    state: GameState,
    *,
    contest_kind: str,
    current_round: int,
    contested_card_id: str | None,
    score: ContestScore,
    nun_sacrifice_player_ids: list[str],
) -> None:
    append_event(
        state.event_log,
        "contest_reveal_resolved",
        contest_kind=contest_kind,
        current_round=current_round,
        contested_card_id=contested_card_id,
        bid_totals=score.bid_totals,
        winner_id=score.winner_id,
        winner_idx=state.player_order.index(score.winner_id) if score.winner_id is not None else None,
        tied_player_ids=list(score.tied_player_ids),
        tie_breaker=score.tie_breaker,
        nun_sacrifice_player_ids=list(nun_sacrifice_player_ids),
    )


def apply_contest_outcome_resolution(
    state: GameState,
    *,
    current_round: int,
    contested_card_id: str | None,
    score: ContestScore,
    tie_manifest_requests: dict[str, str | dict[str, Any]] | None = None,
) -> ContestOutcomeResolution:
    del state, current_round, contested_card_id, tie_manifest_requests
    if score.winner_id is not None:
        return ContestOutcomeResolution(outcome="winner_determined")
    return ContestOutcomeResolution(outcome="no_winner")


def step_contest(state: GameState, contest: ContestState) -> ContestState:
    return step_contest_with_intents(
        state,
        contest,
        turn_intents=None,
        turn_intent_positions=None,
        nun_sacrifice_decisions=None,
        require_explicit_turn_intents=False,
    )


def step_contest_with_intents(
    state: GameState,
    contest: ContestState,
    *,
    turn_intents: dict[str, list[ContestTurnIntent]] | None,
    turn_intent_positions: dict[str, int] | None,
    nun_sacrifice_decisions: dict[str, bool] | None,
    require_explicit_turn_intents: bool = False,
) -> ContestState:
    if contest.ended:
        return contest

    current_player_id = contest.player_order[contest.current_player_idx]
    bid_options = get_legal_bid_options(state, current_player_id, contest)
    explicit_intent = _consume_next_turn_intent(
        player_id=current_player_id,
        turn_intents=turn_intents,
        turn_intent_positions=turn_intent_positions,
    )

    if require_explicit_turn_intents and explicit_intent is None and bid_options:
        raise ValueError(
            f"Player {current_player_id} must provide an explicit contest turn intent when require_explicit_turn_intents is enabled."
        )

    if explicit_intent is not None:
        if explicit_intent.action == "pass":
            _append_player_pass_event(
                state,
                contest=contest,
                player_id=current_player_id,
                decision_source="explicit_intent",
            )
        else:
            normalized_turn_bid = explicit_intent.bid_choice or ContestBidChoice()
            _ensure_single_card_turn_bid(player_id=current_player_id, bid_choice=normalized_turn_bid)
            committed_bid = commit_bid(
                state,
                current_player_id,
                normalized_turn_bid,
                contest_state=contest,
            )
            _record_committed_bid(contest=contest, committed_bid=committed_bid)
            contest.bid_count += 1
            _log_committed_bid(
                state,
                committed_bid=committed_bid,
                current_round=contest.current_round,
                bid_order=contest.bid_count,
                player_bid_index=sum(1 for bid in contest.played_bids if bid.player_id == committed_bid.player_id),
                decision_source="explicit_intent",
            )
    elif not bid_options:
        _append_player_pass_event(
            state,
            contest=contest,
            player_id=current_player_id,
            decision_source="auto_no_bid",
        )
    else:
        _ensure_single_card_turn_bid(player_id=current_player_id, bid_choice=bid_options[0])
        committed_bid = commit_bid(
            state,
            current_player_id,
            bid_options[0],
            contest_state=contest,
        )
        _record_committed_bid(contest=contest, committed_bid=committed_bid)
        contest.bid_count += 1
        _log_committed_bid(
            state,
            committed_bid=committed_bid,
            current_round=contest.current_round,
            bid_order=contest.bid_count,
            player_bid_index=sum(1 for bid in contest.played_bids if bid.player_id == committed_bid.player_id),
            decision_source="auto_first_option",
        )

    _maybe_run_nuns_check_window(
        state,
        contest=contest,
        nun_sacrifice_decisions=nun_sacrifice_decisions,
    )

    active_player_ids = _get_active_player_ids(contest)
    if len(active_player_ids) <= 1:
        contest.ended = True
        contest.winner_id = active_player_ids[0] if active_player_ids else None
        return contest

    next_player_idx = _get_next_active_player_idx(
        contest,
        start_idx=(contest.current_player_idx + 1) % len(contest.player_order),
    )
    if next_player_idx is None:
        contest.ended = True
        contest.winner_id = active_player_ids[0] if len(active_player_ids) == 1 else None
        return contest

    contest.current_player_idx = next_player_idx
    return contest


def resolve_contest(
    state: GameState,
    *,
    contested_card_id: str | None = None,
    tie_manifest_requests: dict[str, str | dict[str, Any]] | None = None,
    nun_sacrifice_decisions: dict[str, bool] | None = None,
    contest_turn_intents: dict[str, list[dict[str, Any] | str] | dict[str, Any] | str] | None = None,
    prediction_guesses: dict[str, str] | None = None,
    require_explicit_turn_intents: bool = False,
) -> ContestState:
    full_turn_order = _get_cyclic_turn_order(state)
    contest_turn_player_ids = [
        player_id
        for player_id in full_turn_order
        if not state.players[player_id].skip_next_contest
        and len(state.players[player_id].stored_phenomena) < _get_phenomena_slot_limit(state.players[player_id])
    ]
    eligible_player_ids, ineligible_player_ids, effect_blocked_player_ids = _compute_contest_eligibility(
        state,
        full_turn_order,
    )
    resolved_contested_card_id = _resolve_contested_phenomenon_card_id(
        state,
        contested_card_id=contested_card_id,
    )
    if resolved_contested_card_id is None:
        contest = ContestState(
            player_order=[],
            current_player_idx=0,
            start_player_idx=state.start_player_idx,
            current_round=state.round_number,
            contested_card_id=None,
            ended=True,
        )
        return contest

    apply_phenomenon_prediction_bonuses(
        state,
        contested_card_id=resolved_contested_card_id,
        current_round=state.round_number,
        prediction_guesses=prediction_guesses,
    )

    normalized_turn_intents = _normalize_contest_turn_intents(
        state,
        turn_intents=contest_turn_intents,
        allowed_player_ids=eligible_player_ids if len(eligible_player_ids) <= 1 else contest_turn_player_ids,
    )
    turn_intent_positions = {player_id: 0 for player_id in normalized_turn_intents}
    contest_player_order = eligible_player_ids if len(eligible_player_ids) <= 1 else contest_turn_player_ids
    contest = ContestState(
        player_order=list(contest_player_order),
        current_player_idx=0,
        start_player_idx=state.start_player_idx,
        current_round=state.round_number,
        contested_card_id=resolved_contested_card_id,
    )
    start_player_id = full_turn_order[0]

    append_event(
        state.event_log,
        "contest_eligibility_computed",
        start_player_idx=state.start_player_idx,
        current_round=state.round_number,
        contested_card_id=resolved_contested_card_id,
        contest_turn_player_ids=list(contest_turn_player_ids),
        eligible_player_ids=eligible_player_ids,
        ineligible_player_ids=ineligible_player_ids,
        effect_blocked_player_ids=effect_blocked_player_ids,
    )

    for blocked_player_id in effect_blocked_player_ids:
        state.players[blocked_player_id].skip_next_contest = False
    if effect_blocked_player_ids:
        append_event(
            state.event_log,
            "contest_effect_blocks_consumed",
            current_round=state.round_number,
            contested_card_id=resolved_contested_card_id,
            player_ids=effect_blocked_player_ids,
        )

    if not eligible_player_ids:
        score = ContestScore(
            bid_totals={},
            winner_id=None,
            tied_player_ids=[],
            tie_breaker="no_eligible_players",
        )
        append_event(
            state.event_log,
            "contest_no_eligible_resolved",
            start_player_idx=state.start_player_idx,
            current_round=state.round_number,
            contested_card_id=resolved_contested_card_id,
            ineligible_player_ids=ineligible_player_ids,
            winner_id=score.winner_id,
            tied_player_ids=list(score.tied_player_ids),
            tie_breaker=score.tie_breaker,
        )
        append_event(
            state.event_log,
            "contest_skipped_no_eligible_players",
            start_player_idx=state.start_player_idx,
            current_round=state.round_number,
            contested_card_id=resolved_contested_card_id,
            ineligible_player_ids=ineligible_player_ids,
        )
        append_contest_reveal_log(
            state,
            contest_kind="playable_no_eligible",
            current_round=contest.current_round,
            contested_card_id=resolved_contested_card_id,
            score=score,
            nun_sacrifice_player_ids=[],
        )
        outcome_resolution = apply_contest_outcome_resolution(
            state,
            current_round=contest.current_round,
            contested_card_id=resolved_contested_card_id,
            score=score,
            tie_manifest_requests=tie_manifest_requests,
        )
        state.phenomenon_discard.append(resolved_contested_card_id)
        append_event(
            state.event_log,
            "contested_phenomenon_discarded_no_eligible",
            current_round=state.round_number,
            card_id=resolved_contested_card_id,
            ineligible_player_ids=ineligible_player_ids,
            phenomenon_discard_size=len(state.phenomenon_discard),
        )
        contest.ended = True
        contest.winner_id = None
        append_event(
            state.event_log,
            "contest_ended",
            current_round=state.round_number,
            start_player_idx=state.start_player_idx,
            contested_card_id=resolved_contested_card_id,
            winner_id=contest.winner_id,
            winner_idx=state.player_order.index(contest.winner_id) if contest.winner_id is not None else None,
            bid_count=0,
            passed_player_ids=[],
            bid_totals={},
            revealed_bid_totals={},
            hidden_bid_counts={},
            nun_sacrifice_player_ids=[],
            tie_breaker=score.tie_breaker,
            tied_player_ids=list(score.tied_player_ids),
            outcome="no_eligible_players",
            manifestation_player_ids=list(outcome_resolution.manifestation_player_ids),
            baptism_player_ids=list(outcome_resolution.baptism_player_ids),
            phenomenon_discarded_due_to_tie=outcome_resolution.phenomenon_discarded_due_to_tie,
            discarded_phenomenon_card_id=resolved_contested_card_id,
        )
        return contest

    opening_player_id = eligible_player_ids[0]
    opening_player_idx = contest.player_order.index(opening_player_id)
    contest.current_player_idx = opening_player_idx

    append_event(
        state.event_log,
        "contest_started",
        start_player_idx=state.start_player_idx,
        current_round=state.round_number,
        contested_card_id=resolved_contested_card_id,
        start_player_id=start_player_id,
        opening_player_id=opening_player_id,
        turn_order=list(contest.player_order),
    )

    opening_intent = _consume_next_turn_intent(
        player_id=opening_player_id,
        turn_intents=normalized_turn_intents,
        turn_intent_positions=turn_intent_positions,
    )
    opening_options = get_legal_bid_options(state, opening_player_id, contest)
    if opening_intent is not None and opening_intent.action == "pass" and opening_options:
        raise ValueError(f"Opening player {opening_player_id} cannot pass in a phenomenon contest.")
    if require_explicit_turn_intents and opening_intent is None and opening_options:
        raise ValueError(
            f"Opening player {opening_player_id} must provide an explicit contest turn intent when require_explicit_turn_intents is enabled."
        )

    if opening_intent is not None and opening_intent.action == "pass":
        _append_player_pass_event(
            state,
            contest=contest,
            player_id=opening_player_id,
            decision_source="explicit_intent",
        )
    elif opening_intent is None and not opening_options:
        _append_player_pass_event(
            state,
            contest=contest,
            player_id=opening_player_id,
            decision_source="auto_no_bid",
        )
    elif opening_intent is not None:
        normalized_opening_bid = opening_intent.bid_choice or ContestBidChoice()
        _ensure_single_card_turn_bid(player_id=opening_player_id, bid_choice=normalized_opening_bid)
        opening_bid = commit_bid(
            state,
            opening_player_id,
            normalized_opening_bid,
            contest_state=contest,
        )
        opening_decision_source = "explicit_intent"
        _record_committed_bid(contest=contest, committed_bid=opening_bid)
        contest.bid_count = 1
        _log_committed_bid(
            state,
            committed_bid=opening_bid,
            current_round=contest.current_round,
            bid_order=contest.bid_count,
            player_bid_index=sum(1 for bid in contest.played_bids if bid.player_id == opening_bid.player_id),
            decision_source=opening_decision_source,
        )
    else:
        _ensure_single_card_turn_bid(player_id=opening_player_id, bid_choice=opening_options[0])
        opening_bid = commit_bid(
            state,
            opening_player_id,
            opening_options[0],
            contest_state=contest,
        )
        opening_decision_source = "auto_first_option"
        _record_committed_bid(contest=contest, committed_bid=opening_bid)
        contest.bid_count = 1
        _log_committed_bid(
            state,
            committed_bid=opening_bid,
            current_round=contest.current_round,
            bid_order=contest.bid_count,
            player_bid_index=sum(1 for bid in contest.played_bids if bid.player_id == opening_bid.player_id),
            decision_source=opening_decision_source,
        )

    active_player_ids = _get_active_player_ids(contest)
    if len(active_player_ids) <= 1:
        contest.ended = True
        contest.winner_id = active_player_ids[0] if active_player_ids else None
    else:
        next_player_idx = _get_next_active_player_idx(
            contest,
            start_idx=(opening_player_idx + 1) % len(contest.player_order),
        )
        if next_player_idx is not None:
            contest.current_player_idx = next_player_idx

    while not contest.ended:
        step_contest_with_intents(
            state,
            contest,
            turn_intents=normalized_turn_intents,
            turn_intent_positions=turn_intent_positions,
            nun_sacrifice_decisions=nun_sacrifice_decisions,
            require_explicit_turn_intents=require_explicit_turn_intents,
        )

    apply_pure_wrath_contest_discards(
        state,
        committed_bids=contest.played_bids,
        current_round=contest.current_round,
        contested_card_id=resolved_contested_card_id,
        contest=contest,
    )
    score = score_committed_bids(state, contest.played_bids)
    _append_contest_reveal_window_events(
        state,
        contest=contest,
        contested_card_id=resolved_contested_card_id,
    )
    append_contest_reveal_log(
        state,
        contest_kind="playable",
        current_round=contest.current_round,
        contested_card_id=resolved_contested_card_id,
        score=score,
        nun_sacrifice_player_ids=contest.nun_sacrifice_player_ids,
    )
    outcome_resolution = apply_contest_outcome_resolution(
        state,
        current_round=contest.current_round,
        contested_card_id=resolved_contested_card_id,
        score=score,
        tie_manifest_requests=tie_manifest_requests,
    )
    contest.winner_id = score.winner_id
    finalize_committed_bids(state, contest.played_bids)

    append_event(
        state.event_log,
        "contest_ended",
        current_round=state.round_number,
        start_player_idx=state.start_player_idx,
        contested_card_id=resolved_contested_card_id,
        winner_id=contest.winner_id,
        winner_idx=state.player_order.index(contest.winner_id) if contest.winner_id is not None else None,
        bid_count=contest.bid_count,
        passed_player_ids=list(contest.passed_player_ids),
        bid_totals=score.bid_totals,
        nun_sacrifice_player_ids=list(contest.nun_sacrifice_player_ids),
        hidden_bid_counts={player_id: len(bids) for player_id, bids in contest.hidden_bid_buffers.items()},
        revealed_bid_totals=score.bid_totals,
        tie_breaker=score.tie_breaker,
        tied_player_ids=list(score.tied_player_ids),
        outcome=outcome_resolution.outcome,
        manifestation_player_ids=list(outcome_resolution.manifestation_player_ids),
        baptism_player_ids=list(outcome_resolution.baptism_player_ids),
        phenomenon_discarded_due_to_tie=outcome_resolution.phenomenon_discarded_due_to_tie,
        discarded_phenomenon_card_id=outcome_resolution.discarded_phenomenon_card_id,
    )
    return contest


def compute_eligible_players(state: GameState) -> tuple[list[str], list[str]]:
    eligible_player_ids, ineligible_player_ids, _ = _compute_contest_eligibility(
        state,
        _get_cyclic_turn_order(state),
    )
    return eligible_player_ids, ineligible_player_ids


def _log_committed_bid(
    state: GameState,
    *,
    committed_bid: CommittedContestBid,
    current_round: int,
    bid_order: int,
    player_bid_index: int,
    decision_source: str | None = None,
) -> None:
    bid_card, category = _get_primary_bid_card(committed_bid)
    forced_first_bid_revealed = (
        player_bid_index == 1
        and _player_has_active_enlightener_rule_text(
            state,
            player_id=committed_bid.player_id,
            text=ENLIGHTENER_FORCE_FIRST_CONTEST_CARD_OPEN_TEXT,
        )
    )
    forced_truth_values = set(
        int(value)
        for value in state.players[committed_bid.player_id].commandment_state.forced_revealed_truth_values
    )
    forced_truth_revealed = any(int(value) in forced_truth_values for value in committed_bid.truth_values)
    forced_revealed = forced_first_bid_revealed or forced_truth_revealed
    committed_bid.is_open = forced_revealed
    committed_bid.bid_order = bid_order
    committed_bid.player_bid_index = player_bid_index

    card_id = bid_card.card_id if (forced_revealed and bid_card is not None) else None
    category_value = category if forced_revealed else None
    effective_truth_value = committed_bid.bid_total if forced_revealed else None
    append_event(
        state.event_log,
        "bid_placed",
        player_id=committed_bid.player_id,
        card_id=card_id,
        category=category_value,
        bid_order=bid_order,
        player_bid_index=player_bid_index,
        forced_revealed=forced_revealed,
        is_open=forced_revealed,
        current_round=current_round,
        effective_truth_value=effective_truth_value,
        decision_source=decision_source,
    )
    if forced_first_bid_revealed and bid_card is not None:
        append_event(
            state.event_log,
            "contest_forced_first_bid_revealed",
            player_id=committed_bid.player_id,
            card_id=bid_card.card_id,
            category=category,
            current_round=current_round,
            bid_order=bid_order,
            player_bid_index=player_bid_index,
            effective_truth_value=committed_bid.bid_total,
        )


def _append_contest_reveal_window_events(
    state: GameState,
    *,
    contest: ContestState,
    contested_card_id: str | None,
) -> None:
    append_event(
        state.event_log,
        "contest_reveal_started",
        current_round=contest.current_round,
        contested_card_id=contested_card_id,
        bid_count=contest.bid_count,
    )

    for committed_bid in contest.played_bids:
        bid_card, category = _get_primary_bid_card(committed_bid)
        append_event(
            state.event_log,
            "contest_bid_revealed",
            current_round=contest.current_round,
            contested_card_id=contested_card_id,
            player_id=committed_bid.player_id,
            bid_order=committed_bid.bid_order,
            player_bid_index=committed_bid.player_bid_index,
            card_id=bid_card.card_id if bid_card is not None else None,
            category=category,
            effective_truth_value=committed_bid.bid_total,
            original_truth_value=(
                bid_card.truth_value if bid_card is not None and category == TRUTH_CATEGORY else None
            ),
            was_open_before_reveal=committed_bid.is_open,
        )
        committed_bid.is_open = True

    append_event(
        state.event_log,
        "contest_reveal_completed",
        current_round=contest.current_round,
        contested_card_id=contested_card_id,
        revealed_bid_count=len(contest.played_bids),
    )


def _get_primary_bid_card(committed_bid: CommittedContestBid) -> tuple[CardRef | None, str | None]:
    if committed_bid.heavenly_cards:
        return committed_bid.heavenly_cards[0], committed_bid.heavenly_cards[0].category
    if committed_bid.truth_cards:
        return committed_bid.truth_cards[0], TRUTH_CATEGORY
    return None, None


def _get_cyclic_turn_order(state: GameState) -> list[str]:
    player_count = len(state.player_order)
    return [
        state.player_order[(state.start_player_idx + offset) % player_count]
        for offset in range(player_count)
    ]


def _resolve_contested_phenomenon_card_id(
    state: GameState,
    *,
    contested_card_id: str | None,
) -> str | None:
    _sync_known_phenomena_from_draw_pile(state)

    if contested_card_id is not None:
        for index, card in enumerate(state.phenomenon_draw_pile):
            if card.card_id != contested_card_id:
                continue
            selected_alignment = card.metadata.get("alignment")
            if not isinstance(selected_alignment, str):
                raise ValueError(
                    f"Contest requires phenomenon {contested_card_id} to have alignment metadata."
                )
            selected_card = state.phenomenon_draw_pile.pop(index)
            _register_known_phenomenon_card(state, selected_card)
            append_event(
                state.event_log,
                "phenomenon_selected_for_contest",
                current_round=state.round_number,
                selection_source="explicit_id_draw_pile",
                card_id=selected_card.card_id,
                card_name=selected_card.name,
                phenomenon_alignment=selected_alignment,
                phenomenon_draw_pile_size=len(state.phenomenon_draw_pile),
            )
            return contested_card_id

        known_record = get_known_phenomenon_record(state, contested_card_id)
        if known_record is None:
            raise ValueError(
                f"Contest requires phenomenon {contested_card_id} to be known and have alignment metadata or provide explicit alignment metadata."
            )
        known_alignment = known_record.get("alignment")
        if not isinstance(known_alignment, str):
            raise ValueError(
                f"Contest requires phenomenon {contested_card_id} to be known and have alignment metadata or provide explicit alignment metadata."
            )
        append_event(
            state.event_log,
            "phenomenon_selected_for_contest",
            current_round=state.round_number,
            selection_source="explicit_id_known_metadata",
            card_id=contested_card_id,
            card_name=known_record.get("name"),
            phenomenon_alignment=known_alignment,
            phenomenon_draw_pile_size=len(state.phenomenon_draw_pile),
        )
        return contested_card_id

    if not state.phenomenon_draw_pile:
        illegal_code = ILLEGAL_STATE_NO_PHENOMENON_AVAILABLE_FOR_CONTEST
        state.illegal_states.append(illegal_code)
        append_event(
            state.event_log,
            illegal_code,
            current_round=state.round_number,
            phenomenon_draw_pile_size=0,
        )
        append_event(
            state.event_log,
            "contest_skipped_no_phenomenon_available",
            current_round=state.round_number,
            phenomenon_draw_pile_size=0,
        )
        return None

    revealed_card = state.phenomenon_draw_pile[0]
    revealed_alignment = revealed_card.metadata.get("alignment")
    if not isinstance(revealed_alignment, str):
        raise ValueError(f"Contest requires phenomenon {revealed_card.card_id} to have alignment metadata.")
    revealed_card = state.phenomenon_draw_pile.pop(0)
    _register_known_phenomenon_card(state, revealed_card)
    append_event(
        state.event_log,
        "phenomenon_drawn_for_contest",
        current_round=state.round_number,
        card_id=revealed_card.card_id,
        card_name=revealed_card.name,
        phenomenon_alignment=revealed_alignment,
        phenomenon_draw_pile_size=len(state.phenomenon_draw_pile),
    )
    return revealed_card.card_id


def _compute_contest_eligibility(
    state: GameState,
    player_order: list[str],
) -> tuple[list[str], list[str], list[str]]:
    eligible_player_ids: list[str] = []
    ineligible_player_ids: list[str] = []
    effect_blocked_player_ids: list[str] = []

    for player_id in player_order:
        player = state.players[player_id]
        if player.skip_next_contest:
            ineligible_player_ids.append(player_id)
            effect_blocked_player_ids.append(player_id)
            continue
        if len(player.stored_phenomena) >= _get_phenomena_slot_limit(player):
            ineligible_player_ids.append(player_id)
            continue
        if not get_bid_options(state, player_id):
            ineligible_player_ids.append(player_id)
            continue
        eligible_player_ids.append(player_id)

    return eligible_player_ids, ineligible_player_ids, effect_blocked_player_ids


def _get_phenomena_slot_limit(player: PlayerState) -> int:
    return 3 if player.alignment == "<Zorn>" else 2


def _get_active_player_ids(contest: ContestState) -> list[str]:
    return [
        player_id
        for player_id in contest.player_order
        if not _player_has_passed(contest, player_id)
    ]


def _get_next_active_player_idx(contest: ContestState, *, start_idx: int) -> int | None:
    for offset in range(len(contest.player_order)):
        candidate_idx = (start_idx + offset) % len(contest.player_order)
        candidate_player_id = contest.player_order[candidate_idx]
        if not _player_has_passed(contest, candidate_player_id):
            return candidate_idx
    return None


def _append_player_pass_event(
    state: GameState,
    *,
    contest: ContestState,
    player_id: str,
    decision_source: str,
) -> None:
    if not _player_has_passed(contest, player_id):
        contest.passed_players.add(player_id)
        contest.passed_player_ids.append(player_id)
        contest.total_pass_count += 1
    if player_id not in contest.pass_order_by_player:
        contest.pass_order_by_player[player_id] = contest.total_pass_count
    append_event(
        state.event_log,
        "player_passed",
        player_id=player_id,
        current_round=contest.current_round,
        pass_order=contest.pass_order_by_player[player_id],
        remaining_active_player_ids=_get_active_player_ids(contest),
        decision_source=decision_source,
    )


def _player_has_passed(contest: ContestState, player_id: str) -> bool:
    return player_id in contest.passed_players or player_id in contest.passed_player_ids


def _maybe_run_nuns_check_window(
    state: GameState,
    *,
    contest: ContestState,
    nun_sacrifice_decisions: dict[str, bool] | None,
) -> None:
    pass_threshold = max(1, len(contest.player_order) - 1)
    if contest.nuns_used or contest.total_pass_count < pass_threshold:
        return

    applied_player_ids = apply_nun_sacrifice_modifiers(
        state,
        contest.played_bids,
        player_order=list(contest.player_order),
        current_round=contest.current_round,
        nun_sacrifice_decisions=nun_sacrifice_decisions,
    )
    for player_id in applied_player_ids:
        if player_id not in contest.nun_sacrifice_player_ids:
            contest.nun_sacrifice_player_ids.append(player_id)

    contest.nuns_used = True


def _record_committed_bid(
    *,
    contest: ContestState,
    committed_bid: CommittedContestBid,
) -> None:
    contest.played_bids.append(committed_bid)
    contest.hidden_bid_buffers.setdefault(committed_bid.player_id, []).append(committed_bid)


def _ensure_single_card_turn_bid(
    *,
    player_id: str,
    bid_choice: ContestBidChoice,
) -> None:
    card_count = len(bid_choice.truth_card_ids) + len(bid_choice.heavenly_card_ids)
    if card_count != 1:
        raise ValueError(
            f"Playable contest requires exactly one card per bid turn; player {player_id} provided {card_count}."
        )


def _consume_next_turn_intent(
    *,
    player_id: str,
    turn_intents: dict[str, list[ContestTurnIntent]] | None,
    turn_intent_positions: dict[str, int] | None,
) -> ContestTurnIntent | None:
    if turn_intents is None or turn_intent_positions is None:
        return None
    player_intents = turn_intents.get(player_id)
    if not player_intents:
        return None

    position = turn_intent_positions.get(player_id, 0)
    if position >= len(player_intents):
        return None

    turn_intent_positions[player_id] = position + 1
    return player_intents[position]


def _normalize_contest_turn_intents(
    state: GameState,
    *,
    turn_intents: dict[str, list[dict[str, Any] | str] | dict[str, Any] | str] | None,
    allowed_player_ids: list[str],
) -> dict[str, list[ContestTurnIntent]]:
    if turn_intents is None:
        return {}

    normalized_turn_intents: dict[str, list[ContestTurnIntent]] = {}
    allowed_player_id_set = set(allowed_player_ids)

    for player_id, raw_player_intents in turn_intents.items():
        if player_id not in state.players:
            raise ValueError(f"Unknown player in contest_turn_intents: {player_id}.")
        if player_id not in allowed_player_id_set:
            raise ValueError(f"Player {player_id} cannot submit contest turn intents for this contest.")

        raw_intent_list = raw_player_intents if isinstance(raw_player_intents, list) else [raw_player_intents]
        normalized_turn_intents[player_id] = [
            _normalize_single_turn_intent(player_id=player_id, raw_intent=raw_intent)
            for raw_intent in raw_intent_list
        ]

    return normalized_turn_intents


def _normalize_single_turn_intent(
    *,
    player_id: str,
    raw_intent: dict[str, Any] | str,
) -> ContestTurnIntent:
    if isinstance(raw_intent, str):
        action = raw_intent
        payload: dict[str, Any] = {}
    elif isinstance(raw_intent, dict):
        action = raw_intent.get("action")
        payload = raw_intent
    else:
        raise ValueError(f"Contest turn intent for player {player_id} must be a dict or string.")

    if action not in {"bid", "pass"}:
        raise ValueError(f"Contest turn intent for player {player_id} must use action 'bid' or 'pass'.")

    if action == "pass":
        return ContestTurnIntent(action="pass")

    raw_bid_choice = _extract_turn_bid_choice_payload(
        player_id=player_id,
        payload=payload,
    )
    if raw_bid_choice is None:
        raise ValueError(f"Contest turn bid intent for player {player_id} requires a bid_choice payload.")

    return ContestTurnIntent(
        action="bid",
        bid_choice=normalize_bid_choice(raw_bid_choice),
    )


def _extract_turn_bid_choice_payload(
    *,
    player_id: str,
    payload: dict[str, Any],
) -> ContestBidChoice | dict[str, Any] | list[int] | None:
    raw_bid_choice = payload.get("bid_choice", payload.get("bid"))
    supported_flat_keys = ("truth", "truth_card_ids", "heavenly_card_ids")
    flat_bid_choice_payload = {
        key: payload[key]
        for key in supported_flat_keys
        if key in payload
    }

    if raw_bid_choice is None:
        return flat_bid_choice_payload or None

    if not flat_bid_choice_payload:
        return raw_bid_choice

    if not isinstance(raw_bid_choice, dict):
        raise ValueError(
            f"Contest turn bid intent for player {player_id} cannot combine flat bid keys with non-dict bid_choice payload."
        )

    merged_bid_choice = dict(raw_bid_choice)
    for key, value in flat_bid_choice_payload.items():
        if key in merged_bid_choice and merged_bid_choice[key] != value:
            raise ValueError(
                f"Contest turn bid intent for player {player_id} has conflicting values for {key!r}."
            )
        merged_bid_choice[key] = value
    return merged_bid_choice


def _normalize_single_manifest_request(
    *,
    player_id: str,
    raw_request: bool | str | dict[str, Any],
) -> tuple[bool, str | None]:
    if isinstance(raw_request, bool):
        if raw_request:
            raise ValueError(
                f"Manifest request for player {player_id} must specify manifest_body_part_category."
            )
        return False, None

    if isinstance(raw_request, str):
        return True, raw_request

    if not isinstance(raw_request, dict):
        raise ValueError(
            f"Manifest request for player {player_id} must be a boolean, body-part string, or dict payload."
        )

    requested = raw_request.get("requested", True)
    if not isinstance(requested, bool):
        raise ValueError(f"Manifest request for player {player_id} must use a boolean 'requested' field.")

    body_part_category = raw_request.get("body_part_category")
    if body_part_category is not None and not isinstance(body_part_category, str):
        raise ValueError(f"Manifest request for player {player_id} must use a string body_part_category.")
    if body_part_category is not None and not requested:
        raise ValueError(
            f"Manifest request for player {player_id} cannot specify body_part_category while requested is false."
        )

    return requested, body_part_category


def _normalize_prediction_guesses(
    state: GameState,
    *,
    prediction_guesses: dict[str, str] | None,
) -> dict[str, str]:
    if prediction_guesses is None:
        return {}
    if not isinstance(prediction_guesses, dict):
        raise ValueError("prediction_guesses must be a dict when provided.")

    normalized_guesses: dict[str, str] = {}
    allowed_alignments = {"<Zorn>", "<Chaos>", "<Sanftmut>", "<Unergründlich>"}
    for player_id, guessed_alignment in prediction_guesses.items():
        if player_id not in state.players:
            raise ValueError(f"Unknown player in prediction_guesses: {player_id}.")
        if not isinstance(guessed_alignment, str):
            raise ValueError(f"Prediction guess for player {player_id} must be a string alignment.")
        normalized_alignment = guessed_alignment.strip()
        if normalized_alignment not in allowed_alignments:
            raise ValueError(
                f"Prediction guess for player {player_id} must be one of {sorted(allowed_alignments)}."
            )
        normalized_guesses[player_id] = normalized_alignment
    return normalized_guesses


def _get_contest_card_limit(player: PlayerState) -> int:
    max_cards = player.commandment_state.max_cards_per_contest
    if max_cards is None:
        return 1_000_000
    return max(0, int(max_cards))


def _count_cards_in_bid_choice(bid_choice: ContestBidChoice) -> int:
    truth_card_count = len(bid_choice.truth_card_ids) or len(bid_choice.truth_values)
    return truth_card_count + len(bid_choice.heavenly_card_ids)


def _get_player_committed_contest_card_count(
    contest_state: ContestState | None,
    *,
    player_id: str,
) -> int:
    if contest_state is None:
        return 0
    total = 0
    for committed_bid in contest_state.played_bids:
        if committed_bid.player_id != player_id:
            continue
        total += len(committed_bid.truth_cards) + len(committed_bid.heavenly_cards)
    return total


def _validate_contest_card_limit(
    player: PlayerState,
    *,
    bid_choice: ContestBidChoice,
    existing_card_count: int = 0,
) -> None:
    max_cards = player.commandment_state.max_cards_per_contest
    if max_cards is None:
        return

    total_card_count = max(0, int(existing_card_count)) + _count_cards_in_bid_choice(bid_choice)
    if total_card_count > int(max_cards):
        raise ValueError(
            f"Player {player.player_id} cannot contribute more than {max_cards} cards to a contest."
        )


def _validate_bid_choice_structure(*, player_id: str, bid_choice: ContestBidChoice) -> None:
    if not bid_choice.truth_card_ids and not bid_choice.heavenly_card_ids:
        raise ValueError(f"Player {player_id} must bid at least 1 contest card.")
    if bid_choice.truth_values and not bid_choice.truth_card_ids:
        raise ValueError(
            f"Player {player_id} must bid truth via truth_card_ids from hand_cards, not raw truth values."
        )
    if bid_choice.truth_values and bid_choice.truth_card_ids:
        raise ValueError(
            f"Player {player_id} cannot mix raw truth values with truth_card_ids in the same bid."
        )

    duplicate_cross_bucket_ids = sorted(
        set(bid_choice.truth_card_ids).intersection(bid_choice.heavenly_card_ids)
    )
    if duplicate_cross_bucket_ids:
        duplicated_card_id = duplicate_cross_bucket_ids[0]
        raise ValueError(
            f"Player {player_id} cannot bid card {duplicated_card_id} in multiple contest buckets."
        )

    duplicate_truth_ids = sorted(
        card_id
        for card_id, count in Counter(bid_choice.truth_card_ids).items()
        if count > 1
    )
    if duplicate_truth_ids:
        duplicated_card_id = duplicate_truth_ids[0]
        raise ValueError(
            f"Player {player_id} cannot bid duplicate truth card {duplicated_card_id} in the same contest bid."
        )

    duplicate_heavenly_ids = sorted(
        card_id
        for card_id, count in Counter(bid_choice.heavenly_card_ids).items()
        if count > 1
    )
    if duplicate_heavenly_ids:
        duplicated_card_id = duplicate_heavenly_ids[0]
        raise ValueError(
            f"Player {player_id} cannot bid duplicate heavenly card {duplicated_card_id} in the same contest bid."
        )


def _can_apply_nun_sacrifice(state: GameState, *, player_id: str) -> bool:
    player = state.players[player_id]
    assigned_nuns = max(0, int(player.assigned_role_meeples.get("Nonnen", 0)))
    if (
        not player.nunnery_state.active
        or player.nunnery_state.prepared_nuns <= 0
        or assigned_nuns <= 0
    ):
        return False
    if "Nonnen" in player.commandment_state.inactive_role_types:
        return False
    if "Nonnen" in player.commandment_state.contest_disabled_role_types:
        return False
    return True


def _sacrifice_prepared_nuns(player: PlayerState, amount: int) -> None:
    if amount < 0:
        raise ValueError("Cannot sacrifice a negative number of prepared nuns.")
    prepared_nuns = max(0, int(player.nunnery_state.prepared_nuns))
    assigned_nuns = max(0, int(player.assigned_role_meeples.get("Nonnen", 0)))
    if amount > prepared_nuns or amount > assigned_nuns:
        raise ValueError(
            f"Cannot sacrifice {amount} prepared nun(s); "
            f"only {prepared_nuns} prepared and {assigned_nuns} assigned."
        )
    player.nunnery_state.prepared_nuns = prepared_nuns - amount
    player.nunnery_state.sacrificed_nuns += amount
    player.assigned_role_meeples["Nonnen"] = assigned_nuns - amount


def _get_lowest_truth_bid_entry(
    committed_bids: list[CommittedContestBid],
    *,
    player_id: str,
) -> tuple[CommittedContestBid, CardRef, int] | None:
    lowest_entry: tuple[CommittedContestBid, CardRef, int] | None = None

    for committed_bid in committed_bids:
        if committed_bid.player_id != player_id or not committed_bid.truth_cards:
            continue

        for truth_card, truth_value in zip(committed_bid.truth_cards, committed_bid.truth_values, strict=True):
            if lowest_entry is None or truth_value < lowest_entry[2]:
                lowest_entry = (committed_bid, truth_card, truth_value)

    return lowest_entry


def _calculate_bid_totals(committed_bids: list[CommittedContestBid]) -> dict[str, int]:
    bid_totals: dict[str, int] = {}
    for committed_bid in committed_bids:
        bid_totals.setdefault(committed_bid.player_id, 0)
        bid_totals[committed_bid.player_id] += committed_bid.bid_total
    return bid_totals


def _validate_truth_bid_cards(
    state: GameState,
    *,
    player_id: str,
    bid_choice: ContestBidChoice,
    contest_state: ContestState | None = None,
) -> None:
    if not bid_choice.truth_card_ids:
        return

    player = state.players[player_id]
    _validate_selected_hand_card_ids(player, card_ids=bid_choice.truth_card_ids)
    _validate_cards_not_already_committed(
        contest_state,
        player_id=player_id,
        card_ids=bid_choice.truth_card_ids,
    )

    for truth_card_id in bid_choice.truth_card_ids:
        truth_card = _get_card_from_hand(player, card_id=truth_card_id)
        if truth_card.category != TRUTH_CATEGORY:
            raise ValueError(f"Card {truth_card_id} is not a truth card.")

    requested_truth_values = [
        _get_truth_card_pool_value(_get_card_from_hand(player, card_id=truth_card_id))
        for truth_card_id in bid_choice.truth_card_ids
    ]
    requested_counter = Counter(requested_truth_values)
    available_counter = Counter(int(value) for value in player.truth_pool)
    for truth_value, requested_count in requested_counter.items():
        if available_counter[truth_value] < requested_count:
            raise ValueError(
                f"Player {player_id} cannot bid truth value {truth_value}; value is not available in truth_pool."
            )


def _validate_heavenly_bid_cards(
    player: PlayerState,
    *,
    bid_choice: ContestBidChoice,
    contest_state: ContestState | None = None,
) -> None:
    if not bid_choice.heavenly_card_ids:
        return

    _validate_selected_hand_card_ids(player, card_ids=bid_choice.heavenly_card_ids)
    _validate_cards_not_already_committed(
        contest_state,
        player_id=player.player_id,
        card_ids=bid_choice.heavenly_card_ids,
    )

    for heavenly_card_id in bid_choice.heavenly_card_ids:
        heavenly_card = _get_card_from_hand(player, card_id=heavenly_card_id)
        if heavenly_card.category not in HEAVENLY_BIDDABLE_CATEGORIES:
            raise ValueError(f"Card {heavenly_card_id} is not a biddable heavenly card.")


def _validate_selected_hand_card_ids(player: PlayerState, *, card_ids: list[str]) -> None:
    selected_card_counter = Counter(card_ids)
    hand_card_counter = Counter(card.card_id for card in player.hand_cards)
    invalid_card_ids = [
        card_id
        for card_id, count in selected_card_counter.items()
        if hand_card_counter[card_id] < count
    ]
    if invalid_card_ids:
        missing_card_id = sorted(invalid_card_ids)[0]
        raise ValueError(f"Player {player.player_id} does not have card {missing_card_id} in hand.")


def _get_player_committed_contest_card_ids(
    contest_state: ContestState | None,
    *,
    player_id: str,
) -> set[str]:
    if contest_state is None:
        return set()
    committed_card_ids: set[str] = set()
    for committed_bid in contest_state.played_bids:
        if committed_bid.player_id != player_id:
            continue
        committed_card_ids.update(card.card_id for card in committed_bid.truth_cards)
        committed_card_ids.update(card.card_id for card in committed_bid.heavenly_cards)
    return committed_card_ids


def _validate_cards_not_already_committed(
    contest_state: ContestState | None,
    *,
    player_id: str,
    card_ids: list[str],
) -> None:
    if not card_ids or contest_state is None:
        return
    committed_card_ids = _get_player_committed_contest_card_ids(contest_state, player_id=player_id)
    duplicate_committed_ids = sorted(card_id for card_id in card_ids if card_id in committed_card_ids)
    if duplicate_committed_ids:
        duplicated_card_id = duplicate_committed_ids[0]
        raise ValueError(
            f"Player {player_id} cannot reuse already committed contest card {duplicated_card_id}."
        )


def _get_card_from_hand(player: PlayerState, *, card_id: str) -> CardRef:
    for card in player.hand_cards:
        if card.card_id == card_id:
            return card
    raise ValueError(f"Player {player.player_id} does not have card {card_id} in hand.")


def _pop_card_from_hand(player: PlayerState, *, card_id: str) -> CardRef:
    for index, card in enumerate(player.hand_cards):
        if card.card_id == card_id:
            return player.hand_cards.pop(index)
    raise ValueError(f"Player {player.player_id} does not have card {card_id} in hand.")


def _consume_truth_value(
    state: GameState,
    *,
    player_id: str,
    truth_value: int,
    card_id: str | None = None,
) -> GameState:
    player = state.players[player_id]
    if truth_value not in player.truth_pool:
        raise ValueError(
            f"Player {player_id} cannot consume truth value {truth_value} from card {card_id}; value is not available in truth_pool."
        )

    player.truth_pool.remove(truth_value)
    player.used_truth.append(truth_value)
    player.truth_pool.sort()
    player.used_truth.sort()
    append_event(state.event_log, "truth_used", player_id=player_id, value=truth_value)
    return state


def _append_truth_discard_card(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
    counts_as_used_truth: bool = True,
) -> None:
    card.metadata["counts_as_used_truth"] = bool(counts_as_used_truth)
    state.players[player_id].truth_discard.append(card)
    state.truth_discard.append(card)


def _truth_discard_card_counts_as_used_truth(card: CardRef) -> bool:
    return bool(card.metadata.get("counts_as_used_truth", True))


def _maybe_reset_truth_after_exhaustion(state: GameState, *, player_id: str) -> GameState:
    player = state.players[player_id]
    if player.truth_pool:
        return state
    if not player.used_truth:
        return state

    discarded_card_id_set = {discarded_card.card_id for discarded_card in player.truth_discard}
    restored_truth_values = [
        _get_truth_card_pool_value(discarded_card)
        for discarded_card in player.truth_discard
        if not _truth_discard_card_counts_as_used_truth(discarded_card)
    ]
    restored_truth_card_ids = [discarded_card.card_id for discarded_card in player.truth_discard]
    if discarded_card_id_set:
        state.truth_discard = [
            discarded_card
            for discarded_card in state.truth_discard
            if discarded_card.card_id not in discarded_card_id_set
        ]
    player.truth_discard.clear()
    player.truth_pool.extend(player.used_truth)
    player.truth_pool.extend(restored_truth_values)
    player.used_truth.clear()
    player.truth_pool.sort()
    append_event(
        state.event_log,
        "truth_reset",
        player_id=player_id,
        truth_pool=list(player.truth_pool),
        restored_truth_card_ids=restored_truth_card_ids,
    )
    return state


def _break_contest_tie(
    state: GameState,
    player_ids: list[str],
    *,
    committed_bids: list[CommittedContestBid],
) -> tuple[str, str]:
    if len(player_ids) == 1:
        return player_ids[0], "highest_bid_total"

    fewest_believers = min(_count_total_believers(state.players[player_id]) for player_id in player_ids)
    tied_on_believers = [
        player_id
        for player_id in player_ids
        if _count_total_believers(state.players[player_id]) == fewest_believers
    ]
    if len(tied_on_believers) == 1:
        return tied_on_believers[0], "fewest_believers"

    tied_player_id_set = set(tied_on_believers)
    latest_contribution = max(
        (
            (
                committed_bid.bid_order if committed_bid.bid_order > 0 else list_index + 1,
                list_index,
                committed_bid.player_id,
            )
            for list_index, committed_bid in enumerate(committed_bids)
            if committed_bid.player_id in tied_player_id_set
        ),
        default=None,
    )
    if latest_contribution is None:
        raise ValueError("Contest tie-break requires a card contribution from every tied player.")
    return latest_contribution[2], "last_card_contributor"


def _get_effective_bid_truth_value(state: GameState, *, player_id: str, card: CardRef) -> int:
    if card.category == TRUTH_CATEGORY:
        truth_value = _get_truth_card_pool_value(card)
        if truth_value in {6, 7} and _player_has_active_enlightener_rule_text(
            state,
            player_id=player_id,
            text=ENLIGHTENER_TRUTH_SIX_SEVEN_ZERO_TEXT,
        ):
            truth_value = 0
        truth_value += _get_empty_nun_temple_truth_bonus(state, player_id=player_id)
        return truth_value

    if card.category == "Heiliges Heer":
        base_truth = 1 if _player_has_defined_legs(state.players[player_id]) else 3
    elif card.category in HEAVENLY_BIDDABLE_CATEGORIES:
        base_truth = 1
    else:
        base_truth = card.truth_value or 0

    if state.players[player_id].commandment_state.heavenly_cards_zero_truth:
        return 0
    return base_truth


def _get_truth_card_pool_value(card: CardRef) -> int:
    if card.truth_value is not None:
        return card.truth_value
    return _extract_first_integer(card.name) or _extract_first_integer(card.card_id) or 0


def _player_has_defined_body(player: PlayerState) -> bool:
    body_parts_present = {card.category for card in player.tableau}
    return {
        "Körperteil Kopf",
        "Körperteil Brust",
        "Körperteil Beine",
    }.issubset(body_parts_present)


def _player_has_defined_chest(player: PlayerState) -> bool:
    return any(card.category == "Körperteil Brust" for card in player.tableau)


def _player_has_defined_legs(player: PlayerState) -> bool:
    return any(card.category == "Körperteil Beine" for card in player.tableau)


def _get_empty_nun_temple_truth_bonus(state: GameState, *, player_id: str) -> int:
    if not _is_nun_temple_empty(state, player_id=player_id):
        return 0
    return _count_active_relic_rule_text(
        state,
        player_id=player_id,
        text=RELIC_EMPTY_NUN_TEMPLE_TRUTH_BONUS_TEXT,
    )


def _is_nun_temple_empty(state: GameState, *, player_id: str) -> bool:
    player = state.players[player_id]
    assigned_nuns = max(0, player.assigned_role_meeples.get("Nonnen", 0))
    return assigned_nuns == 0 and player.nunnery_state.prepared_nuns == 0


def _count_active_relic_rule_text(state: GameState, *, player_id: str, text: str) -> int:
    if _player_has_active_enlightener_rule_text(
        state,
        player_id=player_id,
        text=ENLIGHTENER_DISABLES_RELICS_TEXT,
    ):
        return 0

    count = 0
    for card in state.players[player_id].tableau:
        if card.category != "Reliquie":
            continue
        if is_tableau_card_disabled(state, player_id=player_id, card=card):
            continue
        if text in _get_card_rules_text(card):
            count += 1
    return count


def _player_has_active_relic_rule_text(state: GameState, *, player_id: str, text: str) -> bool:
    return _count_active_relic_rule_text(state, player_id=player_id, text=text) > 0


def _player_has_active_enlightener_rule_text(state: GameState, *, player_id: str, text: str) -> bool:
    for card in state.players[player_id].tableau:
        if card.category != "Aufklärer":
            continue
        if is_tableau_card_disabled(state, player_id=player_id, card=card):
            continue
        if text in _get_card_rules_text(card):
            return True
    return False


def _get_card_rules_text(card: CardRef) -> str:
    metadata_rules_text = card.metadata.get("rules_text")
    if isinstance(metadata_rules_text, str) and metadata_rules_text:
        return metadata_rules_text
    record = get_card_record(card.card_id)
    if isinstance(record, dict):
        record_rules_text = record.get("rules_text")
        if isinstance(record_rules_text, str) and record_rules_text:
            return record_rules_text
    return ""


def _extract_first_integer(value: str) -> int | None:
    match = re.search(r"(\d+)", value)
    return int(match.group(1)) if match else None
