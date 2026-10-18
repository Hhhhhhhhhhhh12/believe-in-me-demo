from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


STARTING_TRUTH_POOL = [2, 2, 2, 3, 3, 4, 5, 6, 7]
MANIFEST_ALIGNMENT_KEYS = ("<Chaos>", "<Sanftmut>", "<Zorn>")
BODY_PART_CATEGORY_TO_NAME = {
    "Körperteil Kopf": "Kopf",
    "Körperteil Brust": "Brust",
    "Körperteil Beine": "Beine",
}
TRINITY_BODY_PARTS = frozenset(BODY_PART_CATEGORY_TO_NAME.values())
GAME_FORMAT_FFA = "ffa"
GAME_FORMAT_TEAM_2V2 = "team_2v2"
SUPPORTED_GAME_FORMATS = frozenset({GAME_FORMAT_FFA, GAME_FORMAT_TEAM_2V2})


def default_manifested_parts_counts() -> dict[str, int]:
    return {alignment: 0 for alignment in MANIFEST_ALIGNMENT_KEYS}


def normalize_manifested_parts_counts(player: "PlayerState") -> dict[str, int]:
    return {
        alignment: max(0, int(player.manifested_parts_counts.get(alignment, 0) or 0))
        for alignment in MANIFEST_ALIGNMENT_KEYS
    }


def get_pure_alignment(player: "PlayerState") -> str | None:
    manifested_counts = normalize_manifested_parts_counts(player)
    total_manifested_parts = sum(manifested_counts.values())
    trinity_part_count = len(TRINITY_BODY_PARTS)
    if total_manifested_parts < trinity_part_count:
        return None
    if all(manifested_counts[alignment] > 0 for alignment in MANIFEST_ALIGNMENT_KEYS):
        return "<Unergründlich>"
    for alignment in MANIFEST_ALIGNMENT_KEYS:
        if manifested_counts[alignment] >= trinity_part_count and all(
            manifested_counts[other_alignment] == 0
            for other_alignment in MANIFEST_ALIGNMENT_KEYS
            if other_alignment != alignment
        ):
            return alignment
    return None


def is_pure_alignment(player: "PlayerState", alignment: str) -> bool:
    return get_pure_alignment(player) == alignment


@dataclass(slots=True)
class CardRef:
    card_id: str
    name: str
    category: str
    truth_value: int | None = None
    tier_effects: dict[int, dict[str, Any]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class HandGrenadeState:
    draft_options: list[CardRef] = field(default_factory=list)
    grenade: CardRef | None = None
    meeples_committed: int = 0
    used: bool = False
    detonated_tier: int | None = None


@dataclass(slots=True)
class NunneryState:
    active: bool = False
    prepared_nuns: int = 0
    sacrificed_nuns: int = 0


@dataclass(slots=True)
class CommandmentState:
    base_hand_limit: int = 6
    effective_hand_limit: int = 6
    blocked_card_categories: list[str] = field(default_factory=list)
    disabled_tableau_categories: list[str] = field(default_factory=list)
    inactive_role_types: list[str] = field(default_factory=list)
    contest_disabled_role_types: list[str] = field(default_factory=list)
    zero_cost_card_categories: list[str] = field(default_factory=list)
    forced_revealed_truth_values: list[int] = field(default_factory=list)
    heavenly_cards_zero_truth: bool = False
    contest_truth_card_value_modifier_per_card: int = 0
    max_cards_per_contest: int | None = None
    global_sacrifice_cost_modifier: int = 0
    category_cost_modifiers: dict[str, int] = field(default_factory=dict)
    role_production_modifiers: dict[str, int] = field(default_factory=dict)
    turn_start_missionary_steal: int = 0
    active_effect_sources: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PlayerState:
    player_id: str
    alignment: str | None = "<Unergründlich>"
    god_revealed: bool = False
    meeples: int = 10
    truth_pool: list[int] = field(default_factory=lambda: list(STARTING_TRUTH_POOL))
    used_truth: list[int] = field(default_factory=list)
    truth_discard: list[CardRef] = field(default_factory=list)
    hand_cards: list[CardRef] = field(default_factory=list)
    tableau: list[CardRef] = field(default_factory=list)
    assigned_role_meeples: dict[str, int] = field(default_factory=dict)
    tracked_role_card_counts: dict[str, int] = field(default_factory=dict)
    stored_phenomena: list[str] = field(default_factory=list)
    used_phenomenon_powers: list[str] = field(default_factory=list)
    heavenly_hand_discard_tally: int = 0
    bonus_actions_this_turn: int = 0
    stored_monument_bonus_actions: int = 0
    next_turn_action_modifier: int = 0
    skip_next_turn: bool = False
    skip_next_contest: bool = False
    phenomena_slots: int = 2
    monks_slots: int = 3
    missionaries_slots: int = 2
    nuns_slots: int = 1
    forge_slots: int = 3
    prophet_owner: bool = False
    missionaries_ready_from_round: int | None = None
    nunnery_state: NunneryState = field(default_factory=NunneryState)
    hand_grenade_state: HandGrenadeState = field(default_factory=HandGrenadeState)
    commandment_state: CommandmentState = field(default_factory=CommandmentState)
    temporary_draw_hand_limit_override: int | None = None
    body_parts: set[str] = field(default_factory=set)
    manifested_parts_counts: dict[str, int] = field(default_factory=default_manifested_parts_counts)

    @property
    def manifested_parts(self) -> dict[str, int]:
        # Backward-compatible alias; canonical field is manifested_parts_counts.
        return self.manifested_parts_counts

    @manifested_parts.setter
    def manifested_parts(self, value: dict[str, int]) -> None:
        self.manifested_parts_counts = dict(value)


def has_complete_trinity(player: PlayerState) -> bool:
    normalized_body_parts = {part for part in player.body_parts if part in TRINITY_BODY_PARTS}
    for card in player.tableau:
        body_part_name = BODY_PART_CATEGORY_TO_NAME.get(card.category)
        if body_part_name is not None:
            normalized_body_parts.add(body_part_name)
    return TRINITY_BODY_PARTS.issubset(normalized_body_parts)


@dataclass(slots=True)
class GameState:
    players: dict[str, PlayerState]
    player_order: list[str]
    game_format: str = GAME_FORMAT_FFA
    beginner_mode: bool = False
    team_by_player_id: dict[str, str] = field(default_factory=dict)
    seed: int | None = None
    require_explicit_action_intents: bool = True
    require_explicit_contest_turn_intents: bool = True
    start_player_idx: int = 0
    current_player_index: int = 0
    round_number: int = 1
    claim_round_number: int | None = None
    turn_number: int = 1
    game_over: bool = False
    game_over_reason: str | None = None
    endgame_active: bool = False
    endgame_rounds_left: int | None = None
    first_trinity_trigger_round: int | None = None
    endgame_triggered_by_player: str | None = None
    gods_twilight_triggered: bool = False
    gods_twilight_trigger_round: int | None = None
    remaining_final_rounds: int | None = None
    nunnery_active: bool = False
    first_phenomenon_claimed: bool = False
    active_commandments: list[CardRef] = field(default_factory=list)
    commandment_draw_pile: list[CardRef] = field(default_factory=list)
    commandment_discard_pile: list[CardRef] = field(default_factory=list)
    pending_commandment_for_player_id: str | None = None
    known_phenomena: dict[str, dict[str, Any]] = field(default_factory=dict)
    heavenly_draw_pile: list[CardRef] = field(default_factory=list)
    heavenly_discard_pile: list[CardRef] = field(default_factory=list)
    phenomenon_draw_pile: list[CardRef] = field(default_factory=list)
    monument_draw_pile: list[CardRef] = field(default_factory=list)
    active_monument_group_keys: list[str] = field(default_factory=list)
    removed_monument_group_keys: list[str] = field(default_factory=list)
    body_part_draw_pile: list[CardRef] = field(default_factory=list)
    body_part_discard_pile: list[CardRef] = field(default_factory=list)
    hand_grenade_draft_pool: list[CardRef] = field(default_factory=list)
    hand_grenade_draft_next_player_index: int = 0
    truth_discard: list[CardRef] = field(default_factory=list)
    phenomenon_discard: list[str] = field(default_factory=list)
    last_meeple_taker_by_victim: dict[str, str] = field(default_factory=dict)
    illegal_states: list[str] = field(default_factory=list)
    event_log: list[dict[str, Any]] = field(default_factory=list)
    validation_cursor: int = 0
    max_total_believers_seen: int = 0


def build_team_assignment(*, game_format: str, player_order: list[str]) -> dict[str, str]:
    if game_format == GAME_FORMAT_FFA:
        return {}
    if game_format != GAME_FORMAT_TEAM_2V2:
        raise ValueError(f"Unsupported game format: {game_format!r}.")
    if len(player_order) != 4:
        raise ValueError("team_2v2 requires exactly four players.")
    return {
        player_id: "team_a" if order_index % 2 == 0 else "team_b"
        for order_index, player_id in enumerate(player_order)
    }


def get_player_team_id(state: GameState, *, player_id: str) -> str | None:
    team_id = state.team_by_player_id.get(player_id)
    return str(team_id) if isinstance(team_id, str) and team_id else None


def get_player_relation(state: GameState, *, source_player_id: str, target_player_id: str) -> str:
    if source_player_id == target_player_id:
        return "self"
    source_team_id = get_player_team_id(state, player_id=source_player_id)
    target_team_id = get_player_team_id(state, player_id=target_player_id)
    if source_team_id is not None and source_team_id == target_team_id:
        return "teammate"
    return "opponent"


def get_teammate_player_ids(state: GameState, *, player_id: str) -> list[str]:
    return [
        candidate_player_id
        for candidate_player_id in state.player_order
        if get_player_relation(
            state,
            source_player_id=player_id,
            target_player_id=candidate_player_id,
        ) == "teammate"
    ]


def get_opponent_player_ids(state: GameState, *, player_id: str) -> list[str]:
    return [
        candidate_player_id
        for candidate_player_id in state.player_order
        if get_player_relation(
            state,
            source_player_id=player_id,
            target_player_id=candidate_player_id,
        ) == "opponent"
    ]
