from __future__ import annotations

import copy
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .catalog import get_card_alignment, get_card_record
from .game_modes import beginner_card_allowed, require_beginner_phenomenon_payload
from .cards import (
    build_default_body_part_draw_pile,
    build_default_commandment_draw_pile,
    build_default_heavenly_draw_pile as build_modeled_heavenly_draw_pile,
    build_default_monument_draw_pile,
    build_default_phenomenon_draw_pile,
    make_heavenly_card,
    make_truth_card,
)
from .commandments import (
    can_use_role_in_contest,
    get_role_production_modifier,
    get_additional_cost_for_card,
    get_turn_start_missionary_steal,
    is_card_cost_waived,
    is_card_play_blocked,
    is_role_active,
    is_tableau_card_disabled,
    recalculate_commandment_effects,
)
from .constants import (
    ALLOWED_PHENOMENON_REMOVAL_REASONS,
    ILLEGAL_STATE_CLAIM_WITHOUT_FREE_SLOT,
    ILLEGAL_STATE_CONTEST_ACTION_BY_INELIGIBLE_PLAYER,
    ILLEGAL_STATE_DOUBLE_MANIFESTATION,
    ILLEGAL_STATE_DRAW_STEP_DREW_AT_OR_ABOVE_HAND_LIMIT,
    ILLEGAL_STATE_DUPLICATE_BODY_PART_MANIFEST,
    ILLEGAL_STATE_ALIGNMENT_INCONSISTENCY,
    ILLEGAL_STATE_INVALID_ROLE_STATE,
    ILLEGAL_STATE_INVALID_STORED_PHENOMENON_REMOVAL_REASON,
    ILLEGAL_STATE_MULTIPLE_CLAIMS_SAME_ROUND,
    ILLEGAL_STATE_PHENOMENA_SLOT_OVERFILL,
    ILLEGAL_STATE_ROLE_SLOT_OVERFILL,
    ILLEGAL_STATE_TRUTH_USED_OUTSIDE_CONTEST,
    PHENOMENON_REMOVAL_REASON_ACTION_PLAYED,
    PHENOMENON_REMOVAL_REASON_SLOT_LOSS,
    PHENOMENON_REMOVAL_SOURCE_ALIGNMENT_CHANGE,
    PHENOMENON_REMOVAL_SOURCE_STATE_VALIDATION,
)
from .contest import (
    ContestBidChoice,
    ContestState,
    apply_pure_wrath_contest_discards,
    apply_phenomenon_prediction_bonuses,
    apply_contest_outcome_resolution,
    apply_nun_sacrifice_modifiers,
    append_contest_reveal_log,
    commit_bid as commit_contest_bid,
    compute_eligible_players,
    finalize_committed_bids,
    get_bid_options,
    must_bid_before_pass,
    estimate_bid_choice_total,
    get_phenomenon_believer_reward,
    get_known_phenomenon_alignment,
    get_known_phenomenon_record,
    normalize_manifest_requests,
    normalize_bid_choice,
    register_known_phenomenon_metadata,
    resolve_contested_phenomenon_card_id,
    score_committed_bids,
    validate_bid_choice as validate_contest_bid_choice,
)
from .logging import append_event
from .phenomena import play_stored_phenomenon_action
from .rng import SeededRNG
from .state import (
    GAME_FORMAT_FFA,
    GAME_FORMAT_TEAM_2V2,
    MANIFEST_ALIGNMENT_KEYS,
    CardRef,
    GameState,
    PlayerState,
    build_team_assignment,
    get_opponent_player_ids,
    get_player_relation,
    get_player_team_id,
    get_pure_alignment,
    has_complete_trinity as player_has_complete_trinity,
    is_pure_alignment,
)


DEFAULT_BOT_NAMES = ("Erik", "Cornel", "Henneke", "Otto")
DEFAULT_PLAYER_IDS = DEFAULT_BOT_NAMES
FIVE_PLAYER_GRENADE_OPTION_COUNTS = (2, 3, 4, 5, 5)


def _has_pure_alignment(player: PlayerState, alignment: str) -> bool:
    return player.alignment == alignment and is_pure_alignment(player, alignment)


def _player_has_friedrich_alignment_override(state: GameState, *, player_id: str) -> bool:
    return _player_has_active_enlightener_rule_text(
        state,
        player_id=player_id,
        text=ENLIGHTENER_SET_ALIGNMENT_UNERGRUENDLICH_TEXT,
    )


def _apply_friedrich_alignment_override_if_active(state: GameState, *, player_id: str) -> None:
    if not _player_has_friedrich_alignment_override(state, player_id=player_id):
        return
    player = state.players[player_id]
    expected_nuns_slots = 2 if state.gods_twilight_triggered else 1
    if player.alignment == "<Unergründlich>" and player.nuns_slots == expected_nuns_slots:
        return
    apply_alignment_change(state, player_id=player_id, new_alignment="<Unergründlich>")


def _is_player_immune_to_missionizing(state: GameState, *, player_id: str) -> bool:
    return _has_pure_alignment(state.players[player_id], "<Sanftmut>")
ACTION_PLAYABLE_HAND_CATEGORIES = {"Aufklärer", "Heiliges Heer", "Reliquie", "Segen"}
SUPPORTED_BLESSING_CARD_NAMES = {
    "Gloria",
    "Klagelied",
    "Huldigung",
    "Loblied",
    "Wahrsagung",
    "Mantra 01",
    "Mantra 02",
    "Mantra 03",
    "Preisung 01",
    "Preisung 02",
    "Preisung 03",
}
SUPPORTED_BLESSING_NAME_PREFIXES = (
    "Mantra",
    "Preisung",
)
ROLE_TYPES = ("Mönche", "Missionare", "Nonnen")
ACTION_ROLE_TYPES = ("Missionare", "Nonnen")
VALIDATION_CONTEST_CLOSE_EVENTS = {
    "contest_ended",
    "contest_resolved",
    "contest_skipped_no_phenomenon_available",
    "contest_no_eligible_resolved",
}
VALIDATION_PHASE_BOUNDARY_EVENTS = {
    "player_turn_started",
    "player_turn_completed",
    "round_started",
    "round_completed",
}
MANIFESTABLE_BODY_PART_CATEGORIES = {
    "Körperteil Kopf": "Kopf",
    "Körperteil Brust": "Brust",
    "Körperteil Beine": "Beine",
}
BODY_PART_NAME_TO_CATEGORY = {name: category for category, name in MANIFESTABLE_BODY_PART_CATEGORIES.items()}
BODY_PART_BASELINE_ORDER = ("Kopf", "Brust", "Beine")
FINAL_SCORING_BODY_PART_CATEGORIES = (
    "Körperteil Kopf",
    "Körperteil Brust",
    "Körperteil Beine",
)
MONUMENT_GROUP_KEY_METADATA = "monument_group_key"
MONUMENT_STARTER_PLAYER_ID_METADATA = "monument_started_by_player_id"
MONUMENT_COMPLETION_BLOCKED_METADATA = "monument_completion_blocked"
ROLE_BASE_PRODUCTION = {
    "Mönche": 1,
}
STARTING_HAND_SIZE = 6
STARTING_TRUTH_CARD_COUNT = 2
STARTING_HEAVENLY_CARD_COUNT = 4
MAX_STARTING_TRUTH_CARDS = STARTING_TRUTH_CARD_COUNT
MAX_ACTIVE_COMMANDMENTS = 5
HAND_CARD_BASE_INTRINSIC_COSTS = {
    "Aufklärer": 2,
    "Reliquie": 2,
}
ENLIGHTENER_BLOCKS_MONUMENTS_TEXT = "Ab sofort: Du darfst keine Monumente mehr bauen."
ENLIGHTENER_BLOCKS_RELICS_TEXT = "Ab sofort: Du darfst keine neuen Reliquien"
ENLIGHTENER_REDUCES_HAND_LIMIT_TEXT = "Ab sofort: Dein Handkartenlimit ist um 1 reduziert."
ENLIGHTENER_DISABLES_RELICS_TEXT = "Ab sofort: Deine Reliquien verlieren"
ENLIGHTENER_SACRIFICE_TWO_TEXT = "Beim Abhandeln: Du musst 2 <CULTISTS> opfern."
ENLIGHTENER_RIGHT_PLAYER_MISSIONIZES_TWO_TEXT = "Beim Abhandeln: Dein rechter Mitgott missioniert"
ENLIGHTENER_LEFT_PLAYER_MISSIONIZES_TWO_TEXT = "Beim Abhandeln: Dein linker Mitgott missioniert"
ENLIGHTENER_OPPONENT_DISCARDS_OWNER_HAND_CARD_TEXT = (
    "Beim Abhandeln: Ein Mitgott deiner Wahl legt 1 deiner Handkarten ungesehen auf den entsprechenden Ablagestapel."
)
ENLIGHTENER_FORCE_FIRST_CONTEST_CARD_OPEN_TEXT = "Ab sofort: Du musst deine erste Karte beim Stechen offen auslegen."
ENLIGHTENER_RETURN_ONE_TEMPLE_MEEPLE_TEXT = "Beim Abhandeln: Du musst 1 <CULTISTS> aus einem deiner TEMPEL zurück"
ENLIGHTENER_SET_ALIGNMENT_UNERGRUENDLICH_TEXT = "Ab sofort: Deine Gesinnung ist unergründlich."
ENLIGHTENER_TRUTH_SIX_SEVEN_ZERO_TEXT = 'Ab sofort: Deine "Wahrheitskarte 6" und "Wahrheitskarte 7" zählen 0 Wahrheit'
ENLIGHTENER_CANNOT_REFILL_TEMPLES_TEXT = "Ab sofort: Du kannst deine Tempel nicht weiter auffüllen."
ENLIGHTENER_PHENOMENON_UNLEASH_COST_TEXT = (
    "Ab sofort: Um ein angelegtes Phänomen"
)
ENLIGHTENER_STORED_POWER_UNLEASH_COST_TEXT = "Ab sofort: Um ein angelegtes Phänomen"
RELIC_WAIVES_HOLY_ARMY_COST_TEXT = "Du musst keine Opferkosten für Heiliges Heer entrichten."
RELIC_WAIVES_ENLIGHTENER_COST_TEXT = "Du musst keine Opferkosten zahlen, um einen Aufklärer auszuspielen."
RELIC_EXTRA_DRAW_TEXT = "Du darfst ab jetzt 1 Handkarte mehr nachziehen"
RELIC_INCREASES_HAND_LIMIT_TEXT = "Dein Handkartenlimit ist um 1 erhöht."
RELIC_BLESSING_BAPTISM_TEXT = "Immer wenn du einen Segen spielst: Taufe 2 <CULTISTS>"
RELIC_MONK_PRODUCTION_TEXT = "Dein Mönchs-Tempel tauft 2 <CULTISTS> mehr"
RELIC_REDUCES_SACRIFICE_COST_TEXT = "Deine Opferkosten verringern sich permanent um 1 <CULTISTS>"
RELIC_REDUCES_SACRIFICE_COST_VARIANT_TEXT = "Ab sofort: Deine Opferkosten verringern sich um 1 <CULTISTS>"
RELIC_EMPTY_NUN_TEMPLE_TRUTH_BONUS_TEXT = (
    "Jede deiner Wahrheitskarten zählt 1 Punkt mehr, solange dein Nonnen-Tempel keine Nonnen beherbergt."
)
RELIC_RECOVER_HEAVENLY_FROM_DISCARD_TEXT = (
    "Du darfst den Himmelreichskarten-Ablagestapel durchsuchen und 1 Karte auf die Hand nehmen."
)
RELIC_RECOVER_TOP_HEAVENLY_FROM_DISCARD_TEXT = (
    "Du darfst die oberste Karte des Himmelreichskarten-Ablagestapel auf die Hand nehmen."
)
RELIC_RECOVER_SHUFFLED_TOP_THREE_HEAVENLY_FROM_DISCARD_TEXT = (
    "Mische den allgemeinen Ablagestapel, sieh dir die obersten 2 Karten an und nimm eine davon auf die Hand."
)
RELIC_SWAP_HEAVENLY_HAND_CARDS_TEXT = "Wirf 0-2 Himmelreichskarten ab und ziehe genauso viele nach."
RELIC_MISSIONIZE_PER_AFFECTING_COMMANDMENT_TEXT = (
    "Missioniere für jedes ausgelegte Gebot, das dich betrifft, 1 <CULTISTS> von einem Mitgott"
)
RELIC_OPPONENT_CHOICE_DISCARD_OR_BAPTISM_TEXT = (
    "Ein Mitgott muss wählen: Er wirft 1 Himmelreichskarte ab oder"
)
RELIC_MISSIONIZE_ON_OPPONENT_LARGE_SACRIFICE_TEXT = (
    "Jedesmal wenn ein Mitgott 3 <CULTISTS> oder mehr auf einmal opfert, darfst du 1 <CULTISTS> davon missionieren"
)
RELIC_IMMUNE_NEXT_ENLIGHTENER_TEXT = (
    "Du bist immun gegen den nächsten Aufklärer (Lege danach die Reliquie ab)"
)
RELIC_IMMUNE_NEXT_ENLIGHTENER_BEFORE_PLACEMENT_TEXT = (
    "Du bist immun gegen den nächsten Aufklärer bevor er angelegt wird. (Lege danach die Reliquie ab)"
)
RELIC_DISCARD_NEXT_INCOMING_ENLIGHTENER_TEXT = (
    "Der nächste Aufklärer, der an dein Göttertableau gelegt werden soll, "
    "wird stattdessen abgelegt. (Lege danach die RELIQUIE ab)"
)
RELIC_PREDICT_NEXT_PHENOMENON_ALIGNMENT_TEXT = (
    "Du darfst vor dem Aufdecken eines Phänomens die Gesinnung vorhersagen. "
    "Liegst du richtig, darfst du 2 <CULTISTS> taufen"
)
RELIC_BUILD_TWO_MONUMENTS_ACTION_PREFIX_TEXT = 'Du darfst in deiner Aktion "Monumente"'
RELIC_BUILD_TWO_MONUMENTS_ACTION_FINAL_PREFIX_TEXT = 'Du darfst in deiner Aktion "Monumente bauen"'
RELIC_TEMPLES_CANNOT_LOSE_ROLE_MEEPLES_TEXT = "Deine Tempel können weder Mönche, Missionare noch Nonnen verlieren."
RELIC_DRAW_TRUTH_AFTER_THREE_HAND_DISCARDS_TEXT = (
    "Wenn du 3 Himmelreichskarten ablegst, darfst du 1 Wahrheitskarte ziehen."
)
RELIC_DRAW_TRUTH_AFTER_THREE_HAND_DISCARDS_VARIANT_TEXT = (
    "Wenn du 3 Himmelreichskarten ablegst, darfst du eine Wahrheitskarte ziehen."
)
PHENOMENON_EFFECT_GAIN_MEEPLES = {
    "gute-ernte__Phänomene__1": 8,
}
PHENOMENON_EFFECT_DESTROY_RELIC_OR_SHATTER_COMMANDMENT = {
    "fata-morgana__Phänomene__1",
    "erdbeben__Phänomene__1",
    "vulkanausbruch__Phänomene__1",
}
PHENOMENON_EFFECT_NEXT_CONTEST_BLOCK = {
    "hungersnot__Phänomene__1",
}
PHENOMENON_EFFECT_NEXT_TURN_SKIP = {
    "yak-mit-2-koepfen__Phänomene__1",
}
PHENOMENON_EFFECT_NEXT_TURN_ACTION_PENALTY = {
    "waldbrand__Phänomene__1",
}
SUPPORTED_STORED_POWER_PHENOMENA = frozenset(
    set(PHENOMENON_EFFECT_GAIN_MEEPLES)
    | PHENOMENON_EFFECT_DESTROY_RELIC_OR_SHATTER_COMMANDMENT
    | PHENOMENON_EFFECT_NEXT_CONTEST_BLOCK
    | PHENOMENON_EFFECT_NEXT_TURN_SKIP
    | PHENOMENON_EFFECT_NEXT_TURN_ACTION_PENALTY
    | {
        "kometeneinschlag__Phänomene__1",
        "nordlichter__Phänomene__1",
        "eichhoernchenplage__Phänomene__1",
        "froschregen__Phänomene__1",
        "kornkreise__Phänomene__1",
        "kugelblitz__Phänomene__1",
        "mondfinsternis__Phänomene__1",
        "pest__Phänomene__1",
        "sonnenfinsternis__Phänomene__1",
        "tornado__Phänomene__1",
        "tsunami__Phänomene__1",
    }
)
HAND_GRENADE_TIER_EFFECTS: dict[str, dict[int, dict[str, Any]]] = {
    "heilige-handgranate-der-kalten-rache__Heilige Handgranate__1": {
        1: {"effect": "forced_total_sacrifice", "label": "Insgesamt 3 opfern", "total_sacrifice": 3},
        2: {"effect": "forced_total_sacrifice", "label": "Insgesamt 5 opfern", "total_sacrifice": 5},
        3: {"effect": "forced_total_sacrifice", "label": "Insgesamt 8 opfern", "total_sacrifice": 8},
    },
    "heilige-handgranate-des-verschlagenen-laechelns__Heilige Handgranate__1": {
        1: {"effect": "forced_temple_role_wipe", "label": "Alle Mönche opfern", "role_types": ("Mönche",)},
        2: {
            "effect": "forced_temple_role_wipe",
            "label": "Alle Mönche und Missionare opfern",
            "role_types": ("Mönche", "Missionare"),
        },
        3: {
            "effect": "forced_temple_role_wipe",
            "label": "Alle Tempelrollen opfern",
            "role_types": ("Mönche", "Missionare", "Nonnen"),
        },
    },
    "heilige-handgranate-des-boesartigen-kicherns__Heilige Handgranate__1": {
        1: {"effect": "destroy_stored_phenomena", "label": "1 Phänomen zerstören", "count": 1, "same_owner_only": True},
        2: {"effect": "destroy_stored_phenomena", "label": "2 Phänomene zerstören", "count": 2, "same_owner_only": True},
        3: {"effect": "destroy_stored_phenomena", "label": "2 Phänomene beliebig zerstören", "count": 2, "same_owner_only": False},
    },
    "heilige-handgranate-der-froehlichen-vergeltung__Heilige Handgranate__1": {
        1: {"effect": "shatter_commandments", "label": "1 Gebot zerschmettern", "count": 1, "award_prophet": False},
        2: {"effect": "shatter_commandments", "label": "2 Gebote zerschmettern", "count": 2, "award_prophet": False},
        # Keep the legacy flag for saved grenades; tier 3 plays the Prophet, rather than awarding it.
        3: {"effect": "shatter_commandments", "label": "1 Gebot + Prophet spielen", "count": 1, "award_prophet": True},
    },
    "heilige-handgranate-der-netten-abrechnung__Heilige Handgranate__1": {
        1: {"effect": "destroy_relics", "label": "1 Reliquie zerstören", "count": 1, "same_owner_only": True},
        2: {"effect": "destroy_relics", "label": "2 Reliquien zerstören", "count": 2, "same_owner_only": True},
        3: {"effect": "destroy_relics", "label": "2 Reliquien beliebig zerstören", "count": 2, "same_owner_only": False},
    },
    "heilige-handgranate-des-durchtriebenen-plans__Heilige Handgranate__1": {
        1: {
            "effect": "next_turn_action_penalty",
            "label": "Nächsten Zug -1 Aktion",
            "penalty": 1,
            "bonus_actions_granted": 0,
            "skip_next_turn": False,
        },
        2: {
            "effect": "next_turn_action_penalty",
            "label": "Nächsten Zug -1 Aktion, jetzt +1 Aktion",
            "penalty": 1,
            "bonus_actions_granted": 1,
            "skip_next_turn": False,
        },
        3: {
            "effect": "next_turn_action_penalty",
            "label": "Nächsten Zug aussetzen",
            "penalty": 0,
            "bonus_actions_granted": 0,
            "skip_next_turn": True,
        },
    },
    "heilige-handgranate-der-gerechten-strafe__Heilige Handgranate__1": {
        1: {"effect": "discard_truth", "label": "1 Truth abwerfen", "count": 1, "discard_all": False},
        2: {"effect": "discard_truth", "label": "2 Truth abwerfen", "count": 2, "discard_all": False},
        3: {"effect": "discard_truth", "label": "Alle Truth abwerfen", "count": None, "discard_all": True},
    },
    "heilige-handgranate-der-vorhersehbaren-list__Heilige Handgranate__1": {
        1: {"effect": "discard_heavenly", "label": "2 Himmelreichskarten abwerfen", "count": 2, "distributed": False},
        2: {"effect": "discard_heavenly", "label": "3 Himmelreichskarten abwerfen", "count": 3, "distributed": False},
        3: {"effect": "discard_heavenly", "label": "Insgesamt 5 Himmelreichskarten abwerfen", "count": 5, "distributed": True},
    },
    "heilige-handgranate-des-tueckischen-taeuschens__Heilige Handgranate__1": {
        1: {
            "effect": "play_free_enlighteners",
            "label": "1 Aufklärer kostenlos anlegen",
            "count": 1,
            "require_overwrite": False,
            "distributed": False,
        },
        2: {
            "effect": "play_free_enlighteners",
            "label": "1 Aufklärer kostenlos überschreiben",
            "count": 1,
            "require_overwrite": True,
            "distributed": False,
        },
        3: {
            "effect": "play_free_enlighteners",
            "label": "2 Aufklärer kostenlos überschreiben",
            "count": 2,
            "require_overwrite": True,
            "distributed": True,
        },
    },
}
HAND_GRENADE_NAMES: dict[str, str] = {
    "heilige-handgranate-der-kalten-rache__Heilige Handgranate__1": "Heilige Handgranate der kalten Rache",
    "heilige-handgranate-des-verschlagenen-laechelns__Heilige Handgranate__1": "Heilige Handgranate des verschlagenen Lächelns",
    "heilige-handgranate-des-boesartigen-kicherns__Heilige Handgranate__1": "Heilige Handgranate des bösartigen Kicherns",
    "heilige-handgranate-der-froehlichen-vergeltung__Heilige Handgranate__1": "Heilige Handgranate der fröhlichen Vergeltung",
    "heilige-handgranate-der-netten-abrechnung__Heilige Handgranate__1": "Heilige Handgranate der netten Abrechnung",
    "heilige-handgranate-des-durchtriebenen-plans__Heilige Handgranate__1": "Heilige Handgranate des durchtriebenen Plans",
    "heilige-handgranate-der-gerechten-strafe__Heilige Handgranate__1": "Heilige Handgranate der gerechten Strafe",
    "heilige-handgranate-der-vorhersehbaren-list__Heilige Handgranate__1": "Heilige Handgranate der vorhersehbaren List",
    "heilige-handgranate-des-tueckischen-taeuschens__Heilige Handgranate__1": "Heilige Handgranate des tückischen Täuschens",
}
TABLEAU_RESOLUTION_PRIORITIES = {
    "Aufklärer": 10,
    "Gesinnung": 20,
    "Mönche": 30,
    "Missionare": 40,
    "Reliquie": 50,
}
MONUMENT_GROUP_SUFFIX_PATTERN = re.compile(r"-(\d{2})$")


def _endgame_rounds_after_first_trinity(state: GameState) -> int:
    return 4 if len(state.player_order) >= 4 else 3


def _sync_remaining_final_rounds_with_endgame(state: GameState) -> GameState:
    if not state.endgame_active:
        return state
    if state.endgame_rounds_left is None:
        state.endgame_rounds_left = _endgame_rounds_after_first_trinity(state)
    state.remaining_final_rounds = state.endgame_rounds_left
    return state


def _start_endgame_countdown(
    state: GameState,
    *,
    trigger_player_id: str,
    trigger_source: str,
) -> GameState:
    if state.endgame_active:
        return _sync_remaining_final_rounds_with_endgame(state)

    state.endgame_active = True
    state.endgame_rounds_left = _endgame_rounds_after_first_trinity(state)
    state.first_trinity_trigger_round = state.round_number
    state.endgame_triggered_by_player = trigger_player_id
    _sync_remaining_final_rounds_with_endgame(state)
    append_event(
        state.event_log,
        "endgame_started",
        trigger_source=trigger_source,
        trigger_round=state.round_number,
        player_id=trigger_player_id,
        endgame_rounds_left=state.endgame_rounds_left,
    )
    return state


def build_default_heavenly_draw_pile() -> list[CardRef]:
    modeled_draw_pile = build_modeled_heavenly_draw_pile()
    if modeled_draw_pile:
        return modeled_draw_pile

    card_specs = (
        ("Segen", "Segen"),
        ("Aufklärer", "Aufklärer"),
        ("Reliquie", "Reliquie"),
        ("Heiliges Heer", "Heiliges Heer"),
    )
    draw_pile: list[CardRef] = []

    for category_index, (category, name_prefix) in enumerate(card_specs, start=1):
        for copy_index in range(1, 7):
            draw_pile.append(
                make_heavenly_card(
                    card_id=f"stub-{category_index}-{copy_index}__{category}__1",
                    name=f"{name_prefix} {copy_index}",
                    category=category,
                )
            )

    return draw_pile


def build_hand_grenade_card(card_id: str) -> CardRef:
    if card_id not in HAND_GRENADE_TIER_EFFECTS:
        raise ValueError(f"Unknown hand grenade card_id: {card_id}")
    return CardRef(
        card_id=card_id,
        name=HAND_GRENADE_NAMES[card_id],
        category="Heilige Handgranate",
        tier_effects={tier: dict(spec) for tier, spec in HAND_GRENADE_TIER_EFFECTS[card_id].items()},
    )


def build_default_hand_grenades() -> list[CardRef]:
    return [build_hand_grenade_card(card_id) for card_id in HAND_GRENADE_TIER_EFFECTS]


def create_game(
    player_ids: list[str] | None = None,
    *,
    seed: int | None = None,
    starting_meeples: int = 10,
    auto_pick_grenade: bool = True,
    deal_starting_hands: bool = False,
    starting_truth_choices: dict[str, list[int]] | None = None,
    require_explicit_action_intents: bool = True,
    require_explicit_contest_turn_intents: bool = True,
    game_format: str = GAME_FORMAT_FFA,
    beginner_mode: bool = False,
) -> GameState:
    ordered_player_ids = list(player_ids or DEFAULT_PLAYER_IDS)
    team_by_player_id = build_team_assignment(
        game_format=game_format,
        player_order=ordered_player_ids,
    )
    players = {
        player_id: PlayerState(player_id=player_id, meeples=starting_meeples)
        for player_id in ordered_player_ids
    }
    state = GameState(
        players=players,
        player_order=ordered_player_ids,
        game_format=game_format,
        team_by_player_id=team_by_player_id,
        beginner_mode=beginner_mode,
        seed=seed,
        require_explicit_action_intents=require_explicit_action_intents,
        require_explicit_contest_turn_intents=require_explicit_contest_turn_intents,
    )
    state.max_total_believers_seen = _count_total_believers_in_game(state)
    setup_heavenly_draw_pile(state, seed=seed)
    setup_commandment_draw_pile(state, seed=seed)
    setup_phenomenon_draw_pile(state, seed=seed)
    setup_monument_draw_pile(state, seed=seed)
    setup_body_part_draw_pile(state, seed=seed)
    setup_hand_grenade_draft(state, seed=seed, auto_pick=auto_pick_grenade)
    if deal_starting_hands:
        setup_starting_hands(state, starting_truth_choices=starting_truth_choices)
    return state


def _opening_pile_shuffle_seed(*, seed: int | None, pile_name: str) -> int | str | None:
    # Keep the existing seed space stable while remapping the pathological Seed 1
    # opener for the heavenly draw pile to a healthier deterministic order.
    if seed == 1 and pile_name == "heavenly_draw_pile":
        return "heavenly-draw-pile|seed=1|v2"
    return seed


def _count_total_believers_in_game(state: GameState) -> int:
    total = 0
    for player in state.players.values():
        total += max(0, int(player.meeples))
        total += sum(max(0, int(amount)) for amount in player.assigned_role_meeples.values())
        total += max(0, int(player.nunnery_state.prepared_nuns))
    return total


def _count_payable_meeples(player: PlayerState) -> int:
    return (
        max(0, int(player.meeples))
        + sum(max(0, int(amount)) for amount in player.assigned_role_meeples.values())
        + max(0, int(player.nunnery_state.prepared_nuns))
    )


def setup_heavenly_draw_pile(state: GameState, *, seed: int | None = None) -> GameState:
    rng = SeededRNG(seed=_opening_pile_shuffle_seed(seed=seed, pile_name="heavenly_draw_pile"))
    cards = build_default_heavenly_draw_pile()
    if state.beginner_mode:
        cards = [card for card in cards if beginner_card_allowed(card.card_id)]
    state.heavenly_draw_pile = rng.shuffle(cards)
    append_event(
        state.event_log,
        "heavenly_draw_pile_initialized",
        deck_size=len(state.heavenly_draw_pile),
    )
    return state


def setup_commandment_draw_pile(state: GameState, *, seed: int | None = None) -> GameState:
    rng = SeededRNG(seed=seed)
    state.commandment_draw_pile = [] if state.beginner_mode else rng.shuffle(build_default_commandment_draw_pile())
    append_event(
        state.event_log,
        "commandment_draw_pile_initialized",
        deck_size=len(state.commandment_draw_pile),
    )
    return state


def setup_body_part_draw_pile(state: GameState, *, seed: int | None = None) -> GameState:
    rng = SeededRNG(seed=seed)
    state.body_part_draw_pile = rng.shuffle(build_default_body_part_draw_pile())
    append_event(
        state.event_log,
        "body_part_draw_pile_initialized",
        deck_size=len(state.body_part_draw_pile),
    )
    return state


def setup_phenomenon_draw_pile(state: GameState, *, seed: int | None = None) -> GameState:
    rng = SeededRNG(seed=seed)
    state.phenomenon_draw_pile = rng.shuffle(build_default_phenomenon_draw_pile())
    append_event(
        state.event_log,
        "phenomenon_draw_pile_initialized",
        deck_size=len(state.phenomenon_draw_pile),
    )
    return state


def setup_monument_draw_pile(state: GameState, *, seed: int | None = None) -> GameState:
    rng = SeededRNG(seed=seed)
    full_monument_draw_pile = build_default_monument_draw_pile()
    all_group_keys = list(
        dict.fromkeys(
            _monument_group_key_from_card_id(card.card_id)
            for card in full_monument_draw_pile
        )
    )
    active_group_limit = min(len(all_group_keys), len(state.player_order) + 1)
    shuffled_group_keys = rng.shuffle(list(all_group_keys))
    active_group_keys = sorted(shuffled_group_keys[:active_group_limit])
    if state.beginner_mode:
        active_group_keys = sorted({
            _monument_group_key_from_card_id(card.card_id)
            for card in full_monument_draw_pile
            if beginner_card_allowed(card.card_id)
        })
    active_group_key_set = set(active_group_keys)
    removed_group_keys = sorted(group_key for group_key in all_group_keys if group_key not in active_group_key_set)

    filtered_monument_draw_pile = [
        card
        for card in full_monument_draw_pile
        if _monument_group_key_from_card_id(card.card_id) in active_group_key_set
    ]
    state.monument_draw_pile = rng.shuffle(filtered_monument_draw_pile)
    state.active_monument_group_keys = active_group_keys
    state.removed_monument_group_keys = removed_group_keys
    append_event(
        state.event_log,
        "monument_draw_pile_initialized",
        deck_size=len(state.monument_draw_pile),
        active_group_count=len(active_group_keys),
        active_group_keys=active_group_keys,
        removed_group_keys=removed_group_keys,
    )
    return state


def setup_starting_hands(
    state: GameState,
    *,
    starting_truth_choices: dict[str, list[int]] | None = None,
) -> GameState:
    truth_choices = (
        {player_id: [2, 2] for player_id in state.player_order}
        if starting_truth_choices is None
        else starting_truth_choices
    )

    for player_id in state.player_order:
        selected_truth_values = list(truth_choices.get(player_id, []))
        if len(selected_truth_values) != STARTING_TRUTH_CARD_COUNT:
            raise ValueError(
                f"Player {player_id} must start with exactly {STARTING_TRUTH_CARD_COUNT} truth cards."
            )

        prepared_truth_cards = _add_truth_cards_to_hand(
            state,
            player_id=player_id,
            truth_values=selected_truth_values,
            source="starting_hand",
        )
        drawn_cards = _draw_to_hand_limit(
            state,
            player_id=player_id,
            cards_needed=STARTING_HEAVENLY_CARD_COUNT,
        )
        if len(drawn_cards) != STARTING_HEAVENLY_CARD_COUNT:
            raise ValueError(
                f"Player {player_id} must start with exactly {STARTING_HEAVENLY_CARD_COUNT} heavenly cards."
            )
        append_event(
            state.event_log,
            "starting_hand_setup_completed",
            player_id=player_id,
            truth_values=selected_truth_values,
            truth_card_ids=[card.card_id for card in prepared_truth_cards],
            heavenly_card_ids=[card.card_id for card in drawn_cards],
            hand_size=len(state.players[player_id].hand_cards),
            heavenly_draw_pile_size=len(state.heavenly_draw_pile),
        )

    return state


def setup_hand_grenade_draft(
    state: GameState,
    *,
    seed: int | str | None = None,
    auto_pick: bool = True,
    grenade_deck: list[CardRef] | None = None,
) -> GameState:
    rng = SeededRNG(seed=seed)
    deck = list(grenade_deck) if grenade_deck is not None else build_default_hand_grenades()

    for player in state.players.values():
        player.hand_grenade_state.draft_options = []
        player.hand_grenade_state.grenade = None
    state.hand_grenade_draft_pool = []
    state.hand_grenade_draft_next_player_index = 0

    if state.beginner_mode:
        return state

    if len(state.player_order) == 5:
        if len(deck) < 9:
            raise ValueError("The 5-player 2/3/4/5/5 hand-grenade draft requires at least nine unique grenades.")
        state.hand_grenade_draft_pool = rng.shuffle(deck)
        append_event(
            state.event_log,
            "grenade_draft_initialized",
            mode="5p_lab",
            option_counts=list(FIVE_PLAYER_GRENADE_OPTION_COUNTS),
            pool_size=len(state.hand_grenade_draft_pool),
        )
        _assign_next_five_player_grenade_options(state)
        if auto_pick:
            while state.hand_grenade_draft_next_player_index < len(state.player_order):
                player_id = state.player_order[state.hand_grenade_draft_next_player_index]
                draft_hand_grenade(state, player_id=player_id, option_index=0)
        return state

    for player_id in state.player_order:
        player = state.players[player_id]
        options = rng.draw_without_replacement(deck, 2)
        player.hand_grenade_state.draft_options = options
        append_event(
            state.event_log,
            "grenade_draft_options_assigned",
            player_id=player_id,
            option_ids=[option.card_id for option in options],
            option_count=len(options),
        )
        if auto_pick:
            draft_hand_grenade(state, player_id=player_id, option_index=0)

    return state


def _assign_next_five_player_grenade_options(state: GameState) -> None:
    player_index = state.hand_grenade_draft_next_player_index
    if player_index >= len(state.player_order):
        append_event(
            state.event_log,
            "grenade_draft_completed",
            mode="5p_lab",
            unchosen_pool_size=len(state.hand_grenade_draft_pool),
        )
        return

    option_count = FIVE_PLAYER_GRENADE_OPTION_COUNTS[player_index]
    if len(state.hand_grenade_draft_pool) < option_count:
        raise ValueError(
            f"5P hand-grenade draft needs {option_count} options for player {player_index + 1}, "
            f"but only {len(state.hand_grenade_draft_pool)} remain."
        )
    player_id = state.player_order[player_index]
    options = state.hand_grenade_draft_pool[:option_count]
    state.hand_grenade_draft_pool = state.hand_grenade_draft_pool[option_count:]
    state.players[player_id].hand_grenade_state.draft_options = options
    append_event(
        state.event_log,
        "grenade_draft_options_assigned",
        player_id=player_id,
        player_index=player_index,
        option_ids=[option.card_id for option in options],
        option_count=len(options),
        mode="5p_lab",
        pool_size_after_draw=len(state.hand_grenade_draft_pool),
    )


def draft_hand_grenade(state: GameState, *, player_id: str, option_index: int) -> GameState:
    if state.beginner_mode:
        raise ValueError("Hand grenades are disabled in beginner mode.")
    player = state.players[player_id]
    if len(state.player_order) == 5:
        expected_player_index = state.hand_grenade_draft_next_player_index
        expected_player_id = (
            state.player_order[expected_player_index]
            if expected_player_index < len(state.player_order)
            else None
        )
        if player_id != expected_player_id:
            raise ValueError(
                f"5P hand-grenade draft expects {expected_player_id}, not {player_id}."
            )
    if player.hand_grenade_state.grenade is not None:
        raise ValueError(f"Player {player_id} already drafted a grenade.")
    options = player.hand_grenade_state.draft_options
    if not options:
        raise ValueError(f"Player {player_id} has no grenade draft options.")
    if option_index < 0 or option_index >= len(options):
        raise IndexError(f"Invalid grenade option index {option_index} for player {player_id}.")

    player.hand_grenade_state.grenade = options[option_index]
    discarded_option_ids = [
        option.card_id
        for index, option in enumerate(options)
        if index != option_index
    ]
    returned_options = [
        option
        for index, option in enumerate(options)
        if index != option_index
    ]
    player.hand_grenade_state.draft_options = []
    append_event(
        state.event_log,
        "grenade_drafted",
        player_id=player_id,
        grenade_id=player.hand_grenade_state.grenade.card_id,
        option_index=option_index,
        discarded_option_ids=[] if len(state.player_order) == 5 else discarded_option_ids,
        returned_option_ids=discarded_option_ids if len(state.player_order) == 5 else [],
    )
    if len(state.player_order) == 5:
        state.hand_grenade_draft_pool.extend(returned_options)
        reshuffle_seed = (
            None
            if state.seed is None
            else f"5p-hand-grenade-return|{state.seed}|{expected_player_index}"
        )
        state.hand_grenade_draft_pool = SeededRNG(seed=reshuffle_seed).shuffle(
            state.hand_grenade_draft_pool
        )
        state.hand_grenade_draft_next_player_index += 1
        append_event(
            state.event_log,
            "grenade_draft_options_returned",
            player_id=player_id,
            returned_option_ids=discarded_option_ids,
            pool_size=len(state.hand_grenade_draft_pool),
            mode="5p_lab",
        )
        _assign_next_five_player_grenade_options(state)
    return state


def apply_event(state: GameState, event: dict[str, Any]) -> GameState:
    event_type = event["type"]

    if event_type == "turn_start":
        return start_turn(
            state,
            player_id=event["player_id"],
            prophet_target_player_id=event.get("prophet_target_player_id"),
            prophet_payment_choice=event.get("prophet_payment_choice"),
            prophet_transfer_payment_choice=event.get("prophet_transfer_payment_choice"),
            tableau_effect_intents=event.get("tableau_effect_intents"),
        )

    if event_type == "play_round":
        return play_round(state)

    if event_type == "choose_head":
        _enforce_head_truth_seven_invariant(
            state,
            player_id=event["player_id"],
            source="head_choice",
            assume_head_defined=True,
        )
        return state

    if event_type == "build_monument_part":
        return build_monument_part(
            state,
            player_id=event["player_id"],
            part=event["part"],
            card_id=event["card_id"],
            card_name=event.get("card_name"),
            truth_source=event.get("truth_source"),
            second_card_id=event.get("second_card_id"),
            second_card_name=event.get("second_card_name"),
        )

    if event_type == "use_truth":
        return use_truth(state, player_id=event["player_id"], value=event["value"])

    if event_type == "reset_truth":
        return reset_truth(state, player_id=event["player_id"])

    if event_type == "award_prophet":
        return award_prophet(state, player_id=event["player_id"])

    if event_type == "reveal_god":
        return reveal_god(state, player_id=event["player_id"])

    if event_type == "change_alignment":
        return apply_alignment_change(
            state,
            player_id=event["player_id"],
            new_alignment=event["new_alignment"],
        )

    if event_type == "pass_prophet":
        return pass_prophet(
            state,
            from_player_id=event["from_player_id"],
            to_player_id=event["to_player_id"],
            target_payment_choice=event.get("target_payment_choice"),
        )

    if event_type == "resolve_contest":
        return resolve_contest(
            state,
            bids=event["bids"],
            contested_card_id=event.get("contested_card_id"),
            contested_card_name=event.get("contested_card_name"),
            contested_card_alignment=event.get("contested_card_alignment"),
            contested_card_category=event.get("contested_card_category"),
            claim_on_win=event.get("claim_on_win", False),
            manifest_requests=event.get("manifest_requests"),
            tie_manifest_requests=event.get("tie_manifest_requests"),
            reset_truth_after=event.get("reset_truth_after", False),
            nun_sacrifice_decisions=event.get("nun_sacrifice_decisions"),
            phenomenon_prediction_guesses=event.get("phenomenon_prediction_guesses"),
        )

    if event_type == "play_phenomenon_contest":
        return play_phenomenon_contest(
            state,
            contested_card_id=event.get("contested_card_id"),
            contested_card_name=event.get("contested_card_name"),
            contested_card_alignment=event.get("contested_card_alignment"),
            manifest_requests=event.get("manifest_requests"),
            tie_manifest_requests=event.get("tie_manifest_requests"),
            nun_sacrifice_decisions=event.get("nun_sacrifice_decisions"),
            contest_turn_intents=event.get("contest_turn_intents"),
            phenomenon_prediction_guesses=event.get("phenomenon_prediction_guesses"),
            require_explicit_turn_intents=event.get("require_explicit_turn_intents"),
        )

    if event_type == "take_actions":
        return take_actions(
            state,
            player_id=event["player_id"],
            actions_available=event.get("actions_available", 2),
            action_intents=event.get("action_intents"),
            role_action_intents=event.get("role_action_intents"),
            require_explicit_action_intents=event.get("require_explicit_action_intents"),
        )

    if event_type == "play_hand_card":
        return play_hand_card(
            state,
            player_id=event["player_id"],
            card_id=event["card_id"],
            effect_payload=event.get("effect_payload"),
            decision_source="event",
        )

    if event_type == "unleash_stored_power":
        return unleash_stored_power(
            state,
            player_id=event["player_id"],
            phenomenon_card_id=event["phenomenon_card_id"],
            payment_choice=event.get("payment_choice"),
            effect_payload=event.get("effect_payload"),
            decision_source="event",
        )

    if event_type == "play_stored_phenomenon_action":
        play_stored_phenomenon_action(
            state,
            player_id=event["player_id"],
            phenomenon_id=event.get("phenomenon_id"),
            action_name=event.get("action_name", "stored_phenomenon_action"),
            decision_source="event",
        )
        return state

    if event_type == "claim_phenomenon":
        return claim_phenomenon(
            state,
            player_id=event["player_id"],
            card_id=event["card_id"],
            card_name=event.get("card_name"),
            card_alignment=event.get("card_alignment"),
            manifest_requested=event.get("manifest_requested", False),
            manifest_body_part_category=event.get("manifest_body_part_category"),
        )

    if event_type == "unleash_phenomenon_power":
        return unleash_phenomenon_power(
            state,
            player_id=event["player_id"],
            card_id=event["card_id"],
            effect_payload=event.get("effect_payload"),
            decision_source="event",
        )

    if event_type == "chisel_commandment":
        return chisel_commandment(
            state,
            player_id=event["player_id"],
            card_id=event.get("card_id"),
            card_name=event.get("card_name"),
        )

    if event_type == "grenade_commit":
        return commit_grenade_meeple(
            state,
            player_id=event["player_id"],
            detonate=event.get("detonate", False),
            effect_payload=event.get("effect_payload"),
            decision_source="event",
        )

    raise ValueError(f"Unsupported event type: {event_type}")


def start_turn(
    state: GameState,
    *,
    player_id: str,
    prophet_target_player_id: str | None = None,
    prophet_payment_choice: dict[str, Any] | None = None,
    prophet_transfer_payment_choice: dict[str, Any] | None = None,
    tableau_effect_intents: dict[str, dict[str, Any]] | None = None,
) -> GameState:
    player = state.players[player_id]
    append_event(state.event_log, "turn_started", player_id=player_id, turn_number=state.turn_number)

    append_event(state.event_log, "turn_phase_started", player_id=player_id, phase="tableau")

    if player.prophet_owner:
        append_event(state.event_log, "turn_phase_started", player_id=player_id, phase="prophet")
        resolve_prophet_upkeep(
            state,
            player_id=player_id,
            target_player_id=prophet_target_player_id,
            payment_choice=prophet_payment_choice,
            target_payment_choice=prophet_transfer_payment_choice,
        )

    resolve_tableau(
        state,
        player_id=player_id,
        tableau_effect_intents=tableau_effect_intents,
    )

    return state


def resolve_prophet_upkeep(
    state: GameState,
    *,
    player_id: str,
    target_player_id: str | None = None,
    payment_choice: dict[str, Any] | None = None,
    target_payment_choice: dict[str, Any] | None = None,
) -> GameState:
    player = state.players[player_id]
    if not player.prophet_owner:
        raise ValueError(f"Player {player_id} does not currently own the prophet.")

    if target_player_id:
        pass_prophet(
            state,
            from_player_id=player_id,
            to_player_id=target_player_id,
            target_payment_choice=target_payment_choice,
        )
        return state

    if len(state.active_commandments) >= MAX_ACTIVE_COMMANDMENTS:
        append_event(
            state.event_log,
            "prophet_linger_cost_forfeited",
            player_id=player_id,
            reason="commandment_limit_reached",
            active_commandment_count=len(state.active_commandments),
            max_active_commandments=MAX_ACTIVE_COMMANDMENTS,
            meeples_remaining=player.meeples,
        )
        return state

    payment_resolution = _spend_player_meeples(
        state,
        player_id=player_id,
        amount=1,
        strict=False,
        payment_choice=payment_choice,
        purpose="prophet_linger_cost",
    )
    append_event(
        state.event_log,
        "prophet_linger_cost_paid",
        player_id=player_id,
        meeples_paid=payment_resolution["paid_total"],
        free_meeples_paid=payment_resolution["free_meeples_paid"],
        role_meeples_paid=dict(payment_resolution["role_meeples_paid"]),
        prepared_nuns_paid=payment_resolution["prepared_nuns_paid"],
        meeples_remaining=player.meeples,
    )
    return state


def play_round(
    state: GameState,
    *,
    turn_intents_by_player: dict[str, dict[str, Any]] | None = None,
    contest_options: dict[str, Any] | None = None,
) -> GameState:
    from .round import play_round as play_round_impl

    return play_round_impl(
        state,
        turn_intents_by_player=turn_intents_by_player,
        contest_options=contest_options,
    )


@dataclass(slots=True)
class TurnFrame:
    player_id: str
    turn_number: int
    actions_available: int


def begin_turn(
    state: GameState,
    *,
    player_id: str,
    prophet_target_player_id: str | None = None,
    prophet_payment_choice: dict[str, Any] | None = None,
    prophet_transfer_payment_choice: dict[str, Any] | None = None,
    tableau_effect_intents: dict[str, dict[str, Any]] | None = None,
) -> TurnFrame | None:
    state.current_player_index = state.player_order.index(player_id)
    player = state.players[player_id]
    player.bonus_actions_this_turn = 0
    append_event(
        state.event_log,
        "player_turn_started",
        player_id=player_id,
        round_number=state.round_number,
        turn_number=state.turn_number,
    )
    if player.skip_next_turn:
        consumed_action_modifier = player.next_turn_action_modifier
        player.skip_next_turn = False
        player.next_turn_action_modifier = 0
        append_event(
            state.event_log,
            "player_turn_skipped_by_effect",
            player_id=player_id,
            round_number=state.round_number,
            turn_number=state.turn_number,
            consumed_action_modifier=consumed_action_modifier,
        )
        append_event(
            state.event_log,
            "player_turn_completed",
            player_id=player_id,
            round_number=state.round_number,
            turn_number=state.turn_number,
            skipped_by_effect=True,
        )
        validate_state(state)
        state.turn_number += 1
        return None

    action_modifier = player.next_turn_action_modifier
    player.next_turn_action_modifier = 0
    pure_chaos_bonus = 1 if _has_pure_alignment(player, "<Chaos>") else 0
    actions_available = max(0, 2 + action_modifier + pure_chaos_bonus)
    if action_modifier != 0:
        append_event(
            state.event_log,
            "turn_action_modifier_applied",
            player_id=player_id,
            round_number=state.round_number,
            turn_number=state.turn_number,
            action_modifier=action_modifier,
            modified_actions_available=actions_available,
        )
    if pure_chaos_bonus > 0:
        player.bonus_actions_this_turn += pure_chaos_bonus
        append_event(
            state.event_log,
            "pure_alignment_effect_resolved",
            player_id=player_id,
            alignment=player.alignment,
            pure_alignment="<Chaos>",
            effect_kind="pure_chaos_bonus_action",
            bonus_actions_granted=pure_chaos_bonus,
            modified_actions_available=actions_available,
            player_bonus_actions_this_turn=player.bonus_actions_this_turn,
            round_number=state.round_number,
            turn_number=state.turn_number,
        )

    start_turn(
        state,
        player_id=player_id,
        prophet_target_player_id=prophet_target_player_id,
        prophet_payment_choice=prophet_payment_choice,
        prophet_transfer_payment_choice=prophet_transfer_payment_choice,
        tableau_effect_intents=tableau_effect_intents,
    )
    return TurnFrame(
        player_id=player_id,
        turn_number=state.turn_number,
        actions_available=actions_available,
    )


def finalize_turn(state: GameState, *, frame: TurnFrame) -> GameState:
    player = state.players[frame.player_id]
    draw_step(state, player_id=frame.player_id)
    player.bonus_actions_this_turn = 0
    append_event(
        state.event_log,
        "player_turn_completed",
        player_id=frame.player_id,
        round_number=state.round_number,
        turn_number=frame.turn_number,
    )
    validate_state(state)
    state.turn_number += 1
    return state


def play_turn(
    state: GameState,
    *,
    player_id: str,
    prophet_target_player_id: str | None = None,
    prophet_payment_choice: dict[str, Any] | None = None,
    prophet_transfer_payment_choice: dict[str, Any] | None = None,
    tableau_effect_intents: dict[str, dict[str, Any]] | None = None,
    action_intents: list[dict[str, Any] | str] | None = None,
    require_explicit_action_intents: bool | None = None,
) -> GameState:
    frame = begin_turn(
        state,
        player_id=player_id,
        prophet_target_player_id=prophet_target_player_id,
        prophet_payment_choice=prophet_payment_choice,
        prophet_transfer_payment_choice=prophet_transfer_payment_choice,
        tableau_effect_intents=tableau_effect_intents,
    )
    if frame is None:
        return state

    take_actions(
        state,
        player_id=player_id,
        actions_available=frame.actions_available,
        action_intents=action_intents,
        require_explicit_action_intents=require_explicit_action_intents,
    )
    return finalize_turn(state, frame=frame)


def has_complete_trinity(player: PlayerState) -> bool:
    return player_has_complete_trinity(player)


def _count_body_parts_for_scoring(player: PlayerState) -> int:
    return sum(
        1
        for category in FINAL_SCORING_BODY_PART_CATEGORIES
        if any(card.category == category for card in player.tableau)
    )


def _count_believers_on_tableau_for_scoring(player: PlayerState) -> int:
    assigned_role_meeples = sum(max(0, int(amount)) for amount in player.assigned_role_meeples.values())
    prepared_nuns = max(0, int(player.nunnery_state.prepared_nuns))
    return assigned_role_meeples + prepared_nuns


def compute_final_score_breakdown(player: PlayerState) -> dict[str, Any]:
    believers_herd = max(0, int(player.meeples))
    believers_on_tableau = max(0, _count_believers_on_tableau_for_scoring(player))
    body_parts_count = max(0, _count_body_parts_for_scoring(player))
    total_believers = max(0, believers_herd + believers_on_tableau)
    trinity_count = 1 if has_complete_trinity(player) else 0

    return {
        "believers_herd": believers_herd,
        "believers_on_tableau": believers_on_tableau,
        "body_parts_count": body_parts_count,
        "total_believers": total_believers,
        "trinity_count": trinity_count,
        "has_complete_trinity": bool(trinity_count),
    }


def compute_final_score(player: PlayerState) -> tuple[int, int]:
    breakdown = compute_final_score_breakdown(player)
    return int(breakdown["trinity_count"]), int(breakdown["total_believers"])


def compute_player_endgame_analysis(state: GameState, *, player_id: str) -> dict[str, Any]:
    if player_id not in state.players:
        raise ValueError(f"Unknown player {player_id!r} for endgame analysis.")

    player = state.players[player_id]

    def _to_int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _payment_total(payload: dict[str, Any]) -> int:
        role_meeples_paid = payload.get("role_meeples_paid")
        role_total = (
            sum(_to_int(amount) for amount in role_meeples_paid.values())
            if isinstance(role_meeples_paid, dict)
            else 0
        )
        base_total = _to_int(payload.get("paid_total"))
        if base_total > 0:
            return base_total
        return (
            _to_int(payload.get("free_meeples_paid"))
            + _to_int(payload.get("prepared_nuns_paid"))
            + role_total
        )

    def _card_label(payload: dict[str, Any], *, prefer_phenomenon: bool = False) -> str:
        if prefer_phenomenon:
            raw_phenomenon_id = str(payload.get("phenomenon_card_id") or "")
            if raw_phenomenon_id:
                return raw_phenomenon_id
        raw_card_name = str(payload.get("card_name") or "").strip()
        if raw_card_name:
            return raw_card_name
        raw_card_id = str(payload.get("card_id") or payload.get("phenomenon_card_id") or "").strip()
        if raw_card_id:
            return raw_card_id
        return "-"

    def _add_total(bucket: dict[str, int], label: str, amount: int) -> None:
        normalized = _to_int(amount)
        if normalized <= 0:
            return
        bucket[label] = bucket.get(label, 0) + normalized

    gain_by_label: dict[str, int] = {}
    loss_by_label: dict[str, int] = {}
    pressure_total = 0
    contest_wins = 0
    stored_power_uses = 0
    monk_baptisms = 0
    missionary_transfers = 0
    monument_parts = sum(1 for card in player.tableau if getattr(card, "category", None) == "Monument")

    for raw_event in state.event_log:
        if not isinstance(raw_event, dict):
            continue
        event_type = str(raw_event.get("type") or "")
        source_player_id = str(raw_event.get("player_id") or "")
        target_player_id = (
            str(raw_event.get("target_player_id"))
            if raw_event.get("target_player_id") is not None
            else None
        )

        if event_type == "phenomenon_claimed" and source_player_id == player_id:
            contest_wins += 1
        if event_type in {"stored_power_effect_resolved", "stored_power_effect_fizzled"} and source_player_id == player_id:
            stored_power_uses += 1

        if source_player_id == player_id:
            if event_type == "role_production_resolved" and str(raw_event.get("role_type") or "") == "Mönche":
                produced_meeples = _to_int(raw_event.get("produced_meeples"))
                monk_baptisms += produced_meeples
                _add_total(gain_by_label, "Mönche", produced_meeples)
            elif event_type == "turn_start_missionary_steal_completed":
                total_transferred = _to_int(raw_event.get("total_transferred"))
                missionary_transfers += total_transferred
                pressure_total += total_transferred
                _add_total(gain_by_label, "Missionare", total_transferred)
            elif event_type == "alignment_tableau_effect_resolved":
                effect_kind = str(raw_event.get("effect_kind") or "")
                if effect_kind == "sanftmut_baptism":
                    _add_total(gain_by_label, "Sanftmut", _to_int(raw_event.get("actual_gain")))
                elif effect_kind == "zorn_strike":
                    pressure_total += _to_int(raw_event.get("actual_loss"))
                elif effect_kind == "chaos_baptism":
                    _add_total(gain_by_label, "Chaos", _to_int(raw_event.get("actual_gain")))
                elif effect_kind == "chaos_self_sacrifice":
                    _add_total(loss_by_label, "Chaos", _to_int(raw_event.get("actual_sacrifice")))
                elif effect_kind == "chaos_opponent_sacrifice":
                    pressure_total += _to_int(raw_event.get("actual_loss"))
                elif effect_kind == "chaos_missionize":
                    actual_transfer = _to_int(raw_event.get("actual_transfer"))
                    pressure_total += actual_transfer
                    _add_total(gain_by_label, "Chaos", actual_transfer)
            elif event_type == "phenomenon_believer_reward_resolved":
                _add_total(gain_by_label, "Contest-Belohnung", _to_int(raw_event.get("reward_amount")))
            elif event_type == "blessing_loblied_resolved":
                _add_total(gain_by_label, "Loblied", _to_int(raw_event.get("reward_amount")))
            elif event_type == "blessing_klagelied_applied":
                pressure_total += _to_int(raw_event.get("actual_sacrifice"))
            elif event_type == "stored_power_effect_resolved":
                effect_kind = str(raw_event.get("effect_kind") or "")
                phenomenon_label = _card_label(raw_event, prefer_phenomenon=True)
                if effect_kind == "baptize_self_meeples":
                    _add_total(gain_by_label, phenomenon_label, _to_int(raw_event.get("baptized_meeples")))
                elif effect_kind == "missionize_from_each_opponent":
                    total_transferred = _to_int(raw_event.get("total_transferred"))
                    pressure_total += total_transferred
                    _add_total(gain_by_label, phenomenon_label, total_transferred)
                elif target_player_id is not None and target_player_id != player_id:
                    pressure_total += (
                        _to_int(raw_event.get("actual_transfer"))
                        + _to_int(raw_event.get("actual_sacrifice"))
                        + _to_int(raw_event.get("total_removed"))
                        + _to_int(raw_event.get("removed_role_meeples"))
                        + _to_int(raw_event.get("removed_prepared_nuns"))
                    )
            elif event_type == "stored_power_effect_target_resolved":
                if target_player_id is not None and target_player_id != player_id:
                    pressure_total += (
                        _to_int(raw_event.get("actual_transfer"))
                        + _to_int(raw_event.get("actual_sacrifice"))
                        + _to_int(raw_event.get("total_removed"))
                    )
            elif event_type == "relic_large_sacrifice_triggered":
                _add_total(gain_by_label, "Reliquie", _to_int(raw_event.get("actual_transfer")))
            elif event_type in {"relic_on_play_effect_resolved", "relic_tableau_effect_resolved"}:
                effect_kind = str(raw_event.get("effect_kind") or "")
                card_label = _card_label(raw_event)
                if effect_kind == "missionize_per_affecting_commandment":
                    actual_transfer = _to_int(raw_event.get("actual_transfer"))
                    pressure_total += actual_transfer
                    _add_total(gain_by_label, card_label, actual_transfer)
                elif effect_kind == "opponent_choice_discard_or_baptism":
                    _add_total(gain_by_label, card_label, _to_int(raw_event.get("actual_baptism")))
            elif event_type == "enlightener_tableau_effect_resolved":
                effect_kind = str(raw_event.get("effect_kind") or "")
                card_label = _card_label(raw_event)
                if effect_kind == "sacrifice_meeples":
                    _add_total(loss_by_label, card_label, _to_int(raw_event.get("actual_sacrifice")))
                elif effect_kind in {"right_player_missionizes", "left_player_missionizes"}:
                    _add_total(loss_by_label, card_label, _to_int(raw_event.get("actual_transfer")))
            elif event_type == "hand_card_intrinsic_cost_paid":
                _add_total(loss_by_label, "Kartenkosten", _payment_total(raw_event))
            elif event_type == "stored_power_unleashed":
                _add_total(
                    loss_by_label,
                    f"{_card_label(raw_event, prefer_phenomenon=True)} entfesseln",
                    _payment_total(raw_event),
                )

        if target_player_id == player_id:
            if event_type == "alignment_tableau_effect_resolved":
                effect_kind = str(raw_event.get("effect_kind") or "")
                if effect_kind == "zorn_strike":
                    _add_total(loss_by_label, "Zorn", _to_int(raw_event.get("actual_loss")))
                elif effect_kind == "chaos_opponent_sacrifice":
                    _add_total(loss_by_label, "Chaos", _to_int(raw_event.get("actual_loss")))
                elif effect_kind == "chaos_missionize":
                    _add_total(loss_by_label, "Chaos", _to_int(raw_event.get("actual_transfer")))
            elif event_type == "turn_start_missionary_steal_resolved":
                _add_total(loss_by_label, "Missionare", _to_int(raw_event.get("meeples_transferred") or 1))
            elif event_type == "blessing_klagelied_applied":
                _add_total(loss_by_label, "Klagelied", _to_int(raw_event.get("actual_sacrifice")))
            elif event_type == "stored_power_effect_target_resolved":
                _add_total(
                    loss_by_label,
                    _card_label(raw_event, prefer_phenomenon=True),
                    _to_int(raw_event.get("actual_transfer"))
                    + _to_int(raw_event.get("actual_sacrifice"))
                    + _to_int(raw_event.get("total_removed")),
                )
            elif event_type == "stored_power_effect_resolved":
                _add_total(
                    loss_by_label,
                    _card_label(raw_event, prefer_phenomenon=True),
                    _to_int(raw_event.get("actual_transfer"))
                    + _to_int(raw_event.get("actual_sacrifice"))
                    + _to_int(raw_event.get("total_removed"))
                    + _to_int(raw_event.get("removed_role_meeples"))
                    + _to_int(raw_event.get("removed_prepared_nuns")),
                )
            elif event_type in {"relic_on_play_effect_resolved", "relic_tableau_effect_resolved"}:
                if str(raw_event.get("effect_kind") or "") == "missionize_per_affecting_commandment":
                    _add_total(loss_by_label, _card_label(raw_event), _to_int(raw_event.get("actual_transfer")))
            elif event_type == "enlightener_tableau_effect_resolved":
                if str(raw_event.get("effect_kind") or "") in {"right_player_missionizes", "left_player_missionizes"}:
                    _add_total(gain_by_label, _card_label(raw_event), _to_int(raw_event.get("actual_transfer")))

    def _top_entry(bucket: dict[str, int]) -> dict[str, Any] | None:
        if not bucket:
            return None
        label, amount = max(bucket.items(), key=lambda entry: (entry[1], entry[0]))
        return {"label": label, "amount": amount}

    score_breakdown = compute_final_score_breakdown(player)
    body_parts_count = _to_int(score_breakdown.get("body_parts_count"))
    active_relic_count = sum(1 for card in player.tableau if getattr(card, "category", None) == "Reliquie")
    tableau_support_count = len(player.tableau)

    phenomenon_focus = contest_wins * 3 + body_parts_count * 2 + stored_power_uses
    engine_focus = monk_baptisms * 2 + monument_parts * 2 + active_relic_count + tableau_support_count
    interaction_focus = missionary_transfers * 2 + pressure_total
    dominant_focus = max(phenomenon_focus, engine_focus, interaction_focus)
    if dominant_focus <= 0:
        playstyle_summary = "Ausgewogenes Spiel ohne klaren Einzelfokus."
    elif phenomenon_focus >= engine_focus and phenomenon_focus >= interaction_focus:
        playstyle_summary = (
            f"Phänomenfokus: {contest_wins} Contest-Sieg(e), "
            f"{body_parts_count} Körperteil(e) und {stored_power_uses} ausgelöste Phänomen-Aktion(en)."
        )
    elif engine_focus >= interaction_focus:
        playstyle_summary = (
            f"Engine Building: {monument_parts} Monumentteil(e), "
            f"{monk_baptisms} Gläubige über Mönche und {active_relic_count} aktive Reliquie(n) im Endtableau."
        )
    else:
        playstyle_summary = (
            f"Interaktiv: {missionary_transfers} Missionars-Transfer(s) "
            f"und {pressure_total} erzwungene Gläubigenverluste bei Mitgöttern."
        )

    return {
        "playstyle_summary": playstyle_summary,
        "gain_by_source": gain_by_label,
        "loss_by_source": loss_by_label,
        "gain_leader": _top_entry(gain_by_label),
        "loss_leader": _top_entry(loss_by_label),
        "contest_wins": contest_wins,
        "stored_power_uses": stored_power_uses,
        "monk_baptisms": monk_baptisms,
        "missionary_transfers": missionary_transfers,
        "pressure_total": pressure_total,
        "monument_parts": monument_parts,
    }


def is_all_lose_terminal(state: GameState, *, end_reason: str | None = None) -> bool:
    """D-109: depletion loses for everyone only without a complete god.

    Simulation may supply its terminal reason before finalizing the state.
    An empty pile alone must not change an otherwise regular final score.
    """
    return (
        (end_reason or get_game_over_reason(state)) == "phenomenon_draw_pile_empty"
        and not any(has_complete_trinity(state.players[player_id]) for player_id in state.player_order)
    )


def resolve_final_winners(state: GameState) -> list[str]:
    if not state.player_order or is_all_lose_terminal(state):
        return []
    score_by_player = {
        player_id: compute_final_score(state.players[player_id])
        for player_id in state.player_order
    }
    best_score = max(score_by_player.values())
    best_player_ids = [
        player_id
        for player_id in state.player_order
        if score_by_player[player_id] == best_score
    ]
    if state.game_format != GAME_FORMAT_TEAM_2V2:
        return best_player_ids

    best_team_ids = {
        team_id
        for player_id in best_player_ids
        if (team_id := get_player_team_id(state, player_id=player_id)) is not None
    }
    if len(best_team_ids) != 1:
        return []
    winning_team_id = next(iter(best_team_ids))
    return [
        player_id
        for player_id in state.player_order
        if get_player_team_id(state, player_id=player_id) == winning_team_id
    ]


def resolve_final_individual_leaders(state: GameState) -> list[str]:
    if not state.player_order or is_all_lose_terminal(state):
        return []
    score_by_player = {
        player_id: compute_final_score(state.players[player_id])
        for player_id in state.player_order
    }
    best_score = max(score_by_player.values())
    return [
        player_id
        for player_id in state.player_order
        if score_by_player[player_id] == best_score
    ]


def get_pending_team_tiebreak_team_ids(state: GameState) -> list[str]:
    if state.game_format != GAME_FORMAT_TEAM_2V2:
        return []
    leader_team_ids = {
        team_id
        for player_id in resolve_final_individual_leaders(state)
        if (team_id := get_player_team_id(state, player_id=player_id)) is not None
    }
    return sorted(leader_team_ids) if len(leader_team_ids) > 1 else []


def resolve_final_winner(state: GameState) -> str | None:
    winners = resolve_final_winners(state)
    if not winners:
        return None
    if state.game_format == GAME_FORMAT_TEAM_2V2:
        individual_leaders = resolve_final_individual_leaders(state)
        return individual_leaders[0] if individual_leaders else None
    return winners[0]


def get_game_over_reason(state: GameState) -> str | None:
    if isinstance(state.game_over_reason, str) and state.game_over_reason:
        return state.game_over_reason

    for event in reversed(state.event_log):
        event_type = event.get("type")
        if event_type == "game_over_endgame":
            return "game_over_endgame"
        if event_type == "game_over_terminal":
            reason = event.get("reason")
            return reason if isinstance(reason, str) and reason else "game_over_terminal"
    return None


def finalize_terminal_game_if_needed(
    state: GameState,
    *,
    reason: str,
    completed_round: int | None = None,
) -> GameState:
    if state.game_over:
        if not state.game_over_reason:
            state.game_over_reason = get_game_over_reason(state) or reason
        return state

    state.game_over = True
    state.game_over_reason = reason
    winner_ids = resolve_final_winners(state)
    winner_id = resolve_final_winner(state)
    individual_leader_ids = resolve_final_individual_leaders(state)
    pending_team_tiebreak_team_ids = get_pending_team_tiebreak_team_ids(state)
    score_by_player = {
        player_id: compute_final_score_breakdown(state.players[player_id])
        for player_id in state.player_order
    }
    append_event(
        state.event_log,
        "game_over_terminal",
        reason=reason,
        completed_round=completed_round,
        trigger_round=state.first_trinity_trigger_round or state.gods_twilight_trigger_round,
        remaining_final_rounds=(
            state.endgame_rounds_left
            if state.endgame_active and state.endgame_rounds_left is not None
            else state.remaining_final_rounds
        ),
        phenomenon_draw_pile_size=len(state.phenomenon_draw_pile),
        winner_id=winner_id,
        winner_ids=winner_ids,
        shared_win=len(winner_ids) > 1 and state.game_format != GAME_FORMAT_TEAM_2V2,
        individual_leader_ids=individual_leader_ids,
        winning_team_id=(
            get_player_team_id(state, player_id=winner_id)
            if winner_id is not None and state.game_format == GAME_FORMAT_TEAM_2V2
            else None
        ),
        team_tiebreak_required=bool(pending_team_tiebreak_team_ids),
        team_tiebreak_team_ids=pending_team_tiebreak_team_ids,
        score_by_player=score_by_player,
    )
    return state


def finalize_round_terminal_state(
    state: GameState,
    *,
    completed_round: int,
) -> GameState:
    if state.game_over:
        return state
    if state.endgame_active and state.endgame_rounds_left == 0:
        return finalize_terminal_game_if_needed(
            state,
            reason="gods_twilight_final_rounds_exhausted",
            completed_round=completed_round,
        )
    if not state.phenomenon_draw_pile:
        return finalize_terminal_game_if_needed(
            state,
            reason="phenomenon_draw_pile_empty",
            completed_round=completed_round,
        )
    return state


def maybe_start_endgame_countdown(
    state: GameState,
    *,
    trigger_source: str,
    preferred_player_id: str | None = None,
) -> GameState:
    candidate_player_ids: list[str] = []
    if (
        isinstance(preferred_player_id, str)
        and preferred_player_id in state.players
        and has_complete_trinity(state.players[preferred_player_id])
    ):
        candidate_player_ids.append(preferred_player_id)
    candidate_player_ids.extend(
        player_id
        for player_id in state.player_order
        if has_complete_trinity(state.players[player_id]) and player_id not in candidate_player_ids
    )
    trigger_player_id = candidate_player_ids[0] if candidate_player_ids else None

    if trigger_player_id is None:
        return state

    reveal_player_id = next(
        (
            player_id
            for player_id in candidate_player_ids
            if not state.players[player_id].god_revealed
        ),
        None,
    )
    if reveal_player_id is not None:
        return reveal_god(state, player_id=reveal_player_id)

    return _start_endgame_countdown(
        state,
        trigger_player_id=trigger_player_id,
        trigger_source=trigger_source,
    )


def advance_endgame_countdown_after_round(
    state: GameState,
    *,
    completed_round: int,
) -> GameState:
    if not state.endgame_active:
        return state
    _sync_remaining_final_rounds_with_endgame(state)
    if state.endgame_rounds_left <= 0:
        if not state.game_over:
            state.game_over = True
            state.game_over_reason = state.game_over_reason or "game_over_endgame"
        return state
    if (
        state.first_trinity_trigger_round is not None
        and completed_round <= state.first_trinity_trigger_round
    ):
        _sync_remaining_final_rounds_with_endgame(state)
        return state

    state.endgame_rounds_left -= 1
    _sync_remaining_final_rounds_with_endgame(state)
    append_event(
        state.event_log,
        "final_rounds_remaining_updated",
        completed_round=completed_round,
        remaining_final_rounds=state.remaining_final_rounds,
    )
    append_event(
        state.event_log,
        "endgame_round_completed",
        completed_round=completed_round,
        endgame_rounds_left=state.endgame_rounds_left,
        trigger_round=state.first_trinity_trigger_round,
        trigger_player_id=state.endgame_triggered_by_player,
    )

    if state.endgame_rounds_left > 0:
        return state

    state.game_over = True
    state.game_over_reason = "game_over_endgame"
    winner_ids = resolve_final_winners(state)
    winner_id = resolve_final_winner(state)
    individual_leader_ids = resolve_final_individual_leaders(state)
    pending_team_tiebreak_team_ids = get_pending_team_tiebreak_team_ids(state)
    score_by_player = {
        player_id: compute_final_score_breakdown(state.players[player_id])
        for player_id in state.player_order
    }
    append_event(
        state.event_log,
        "game_over_endgame",
        completed_round=completed_round,
        trigger_round=state.first_trinity_trigger_round,
        trigger_player_id=state.endgame_triggered_by_player,
        winner_id=winner_id,
        winner_ids=winner_ids,
        shared_win=len(winner_ids) > 1 and state.game_format != GAME_FORMAT_TEAM_2V2,
        individual_leader_ids=individual_leader_ids,
        winning_team_id=(
            get_player_team_id(state, player_id=winner_id)
            if winner_id is not None and state.game_format == GAME_FORMAT_TEAM_2V2
            else None
        ),
        team_tiebreak_required=bool(pending_team_tiebreak_team_ids),
        team_tiebreak_team_ids=pending_team_tiebreak_team_ids,
        score_by_player=score_by_player,
    )
    return state


def validate_state(state: GameState) -> GameState:
    start_index = max(0, min(state.validation_cursor, len(state.event_log)))
    validation_events = state.event_log[start_index:]
    state.max_total_believers_seen = max(
        int(state.max_total_believers_seen or 0),
        _count_total_believers_in_game(state),
    )

    _validate_draw_step_hand_limit_invariant(
        state,
        events=validation_events,
        event_offset=start_index,
    )
    _validate_truth_contest_usage_invariant(
        state,
        events=validation_events,
        event_offset=start_index,
    )
    _validate_contest_eligibility_invariant(
        state,
        events=validation_events,
        event_offset=start_index,
    )
    _validate_stored_phenomenon_removal_reason_invariant(
        state,
        events=validation_events,
        event_offset=start_index,
    )
    _enforce_head_truth_seven_invariants(
        state,
        source="state_validation",
    )
    _enforce_slot_overfill_invariants(state)
    _validate_role_state_invariants(state)
    _validate_alignment_consistency_invariants(state)

    state.validation_cursor = len(state.event_log)
    return state


def _record_illegal_state(
    state: GameState,
    *,
    illegal_code: str,
    **payload: Any,
) -> None:
    state.illegal_states.append(illegal_code)
    append_event(
        state.event_log,
        illegal_code,
        validator="validate_state",
        **payload,
    )


def _discard_newest_stored_phenomenon_for_slot_loss(
    state: GameState,
    *,
    player_id: str,
    old_alignment: str,
    new_alignment: str,
    event_type: str,
    source: str,
) -> str:
    player = state.players[player_id]
    stored_before = list(player.stored_phenomena)
    discarded_card_id = player.stored_phenomena.pop()
    state.phenomenon_discard.append(discarded_card_id)
    append_event(
        state.event_log,
        event_type,
        player_id=player_id,
        phenomenon_id=discarded_card_id,
        card_id=discarded_card_id,
        old_alignment=old_alignment,
        new_alignment=new_alignment,
        stored_before=stored_before,
        stored_after=list(player.stored_phenomena),
        alignment=player.alignment,
        remaining_stored_phenomena=list(player.stored_phenomena),
        phenomenon_discard_size=len(state.phenomenon_discard),
        reason=PHENOMENON_REMOVAL_REASON_SLOT_LOSS,
        source=source,
    )
    return discarded_card_id


def _validate_draw_step_hand_limit_invariant(
    state: GameState,
    *,
    events: list[dict[str, Any]],
    event_offset: int,
) -> None:
    pending_draw_start_by_player_id: dict[str, dict[str, Any]] = {}

    for local_index, event in enumerate(events):
        event_type = event.get("type")
        player_id = event.get("player_id")
        if not isinstance(player_id, str):
            continue

        if event_type == "draw_step_started":
            pending_draw_start_by_player_id[player_id] = {
                "event_index": event_offset + local_index,
                "hand_size": event.get("hand_size"),
                "hand_limit": event.get("hand_limit"),
            }
            continue

        if event_type != "draw_step_resolved":
            continue

        draw_start_event = pending_draw_start_by_player_id.pop(player_id, None)
        if draw_start_event is None:
            continue
        hand_size = _coerce_event_int(draw_start_event.get("hand_size"))
        hand_limit = _coerce_event_int(draw_start_event.get("hand_limit"))
        cards_drawn = _coerce_event_int(event.get("cards_drawn"))
        if hand_size is None or hand_limit is None or cards_drawn is None:
            continue
        if hand_size < hand_limit or cards_drawn <= 0:
            continue

        _record_illegal_state(
            state,
            illegal_code=ILLEGAL_STATE_DRAW_STEP_DREW_AT_OR_ABOVE_HAND_LIMIT,
            player_id=player_id,
            draw_step_started_index=draw_start_event["event_index"],
            draw_step_resolved_index=event_offset + local_index,
            hand_size_before_draw=hand_size,
            hand_limit=hand_limit,
            cards_drawn=cards_drawn,
        )


def _validate_truth_contest_usage_invariant(
    state: GameState,
    *,
    events: list[dict[str, Any]],
    event_offset: int,
) -> None:
    contest_depth = 0

    for local_index, event in enumerate(events):
        event_type = event.get("type")
        if event_type == "contest_started":
            contest_depth += 1
            continue
        if event_type in VALIDATION_CONTEST_CLOSE_EVENTS and contest_depth > 0:
            contest_depth -= 1
            continue
        if event_type != "truth_used":
            continue
        if contest_depth > 0:
            continue
        if _truth_used_is_followed_by_manual_contest_resolution(events, local_index):
            continue

        _record_illegal_state(
            state,
            illegal_code=ILLEGAL_STATE_TRUTH_USED_OUTSIDE_CONTEST,
            event_index=event_offset + local_index,
            player_id=event.get("player_id"),
            truth_value=event.get("value"),
        )


def _truth_used_is_followed_by_manual_contest_resolution(
    events: list[dict[str, Any]],
    truth_event_index: int,
) -> bool:
    for event in events[truth_event_index + 1 :]:
        event_type = event.get("type")
        if event_type == "contest_resolved":
            return True
        if event_type == "contest_started":
            return False
        if event_type in VALIDATION_PHASE_BOUNDARY_EVENTS:
            return False
    return False


def _validate_contest_eligibility_invariant(
    state: GameState,
    *,
    events: list[dict[str, Any]],
    event_offset: int,
) -> None:
    allowed_bid_actor_ids: set[str] | None = None
    allowed_pass_actor_ids: set[str] | None = None

    for local_index, event in enumerate(events):
        event_type = event.get("type")
        if event_type == "contest_eligibility_computed":
            raw_contest_turn_player_ids = event.get("contest_turn_player_ids")
            contest_turn_player_ids: set[str] = set()
            if isinstance(raw_contest_turn_player_ids, list):
                contest_turn_player_ids = {
                    player_id for player_id in raw_contest_turn_player_ids if isinstance(player_id, str)
                }
            raw_eligible_player_ids = event.get("eligible_player_ids")
            if isinstance(raw_eligible_player_ids, list):
                allowed_bid_actor_ids = {
                    player_id for player_id in raw_eligible_player_ids if isinstance(player_id, str)
                }
            else:
                allowed_bid_actor_ids = set()
            allowed_pass_actor_ids = contest_turn_player_ids or set(allowed_bid_actor_ids)
            continue

        if event_type in VALIDATION_CONTEST_CLOSE_EVENTS:
            allowed_bid_actor_ids = None
            allowed_pass_actor_ids = None
            continue

        if event_type == "bid_placed":
            allowed_actor_ids = allowed_bid_actor_ids
        elif event_type == "player_passed":
            allowed_actor_ids = allowed_pass_actor_ids
        else:
            allowed_actor_ids = None

        if allowed_actor_ids is None:
            continue

        player_id = event.get("player_id")
        if not isinstance(player_id, str) or player_id in allowed_actor_ids:
            continue

        _record_illegal_state(
            state,
            illegal_code=ILLEGAL_STATE_CONTEST_ACTION_BY_INELIGIBLE_PLAYER,
            event_index=event_offset + local_index,
            player_id=player_id,
            action_event_type=event_type,
            eligible_player_ids=sorted(allowed_actor_ids),
        )


def _validate_stored_phenomenon_removal_reason_invariant(
    state: GameState,
    *,
    events: list[dict[str, Any]],
    event_offset: int,
) -> None:
    expected_reason_by_event_type = {
        "phenomenon_discarded_due_to_slot_loss": PHENOMENON_REMOVAL_REASON_SLOT_LOSS,
        "phenomenon_discarded_due_to_validation_overfill": PHENOMENON_REMOVAL_REASON_SLOT_LOSS,
        "phenomenon_discarded_after_action": PHENOMENON_REMOVAL_REASON_ACTION_PLAYED,
    }

    for local_index, event in enumerate(events):
        event_type = event.get("type")
        expected_reason = expected_reason_by_event_type.get(event_type)
        if expected_reason is None:
            continue

        reason = event.get("reason")
        if not isinstance(reason, str):
            _record_illegal_state(
                state,
                illegal_code=ILLEGAL_STATE_INVALID_STORED_PHENOMENON_REMOVAL_REASON,
                event_index=event_offset + local_index,
                removal_event_type=event_type,
                reason=reason,
                expected_reason=expected_reason,
            )
            continue

        if reason not in ALLOWED_PHENOMENON_REMOVAL_REASONS or reason != expected_reason:
            _record_illegal_state(
                state,
                illegal_code=ILLEGAL_STATE_INVALID_STORED_PHENOMENON_REMOVAL_REASON,
                event_index=event_offset + local_index,
                removal_event_type=event_type,
                reason=reason,
                expected_reason=expected_reason,
            )


def _enforce_slot_overfill_invariants(state: GameState) -> None:
    for player_id, player in state.players.items():
        phenomena_slot_limit = max(0, _get_slot_limit(player, slot_kind="phenomena"))
        while len(player.stored_phenomena) > phenomena_slot_limit:
            stored_count_before = len(player.stored_phenomena)
            discarded_card_id = _discard_newest_stored_phenomenon_for_slot_loss(
                state,
                player_id=player_id,
                old_alignment=player.alignment,
                new_alignment=player.alignment,
                event_type="phenomenon_discarded_due_to_validation_overfill",
                source=PHENOMENON_REMOVAL_SOURCE_STATE_VALIDATION,
            )
            _record_illegal_state(
                state,
                illegal_code=ILLEGAL_STATE_PHENOMENA_SLOT_OVERFILL,
                player_id=player_id,
                discarded_card_id=discarded_card_id,
                stored_count_before=stored_count_before,
                phenomena_slot_limit=phenomena_slot_limit,
            )

        for role_type in ROLE_TYPES:
            assigned_role_meeples = max(0, player.assigned_role_meeples.get(role_type, 0))
            role_card_count = _get_role_card_count(player, role_type=role_type)
            role_slot_limit = max(0, _get_role_slot_limit(player, role_type=role_type))
            max_assignable_meeples = (
                role_slot_limit
                if role_type in {"Mönche", "Missionare", "Nonnen"}
                else min(role_card_count, role_slot_limit)
            )
            if assigned_role_meeples <= max_assignable_meeples:
                continue

            returned_meeples = assigned_role_meeples - max_assignable_meeples
            player.assigned_role_meeples[role_type] = max_assignable_meeples
            player.meeples += returned_meeples
            removed_prepared_nuns = 0
            if role_type == "Nonnen":
                prepared_nuns = max(0, int(player.nunnery_state.prepared_nuns))
                prepared_nun_limit = min(max_assignable_meeples, max(0, int(player.nuns_slots)))
                if prepared_nuns > prepared_nun_limit:
                    removed_prepared_nuns = prepared_nuns - prepared_nun_limit
                    player.nunnery_state.prepared_nuns = prepared_nun_limit
                    player.nunnery_state.sacrificed_nuns += removed_prepared_nuns
            append_event(
                state.event_log,
                "role_slot_meeples_returned_due_to_slot_loss",
                player_id=player_id,
                role_type=role_type,
                returned_meeples=returned_meeples,
                remaining_assigned_role_meeples=max_assignable_meeples,
                role_card_count=role_card_count,
                slot_limit=role_slot_limit,
                reason=PHENOMENON_REMOVAL_SOURCE_STATE_VALIDATION,
                removed_prepared_nuns=removed_prepared_nuns,
            )
            _record_illegal_state(
                state,
                illegal_code=ILLEGAL_STATE_ROLE_SLOT_OVERFILL,
                player_id=player_id,
                role_type=role_type,
                assigned_role_meeples=assigned_role_meeples,
                max_assignable_meeples=max_assignable_meeples,
                returned_meeples=returned_meeples,
            )

        assigned_nuns = max(0, int(player.assigned_role_meeples.get("Nonnen", 0)))
        prepared_nuns = max(0, int(player.nunnery_state.prepared_nuns))
        prepared_nun_limit = min(assigned_nuns, max(0, int(player.nuns_slots)))
        if assigned_nuns > 0 and prepared_nuns > prepared_nun_limit:
            removed_prepared_nuns = prepared_nuns - prepared_nun_limit
            player.nunnery_state.prepared_nuns = prepared_nun_limit
            player.nunnery_state.sacrificed_nuns += removed_prepared_nuns
            append_event(
                state.event_log,
                "role_slot_meeples_returned_due_to_slot_loss",
                player_id=player_id,
                role_type="Nonnen",
                returned_meeples=0,
                remaining_assigned_role_meeples=assigned_nuns,
                role_card_count=_get_role_card_count(player, role_type="Nonnen"),
                slot_limit=max(0, int(player.nuns_slots)),
                reason=PHENOMENON_REMOVAL_SOURCE_STATE_VALIDATION,
                removed_prepared_nuns=removed_prepared_nuns,
            )


def _validate_role_state_invariants(state: GameState) -> None:
    for player_id, player in state.players.items():
        if player.nunnery_state.prepared_nuns < 0 or player.nunnery_state.sacrificed_nuns < 0:
            _record_illegal_state(
                state,
                illegal_code=ILLEGAL_STATE_INVALID_ROLE_STATE,
                player_id=player_id,
                role_type="Nonnen",
                reason="negative_nunnery_state",
                prepared_nuns=player.nunnery_state.prepared_nuns,
                sacrificed_nuns=player.nunnery_state.sacrificed_nuns,
            )
        if player.nunnery_state.prepared_nuns > max(0, int(player.nuns_slots)):
            _record_illegal_state(
                state,
                illegal_code=ILLEGAL_STATE_INVALID_ROLE_STATE,
                player_id=player_id,
                role_type="Nonnen",
                reason="prepared_nuns_exceed_nun_slots",
                prepared_nuns=player.nunnery_state.prepared_nuns,
                nuns_slots=player.nuns_slots,
            )
        if player.nunnery_state.prepared_nuns > max(0, int(player.assigned_role_meeples.get("Nonnen", 0))):
            _record_illegal_state(
                state,
                illegal_code=ILLEGAL_STATE_INVALID_ROLE_STATE,
                player_id=player_id,
                role_type="Nonnen",
                reason="prepared_nuns_without_assigned_nuns",
                prepared_nuns=player.nunnery_state.prepared_nuns,
                assigned_nuns=player.assigned_role_meeples.get("Nonnen", 0),
            )
        for role_type, assigned_amount in player.assigned_role_meeples.items():
            if int(assigned_amount) < 0:
                _record_illegal_state(
                    state,
                    illegal_code=ILLEGAL_STATE_INVALID_ROLE_STATE,
                    player_id=player_id,
                    role_type=role_type,
                    reason="negative_assigned_role_meeples",
                    assigned_role_meeples=assigned_amount,
                )


def _validate_alignment_consistency_invariants(state: GameState) -> None:
    for player_id, player in state.players.items():
        expected_phenomena_slots = 3 if player.alignment == "<Zorn>" else 2
        expected_monks_slots = 4 if player.alignment == "<Sanftmut>" else 3
        expected_nuns_slots = 2 if state.gods_twilight_triggered and player.alignment == "<Unergründlich>" else 1
        mismatches: dict[str, dict[str, int]] = {}
        if int(player.phenomena_slots) != expected_phenomena_slots:
            mismatches["phenomena_slots"] = {"actual": int(player.phenomena_slots), "expected": expected_phenomena_slots}
        if int(player.monks_slots) != expected_monks_slots:
            mismatches["monks_slots"] = {"actual": int(player.monks_slots), "expected": expected_monks_slots}
        if int(player.nuns_slots) != expected_nuns_slots:
            mismatches["nuns_slots"] = {"actual": int(player.nuns_slots), "expected": expected_nuns_slots}
        if not mismatches:
            continue
        _record_illegal_state(
            state,
            illegal_code=ILLEGAL_STATE_ALIGNMENT_INCONSISTENCY,
            player_id=player_id,
            alignment=player.alignment,
            phenomena_slots=int(player.phenomena_slots),
            expected_phenomena_slots=expected_phenomena_slots,
            monks_slots=int(player.monks_slots),
            expected_monks_slots=expected_monks_slots,
            nuns_slots=int(player.nuns_slots),
            expected_nuns_slots=expected_nuns_slots,
            mismatches=mismatches,
        )


def _coerce_event_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, int):
        return None
    return value


def resolve_tableau(
    state: GameState,
    *,
    player_id: str,
    tableau_effect_intents: dict[str, dict[str, Any]] | None = None,
    resolution_stage: str | None = None,
) -> GameState:
    if resolution_stage not in {None, "scouts", "remaining"}:
        raise ValueError(f"Unknown tableau resolution stage: {resolution_stage}")
    player = state.players[player_id]
    _sync_role_slot_assignments(state, player_id=player_id)
    monks_resolved = False
    missionaries_resolved = False
    alignment_resolved = False
    turn_start_missionary_steal_intent = (
        None if tableau_effect_intents is None else tableau_effect_intents.get("turn_start_missionary_steal")
    )
    alignment_effect_intent = (
        None if tableau_effect_intents is None else tableau_effect_intents.get("alignment_effect")
    )

    cards = _get_tableau_resolution_order(player)
    if resolution_stage == "scouts":
        cards = [card for card in cards if card.category == "Aufklärer"]
    elif resolution_stage == "remaining":
        cards = [card for card in cards if card.category != "Aufklärer"]
    for card in cards:
        if (
            not alignment_resolved
            and TABLEAU_RESOLUTION_PRIORITIES.get(card.category, 100)
            > TABLEAU_RESOLUTION_PRIORITIES["Gesinnung"]
        ):
            _resolve_alignment_tableau_effect(
                state,
                player_id=player_id,
                effect_intent=alignment_effect_intent,
            )
            alignment_resolved = True
        append_event(
            state.event_log,
            "tableau_card_resolved",
            player_id=player_id,
            card_id=card.card_id,
            category=card.category,
        )
        if card.category == "Aufklärer" and not is_tableau_card_disabled(state, player_id=player_id, card=card):
            _resolve_enlightener_tableau_effect(
                state,
                player_id=player_id,
                card=card,
                effect_intent=None if tableau_effect_intents is None else tableau_effect_intents.get(card.card_id),
            )
        if card.category == "Reliquie" and is_tableau_card_active(state, player_id=player_id, card=card):
            _resolve_relic_tableau_effect(
                state,
                player_id=player_id,
                card=card,
                effect_intent=None if tableau_effect_intents is None else tableau_effect_intents.get(card.card_id),
            )
        if card.category == "Mönche" and not monks_resolved:
            resolve_role_production(state, player_id=player_id)
            monks_resolved = True
        if card.category == "Missionare" and not missionaries_resolved:
            _resolve_turn_start_missionary_steal(
                state,
                player_id=player_id,
                effect_intent=turn_start_missionary_steal_intent,
            )
            missionaries_resolved = True
        if "tableau_stub_label" in card.metadata:
            raise ValueError(
                f"Unsupported tableau effect placeholder {card.metadata['tableau_stub_label']} on card {card.card_id}."
            )
    if resolution_stage == "scouts":
        return state
    if not alignment_resolved:
        _resolve_alignment_tableau_effect(
            state,
            player_id=player_id,
            effect_intent=alignment_effect_intent,
        )
    if not monks_resolved and _get_assigned_role_meeples(state, player_id=player_id, role_type="Mönche") > 0:
        resolve_role_production(state, player_id=player_id)
    if not missionaries_resolved and _get_assigned_role_meeples(state, player_id=player_id, role_type="Missionare") > 0:
        _resolve_turn_start_missionary_steal(
            state,
            player_id=player_id,
            effect_intent=turn_start_missionary_steal_intent,
        )
    return state


def _get_alignment_tableau_target_player_ids(state: GameState, *, player_id: str) -> list[str]:
    return [
        candidate_player_id
        for candidate_player_id in _get_opponent_player_ids_in_turn_order(state, player_id=player_id)
        if state.players[candidate_player_id].meeples > 0
    ]


def _get_next_alignment_tableau_target_player_id(
    state: GameState,
    *,
    player_id: str,
    target_player_id: str | None = None,
) -> tuple[str | None, str]:
    candidates = _get_alignment_tableau_target_player_ids(state, player_id=player_id)
    if target_player_id is not None:
        if target_player_id == player_id:
            raise ValueError(f"Player {player_id} cannot target themselves with alignment tableau.")
        if target_player_id not in candidates:
            raise ValueError(f"Player {player_id} cannot target {target_player_id} right now.")
        return target_player_id, "explicit_intent"
    if not candidates:
        return None, "no_valid_target"
    return candidates[0], "turn_order_default"


CHAOS_ALIGNMENT_FACE_DETAILS: dict[int, dict[str, Any]] = {
    1: {
        "effect_kind": "chaos_baptism",
        "label": "1 Gläubigen taufen",
        "short_label": "+1 taufen",
        "requires_target": False,
    },
    2: {
        "effect_kind": "chaos_self_sacrifice",
        "label": "1 Gläubigen opfern",
        "short_label": "-1 selbst",
        "requires_target": False,
    },
    3: {
        "effect_kind": "chaos_opponent_sacrifice",
        "label": "1 Mitgott opfert 1",
        "short_label": "Mitgott opfert 1",
        "requires_target": True,
    },
    4: {
        "effect_kind": "chaos_missionize",
        "label": "1 missionieren",
        "short_label": "1 missionieren",
        "requires_target": True,
    },
    5: {
        "effect_kind": "chaos_baptism",
        "label": "2 Gläubige taufen",
        "short_label": "+2 taufen",
        "requires_target": False,
    },
    6: {
        "effect_kind": "chaos_nothing",
        "label": "Niete",
        "short_label": "Niete",
        "requires_target": False,
    },
}


def get_chaos_alignment_face_details(face: int) -> dict[str, Any]:
    normalized_face = int(face)
    if normalized_face not in CHAOS_ALIGNMENT_FACE_DETAILS:
        raise ValueError(f"Chaos alignment face must be between 1 and 6, got {face!r}.")
    return dict(CHAOS_ALIGNMENT_FACE_DETAILS[normalized_face])


def _count_prior_chaos_alignment_rolls(state: GameState, *, player_id: str) -> int:
    return sum(
        1
        for event in state.event_log
        if str(event.get("type") or "") == "alignment_tableau_effect_resolved"
        and str(event.get("player_id") or "") == player_id
        and str(event.get("effect_kind") or "").startswith("chaos_")
    )


def roll_chaos_alignment_face(state: GameState, *, player_id: str) -> int:
    if player_id not in state.players:
        raise ValueError(f"Unknown chaos alignment player {player_id}.")
    player_index = state.player_order.index(player_id) if player_id in state.player_order else 0
    prior_rolls = _count_prior_chaos_alignment_rolls(state, player_id=player_id)
    seed = (
        int(state.seed or 0) * 1_000_003
        + int(state.round_number or 0) * 10_007
        + int(state.turn_number or 0) * 1_009
        + (player_index + 1) * 97
        + prior_rolls * 31
    )
    rng = SeededRNG(seed=seed)
    return int(rng.shuffle([1, 2, 3, 4, 5, 6])[0])


def _resolve_alignment_tableau_effect(
    state: GameState,
    *,
    player_id: str,
    effect_intent: dict[str, Any] | None,
) -> None:
    player = state.players[player_id]
    alignment = player.alignment
    pure_alignment = get_pure_alignment(player)
    if pure_alignment in {"<Sanftmut>", "<Zorn>", "<Chaos>"} and pure_alignment == alignment:
        append_event(
            state.event_log,
            "alignment_tableau_effect_resolved",
            player_id=player_id,
            alignment=alignment,
            pure_alignment=pure_alignment,
            effect_kind="pure_alignment_replaces_base_effect",
            actual_gain=0,
            actual_loss=0,
            actual_transfer=0,
            meeples_after=player.meeples,
        )
        return
    if alignment == "<Sanftmut>":
        gain_amount = 1
        player.meeples += gain_amount
        append_event(
            state.event_log,
            "alignment_tableau_effect_resolved",
            player_id=player_id,
            alignment=alignment,
            effect_kind="sanftmut_baptism",
            gain_amount=gain_amount,
            actual_gain=gain_amount,
            meeples_after=player.meeples,
        )
        return
    if alignment == "<Zorn>":
        raw_target_player_id = None if effect_intent is None else effect_intent.get("target_player_id")
        if raw_target_player_id is not None and not isinstance(raw_target_player_id, str):
            raise ValueError("Alignment tableau intent must use string target_player_id.")
        target_player_id, decision_source = _get_next_alignment_tableau_target_player_id(
            state,
            player_id=player_id,
            target_player_id=raw_target_player_id,
        )
        if target_player_id is None:
            append_event(
                state.event_log,
                "alignment_tableau_effect_resolved",
                player_id=player_id,
                alignment=alignment,
                effect_kind="zorn_strike",
                target_player_id=None,
                loss_amount=1,
                actual_loss=0,
                decision_source=decision_source,
                meeples_after=player.meeples,
            )
            return
        target_player = state.players[target_player_id]
        actual_loss = min(1, target_player.meeples)
        if actual_loss > 0:
            target_player.meeples -= actual_loss
            state.last_meeple_taker_by_victim[target_player_id] = player_id
        append_event(
            state.event_log,
            "alignment_tableau_effect_resolved",
            player_id=player_id,
            alignment=alignment,
            effect_kind="zorn_strike",
            target_player_id=target_player_id,
            loss_amount=1,
            actual_loss=actual_loss,
            decision_source=decision_source,
            target_meeples_after=target_player.meeples,
            meeples_after=player.meeples,
        )
        return
    if alignment == "<Chaos>":
        raw_face = None if effect_intent is None else effect_intent.get("chaos_face")
        if isinstance(raw_face, str):
            raw_face = raw_face.strip()
            if raw_face.isdigit():
                raw_face = int(raw_face)
        if raw_face is None:
            chaos_face = roll_chaos_alignment_face(state, player_id=player_id)
        elif isinstance(raw_face, int) and not isinstance(raw_face, bool):
            chaos_face = int(raw_face)
        else:
            raise ValueError("Chaos tableau intent must use integer chaos_face.")
        face_details = get_chaos_alignment_face_details(chaos_face)
        effect_kind = str(face_details["effect_kind"])
        raw_target_player_id = None if effect_intent is None else effect_intent.get("target_player_id")
        if raw_target_player_id is not None and not isinstance(raw_target_player_id, str):
            raise ValueError("Chaos tableau intent must use string target_player_id.")

        if effect_kind == "chaos_baptism":
            gain_amount = 2 if chaos_face == 5 else 1
            player.meeples += gain_amount
            append_event(
                state.event_log,
                "alignment_tableau_effect_resolved",
                player_id=player_id,
                alignment=alignment,
                chaos_face=chaos_face,
                chaos_label=face_details["label"],
                effect_kind=effect_kind,
                gain_amount=gain_amount,
                actual_gain=gain_amount,
                meeples_after=player.meeples,
            )
            return

        if effect_kind == "chaos_self_sacrifice":
            sacrifice_amount = 1
            effective_sacrifice_amount = _apply_sacrifice_cost_reduction(
                state,
                player_id=player_id,
                amount=sacrifice_amount,
            )
            actual_sacrifice = min(effective_sacrifice_amount, player.meeples)
            if actual_sacrifice > 0:
                player.meeples -= actual_sacrifice
            append_event(
                state.event_log,
                "alignment_tableau_effect_resolved",
                player_id=player_id,
                alignment=alignment,
                chaos_face=chaos_face,
                chaos_label=face_details["label"],
                effect_kind=effect_kind,
                sacrifice_amount=sacrifice_amount,
                effective_sacrifice_amount=effective_sacrifice_amount,
                actual_sacrifice=actual_sacrifice,
                meeples_after=player.meeples,
            )
            return

        if effect_kind == "chaos_opponent_sacrifice":
            target_player_id, decision_source = _get_next_missionary_target_player_id(
                state,
                player_id=player_id,
                target_player_id=raw_target_player_id,
            )
            if target_player_id is None:
                append_event(
                    state.event_log,
                    "alignment_tableau_effect_resolved",
                    player_id=player_id,
                    alignment=alignment,
                    chaos_face=chaos_face,
                    chaos_label=face_details["label"],
                    effect_kind=effect_kind,
                    target_player_id=None,
                    loss_amount=1,
                    actual_loss=0,
                    decision_source=decision_source,
                    meeples_after=player.meeples,
                )
                return
            target_player = state.players[target_player_id]
            actual_loss = min(1, target_player.meeples)
            if actual_loss > 0:
                target_player.meeples -= actual_loss
                state.last_meeple_taker_by_victim[target_player_id] = player_id
            append_event(
                state.event_log,
                "alignment_tableau_effect_resolved",
                player_id=player_id,
                alignment=alignment,
                chaos_face=chaos_face,
                chaos_label=face_details["label"],
                effect_kind=effect_kind,
                target_player_id=target_player_id,
                loss_amount=1,
                actual_loss=actual_loss,
                decision_source=decision_source,
                target_meeples_after=target_player.meeples,
                meeples_after=player.meeples,
            )
            return

        if effect_kind == "chaos_missionize":
            target_player_id, decision_source = _get_next_missionary_target_player_id(
                state,
                player_id=player_id,
                target_player_id=raw_target_player_id,
            )
            if target_player_id is None:
                append_event(
                    state.event_log,
                    "alignment_tableau_effect_resolved",
                    player_id=player_id,
                    alignment=alignment,
                    chaos_face=chaos_face,
                    chaos_label=face_details["label"],
                    effect_kind=effect_kind,
                    target_player_id=None,
                    transfer_amount=1,
                    actual_transfer=0,
                    decision_source=decision_source,
                    meeples_after=player.meeples,
                )
                return
            target_player = state.players[target_player_id]
            actual_transfer = min(1, target_player.meeples)
            if actual_transfer > 0:
                target_player.meeples -= actual_transfer
                player.meeples += actual_transfer
                state.last_meeple_taker_by_victim[target_player_id] = player_id
            append_event(
                state.event_log,
                "alignment_tableau_effect_resolved",
                player_id=player_id,
                alignment=alignment,
                chaos_face=chaos_face,
                chaos_label=face_details["label"],
                effect_kind=effect_kind,
                target_player_id=target_player_id,
                transfer_amount=1,
                actual_transfer=actual_transfer,
                decision_source=decision_source,
                target_meeples_after=target_player.meeples,
                meeples_after=player.meeples,
            )
            return

        append_event(
            state.event_log,
            "alignment_tableau_effect_resolved",
            player_id=player_id,
            alignment=alignment,
            chaos_face=chaos_face,
            chaos_label=face_details["label"],
            effect_kind="chaos_nothing",
            meeples_after=player.meeples,
        )
        return
    append_event(
        state.event_log,
        "alignment_tableau_effect_resolved",
        player_id=player_id,
        alignment=alignment,
        effect_kind="none",
        meeples_after=player.meeples,
    )


def _get_tableau_resolution_order(player: PlayerState) -> list[CardRef]:
    indexed_cards = list(enumerate(player.tableau))
    indexed_cards.sort(
        key=lambda item: (
            TABLEAU_RESOLUTION_PRIORITIES.get(item[1].category, 100),
            item[0],
        )
    )
    return [card for _, card in indexed_cards]


def _resolve_enlightener_tableau_effect(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
    effect_intent: dict[str, Any] | None = None,
) -> None:
    rules_text = _get_card_rules_text(card)
    player = state.players[player_id]

    if ENLIGHTENER_SACRIFICE_TWO_TEXT in rules_text:
        sacrifice_amount = 2
        effective_sacrifice_amount = _apply_sacrifice_cost_reduction(
            state,
            player_id=player_id,
            amount=sacrifice_amount,
        )
        payment_resolution = _spend_player_meeples(
            state,
            player_id=player_id,
            amount=effective_sacrifice_amount,
            strict=False,
            payment_choice=None if effect_intent is None else effect_intent.get("sacrifice_payment_choice"),
            purpose="enlightener_sacrifice",
        )
        append_event(
            state.event_log,
            "enlightener_tableau_effect_resolved",
            player_id=player_id,
            card_id=card.card_id,
            effect_kind="sacrifice_meeples",
            sacrifice_amount=sacrifice_amount,
            effective_sacrifice_amount=effective_sacrifice_amount,
            actual_sacrifice=payment_resolution["paid_total"],
            free_meeples_paid=payment_resolution["free_meeples_paid"],
            role_meeples_paid=dict(payment_resolution["role_meeples_paid"]),
            prepared_nuns_paid=payment_resolution["prepared_nuns_paid"],
            meeples_after=player.meeples,
        )
        return

    if ENLIGHTENER_RIGHT_PLAYER_MISSIONIZES_TWO_TEXT in rules_text:
        _resolve_enlightener_forced_missionize(
            state,
            player_id=player_id,
            card=card,
            effect_kind="right_player_missionizes",
            relative_offset=-1,
        )
        return

    if ENLIGHTENER_LEFT_PLAYER_MISSIONIZES_TWO_TEXT in rules_text:
        _resolve_enlightener_forced_missionize(
            state,
            player_id=player_id,
            card=card,
            effect_kind="left_player_missionizes",
            relative_offset=1,
        )
        return

    if ENLIGHTENER_OPPONENT_DISCARDS_OWNER_HAND_CARD_TEXT in rules_text:
        _resolve_enlightener_forced_hand_discard(
            state,
            player_id=player_id,
            card=card,
            effect_intent=effect_intent,
        )
        return

    if ENLIGHTENER_RETURN_ONE_TEMPLE_MEEPLE_TEXT in rules_text:
        _resolve_enlightener_return_temple_meeple(
            state,
            player_id=player_id,
            card=card,
            effect_intent=effect_intent,
        )
        return

    if ENLIGHTENER_SET_ALIGNMENT_UNERGRUENDLICH_TEXT in rules_text:
        alignment_changed = player.alignment != "<Unergründlich>"
        if alignment_changed:
            apply_alignment_change(state, player_id=player_id, new_alignment="<Unergründlich>")
        append_event(
            state.event_log,
            "enlightener_tableau_effect_resolved",
            player_id=player_id,
            card_id=card.card_id,
            effect_kind="set_alignment_unergruendlich",
            alignment_changed=alignment_changed,
            alignment_after=state.players[player_id].alignment,
        )
        return


def _resolve_enlightener_forced_missionize(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
    effect_kind: str,
    relative_offset: int,
) -> None:
    player = state.players[player_id]
    target_player_id = _get_relative_player_id(state, player_id=player_id, offset=relative_offset)
    target_player = state.players[target_player_id]
    missionize_amount = 2
    if _is_player_immune_to_missionizing(state, player_id=target_player_id):
        actual_transfer = 0
        resolution_reason = "target_is_pure_gentleness"
    else:
        actual_transfer = min(player.meeples, missionize_amount)
        player.meeples -= actual_transfer
        target_player.meeples += actual_transfer
        state.last_meeple_taker_by_victim[player_id] = target_player_id
        resolution_reason = "resolved"
    append_event(
        state.event_log,
        "enlightener_tableau_effect_resolved",
        player_id=player_id,
        card_id=card.card_id,
        effect_kind=effect_kind,
        target_player_id=target_player_id,
        missionize_amount=missionize_amount,
        actual_transfer=actual_transfer,
        resolution_reason=resolution_reason,
        player_meeples_after=player.meeples,
        target_meeples_after=target_player.meeples,
    )


def _resolve_enlightener_forced_hand_discard(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
    effect_intent: dict[str, Any] | None,
) -> None:
    player = state.players[player_id]
    eligible_target_player_ids = [
        candidate_player_id
        for candidate_player_id in _get_turn_order_from_player(state, player_id=player_id)
        if candidate_player_id in set(_get_opponent_player_ids_in_turn_order(state, player_id=player_id))
    ]

    if not player.hand_cards:
        append_event(
            state.event_log,
            "enlightener_tableau_effect_resolved",
            player_id=player_id,
            card_id=card.card_id,
            effect_kind="opponent_discards_owner_hand_card",
            target_player_id=None,
            discarded_card_id=None,
            discarded_category=None,
            discard_zone=None,
            decision_source="no_hand_cards",
            hand_size_after=len(player.hand_cards),
        )
        return

    explicit_target_player_id = None if effect_intent is None else effect_intent.get("target_player_id")
    if explicit_target_player_id is not None and not isinstance(explicit_target_player_id, str):
        raise ValueError(f"Tableau effect intent for {card.card_id} must use string target_player_id.")

    if effect_intent is not None and "discarded_card_id" in effect_intent:
        raise ValueError(
            f"Tableau effect intent for {card.card_id} must not specify discarded_card_id; Helga is resolved as blind discard."
        )

    explicit_blind_pick_index = None if effect_intent is None else effect_intent.get("blind_pick_index")
    if explicit_blind_pick_index is not None and not isinstance(explicit_blind_pick_index, int):
        raise ValueError(f"Tableau effect intent for {card.card_id} must use integer blind_pick_index.")

    if explicit_target_player_id is not None:
        if explicit_target_player_id not in eligible_target_player_ids:
            raise ValueError(
                f"Player {player_id} cannot target {explicit_target_player_id} with {card.card_id}."
            )
        target_player_id = explicit_target_player_id
        decision_source = "explicit_intent"
    else:
        target_player_id = eligible_target_player_ids[0] if eligible_target_player_ids else None
        decision_source = "auto_policy"

    if target_player_id is None:
        append_event(
            state.event_log,
            "enlightener_tableau_effect_resolved",
            player_id=player_id,
            card_id=card.card_id,
            effect_kind="opponent_discards_owner_hand_card",
            target_player_id=None,
            discarded_card_id=None,
            discarded_category=None,
            discard_zone=None,
            decision_source="no_target_player",
            hand_size_after=len(player.hand_cards),
        )
        return

    if explicit_blind_pick_index is not None:
        if explicit_blind_pick_index < 0 or explicit_blind_pick_index >= len(player.hand_cards):
            raise ValueError(
                f"Player {player_id} cannot resolve blind pick index {explicit_blind_pick_index} for {card.card_id}."
            )
        discarded_card = player.hand_cards.pop(explicit_blind_pick_index)
        blind_pick_index = explicit_blind_pick_index
    else:
        discarded_card = player.hand_cards.pop(0)
        blind_pick_index = 0

    discard_zone = _discard_forced_hand_card(
        state,
        player_id=player_id,
        card=discarded_card,
    )
    append_event(
        state.event_log,
        "enlightener_tableau_effect_resolved",
        player_id=player_id,
        card_id=card.card_id,
        effect_kind="opponent_discards_owner_hand_card",
        target_player_id=target_player_id,
        chooser_player_id=target_player_id,
        blind_pick_index=blind_pick_index,
        discarded_card_id=discarded_card.card_id,
        discarded_category=discarded_card.category,
        discard_zone=discard_zone,
        decision_source=decision_source,
        hand_size_after=len(player.hand_cards),
    )


def _resolve_enlightener_return_temple_meeple(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
    effect_intent: dict[str, Any] | None,
) -> None:
    player = state.players[player_id]
    occupied_role_types = [
        role_type
        for role_type in ROLE_TYPES
        if _get_assigned_role_meeples(state, player_id=player_id, role_type=role_type) > 0
    ]
    if not occupied_role_types:
        append_event(
            state.event_log,
            "enlightener_tableau_effect_resolved",
            player_id=player_id,
            card_id=card.card_id,
            effect_kind="return_temple_meeple",
            chosen_role_type=None,
            actual_returned=0,
            decision_source="no_available_temple",
            meeples_after=player.meeples,
        )
        return

    explicit_role_type = None if effect_intent is None else effect_intent.get("role_type")
    if explicit_role_type is not None and not isinstance(explicit_role_type, str):
        raise ValueError(f"Tableau effect intent for {card.card_id} must use string role_type.")
    if explicit_role_type is not None:
        if explicit_role_type not in occupied_role_types:
            raise ValueError(
                f"Player {player_id} cannot return a temple meeple from role {explicit_role_type} for {card.card_id}."
            )
        chosen_role_type = explicit_role_type
        decision_source = "explicit_intent"
    else:
        chosen_role_type = _choose_abdul_return_role_type(state, player_id=player_id, occupied_role_types=occupied_role_types)
        decision_source = "auto_policy"

    if _player_has_temple_loss_protection_relic(state, player_id=player_id):
        append_event(
            state.event_log,
            "enlightener_tableau_effect_resolved",
            player_id=player_id,
            card_id=card.card_id,
            effect_kind="return_temple_meeple",
            chosen_role_type=chosen_role_type,
            actual_returned=0,
            decision_source="temple_protected",
            meeples_after=player.meeples,
            remaining_assigned_role_meeples=player.assigned_role_meeples[chosen_role_type],
        )
        return

    returned_prepared_nuns = 0
    if chosen_role_type == "Nonnen":
        assigned_nuns = max(0, int(player.assigned_role_meeples.get("Nonnen", 0)))
        prepared_nuns = max(0, int(player.nunnery_state.prepared_nuns))
        unprepared_nuns = max(0, assigned_nuns - prepared_nuns)
        if unprepared_nuns <= 0 and prepared_nuns > 0:
            player.nunnery_state.prepared_nuns = prepared_nuns - 1
            returned_prepared_nuns = 1

    player.assigned_role_meeples[chosen_role_type] -= 1
    player.meeples += 1
    append_event(
        state.event_log,
        "enlightener_tableau_effect_resolved",
        player_id=player_id,
        card_id=card.card_id,
        effect_kind="return_temple_meeple",
        chosen_role_type=chosen_role_type,
        actual_returned=1,
        decision_source=decision_source,
        meeples_after=player.meeples,
        remaining_assigned_role_meeples=player.assigned_role_meeples[chosen_role_type],
        returned_prepared_nuns=returned_prepared_nuns,
        prepared_nuns_remaining=player.nunnery_state.prepared_nuns,
    )


def take_actions(
    state: GameState,
    *,
    player_id: str,
    actions_available: int = 2,
    action_intents: list[dict[str, Any] | str] | None = None,
    role_action_intents: dict[str, dict[str, Any]] | None = None,
    require_explicit_action_intents: bool | None = None,
) -> GameState:
    legal_action_cards = get_legal_action_hand_cards(state, player_id=player_id)
    legal_role_types, inactive_role_types = get_legal_action_role_types(state, player_id=player_id)
    effective_action_intents = _merge_legacy_role_action_intents(
        state,
        player_id=player_id,
        action_intents=action_intents,
        role_action_intents=role_action_intents,
    )
    if not action_intents:
        _validate_role_action_intents(
            state,
            player_id=player_id,
            legal_role_types=legal_role_types,
            role_action_intents=role_action_intents,
        )
    normalized_action_intents = _normalize_action_intents(
        state,
        player_id=player_id,
        legal_role_types=legal_role_types,
        legal_action_card_ids=[card.card_id for card in legal_action_cards],
        action_intents=effective_action_intents,
    )
    explicit_actions_required = (
        state.require_explicit_action_intents
        if require_explicit_action_intents is None
        else require_explicit_action_intents
    )
    append_event(
        state.event_log,
        "take_actions_started",
        player_id=player_id,
        actions_available=actions_available,
        legal_action_card_ids=[card.card_id for card in legal_action_cards],
        legal_role_types=legal_role_types,
        inactive_role_types=inactive_role_types,
        action_intent_count=len(normalized_action_intents),
        role_action_intent_types=sorted((role_action_intents or {}).keys()),
        explicit_actions_required=explicit_actions_required,
    )

    if explicit_actions_required and actions_available > 0 and not normalized_action_intents:
        raise ValueError(
            f"Player {player_id} must provide explicit action_intents when require_explicit_action_intents is enabled."
        )

    actions_taken = 0
    total_actions_available = max(0, actions_available)
    remaining_actions = total_actions_available
    resolved_role_actions: list[str] = []
    resolved_hand_card_actions: list[str] = []
    resolved_power_actions: list[str] = []
    resolved_phenomenon_actions: list[str] = []
    resolved_grenade_actions: list[int] = []
    skipped_action_count = 0
    action_slots_consumed = 0
    phenomenon_action_count = 0
    bonus_actions_granted_total = 0
    if normalized_action_intents:
        intent_index = 0
        while intent_index < len(normalized_action_intents):
            action_intent = normalized_action_intents[intent_index]
            intent_index += 1
            if action_intent["action"] == "use_monument_bonus":
                player = state.players[player_id]
                if player.stored_monument_bonus_actions <= 0:
                    raise ValueError("Keine gespeicherte Monument-Zusatzaktion verfügbar.")
                player.stored_monument_bonus_actions -= 1
                player.bonus_actions_this_turn += 1
                remaining_actions += 1
                bonus_actions_granted_total += 1
                append_event(
                    state.event_log, "monument_bonus_action_used", player_id=player_id,
                    bonus_actions_granted=1, remaining_actions=remaining_actions,
                    stored_bonus_actions=player.stored_monument_bonus_actions,
                )
                continue
            if remaining_actions <= 0:
                raise ValueError(f"Player {player_id} provided more normal actions than available.")

            if action_intent["action"] == "skip":
                skipped_action_count += 1
                action_slots_consumed += 1
                remaining_actions -= 1
                append_event(
                    state.event_log,
                    "action_skipped",
                    player_id=player_id,
                    action_index=action_slots_consumed,
                    decision_source="explicit_intent",
                )
            elif action_intent["action"] == "play_hand_card":
                play_hand_card(
                    state,
                    player_id=player_id,
                    card_id=action_intent["card_id"],
                    effect_payload=action_intent.get("effect_payload"),
                    decision_source="explicit_intent",
                )
                resolved_hand_card_actions.append(action_intent["card_id"])
                actions_taken += 1
                action_slots_consumed += 1
                remaining_actions -= 1
            elif action_intent["action"] == "unleash_stored_power":
                event_start_idx = len(state.event_log)
                unleash_stored_power(
                    state,
                    player_id=player_id,
                    phenomenon_card_id=action_intent["phenomenon_card_id"],
                    payment_choice=action_intent.get("payment_choice"),
                    effect_payload=action_intent.get("effect_payload"),
                    decision_source="explicit_intent",
                )
                resolved_power_actions.append(action_intent["phenomenon_card_id"])
                actions_taken += 1
                action_slots_consumed += 1
                remaining_actions -= 1
                granted_bonus_actions = 0
                for event in state.event_log[event_start_idx:]:
                    if event.get("type") != "stored_power_effect_resolved":
                        continue
                    if str(event.get("player_id") or "") != player_id:
                        continue
                    if str(event.get("phenomenon_card_id") or "") != str(action_intent["phenomenon_card_id"]):
                        continue
                    granted_bonus_actions = max(granted_bonus_actions, int(event.get("bonus_actions_granted") or 0))
                if granted_bonus_actions > 0:
                    remaining_actions += granted_bonus_actions
                    bonus_actions_granted_total += granted_bonus_actions
            elif action_intent["action"] == "prophet_send":
                pass_prophet(
                    state,
                    from_player_id=player_id,
                    to_player_id=action_intent["target_player_id"],
                    squirrel_draw_counts=action_intent.get("squirrel_draw_counts"),
                )
                actions_taken += 1
                action_slots_consumed += 1
                remaining_actions -= 1
            elif action_intent["action"] == "play_stored_phenomenon_action":
                played_phenomenon_id = play_stored_phenomenon_action(
                    state,
                    player_id=player_id,
                    phenomenon_id=action_intent.get("phenomenon_id"),
                    action_name=action_intent.get("action_name", "stored_phenomenon_action"),
                    decision_source="explicit_intent",
                )
                resolved_phenomenon_actions.append(played_phenomenon_id)
                actions_taken += 1
                action_slots_consumed += 1
                remaining_actions -= 1
                phenomenon_action_count += 1
            elif action_intent["action"] == "grenade":
                event_start_idx = len(state.event_log)
                resolved_grenade_actions.append(
                    _resolve_grenade_action(
                        state,
                        player_id=player_id,
                        target_level=action_intent["level"],
                        detonate=bool(action_intent.get("detonate", False)),
                        effect_payload=action_intent.get("effect_payload"),
                        decision_source="explicit_intent",
                    )
                )
                actions_taken += 1
                action_slots_consumed += 1
                remaining_actions -= 1
                granted_bonus_actions = 0
                for event in state.event_log[event_start_idx:]:
                    if event.get("type") != "grenade_tier_effect_resolved":
                        continue
                    if str(event.get("player_id") or "") != player_id:
                        continue
                    granted_bonus_actions = max(granted_bonus_actions, int(event.get("bonus_actions_granted") or 0))
                if granted_bonus_actions > 0:
                    remaining_actions += granted_bonus_actions
                    bonus_actions_granted_total += granted_bonus_actions
            else:
                event_start_idx = len(state.event_log)
                resolved_role_type = _resolve_specific_role_action(
                    state,
                    player_id=player_id,
                    role_type=action_intent["role_type"],
                    legal_role_types=legal_role_types,
                    already_used_role_types=resolved_role_actions,
                    role_action_intent=action_intent.get("role_action_intent"),
                )
                if resolved_role_type is None:
                    raise ValueError(
                        f"Player {player_id} could not resolve explicit action intent for role {action_intent['role_type']}."
                    )
                resolved_role_actions.append(resolved_role_type)
                actions_taken += 1
                action_slots_consumed += 1
                remaining_actions -= 1
                granted_bonus_actions = 0
                for event in state.event_log[event_start_idx:]:
                    if event.get("type") != "monument_line_bonus_resolved":
                        continue
                    if str(event.get("player_id") or "") != player_id:
                        continue
                    granted_bonus_actions = max(granted_bonus_actions, int(event.get("bonus_actions_granted") or 0))
                if granted_bonus_actions > 0:
                    remaining_actions += granted_bonus_actions
                    bonus_actions_granted_total += granted_bonus_actions
    else:
        while remaining_actions > 0:
            event_start_idx = len(state.event_log)
            resolved_role_type = _resolve_next_role_action(
                state,
                player_id=player_id,
                legal_role_types=legal_role_types,
                already_used_role_types=resolved_role_actions,
            )
            if resolved_role_type is None:
                break
            resolved_role_actions.append(resolved_role_type)
            actions_taken += 1
            action_slots_consumed += 1
            remaining_actions -= 1
            granted_bonus_actions = 0
            for event in state.event_log[event_start_idx:]:
                if event.get("type") != "monument_line_bonus_resolved":
                    continue
                if str(event.get("player_id") or "") != player_id:
                    continue
                granted_bonus_actions = max(granted_bonus_actions, int(event.get("bonus_actions_granted") or 0))
            if granted_bonus_actions > 0:
                remaining_actions += granted_bonus_actions
                bonus_actions_granted_total += granted_bonus_actions

    append_event(
        state.event_log,
        "take_actions_resolved",
        player_id=player_id,
        actions_available=total_actions_available,
        actions_taken=actions_taken,
        action_slots_consumed=action_slots_consumed,
        remaining_actions=remaining_actions,
        skipped_action_count=skipped_action_count,
        phenomenon_action_count=phenomenon_action_count,
        phenomenon_extra_action_used=phenomenon_action_count > 0,
        bonus_actions_granted=bonus_actions_granted_total,
        resolved_role_actions=resolved_role_actions,
        resolved_hand_card_actions=resolved_hand_card_actions,
        resolved_power_actions=resolved_power_actions,
        resolved_phenomenon_actions=resolved_phenomenon_actions,
        resolved_grenade_actions=resolved_grenade_actions,
    )
    # TODO: Replace remaining stub with broader hand-card action selection beyond the first blessing subset.
    # Truth cards are intentionally excluded here and are only usable during phenomenon contests.
    return state


def resolve_role_production(state: GameState, *, player_id: str) -> GameState:
    player = state.players[player_id]
    _sync_role_slot_assignments(state, player_id=player_id)
    recalculate_commandment_effects(state)

    for role_type, base_per_card in ROLE_BASE_PRODUCTION.items():
        role_card_count = sum(1 for card in player.tableau if card.category == role_type)
        assigned_role_meeples = _get_assigned_role_meeples(
            state,
            player_id=player_id,
            role_type=role_type,
        )
        if role_card_count == 0 and assigned_role_meeples <= 0:
            continue
        active = is_role_active(state, player_id=player_id, role_type=role_type)
        modifier = get_role_production_modifier(state, player_id=player_id, role_type=role_type)
        if role_type == "Mönche":
            modifier += 2 * _count_active_relic_rule_text(
                state,
                player_id=player_id,
                text=RELIC_MONK_PRODUCTION_TEXT,
            )
        produced_meeples = 0
        if active and assigned_role_meeples > 0:
            produced_meeples = max(0, assigned_role_meeples * base_per_card + modifier)
            player.meeples += produced_meeples

        append_event(
            state.event_log,
            "role_production_resolved",
            player_id=player_id,
            role_type=role_type,
            role_card_count=role_card_count,
            assigned_role_meeples=assigned_role_meeples,
            active=active,
            base_per_card=base_per_card,
            modifier=modifier,
            produced_meeples=produced_meeples,
            meeples_after=player.meeples,
        )

    return state


def draw_step(state: GameState, *, player_id: str) -> GameState:
    player = state.players[player_id]
    override_hand_limit = player.temporary_draw_hand_limit_override
    hand_limit = override_hand_limit or (
        player.commandment_state.effective_hand_limit + _get_local_hand_limit_modifier(state, player_id=player_id)
    )
    hand_limit = max(0, hand_limit)
    cards_needed = max(0, hand_limit - len(player.hand_cards))
    append_event(
        state.event_log,
        "draw_step_started",
        player_id=player_id,
        hand_size=len(player.hand_cards),
        hand_limit=hand_limit,
        hand_limit_source="temporary_override" if override_hand_limit is not None else "commandment_state",
        heavenly_draw_pile_size=len(state.heavenly_draw_pile),
        cards_needed=cards_needed,
    )

    drawn_cards: list[CardRef] = []
    if cards_needed > 0:
        drawn_cards = _draw_to_hand_limit(state, player_id=player_id, cards_needed=cards_needed)

    append_event(
        state.event_log,
        "draw_step_resolved",
        player_id=player_id,
        hand_size=len(player.hand_cards),
        hand_limit=hand_limit,
        can_draw=len(player.hand_cards) < hand_limit and bool(state.heavenly_draw_pile or state.heavenly_discard_pile),
        cards_drawn=len(drawn_cards),
        drawn_card_ids=[card.card_id for card in drawn_cards],
        heavenly_draw_pile_size=len(state.heavenly_draw_pile),
        heavenly_discard_pile_size=len(state.heavenly_discard_pile),
    )
    player.temporary_draw_hand_limit_override = None
    # TODO: Add a dedicated truth draw model if Truth hand cards should be generated by decks in a later milestone.
    return state


def play_hand_card(
    state: GameState,
    *,
    player_id: str,
    card_id: str,
    effect_payload: dict[str, Any] | None = None,
    decision_source: str = "direct_call",
) -> GameState:
    player = state.players[player_id]
    effect_payload = effect_payload or {}
    card = _get_hand_card(player, card_id=card_id)
    if card.category == "Segen" and card.name == "Klagelied":
        _validate_free_believer_target_payments(
            state, player_id=player_id, effect_payload=effect_payload, context="Klagelied",
        )
    _validate_hand_card_action(state, player_id=player_id, card=card, effect_payload=effect_payload)

    card_cost_waived = is_card_cost_currently_waived(
        state,
        player_id=player_id,
        card=card,
    ) or _is_intrinsic_cost_waived_by_tableau(state, player_id=player_id, card=card)
    base_additional_cost = 0 if card_cost_waived else get_additional_cost_for_card(state, player_id=player_id, card=card)
    additional_cost = 0 if card_cost_waived else _get_effective_additional_cost_for_hand_card_payment(
        state,
        player_id=player_id,
        card=card,
        effect_payload=effect_payload,
    )
    additional_cost_reduction = max(0, base_additional_cost - additional_cost)
    additional_cost_reduction_sources = (
        _get_active_relic_names_with_rule_fragments(
            state,
            player_id=player_id,
            texts=(
                RELIC_REDUCES_SACRIFICE_COST_TEXT,
                RELIC_REDUCES_SACRIFICE_COST_VARIANT_TEXT,
            ),
        )
        if additional_cost_reduction > 0
        else []
    )
    if additional_cost > player.meeples:
        normalized_payment_choice = _normalize_meeple_payment_choice(
            effect_payload.get("additional_cost_payment_choice"),
            context=f"hand card {card.card_id} additional_cost_payment_choice",
        )
        if player.meeples + _count_bound_meeples_in_payment_choice(normalized_payment_choice) < additional_cost:
            raise ValueError(
                f"Player {player_id} cannot play card {card.card_id}; additional cost {additional_cost} exceeds available meeples {player.meeples}."
            )

    if card.category == "Heiliges Heer":
        # Validate the complete selected payment and target on an isolated state
        # before charging costs or removing the live hand card.
        payment_preview = copy.deepcopy(state)
        if additional_cost > 0:
            _spend_player_meeples(
                payment_preview, player_id=player_id, amount=additional_cost,
                strict=True, payment_choice=effect_payload.get("additional_cost_payment_choice"),
                purpose="hand_card_additional_cost",
            )
        _resolve_holy_army_play(
            payment_preview, player_id=player_id,
            card=_get_hand_card(payment_preview.players[player_id], card_id=card_id),
            effect_payload=effect_payload,
        )

    append_event(
        state.event_log,
        "hand_card_play_started",
        player_id=player_id,
        card_id=card.card_id,
        card_name=card.name,
        category=card.category,
        card_alignment=_get_card_alignment_from_card(card),
        decision_source=decision_source,
        additional_cost=additional_cost,
        base_additional_cost=base_additional_cost,
        additional_cost_reduction=additional_cost_reduction,
        additional_cost_reduction_sources=list(additional_cost_reduction_sources),
    )

    if additional_cost > 0:
        payment_resolution = _spend_player_meeples(
            state,
            player_id=player_id,
            amount=additional_cost,
            strict=True,
            payment_choice=effect_payload.get("additional_cost_payment_choice"),
            purpose="hand_card_additional_cost",
        )
        append_event(
            state.event_log,
            "hand_card_additional_cost_paid",
            player_id=player_id,
            card_id=card.card_id,
            card_name=card.name,
            category=card.category,
            additional_cost=additional_cost,
            base_additional_cost=base_additional_cost,
            additional_cost_reduction=additional_cost_reduction,
            additional_cost_reduction_sources=list(additional_cost_reduction_sources),
            free_meeples_paid=payment_resolution["free_meeples_paid"],
            role_meeples_paid=dict(payment_resolution["role_meeples_paid"]),
            prepared_nuns_paid=payment_resolution["prepared_nuns_paid"],
            meeples_after=player.meeples,
        )

    played_card = _pop_card_from_hand(player, card_id=card_id)
    intrinsic_cost_paid = 0
    if played_card.category == "Segen":
        _resolve_blessing_play(
            state,
            player_id=player_id,
            card=played_card,
            effect_payload=effect_payload,
        )
    elif played_card.category == "Heiliges Heer":
        _resolve_holy_army_play(
            state,
            player_id=player_id,
            card=played_card,
            effect_payload=effect_payload,
        )
    elif played_card.category == "Aufklärer":
        intrinsic_cost_paid = _resolve_enlightener_play(
            state,
            player_id=player_id,
            card=played_card,
            effect_payload=effect_payload,
        )
    elif played_card.category == "Reliquie":
        intrinsic_cost_paid = _resolve_relic_play(
            state,
            player_id=player_id,
            card=played_card,
            effect_payload=effect_payload,
        )
    else:
        raise ValueError(f"Playing hand card category {played_card.category} as a normal action is not implemented.")

    final_zone = "tableau"
    if played_card.category in {"Segen", "Heiliges Heer"}:
        state.heavenly_discard_pile.append(played_card)
        final_zone = "heavenly_discard_pile"
    append_event(
        state.event_log,
        "hand_card_played",
        player_id=player_id,
        card_id=played_card.card_id,
        card_name=played_card.name,
        category=played_card.category,
        card_alignment=_get_card_alignment_from_card(played_card),
        decision_source=decision_source,
        intrinsic_cost_paid=intrinsic_cost_paid,
        final_zone=final_zone,
        heavenly_discard_pile_size=len(state.heavenly_discard_pile),
    )
    return state


def play_phenomenon_contest(
    state: GameState,
    *,
    contested_card_id: str | None = None,
    contested_card_name: str | None = None,
    contested_card_alignment: str | None = None,
    manifest_requests: dict[str, bool | str | dict[str, Any]] | None = None,
    tie_manifest_requests: dict[str, str | dict[str, Any]] | None = None,
    nun_sacrifice_decisions: dict[str, bool] | None = None,
    contest_turn_intents: dict[str, list[dict[str, Any] | str] | dict[str, Any] | str] | None = None,
    phenomenon_prediction_guesses: dict[str, str] | None = None,
    require_explicit_turn_intents: bool | None = None,
) -> GameState:
    from .round import play_phenomenon_contest as play_phenomenon_contest_impl

    return play_phenomenon_contest_impl(
        state,
        contested_card_id=contested_card_id,
        contested_card_name=contested_card_name,
        contested_card_alignment=contested_card_alignment,
        manifest_requests=manifest_requests,
        tie_manifest_requests=tie_manifest_requests,
        nun_sacrifice_decisions=nun_sacrifice_decisions,
        contest_turn_intents=contest_turn_intents,
        phenomenon_prediction_guesses=phenomenon_prediction_guesses,
        require_explicit_turn_intents=require_explicit_turn_intents,
    )


def award_prophet(state: GameState, *, player_id: str) -> GameState:
    if state.beginner_mode:
        raise ValueError("The Prophet is disabled in beginner mode.")
    if state.first_phenomenon_claimed:
        raise ValueError("Prophet has already been awarded for the first claimed phenomenon.")

    for player in state.players.values():
        player.prophet_owner = False

    state.players[player_id].prophet_owner = True
    state.first_phenomenon_claimed = True
    append_event(state.event_log, "prophet_awarded", player_id=player_id)
    return state


def apply_alignment_change(
    state: GameState,
    *,
    player_id: str,
    new_alignment: str | None,
) -> GameState:
    player = state.players[player_id]
    old_alignment = player.alignment
    requested_alignment = new_alignment
    if (
        requested_alignment != "<Unergründlich>"
        and _player_has_friedrich_alignment_override(state, player_id=player_id)
    ):
        new_alignment = "<Unergründlich>"
    player.alignment = new_alignment
    player.phenomena_slots = 3 if player.alignment == "<Zorn>" else 2
    player.monks_slots = 4 if player.alignment == "<Sanftmut>" else 3
    player.missionaries_slots = 2
    player.nuns_slots = 2 if state.gods_twilight_triggered and player.alignment == "<Unergründlich>" else 1
    player.forge_slots = 3
    _refresh_player_monument_passives(state, player_id=player_id)

    append_event(
        state.event_log,
        "alignment_changed",
        player_id=player_id,
        old_alignment=old_alignment,
        new_alignment=new_alignment,
        requested_alignment=requested_alignment,
        alignment_override="friedrich" if requested_alignment != new_alignment else None,
        phenomena_slots=player.phenomena_slots,
        monks_slots=player.monks_slots,
        missionaries_slots=player.missionaries_slots,
        nuns_slots=player.nuns_slots,
        forge_slots=player.forge_slots,
    )
    append_event(
        state.event_log,
        "alignment_updated",
        player=player_id,
        player_id=player_id,
        manifested_counts=dict(player.manifested_parts_counts),
        manifested_parts_counts=dict(player.manifested_parts_counts),
        previous_alignment=old_alignment,
        computed_alignment=requested_alignment,
        old_alignment=old_alignment,
        new_alignment=player.alignment,
        alignment_update_applied=old_alignment != player.alignment,
        alignment_override="friedrich" if requested_alignment != player.alignment else None,
        alignment_resolution="direct_set",
        source="apply_alignment_change",
    )

    _sync_role_slot_assignments(
        state,
        player_id=player_id,
        log_slot_loss=True,
        reason=PHENOMENON_REMOVAL_SOURCE_ALIGNMENT_CHANGE,
    )
    recalculate_commandment_effects(state)

    while len(player.stored_phenomena) > _get_slot_limit(player, slot_kind="phenomena"):
        _discard_newest_stored_phenomenon_for_slot_loss(
            state,
            player_id=player_id,
            old_alignment=old_alignment,
            new_alignment=new_alignment,
            event_type="phenomenon_discarded_due_to_slot_loss",
            source=PHENOMENON_REMOVAL_SOURCE_ALIGNMENT_CHANGE,
        )

    return state


def _compute_alignment_with_resolution(manifested_parts: dict[str, int]) -> tuple[str, str]:
    normalized_counts: dict[str, int] = {}
    for alignment in MANIFEST_ALIGNMENT_KEYS:
        raw_count = manifested_parts.get(alignment, 0)
        try:
            parsed_count = int(raw_count)
        except (TypeError, ValueError):
            parsed_count = 0
        normalized_counts[alignment] = max(0, parsed_count)

    highest_count = max(normalized_counts.values(), default=0)
    if highest_count == 0:
        return "<Unergründlich>", "zero_parts_fallback"

    leaders = [alignment for alignment, count in normalized_counts.items() if count == highest_count]
    if len(leaders) != 1:
        return "<Unergründlich>", "tie_fallback"
    return leaders[0], "majority"


def compute_alignment(manifested_parts: dict[str, int]) -> str:
    alignment, _ = _compute_alignment_with_resolution(manifested_parts)
    return alignment


def resolve_contest(
    state: GameState,
    *,
    bids: dict[str, Any],
    contested_card_id: str | None = None,
    contested_card_name: str | None = None,
    contested_card_alignment: str | None = None,
    contested_card_category: str | None = None,
    claim_on_win: bool = False,
    manifest_requests: dict[str, bool | str | dict[str, Any]] | None = None,
    tie_manifest_requests: dict[str, str | dict[str, Any]] | None = None,
    reset_truth_after: bool = False,
    nun_sacrifice_decisions: dict[str, bool] | None = None,
    phenomenon_prediction_guesses: dict[str, str] | None = None,
) -> GameState:
    if not bids:
        raise ValueError("Contest requires at least one player bid.")

    register_known_phenomenon_metadata(
        state,
        card_id=contested_card_id,
        card_name=contested_card_name,
        card_category=contested_card_category,
        card_alignment=contested_card_alignment,
    )
    explicit_record = get_known_phenomenon_record(state, contested_card_id)
    resolved_contested_card_category = contested_card_category or (
        str(explicit_record.get("category"))
        if isinstance(explicit_record, dict) and explicit_record.get("category") is not None
        else None
    )
    resolved_contested_card_id = contested_card_id
    if resolved_contested_card_category != "Gebote":
        resolved_contested_card_id = resolve_contested_phenomenon_card_id(
            state,
            contested_card_id=contested_card_id,
        )
        if resolved_contested_card_id is not None:
            apply_phenomenon_prediction_bonuses(
                state,
                contested_card_id=resolved_contested_card_id,
                current_round=state.round_number,
                prediction_guesses=phenomenon_prediction_guesses,
            )

    resolved_record = get_known_phenomenon_record(state, resolved_contested_card_id)
    resolved_contested_card_name = contested_card_name or (
        str(resolved_record.get("name"))
        if isinstance(resolved_record, dict) and resolved_record.get("name") is not None
        else contested_card_name
    )
    resolved_contested_card_category = resolved_contested_card_category or (
        str(resolved_record.get("category"))
        if isinstance(resolved_record, dict) and resolved_record.get("category") is not None
        else None
    )
    allowed_manifest_player_ids = list(bids.keys())
    normalized_manifest_requests = normalize_manifest_requests(
        state,
        manifest_requests=manifest_requests,
        allowed_player_ids=allowed_manifest_player_ids,
    )
    if resolved_contested_card_category == "Gebote" and any(
        requested for requested, _ in normalized_manifest_requests.values()
    ):
        raise ValueError("Manifest requests are only valid when the contested card is a phenomenon.")

    submitted_bids: dict[str, dict[str, Any]] = {}
    participating_player_ids: list[str] = []
    normalized_bids: list[tuple[str, ContestBidChoice]] = []
    committed_bids = []
    phenomenon_contest = resolved_contested_card_category != "Gebote"

    for player_id, bid in bids.items():
        if player_id not in state.players:
            raise ValueError(f"Unknown player in contest: {player_id}.")
        if phenomenon_contest and not _has_free_slot(state.players[player_id], slot_kind="phenomena"):
            raise ValueError(
                f"Player {player_id} cannot participate in a phenomenon contest; no free phenomenon slot remains."
            )

        participating_player_ids.append(player_id)
        normalized_bid = _normalize_resolve_contest_bid_choice(bid, player_id=player_id)
        submitted_bids[player_id] = _serialize_resolve_contest_bid_choice(normalized_bid)
        normalized_bids.append((player_id, normalized_bid))

    for player_id, normalized_bid in normalized_bids:
        validate_contest_bid_choice(state, player_id=player_id, bid_choice=normalized_bid)

    for player_id, normalized_bid in normalized_bids:
        committed_bid = commit_contest_bid(state, player_id, normalized_bid)
        committed_bids.append(committed_bid)

        heavenly_cards = committed_bid.heavenly_cards
        if heavenly_cards:
            heavenly_truth_values = [
                _get_effective_hand_card_truth_value(state, player_id=player_id, card=card)
                for card in heavenly_cards
            ]
            append_event(
                state.event_log,
                "contest_heavenly_cards_discarded",
                player_id=player_id,
                card_ids=[card.card_id for card in heavenly_cards],
                truth_values=heavenly_truth_values,
            )

    nun_sacrifice_player_ids = apply_nun_sacrifice_modifiers(
        state,
        committed_bids,
        player_order=_get_cyclic_player_order_for_ids(state, player_ids=participating_player_ids),
        current_round=state.round_number,
        nun_sacrifice_decisions=nun_sacrifice_decisions,
    )
    apply_pure_wrath_contest_discards(
        state,
        committed_bids=committed_bids,
        current_round=state.round_number,
        contested_card_id=resolved_contested_card_id,
    )
    score = score_committed_bids(state, committed_bids)
    append_contest_reveal_log(
        state,
        contest_kind="manual",
        current_round=state.round_number,
        contested_card_id=resolved_contested_card_id,
        score=score,
        nun_sacrifice_player_ids=nun_sacrifice_player_ids,
    )
    outcome_resolution = apply_contest_outcome_resolution(
        state,
        current_round=state.round_number,
        contested_card_id=resolved_contested_card_id,
        score=score,
        tie_manifest_requests=tie_manifest_requests,
    )
    finalize_committed_bids(state, committed_bids)

    append_event(
        state.event_log,
        "contest_resolved",
        bids=submitted_bids,
        bid_totals=score.bid_totals,
        revealed_bid_totals=score.bid_totals,
        contested_card_id=resolved_contested_card_id,
        contested_card_category=resolved_contested_card_category,
        winner_id=score.winner_id,
        winner_idx=state.player_order.index(score.winner_id) if score.winner_id is not None else None,
        tied_player_ids=score.tied_player_ids,
        tie_breaker=score.tie_breaker,
        nun_sacrifice_player_ids=nun_sacrifice_player_ids,
        bid_count=len(committed_bids),
        passed_player_ids=[],
        outcome=outcome_resolution.outcome,
        manifestation_player_ids=outcome_resolution.manifestation_player_ids,
        baptism_player_ids=outcome_resolution.baptism_player_ids,
        phenomenon_discarded_due_to_tie=outcome_resolution.phenomenon_discarded_due_to_tie,
        discarded_phenomenon_card_id=outcome_resolution.discarded_phenomenon_card_id,
    )

    if claim_on_win and score.winner_id is not None and resolved_contested_card_id is not None:
        _award_contested_card(
            state,
            player_id=score.winner_id,
            card_id=resolved_contested_card_id,
            card_name=resolved_contested_card_name,
            card_category=resolved_contested_card_category,
            manifest_requested=normalized_manifest_requests.get(score.winner_id, (False, None))[0],
            manifest_body_part_category=normalized_manifest_requests.get(score.winner_id, (False, None))[1],
        )

    if reset_truth_after:
        for player_id in participating_player_ids:
            reset_truth(state, player_id=player_id)

    maybe_start_endgame_countdown(
        state,
        trigger_source="manual_contest_end",
        preferred_player_id=score.winner_id,
    )

    # TODO: Add full contest timing, reactions, and tie-break rules once the bidding system is specified.
    validate_state(state)
    return state


def _normalize_resolve_contest_bid_choice(
    bid: Any,
    *,
    player_id: str,
) -> ContestBidChoice:
    normalized_bid = normalize_bid_choice(bid)
    if normalized_bid.truth_values and normalized_bid.truth_card_ids:
        raise ValueError(
            f"resolve_contest requires player {player_id} to use either raw truth values or truth_card_ids, not both."
        )
    if normalized_bid.truth_values:
        raise ValueError(
            f"resolve_contest requires player {player_id} to bid truth via truth_card_ids from hand_cards, not raw truth values."
        )
    return normalized_bid


def _serialize_resolve_contest_bid_choice(choice: ContestBidChoice) -> dict[str, Any]:
    serialized: dict[str, Any] = {
        "heavenly_card_ids": list(choice.heavenly_card_ids),
    }
    if choice.truth_card_ids:
        serialized["truth_card_ids"] = list(choice.truth_card_ids)
    return serialized


def _get_cyclic_player_order_for_ids(state: GameState, *, player_ids: list[str]) -> list[str]:
    player_id_set = set(player_ids)
    player_count = len(state.player_order)
    return [
        state.player_order[(state.start_player_idx + offset) % player_count]
        for offset in range(player_count)
        if state.player_order[(state.start_player_idx + offset) % player_count] in player_id_set
    ]


def claim_phenomenon(
    state: GameState,
    *,
    player_id: str,
    card_id: str,
    card_name: str | None = None,
    card_alignment: str | None = None,
    manifest_requested: bool = False,
    manifest_body_part_category: str | None = None,
    allow_baseline_manifestation: bool = True,
) -> GameState:
    if state.claim_round_number == state.round_number:
        illegal_code = ILLEGAL_STATE_MULTIPLE_CLAIMS_SAME_ROUND
        state.illegal_states.append(illegal_code)
        append_event(
            state.event_log,
            illegal_code,
            round=state.round_number,
            current_round=state.round_number,
            player_id=player_id,
            winner=player_id,
            attempted_phenomenon_id=card_id,
            claim_round_number=state.claim_round_number,
        )
        return state

    player = state.players[player_id]
    phenomena_slot_limit = _get_slot_limit(player, slot_kind="phenomena")
    if len(player.stored_phenomena) >= phenomena_slot_limit:
        illegal_code = ILLEGAL_STATE_CLAIM_WITHOUT_FREE_SLOT
        state.illegal_states.append(illegal_code)
        append_event(
            state.event_log,
            illegal_code,
            round=state.round_number,
            current_round=state.round_number,
            player_id=player_id,
            winner=player_id,
            phenomenon_id=card_id,
            stored_before=list(player.stored_phenomena),
            stored_phenomena_count=len(player.stored_phenomena),
            phenomena_slot_limit=phenomena_slot_limit,
        )
        return state
    if manifest_requested and manifest_body_part_category is None:
        raise ValueError(
            f"Player {player_id} must specify manifest_body_part_category to manifest phenomenon {card_id}."
        )
    register_known_phenomenon_metadata(
        state,
        card_id=card_id,
        card_name=card_name,
        card_alignment=card_alignment,
    )
    catalog_record = get_known_phenomenon_record(state, card_id)
    resolved_card_name = card_name or (
        str(catalog_record.get("name"))
        if isinstance(catalog_record, dict) and catalog_record.get("name") is not None
        else card_id
    )
    phenomenon_alignment = get_known_phenomenon_alignment(state, card_id)
    if phenomenon_alignment is None:
        raise ValueError(
            f"Claiming phenomenon {card_id} requires alignment metadata from catalog, draw pile, or explicit input."
        )

    manifest_decision_source = (
        "explicit_request"
        if manifest_requested or manifest_body_part_category is not None
        else "baseline_policy" if allow_baseline_manifestation else "explicit_skip"
    )
    if manifest_body_part_category is not None:
        manifest_requested = True
    elif not manifest_requested and allow_baseline_manifestation:
        baseline_manifest_body_part_category = _choose_baseline_manifestation_body_part_category(
            state,
            player_id=player_id,
            phenomenon_alignment=phenomenon_alignment,
        )
        if baseline_manifest_body_part_category is not None:
            manifest_requested = True
            manifest_body_part_category = baseline_manifest_body_part_category
            manifest_decision_source = "baseline_policy_auto_manifest"
        else:
            manifest_decision_source = "baseline_policy_no_valid_body_part"

    player.stored_phenomena.append(card_id)
    state.claim_round_number = state.round_number
    append_event(
        state.event_log,
        "phenomenon_claimed",
        round=state.round_number,
        current_round=state.round_number,
        winner=player_id,
        player_id=player_id,
        phenomenon_id=card_id,
        card_id=card_id,
        card_name=resolved_card_name,
        first_claim=not state.first_phenomenon_claimed,
        storage_mode="stored_power",
        phenomenon_alignment=phenomenon_alignment,
        stored_phenomena=list(player.stored_phenomena),
        stored_phenomena_count=len(player.stored_phenomena),
        manifest_requested=manifest_requested,
        manifest_body_part_category=manifest_body_part_category,
        manifest_decision_source=manifest_decision_source,
    )
    append_event(
        state.event_log,
        "stored_phenomena_after_claim",
        round=state.round_number,
        current_round=state.round_number,
        player=player_id,
        player_id=player_id,
        winner=player_id,
        phenomenon_id=card_id,
        stored_list=list(player.stored_phenomena),
        stored_phenomena=list(player.stored_phenomena),
    )
    _resolve_phenomenon_believer_reward(
        state,
        player_id=player_id,
        card_id=card_id,
        card_name=resolved_card_name,
        phenomenon_alignment=phenomenon_alignment,
    )
    manifested_in_this_claim = False

    def _manifest_once() -> None:
        nonlocal manifested_in_this_claim
        if manifested_in_this_claim:
            illegal_code = ILLEGAL_STATE_DOUBLE_MANIFESTATION
            state.illegal_states.append(illegal_code)
            append_event(
                state.event_log,
                illegal_code,
                round=state.round_number,
                current_round=state.round_number,
                player_id=player_id,
                winner=player_id,
                phenomenon_id=card_id,
                body_part_category=manifest_body_part_category,
            )
            return
        manifested_in_this_claim = True
        _resolve_phenomenon_manifestation(
            state,
            player_id=player_id,
            card_id=card_id,
            card_name=resolved_card_name,
            body_part_category=manifest_body_part_category,
            phenomenon_alignment=phenomenon_alignment,
        )

    if manifest_requested:
        _manifest_once()
    if not state.first_phenomenon_claimed:
        if state.beginner_mode:
            state.first_phenomenon_claimed = True
        elif any(player.prophet_owner for player in state.players.values()):
            # A grenade may already have brought the unique Prophet into play.
            state.first_phenomenon_claimed = True
        else:
            award_prophet(state, player_id=player_id)
    return state


def unleash_phenomenon_power(
    state: GameState,
    *,
    player_id: str,
    card_id: str,
    effect_payload: dict[str, Any] | None = None,
    decision_source: str = "direct_call",
) -> GameState:
    player = state.players[player_id]
    if card_id not in player.stored_phenomena:
        raise ValueError(f"Player {player_id} cannot unleash phenomenon {card_id}; card is not stored.")
    if card_id in player.used_phenomenon_powers:
        raise ValueError(f"Player {player_id} cannot unleash phenomenon {card_id}; power already used.")

    payload = effect_payload or {}
    if state.beginner_mode:
        require_beginner_phenomenon_payload(payload)
    _validate_stored_power_effect_choices(
        state, player_id=player_id, phenomenon_card_id=card_id, effect_payload=payload,
    )
    payment_choice = payload.get("cost_payment_choice")
    additional_cost = 3 * _count_active_enlightener_rule_text(
        state,
        player_id=player_id,
        text=ENLIGHTENER_PHENOMENON_UNLEASH_COST_TEXT,
    )
    if additional_cost > 0:
        effective_additional_cost = _apply_sacrifice_cost_reduction(
            state,
            player_id=player_id,
            amount=additional_cost,
        )
        payment_resolution = _spend_player_meeples(
            state,
            player_id=player_id,
            amount=effective_additional_cost,
            strict=True,
            payment_choice=payment_choice,
            purpose="phenomenon_unleash_cost",
        )
        append_event(
            state.event_log,
            "phenomenon_unleash_cost_paid",
            player_id=player_id,
            card_id=card_id,
            additional_cost=additional_cost,
            effective_additional_cost=payment_resolution["paid_total"],
            free_meeples_paid=payment_resolution["free_meeples_paid"],
            role_meeples_paid=dict(payment_resolution["role_meeples_paid"]),
            prepared_nuns_paid=payment_resolution["prepared_nuns_paid"],
            meeples_after=player.meeples,
        )

    player.used_phenomenon_powers.append(card_id)
    append_event(
        state.event_log,
        "phenomenon_power_unleashed",
        player_id=player_id,
        card_id=card_id,
        decision_source=decision_source,
        additional_cost=additional_cost,
        effective_additional_cost=payment_resolution["paid_total"] if additional_cost > 0 else 0,
        remaining_unused_power_count=max(0, len(player.stored_phenomena) - len(player.used_phenomenon_powers)),
        used_phenomenon_powers=list(player.used_phenomenon_powers),
    )
    _resolve_stored_power_effect(
        state,
        player_id=player_id,
        phenomenon_card_id=card_id,
        effect_payload=payload,
        decision_source=decision_source,
    )
    return state


def _resolve_phenomenon_believer_reward(
    state: GameState,
    *,
    player_id: str,
    card_id: str,
    card_name: str,
    phenomenon_alignment: str | None,
) -> GameState:
    player = state.players[player_id]
    reward_amount = get_phenomenon_believer_reward(
        player_alignment=player.alignment,
        phenomenon_alignment=phenomenon_alignment,
        player=player,
    )
    if reward_amount is None:
        append_event(
            state.event_log,
            "phenomenon_believer_reward_unresolved_missing_alignment",
            player_id=player_id,
            card_id=card_id,
            card_name=card_name,
            reward_alignment=phenomenon_alignment,
            player_alignment=player.alignment,
        )
        return state

    if _has_completed_monument_line(
        state,
        player_id=player_id,
        group_key="goldene-oma-hedwig-der-perfekten-dampfnudeln",
    ):
        reward_amount += 1

    player.meeples += reward_amount
    append_event(
        state.event_log,
        "phenomenon_believer_reward_resolved",
        player_id=player_id,
        card_id=card_id,
        card_name=card_name,
        reward_alignment=phenomenon_alignment,
        player_alignment=player.alignment,
        reward_amount=reward_amount,
        reward_source="heathen_pile",
        meeples_after=player.meeples,
    )
    return state


def claim_commandment(
    state: GameState,
    *,
    player_id: str,
    card_id: str,
    card_name: str | None = None,
) -> GameState:
    commandment = _activate_commandment(
        state,
        card_id=card_id,
        card_name=card_name,
    )
    append_event(
        state.event_log,
        "commandment_claimed",
        player_id=player_id,
        card_id=commandment.card_id,
        active_commandment_count=len(state.active_commandments),
    )
    # TODO: Add full board-wide Gebote effects once those rules are specified.
    return state


def _resolve_prophet_move_monument_bonuses(
    state: GameState,
    *,
    from_player_id: str,
    to_player_id: str,
    squirrel_draw_counts: dict[str, int] | None = None,
) -> None:
    squirrel_group_key = "goldenes-eichhoernchen-der-uebertriebenen-putzigkeit"
    gundel_group_key = "die-goldene-gundel-der-wahnsinnigen-wuseligkeit"
    for player_id in state.player_order:
        if _get_player_monument_line_card_count(state, player_id=player_id, group_key=squirrel_group_key) < 3:
            pass
        else:
            explicit_draw_count = None if squirrel_draw_counts is None else squirrel_draw_counts.get(player_id)
            cards_needed = 2
            decision_source = "deterministic_fallback_max_draw"
            if explicit_draw_count is not None:
                cards_needed = max(0, min(2, int(explicit_draw_count)))
                decision_source = "explicit_intent"
            drawn_cards = _draw_to_hand_limit(state, player_id=player_id, cards_needed=cards_needed)
            append_event(
                state.event_log,
                "monument_prophet_bonus_resolved",
                player_id=player_id,
                from_player_id=from_player_id,
                to_player_id=to_player_id,
                monument_group_key=squirrel_group_key,
                effect_kind="draw_heavenly",
                draw_count=len(drawn_cards),
                drawn_card_ids=[card.card_id for card in drawn_cards],
                decision_source=decision_source,
                requested_draw_count=cards_needed,
            )
        if _get_player_monument_line_card_count(state, player_id=player_id, group_key=gundel_group_key) < 3:
            continue
        remaining_truth_counter = _available_truth_draw_counter_for_hand_preparation(
            state,
            player_id=player_id,
        )
        available_truth_values = sorted(
            (
                int(truth_value)
                for truth_value, count in remaining_truth_counter.items()
                if int(count or 0) > 0
            ),
            reverse=True,
        )
        drawn_truth_cards: list[CardRef] = []
        drawn_truth_value: int | None = None
        if available_truth_values:
            drawn_truth_value = available_truth_values[0]
            drawn_truth_cards = _add_truth_cards_to_hand(
                state,
                player_id=player_id,
                truth_values=[drawn_truth_value],
                source="monument_prophet_bonus_gundel",
            )
        append_event(
            state.event_log,
            "monument_prophet_bonus_resolved",
            player_id=player_id,
            from_player_id=from_player_id,
            to_player_id=to_player_id,
            monument_group_key=gundel_group_key,
            effect_kind="draw_truth_to_hand",
            draw_count=len(drawn_truth_cards),
            truth_value=drawn_truth_value,
            drawn_card_ids=[card.card_id for card in drawn_truth_cards],
            decision_source="deterministic_fallback_highest_truth",
        )


def pass_prophet(
    state: GameState,
    *,
    from_player_id: str,
    to_player_id: str,
    target_payment_choice: dict[str, Any] | None = None,
    squirrel_draw_counts: dict[str, int] | None = None,
) -> GameState:
    from_player = state.players[from_player_id]

    if not from_player.prophet_owner:
        raise ValueError(f"Player {from_player_id} does not currently own the prophet.")
    if from_player_id == to_player_id:
        raise ValueError("Prophet cannot be passed to the same player.")

    return _play_prophet_on_opponent(
        state,
        from_player_id=from_player_id,
        to_player_id=to_player_id,
        target_payment_choice=target_payment_choice,
        squirrel_draw_counts=squirrel_draw_counts,
    )


def _play_prophet_on_opponent(
    state: GameState,
    *,
    from_player_id: str,
    to_player_id: str,
    target_payment_choice: dict[str, Any] | None = None,
    squirrel_draw_counts: dict[str, int] | None = None,
) -> GameState:
    """Shared consequences; callers determine whether ownership is required."""
    if state.beginner_mode:
        raise ValueError("The Prophet is disabled in beginner mode.")
    if to_player_id not in _get_opponent_player_ids_in_turn_order(state, player_id=from_player_id):
        raise ValueError("Prophet must be played on another player.")
    previous_owner_id = next((pid for pid, player in state.players.items() if player.prophet_owner), None)
    to_player = state.players[to_player_id]
    for player in state.players.values():
        player.prophet_owner = False
    to_player.prophet_owner = True

    payment_resolution = _spend_player_meeples(
        state,
        player_id=to_player_id,
        amount=3,
        strict=False,
        payment_choice=target_payment_choice,
        purpose="prophet_transfer_cost",
    )

    append_event(
        state.event_log,
        "prophet_passed",
        from_player_id=from_player_id,
        to_player_id=to_player_id,
        previous_owner_id=previous_owner_id,
        target_meeples_paid=payment_resolution["paid_total"],
        free_meeples_paid=payment_resolution["free_meeples_paid"],
        role_meeples_paid=dict(payment_resolution["role_meeples_paid"]),
        prepared_nuns_paid=payment_resolution["prepared_nuns_paid"],
        target_meeples_remaining=to_player.meeples,
    )
    _resolve_prophet_move_monument_bonuses(
        state,
        from_player_id=from_player_id,
        to_player_id=to_player_id,
        squirrel_draw_counts=squirrel_draw_counts,
    )
    state.pending_commandment_for_player_id = from_player_id
    _reshuffle_commandment_discard_into_draw_pile_if_empty(state)
    append_event(
        state.event_log,
        "commandment_chisel_created",
        player_id=from_player_id,
        selection_mode="draw_top_3_choose_1",
        commandment_draw_pile_size=len(state.commandment_draw_pile),
        commandment_discard_pile_size=len(state.commandment_discard_pile),
    )
    return state


def chisel_commandment(
    state: GameState,
    *,
    player_id: str,
    card_id: str | None = None,
    card_name: str | None = None,
) -> GameState:
    if state.beginner_mode:
        raise ValueError("Commandments are disabled in beginner mode.")
    pending_player_id = state.pending_commandment_for_player_id
    if pending_player_id is not None and pending_player_id != player_id:
        raise ValueError(
            f"Player {player_id} cannot chisel a commandment reserved for {pending_player_id}."
        )

    offered_count: int | None = None
    discarded_card_ids: list[str] | None = None
    selected_source = "explicit"
    selected_card_id: str | None = card_id
    commandment = None
    if pending_player_id is not None:
        _reshuffle_commandment_discard_into_draw_pile_if_empty(state)
        offered_cards = state.commandment_draw_pile[:3]
        offered_count = len(offered_cards)
        if not offered_cards:
            state.pending_commandment_for_player_id = None
            append_event(
                state.event_log,
                "commandment_chiseled",
                player_id=player_id,
                card_id=None,
                active_commandment_count=len(state.active_commandments),
                offered_count=0,
                discarded_card_ids=[],
                selection_source="no_available_commandments",
                commandment_draw_pile_size=len(state.commandment_draw_pile),
                commandment_discard_pile_size=len(state.commandment_discard_pile),
            )
            return state

        legal_offered_cards = [
            offered_card
            for offered_card in offered_cards
            if len(state.active_commandments) < MAX_ACTIVE_COMMANDMENTS
            and not any(active.card_id == offered_card.card_id for active in state.active_commandments)
        ]

        if selected_card_id is None:
            if legal_offered_cards:
                selected_card_id = legal_offered_cards[0].card_id
                selected_source = "deterministic_fallback_first_legal_offer"
            else:
                discarded_card_ids = _discard_unselected_commandment_offers(
                    state,
                    offered_cards=offered_cards,
                    selected_card_id="",
                )
                state.pending_commandment_for_player_id = None
                append_event(
                    state.event_log,
                    "commandment_chiseled",
                    player_id=player_id,
                    card_id=None,
                    active_commandment_count=len(state.active_commandments),
                    offered_count=offered_count,
                    discarded_card_ids=discarded_card_ids,
                    selection_source="no_legal_offer",
                    commandment_draw_pile_size=len(state.commandment_draw_pile),
                    commandment_discard_pile_size=len(state.commandment_discard_pile),
                )
                return state
        elif all(offered.card_id != selected_card_id for offered in offered_cards):
            raise ValueError(
                f"Selected commandment {selected_card_id} is not among the currently offered top-3 cards."
            )

        selected_card = next(card for card in offered_cards if card.card_id == selected_card_id)
        commandment = _activate_commandment(
            state,
            card_id=selected_card_id,
            card_name=card_name or selected_card.name,
        )
        discarded_card_ids = _discard_unselected_commandment_offers(
            state,
            offered_cards=offered_cards,
            selected_card_id=selected_card_id,
        )
    elif card_id is not None:
        commandment = _activate_commandment(
            state,
            card_id=card_id,
            card_name=card_name,
        )

    state.pending_commandment_for_player_id = None
    append_event(
        state.event_log,
        "commandment_chiseled",
        player_id=player_id,
        card_id=commandment.card_id if commandment else None,
        active_commandment_count=len(state.active_commandments),
        offered_count=offered_count,
        discarded_card_ids=discarded_card_ids,
        selection_source=selected_source,
        commandment_draw_pile_size=len(state.commandment_draw_pile),
        commandment_discard_pile_size=len(state.commandment_discard_pile),
    )
    return state


def _reshuffle_commandment_discard_into_draw_pile_if_empty(state: GameState) -> None:
    if state.commandment_draw_pile or not state.commandment_discard_pile:
        return
    rng = SeededRNG(
        seed=(
            f"commandment-reshuffle|r{state.round_number}|t{state.turn_number}|"
            f"{'|'.join(card.card_id for card in state.commandment_discard_pile)}"
        )
    )
    state.commandment_draw_pile = list(rng.shuffle(list(state.commandment_discard_pile)))
    state.commandment_discard_pile = []


def _get_monument_group_key_from_card(card: CardRef) -> str:
    metadata_group_key = card.metadata.get(MONUMENT_GROUP_KEY_METADATA)
    if isinstance(metadata_group_key, str) and metadata_group_key:
        return metadata_group_key
    return _monument_group_key_from_card_id(card.card_id)


def _get_monument_starter_player_id(card: CardRef, *, fallback_owner_id: str) -> str:
    metadata_starter = card.metadata.get(MONUMENT_STARTER_PLAYER_ID_METADATA)
    if isinstance(metadata_starter, str) and metadata_starter:
        return metadata_starter
    return fallback_owner_id


def _is_monument_card_completion_blocked(card: CardRef) -> bool:
    return bool(card.metadata.get(MONUMENT_COMPLETION_BLOCKED_METADATA))


def _iter_monument_cards_with_owners(state: GameState):
    for owner_id, player in state.players.items():
        for card in player.tableau:
            if card.category != "Monument":
                continue
            yield owner_id, card


def _find_existing_monument_line_starter_player_id(state: GameState, *, group_key: str) -> str | None:
    for owner_id, card in _iter_monument_cards_with_owners(state):
        if _get_monument_group_key_from_card(card) != group_key:
            continue
        return _get_monument_starter_player_id(card, fallback_owner_id=owner_id)
    return None


def _is_monument_line_completion_blocked(state: GameState, *, group_key: str) -> bool:
    for _owner_id, card in _iter_monument_cards_with_owners(state):
        if _get_monument_group_key_from_card(card) != group_key:
            continue
        if _is_monument_card_completion_blocked(card):
            return True
    return False


def _get_player_started_monument_group_keys(state: GameState, *, player_id: str) -> set[str]:
    player = state.players[player_id]
    group_keys: set[str] = set()
    for card in player.tableau:
        if card.category != "Monument":
            continue
        group_keys.add(_get_monument_group_key_from_card(card))
    return group_keys


def _get_player_monument_line_card_count(
    state: GameState,
    *,
    player_id: str,
    group_key: str,
) -> int:
    player = state.players[player_id]
    return sum(
        1
        for card in player.tableau
        if card.category == "Monument" and _get_monument_group_key_from_card(card) == group_key
    )


def _has_completed_monument_line(
    state: GameState,
    *,
    player_id: str,
    group_key: str,
) -> bool:
    return _get_player_monument_line_card_count(state, player_id=player_id, group_key=group_key) >= 3


def _refresh_player_monument_passives(state: GameState, *, player_id: str) -> None:
    player = state.players[player_id]
    player.missionaries_slots = 2


def _get_herring_missionary_steal_bonus(state: GameState, *, player_id: str) -> int:
    group_key = "goldener-hering-der-unterbrochenen-kuehlkette"
    if not _has_completed_monument_line(state, player_id=player_id, group_key=group_key):
        return 0
    if _is_monument_line_completion_blocked(state, group_key=group_key):
        return 0
    if any(
        _get_monument_starter_player_id(card, fallback_owner_id=player_id) != player_id
        for card in state.players[player_id].tableau
        if card.category == "Monument" and _get_monument_group_key_from_card(card) == group_key
    ):
        return 0
    return 1


def normalize_legacy_herring_missionary_slots(state: GameState) -> None:
    """Repair the former Herring capacity bonus when restoring a saved game."""
    for player_id, player in state.players.items():
        if player.missionaries_slots != 3 or not _has_completed_monument_line(
            state,
            player_id=player_id,
            group_key="goldener-hering-der-unterbrochenen-kuehlkette",
        ):
            continue
        _refresh_player_monument_passives(state, player_id=player_id)
        assigned = max(0, int(player.assigned_role_meeples.get("Missionare", 0)))
        returned = max(0, assigned - player.missionaries_slots)
        player.assigned_role_meeples["Missionare"] = min(assigned, player.missionaries_slots)
        player.meeples += returned
        append_event(
            state.event_log,
            "missionary_temple_capacity_corrected",
            player_id=player_id,
            previous_slots=3,
            missionaries_slots=player.missionaries_slots,
            returned_meeples=returned,
            source="legacy_herring_slot_bonus",
        )


def _resolve_completed_monument_line_bonus(
    state: GameState,
    *,
    player_id: str,
    group_key: str,
) -> dict[str, Any] | None:
    player = state.players[player_id]
    if group_key == "goldener-hering-der-unterbrochenen-kuehlkette":
        _refresh_player_monument_passives(state, player_id=player_id)
        bonus_payload = {
            "effect_kind": "missionary_steal_bonus",
            "missionary_steal_bonus": 1,
            "missionaries_slots_after": player.missionaries_slots,
        }
    elif group_key == "goldener-loeffel-des-spaeten-saettigungsgefuehls":
        player.stored_monument_bonus_actions += 1
        bonus_payload = {
            "effect_kind": "store_bonus_action",
            "stored_bonus_actions": player.stored_monument_bonus_actions,
        }
    elif group_key == "goldene-zwiebel-der-bittersuessen-traenen":
        _remove_truth_value(
            state,
            player_id=player_id,
            value=2,
            source="monument_line_bonus_zwiebel",
        )
        removal_event = next(
            (
                event
                for event in reversed(state.event_log)
                if event.get("type") == "truth_removed"
                and event.get("player_id") == player_id
                and event.get("source") == "monument_line_bonus_zwiebel"
            ),
            None,
        )
        bonus_payload = {
            "effect_kind": "remove_last_truth_two",
            "removed_truth_source": (
                removal_event.get("removed_from") if isinstance(removal_event, dict) else None
            ),
            "truth_pool_after": list(player.truth_pool),
            "used_truth_after": list(player.used_truth),
        }
    else:
        return None

    append_event(
        state.event_log,
        "monument_line_bonus_resolved",
        player_id=player_id,
        monument_group_key=group_key,
        **bonus_payload,
    )
    return bonus_payload


def _monument_line_progress_after_build(
    state: GameState,
    *,
    player_id: str,
    group_key: str,
) -> int:
    return _get_player_monument_line_card_count(state, player_id=player_id, group_key=group_key) + 1


def _get_monument_build_reason(
    state: GameState,
    *,
    player_id: str,
    card_id: str,
) -> str | None:
    group_key = _monument_group_key_from_card_id(card_id)
    started_group_keys = _get_player_started_monument_group_keys(state, player_id=player_id)
    if started_group_keys and group_key not in started_group_keys:
        return (
            f"Player {player_id} has already started monument line "
            f"{sorted(started_group_keys)[0]} and cannot start {group_key}."
        )
    line_progress_after = _monument_line_progress_after_build(
        state,
        player_id=player_id,
        group_key=group_key,
    )
    if line_progress_after in {1, 2} and not _get_available_truth_sources(state, player_id=player_id, value=2):
        return f"Player {player_id} has no available Truth 2 source for monument line {group_key}."
    return None


def get_forge_monument_reveal_count(state: GameState, *, player_id: str) -> int:
    player = state.players[player_id]
    return 4 if player.alignment == "<Chaos>" else 3


def _visible_forge_monument_cards(state: GameState, *, player_id: str) -> list[CardRef]:
    reveal_count = get_forge_monument_reveal_count(state, player_id=player_id)
    return list(state.monument_draw_pile[:reveal_count])


def get_forge_monument_choices(state: GameState, *, player_id: str) -> list[dict[str, Any]]:
    choices: list[dict[str, Any]] = []
    for card in _visible_forge_monument_cards(state, player_id=player_id):
        group_key = _monument_group_key_from_card_id(card.card_id)
        line_starter_player_id = _find_existing_monument_line_starter_player_id(state, group_key=group_key)
        part = _infer_monument_part_from_card_id(card.card_id)
        line_progress_before = _get_player_monument_line_card_count(
            state,
            player_id=player_id,
            group_key=group_key,
        )
        line_progress_after = line_progress_before + 1
        reason = _get_monument_build_reason(state, player_id=player_id, card_id=card.card_id)
        required_truth_value = 2 if line_progress_after in {1, 2} else None
        available_truth_sources = (
            _get_available_truth_sources(state, player_id=player_id, value=required_truth_value)
            if required_truth_value is not None
            else []
        )
        building_other_player_monument = line_starter_player_id is not None and line_starter_player_id != player_id
        completion_blocked = building_other_player_monument or _is_monument_line_completion_blocked(
            state,
            group_key=group_key,
        )
        choices.append(
            {
                "card_id": card.card_id,
                "card_name": card.name,
                "part": part,
                "group_key": group_key,
                "line_progress_before": line_progress_before,
                "line_progress_after": line_progress_after,
                "reward_truth_value": 2 if line_progress_after in {1, 2} else 6,
                "required_truth_value": required_truth_value,
                "available_truth_sources": available_truth_sources,
                "truth_source_required": len(available_truth_sources) > 1,
                "line_completion_after_build": line_progress_after >= 3,
                "started_by_player_id": line_starter_player_id,
                "building_other_player_monument": building_other_player_monument,
                "completion_blocked": completion_blocked,
                "enabled": reason is None,
                "reason": reason or "",
            }
        )
    return choices


def get_legal_forge_monument_options(state: GameState, *, player_id: str) -> list[CardRef]:
    legal_card_ids = {
        str(choice["card_id"])
        for choice in get_forge_monument_choices(state, player_id=player_id)
        if bool(choice["enabled"])
    }
    return [card for card in _visible_forge_monument_cards(state, player_id=player_id) if card.card_id in legal_card_ids]


def _forge_monument_bot_priority(
    state: GameState,
    *,
    player_id: str,
    choice: Mapping[str, Any],
) -> tuple[int, int, str]:
    if not bool(choice["enabled"]):
        return (0, 0, "")

    if not bool(choice["building_other_player_monument"]):
        if str(choice.get("started_by_player_id") or "") == player_id:
            return (3, int(choice["line_progress_after"]), "")
        return (2, int(choice["line_progress_after"]), "")

    starter_player_id = str(choice.get("started_by_player_id") or "")
    if starter_player_id:
        starter_progress = _get_player_monument_line_card_count(
            state,
            player_id=starter_player_id,
            group_key=str(choice["group_key"]),
        )
        if starter_progress >= 2:
            return (4, starter_progress, "")
    return (1, int(choice["line_progress_after"]), "")


def _select_default_forge_monument_card(
    *,
    drawn_options: Sequence[CardRef],
    choice_by_card_id: Mapping[str, Mapping[str, Any]],
) -> int | None:
    prioritized_indices = [
        (
            choice_by_card_id[card.card_id]["bot_priority"],
            index,
        )
        for index, card in enumerate(drawn_options)
        if card.card_id in choice_by_card_id
    ]
    if not prioritized_indices:
        return None
    return max(prioritized_indices, key=lambda item: (item[0], -item[1]))[1]


def get_player_monument_overview(state: GameState, *, player_id: str) -> dict[str, Any]:
    started_lines: dict[str, dict[str, Any]] = {}
    supporting_lines: dict[str, dict[str, Any]] = {}
    line_contributors: dict[str, set[str]] = {}

    for owner_id, card in _iter_monument_cards_with_owners(state):
        group_key = _get_monument_group_key_from_card(card)
        line_contributors.setdefault(group_key, set()).add(owner_id)

    for owner_id, card in _iter_monument_cards_with_owners(state):
        group_key = _get_monument_group_key_from_card(card)
        starter_player_id = _get_monument_starter_player_id(card, fallback_owner_id=owner_id)
        entry = {
            "group_key": group_key,
            "starter_player_id": starter_player_id,
            "card_ids": [],
            "completion_blocked": _is_monument_line_completion_blocked(state, group_key=group_key),
            "contributors": sorted(line_contributors.get(group_key, set())),
        }
        if owner_id == player_id and starter_player_id == player_id:
            started_lines.setdefault(group_key, dict(entry))["card_ids"].append(card.card_id)
        elif owner_id == player_id:
            supporting_lines.setdefault(group_key, dict(entry))["card_ids"].append(card.card_id)

    return {
        "started_lines": sorted(started_lines.values(), key=lambda line: str(line["group_key"])),
        "supporting_lines": sorted(supporting_lines.values(), key=lambda line: str(line["group_key"])),
    }


def build_monument_part(
    state: GameState,
    *,
    player_id: str,
    part: int,
    card_id: str,
    card_name: str | None = None,
    truth_source: str | None = None,
    second_card_id: str | None = None,
    second_card_name: str | None = None,
) -> GameState:
    if part not in (1, 2, 3):
        raise ValueError(f"Unsupported monument part: {part}")

    if _player_has_active_enlightener_rule_text(
        state,
        player_id=player_id,
        text=ENLIGHTENER_BLOCKS_MONUMENTS_TEXT,
    ):
        append_event(
            state.event_log,
            "monument_build_blocked_by_aufklaerer",
            player_id=player_id,
            part=part,
            card_id=card_id,
            card_name=card_name or card_id,
        )
        return state

    build_card_specs = [(card_id, card_name or card_id, part)]
    if second_card_id is not None:
        if not _player_has_zacharias_double_monument_relic(state, player_id=player_id):
            raise ValueError(
                f"Player {player_id} cannot build a second monument card in one action without the Zacharias relic effect."
            )
        second_part = _infer_monument_part_from_card_id(second_card_id)
        if second_part not in {1, 2, 3}:
            raise ValueError(f"Monument card {second_card_id} does not encode part 1-3.")
        build_card_specs.append((second_card_id, second_card_name or second_card_id, second_part))

    player = state.players[player_id]
    for build_index, (build_card_id, build_card_name, build_part) in enumerate(build_card_specs, start=1):
        if not _has_free_slot(player, slot_kind="forge"):
            _append_slot_full_event(
                state,
                player_id=player_id,
                slot_kind="forge",
                event_type="monument_build_expired_full_slot",
                part=build_part,
                card_id=build_card_id,
                card_name=build_card_name,
                build_index=build_index,
                requested_builds=len(build_card_specs),
            )
            break

        group_key = _monument_group_key_from_card_id(build_card_id)
        line_starter_player_id = _find_existing_monument_line_starter_player_id(state, group_key=group_key)
        started_group_keys = _get_player_started_monument_group_keys(state, player_id=player_id)
        if started_group_keys and group_key not in started_group_keys:
            raise ValueError(
                f"Player {player_id} has already started monument line {sorted(started_group_keys)[0]} "
                f"and cannot start {group_key}."
            )
        if line_starter_player_id is None:
            line_starter_player_id = player_id

        line_progress_before = _get_player_monument_line_card_count(
            state,
            player_id=player_id,
            group_key=group_key,
        )
        if line_progress_before >= 3:
            raise ValueError(
                f"Player {player_id} has already completed monument line {group_key}."
            )
        line_progress_after = line_progress_before + 1
        building_other_player_monument = line_starter_player_id != player_id
        line_completion_blocked = building_other_player_monument or _is_monument_line_completion_blocked(
            state,
            group_key=group_key,
        )

        if line_progress_after in (1, 2):
            _remove_truth_value(
                state,
                player_id=player_id,
                value=2,
                source=f"monument_line_step_{line_progress_after}",
                preferred_source=truth_source,
            )

        player.tableau.append(
            CardRef(
                card_id=build_card_id,
                name=build_card_name,
                category="Monument",
                metadata={
                    "monument_part": build_part,
                    MONUMENT_GROUP_KEY_METADATA: group_key,
                    MONUMENT_STARTER_PLAYER_ID_METADATA: line_starter_player_id,
                    MONUMENT_COMPLETION_BLOCKED_METADATA: line_completion_blocked,
                },
            )
        )
        if line_starter_player_id == player_id and build_index == 1 and not any(
            _get_monument_group_key_from_card(card) == group_key
            and _get_monument_starter_player_id(card, fallback_owner_id=player_id) == player_id
            for card in player.tableau[:-1]
        ):
            append_event(
                state.event_log,
                "monument_line_started",
                player_id=player_id,
                monument_group_key=group_key,
                card_id=build_card_id,
            )
        append_event(
            state.event_log,
            "monument_part_built",
            player_id=player_id,
            part=build_part,
            line_progress_before=line_progress_before,
            line_progress_after=line_progress_after,
            card_id=build_card_id,
            build_index=build_index,
            requested_builds=len(build_card_specs),
            monument_group_key=group_key,
            starter_player_id=line_starter_player_id,
            building_other_player_monument=building_other_player_monument,
            completion_blocked=_is_monument_line_completion_blocked(state, group_key=group_key),
        )

        if line_progress_after == 3 and not line_completion_blocked and not building_other_player_monument:
            _add_truth_value(
                state,
                player_id=player_id,
                value=6,
                source="monument_part_3",
                prepare_to_hand_source="monument-completion",
            )
            _resolve_completed_monument_line_bonus(
                state,
                player_id=player_id,
                group_key=group_key,
            )
        else:
            _refresh_player_monument_passives(state, player_id=player_id)

    recalculate_commandment_effects(state)
    return state


def refresh_commandment_effects(state: GameState) -> GameState:
    return recalculate_commandment_effects(state)


def can_play_card(state: GameState, *, player_id: str, card: CardRef) -> bool:
    if is_card_play_blocked(state, player_id=player_id, card=card):
        return False
    if card.category == "Reliquie" and _player_has_active_enlightener_rule_text(
        state,
        player_id=player_id,
        text=ENLIGHTENER_BLOCKS_RELICS_TEXT,
    ):
        return False
    return True


def is_tableau_card_active(state: GameState, *, player_id: str, card: CardRef) -> bool:
    if is_tableau_card_disabled(state, player_id=player_id, card=card):
        return False
    if card.category == "Reliquie" and _player_has_active_enlightener_rule_text(
        state,
        player_id=player_id,
        text=ENLIGHTENER_DISABLES_RELICS_TEXT,
    ):
        return False
    return True


def get_effective_additional_cost(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
    effect_payload: dict[str, Any] | None = None,
) -> int:
    if _is_intrinsic_cost_waived_by_tableau(state, player_id=player_id, card=card):
        return 0
    base_cost = get_additional_cost_for_card(state, player_id=player_id, card=card)
    return _apply_sacrifice_cost_reduction(state, player_id=player_id, amount=base_cost)


def _get_effective_additional_cost_for_hand_card_payment(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
    effect_payload: dict[str, Any] | None = None,
) -> int:
    if _is_intrinsic_cost_waived_by_tableau(state, player_id=player_id, card=card):
        return 0
    base_cost = get_additional_cost_for_card(state, player_id=player_id, card=card)
    if _get_hand_card_intrinsic_cost_before_sacrifice_reduction(
        state,
        player_id=player_id,
        card=card,
        effect_payload=effect_payload,
    ) > 0:
        return base_cost
    return get_effective_additional_cost(
        state,
        player_id=player_id,
        card=card,
        effect_payload=effect_payload,
    )


def _get_sacrifice_cost_reduction(state: GameState, *, player_id: str) -> int:
    return _count_active_relic_rule_fragments(
        state,
        player_id=player_id,
        texts=(
            RELIC_REDUCES_SACRIFICE_COST_TEXT,
            RELIC_REDUCES_SACRIFICE_COST_VARIANT_TEXT,
        ),
    )


def _apply_sacrifice_cost_reduction(state: GameState, *, player_id: str, amount: int) -> int:
    return max(0, amount - _get_sacrifice_cost_reduction(state, player_id=player_id))


def _player_has_zacharias_double_monument_relic(state: GameState, *, player_id: str) -> bool:
    return _count_active_relic_rule_fragments(
        state,
        player_id=player_id,
        texts=(
            RELIC_BUILD_TWO_MONUMENTS_ACTION_PREFIX_TEXT,
            RELIC_BUILD_TWO_MONUMENTS_ACTION_FINAL_PREFIX_TEXT,
        ),
    ) > 0


def _sacrifice_cost_reduction_event_fields(
    state: GameState,
    *,
    player_id: str,
    base_amount: int,
    effective_amount: int,
    prefix: str,
) -> dict[str, Any]:
    reduction = max(0, int(base_amount) - int(effective_amount))
    if reduction <= 0:
        return {
            f"{prefix}_reduction": 0,
            f"{prefix}_reduction_sources": [],
        }
    return {
        f"{prefix}_reduction": reduction,
        f"{prefix}_reduction_sources": _get_active_relic_names_with_rule_fragments(
            state,
            player_id=player_id,
            texts=(
                RELIC_REDUCES_SACRIFICE_COST_TEXT,
                RELIC_REDUCES_SACRIFICE_COST_VARIANT_TEXT,
            ),
        ),
    }


def is_card_cost_currently_waived(state: GameState, *, player_id: str, card: CardRef) -> bool:
    return is_card_cost_waived(state, player_id=player_id, card=card)


def is_role_currently_active(state: GameState, *, player_id: str, role_type: str) -> bool:
    return is_role_active(state, player_id=player_id, role_type=role_type)


def can_use_role_for_contest(state: GameState, *, player_id: str, role_type: str) -> bool:
    if role_type == "Nonnen" and not state.players[player_id].nunnery_state.active:
        return False
    return can_use_role_in_contest(state, player_id=player_id, role_type=role_type)


def get_role_production_bonus(state: GameState, *, player_id: str, role_type: str) -> int:
    return get_role_production_modifier(state, player_id=player_id, role_type=role_type)


def get_tableau_missionary_resolution_count(state: GameState, *, player_id: str) -> int:
    if not _has_active_missionary_pair(state, player_id=player_id):
        return 0
    bonus_missionary_steal = max(0, int(get_turn_start_missionary_steal(state, player_id=player_id)))
    return 1 + bonus_missionary_steal + _get_herring_missionary_steal_bonus(state, player_id=player_id)


def _get_missionary_role_status(state: GameState, *, player_id: str) -> dict[str, Any]:
    player = state.players[player_id]
    assigned_missionaries = max(0, int(player.assigned_role_meeples.get("Missionare", 0)))
    missionaries_slot_limit = max(0, int(player.missionaries_slots))
    free_slots = max(0, missionaries_slot_limit - assigned_missionaries)
    temple_refill_blocked = _player_has_active_enlightener_rule_text(
        state,
        player_id=player_id,
        text=ENLIGHTENER_CANNOT_REFILL_TEMPLES_TEXT,
    )
    missionaries_present = assigned_missionaries > 0 or _get_role_card_count(player, role_type="Missionare") > 0
    has_nun_tableau_card = any(card.category == "Nonnen" for card in player.tableau)
    ordain_count = min(2, free_slots, max(0, int(player.meeples)))
    if temple_refill_blocked or (has_nun_tableau_card and not missionaries_present):
        ordain_count = 0

    missionaries_pair_full = missionaries_slot_limit > 0 and assigned_missionaries >= missionaries_slot_limit
    missionaries_pair_active = _has_active_missionary_pair(state, player_id=player_id)

    return {
        "assigned_missionaries": assigned_missionaries,
        "missionaries_slot_limit": missionaries_slot_limit,
        "ordain_count": ordain_count,
        "pair_full": missionaries_pair_full,
        "pair_active": missionaries_pair_active,
        "missionaries_ready_from_round": player.missionaries_ready_from_round,
    }


def get_legal_action_role_types(state: GameState, *, player_id: str) -> tuple[list[str], list[str]]:
    player = state.players[player_id]
    _sync_role_slot_assignments(state, player_id=player_id)
    legal_role_types: list[str] = []
    inactive_role_types: list[str] = []
    seen_role_types: set[str] = {"Mönche", "Missionare", "Nonnen"}
    temple_refill_blocked = _player_has_active_enlightener_rule_text(
        state,
        player_id=player_id,
        text=ENLIGHTENER_CANNOT_REFILL_TEMPLES_TEXT,
    )

    missionaries_assigned = max(0, int(player.assigned_role_meeples.get("Missionare", 0)))
    missionary_role_card_count = _get_role_card_count(player, role_type="Missionare")
    missionaries_present = missionaries_assigned > 0 or missionary_role_card_count > 0
    has_nun_tableau_card = any(card.category == "Nonnen" for card in player.tableau)
    monks_active = is_role_active(state, player_id=player_id, role_type="Mönche")
    monks_assigned = max(0, int(player.assigned_role_meeples.get("Mönche", 0)))
    monks_present = (
        _get_role_card_count(player, role_type="Mönche") > 0
        or monks_assigned > 0
        or missionaries_present
        or not has_nun_tableau_card
    )
    if not monks_active:
        inactive_role_types.append("Mönche")
    elif monks_present:
        monks_has_free_slot = monks_assigned < max(0, int(player.monks_slots))
        if monks_has_free_slot and player.meeples > 0 and not temple_refill_blocked:
            legal_role_types.append("Mönche")

    missionaries_active = is_role_active(state, player_id=player_id, role_type="Missionare")
    if not missionaries_active:
        inactive_role_types.append("Missionare")
    else:
        missionary_status = _get_missionary_role_status(state, player_id=player_id)
        if int(missionary_status["ordain_count"]) > 0:
            legal_role_types.append("Missionare")

    forge_available = (
        not _player_has_active_enlightener_rule_text(
            state,
            player_id=player_id,
            text=ENLIGHTENER_BLOCKS_MONUMENTS_TEXT,
        )
        and _has_free_slot(player, slot_kind="forge")
        and bool(state.monument_draw_pile)
    )
    if forge_available:
        legal_role_types.append("Monumente")

    if (
        player.nunnery_state.active
        and not temple_refill_blocked
        and _get_nun_preparation_count_for_action(player) > 0
    ):
        legal_role_types.append("Nonnen")

    for card in player.tableau:
        role_type = card.category
        if role_type not in ROLE_TYPES or role_type in seen_role_types:
            continue

        seen_role_types.add(role_type)
        if not is_role_active(state, player_id=player_id, role_type=role_type):
            inactive_role_types.append(role_type)
            continue

        if role_type == "Nonnen" and not player.nunnery_state.active:
            continue

        if role_type == "Nonnen" and temple_refill_blocked:
            continue

        if role_type == "Nonnen" and _get_nun_preparation_count_for_action(player) <= 0:
            continue

        if role_type in ACTION_ROLE_TYPES:
            legal_role_types.append(role_type)

    return legal_role_types, inactive_role_types


def get_legal_action_hand_cards(state: GameState, *, player_id: str) -> list[CardRef]:
    player = state.players[player_id]
    available_payable_meeples = _count_payable_meeples(player)
    return [
        card
        for card in player.hand_cards
        if card.category in ACTION_PLAYABLE_HAND_CATEGORIES
        and _is_hand_card_action_implemented(card)
        and can_play_card(state, player_id=player_id, card=card)
        and _is_hand_card_action_currently_legal(state, player_id=player_id, card=card)
        and not is_card_play_blocked(state, player_id=player_id, card=card)
        # Hand-card play moves are only legal when the current sacrifice cost is affordable.
        and _get_current_hand_card_action_sacrifice_cost(state, player_id=player_id, card=card)
        <= available_payable_meeples
    ]


def _get_current_hand_card_action_sacrifice_cost(state: GameState, *, player_id: str, card: CardRef) -> int:
    if is_card_cost_waived(state, player_id=player_id, card=card) or _is_intrinsic_cost_waived_by_tableau(
        state,
        player_id=player_id,
        card=card,
    ):
        return 0
    if card.category == "Heiliges Heer":
        base_intrinsic_cost = _get_minimum_holy_army_intrinsic_cost_before_sacrifice_reduction(
            state,
            player_id=player_id,
            card=card,
        )
    else:
        base_intrinsic_cost = _get_hand_card_intrinsic_cost_before_sacrifice_reduction(
            state,
            player_id=player_id,
            card=card,
        )
    additional_cost = get_additional_cost_for_card(state, player_id=player_id, card=card)
    return _apply_sacrifice_cost_reduction(
        state,
        player_id=player_id,
        amount=base_intrinsic_cost + additional_cost,
    )


def get_legal_moves(
    state: GameState,
    *,
    player_id: str | None = None,
    phase: str | None = None,
    actions_available: int = 2,
    planned_action_intents: list[dict[str, Any] | str] | None = None,
    contest_state: ContestState | None = None,
    eligible_player_ids: list[str] | None = None,
    include_monument_choices: bool = True,
) -> list[dict[str, Any]]:
    """Enumerate legal moves; autonomous bots must exclude hidden monument choices.

    With include_monument_choices=False, the monument move commits only to
    spending the action. The resolver chooses a card after drawing. The default
    retains concrete choices for explicit picker/command and replay consumers.
    """
    resolved_phase = phase or ("contest" if contest_state is not None else "turn")
    if resolved_phase not in {"turn", "contest"}:
        raise ValueError(f"Unsupported legal-move phase {resolved_phase!r}.")

    resolved_player_id = _resolve_legal_move_player_id(
        state,
        player_id=player_id,
        phase=resolved_phase,
        contest_state=contest_state,
    )
    if resolved_player_id is None:
        return []

    if resolved_phase == "contest":
        return _get_legal_contest_moves(
            state,
            player_id=resolved_player_id,
            contest_state=contest_state,
            eligible_player_ids=eligible_player_ids,
        )

    return _get_legal_turn_moves(
        state,
        player_id=resolved_player_id,
        actions_available=actions_available,
        planned_action_intents=planned_action_intents,
        include_monument_choices=include_monument_choices,
    )


def is_legal_move(
    state: GameState,
    move: dict[str, Any],
    *,
    player_id: str | None = None,
    phase: str | None = None,
    actions_available: int = 2,
    planned_action_intents: list[dict[str, Any] | str] | None = None,
    contest_state: ContestState | None = None,
    eligible_player_ids: list[str] | None = None,
) -> bool:
    legal_moves = get_legal_moves(
        state,
        player_id=player_id,
        phase=phase,
        actions_available=actions_available,
        planned_action_intents=planned_action_intents,
        contest_state=contest_state,
        eligible_player_ids=eligible_player_ids,
        include_monument_choices=bool(move.get("monument_card_id")),
    )
    target_signature = _legal_move_signature(move)
    return any(_legal_move_signature(candidate) == target_signature for candidate in legal_moves)


def is_legal(
    state: GameState,
    move: dict[str, Any],
    *,
    player_id: str | None = None,
    phase: str | None = None,
    actions_available: int = 2,
    planned_action_intents: list[dict[str, Any] | str] | None = None,
    contest_state: ContestState | None = None,
    eligible_player_ids: list[str] | None = None,
) -> bool:
    return is_legal_move(
        state,
        move,
        player_id=player_id,
        phase=phase,
        actions_available=actions_available,
        planned_action_intents=planned_action_intents,
        contest_state=contest_state,
        eligible_player_ids=eligible_player_ids,
    )


def has_legal_turn_action_available(
    state: GameState,
    *,
    player_id: str,
    actions_available: int,
    planned_action_intents: list[dict[str, Any] | str] | None = None,
) -> bool:
    return any(
        str(move.get("action") or "") != "skip"
        for move in get_legal_moves(
            state,
            player_id=player_id,
            phase="turn",
            actions_available=actions_available,
            planned_action_intents=planned_action_intents,
        )
    )


def get_turn_move_status(
    state: GameState,
    move: dict[str, Any],
    *,
    player_id: str,
    actions_available: int,
    planned_action_intents: list[dict[str, Any] | str] | None = None,
) -> dict[str, Any]:
    normalized_move = _normalize_turn_move_status_query(move)
    legal_moves = get_legal_moves(
        state,
        player_id=player_id,
        phase="turn",
        actions_available=actions_available,
        planned_action_intents=planned_action_intents,
        include_monument_choices=bool(normalized_move.get("monument_card_id")),
    )
    target_signature = _legal_move_signature(normalized_move)
    for candidate in legal_moves:
        if _legal_move_signature(candidate) == target_signature:
            return dict(candidate)

    projected_state, remaining_normal_actions = _project_turn_state_for_action_intents(
        state,
        player_id=player_id,
        actions_available=actions_available,
        planned_action_intents=planned_action_intents,
    )
    if projected_state is None or player_id not in projected_state.players:
        return _make_disabled_move_status("turn_projection_failed")
    if remaining_normal_actions <= 0:
        return _make_disabled_move_status("no_normal_actions_remaining")
    return _get_disabled_turn_move_status(
        projected_state,
        player_id=player_id,
        move=normalized_move,
    )


def _normalize_turn_move_status_query(move: dict[str, Any]) -> dict[str, Any]:
    normalized_move = dict(move)
    role_action_intent = normalized_move.get("role_action_intent")
    if isinstance(role_action_intent, dict):
        for field_name in ("monument_card_id", "target_player_id", "truth_source"):
            if field_name in role_action_intent and field_name not in normalized_move:
                normalized_move[field_name] = role_action_intent[field_name]
    return normalized_move


def _make_disabled_move_status(
    reason_code: str,
    *,
    reason: str = "",
) -> dict[str, Any]:
    return {
        "enabled": False,
        "reason": reason,
        "reason_code": reason_code,
    }


def _get_disabled_turn_move_status(
    state: GameState,
    *,
    player_id: str,
    move: dict[str, Any],
) -> dict[str, Any]:
    action = str(move.get("action") or "")
    if action == "play_hand_card":
        return _get_disabled_hand_card_move_status(state, player_id=player_id, move=move)
    if action == "role":
        return _get_disabled_role_move_status(state, player_id=player_id, move=move)
    if action == "unleash_stored_power":
        return _get_disabled_stored_power_move_status(state, player_id=player_id, move=move)
    if action == "prophet_send":
        return _get_disabled_prophet_move_status(state, player_id=player_id, move=move)
    if action == "grenade":
        return _get_disabled_grenade_move_status(state, player_id=player_id, move=move)
    if action == "skip":
        return _make_disabled_move_status("skip_not_available")
    return _make_disabled_move_status("move_not_legal")


def _get_disabled_hand_card_move_status(
    state: GameState,
    *,
    player_id: str,
    move: dict[str, Any],
) -> dict[str, Any]:
    player = state.players[player_id]
    card_id = str(move.get("card_id") or "")
    card = next((candidate for candidate in player.hand_cards if candidate.card_id == card_id), None)
    if card is None:
        return _make_disabled_move_status("hand_card_not_in_hand")
    if not _is_hand_card_action_implemented(card):
        return _make_disabled_move_status("hand_card_unimplemented")
    if card.category in player.commandment_state.blocked_card_categories:
        return _make_disabled_move_status(
            "hand_card_blocked_by_commandment",
            reason=card.category,
        )
    if is_tableau_card_disabled(state, player_id=player_id, card=card):
        return _make_disabled_move_status(
            "hand_card_disabled_by_commandment",
            reason=card.category,
        )
    if card.category == "Reliquie" and _player_has_active_enlightener_rule_text(
        state,
        player_id=player_id,
        text=ENLIGHTENER_BLOCKS_RELICS_TEXT,
    ):
        return _make_disabled_move_status("relics_blocked_by_enlightener")
    if not can_play_card(state, player_id=player_id, card=card):
        return _make_disabled_move_status("hand_card_blocked")
    if card.category == "Aufklärer" and not get_legal_enlightener_target_player_ids(state, player_id=player_id):
        return _make_disabled_move_status("no_legal_enlightener_target")
    if card.category in {"Aufklärer", "Reliquie"}:
        additional_cost = (
            0
            if is_card_cost_currently_waived(state, player_id=player_id, card=card)
            else get_effective_additional_cost(state, player_id=player_id, card=card)
        )
        intrinsic_cost = _get_effective_hand_card_intrinsic_cost(state, player_id=player_id, card=card)
        if additional_cost + intrinsic_cost > _count_payable_meeples(player):
            return _make_disabled_move_status("hand_card_cost_unaffordable")
    if card.category == "Heiliges Heer" and _get_current_hand_card_action_sacrifice_cost(
        state, player_id=player_id, card=card,
    ) > _count_payable_meeples(player):
        return _make_disabled_move_status("hand_card_cost_unaffordable")
    if not _is_hand_card_action_currently_legal(state, player_id=player_id, card=card):
        return _make_disabled_move_status("hand_card_not_legal")
    return _make_disabled_move_status("hand_card_not_legal")


def _get_disabled_role_move_status(
    state: GameState,
    *,
    player_id: str,
    move: dict[str, Any],
) -> dict[str, Any]:
    player = state.players[player_id]
    role_type = str(move.get("role_type") or "")
    legal_role_types, inactive_role_types = get_legal_action_role_types(state, player_id=player_id)
    temple_refill_blocked = _player_has_active_enlightener_rule_text(
        state,
        player_id=player_id,
        text=ENLIGHTENER_CANNOT_REFILL_TEMPLES_TEXT,
    )

    if role_type == "Monumente":
        if _player_has_active_enlightener_rule_text(
            state,
            player_id=player_id,
            text=ENLIGHTENER_BLOCKS_MONUMENTS_TEXT,
        ):
            return _make_disabled_move_status("monument_blocked_by_enlightener")
        if not _has_free_slot(player, slot_kind="forge"):
            return _make_disabled_move_status("forge_slot_full")
        forge_choices = get_forge_monument_choices(state, player_id=player_id)
        monument_card_id = str(move.get("monument_card_id") or "")
        if monument_card_id:
            choice = next(
                (candidate for candidate in forge_choices if str(candidate.get("card_id") or "") == monument_card_id),
                None,
            )
            if isinstance(choice, dict):
                choice_reason = str(choice.get("reason") or "")
                if choice_reason:
                    return _make_disabled_move_status("forge_choice_blocked", reason=choice_reason)
            return _make_disabled_move_status("no_monument_choices")
        if not forge_choices:
            return _make_disabled_move_status("no_monument_choices")
        blocked_reasons = [
            str(choice.get("reason") or "").strip()
            for choice in forge_choices
            if isinstance(choice, dict) and str(choice.get("reason") or "").strip()
        ]
        if blocked_reasons and not any(bool(choice.get("enabled")) for choice in forge_choices):
            return _make_disabled_move_status("no_monument_choices", reason=" / ".join(dict.fromkeys(blocked_reasons)))
        if "Monumente" not in legal_role_types:
            return _make_disabled_move_status("forge_not_legal")
        return _make_disabled_move_status("forge_not_legal")

    if role_type in inactive_role_types:
        return _make_disabled_move_status("role_inactive")
    if role_type == "Mönche":
        if temple_refill_blocked:
            return _make_disabled_move_status(
                "temple_refill_blocked",
                reason="Ein aktiver Aufklärer blockiert das Auffüllen deiner Tempel.",
            )
        if max(0, int(player.assigned_role_meeples.get("Mönche", 0))) >= max(0, int(player.monks_slots)):
            return _make_disabled_move_status("role_slot_full")
        if int(player.meeples) <= 0:
            return _make_disabled_move_status("no_free_meeples")
        return _make_disabled_move_status("role_not_legal")
    if role_type == "Missionare":
        missionary_status = _get_missionary_role_status(state, player_id=player_id)
        if temple_refill_blocked and int(missionary_status.get("ordain_count") or 0) <= 0:
            return _make_disabled_move_status(
                "temple_refill_blocked",
                reason="Ein aktiver Aufklärer blockiert das Auffüllen deiner Tempel.",
            )
        if int(missionary_status.get("assigned_missionaries") or 0) >= int(
            missionary_status.get("missionaries_slot_limit") or 0
        ):
            return _make_disabled_move_status("role_slot_full")
        if int(player.meeples) <= 0 and int(missionary_status.get("ordain_count") or 0) <= 0:
            return _make_disabled_move_status("no_free_meeples")
        return _make_disabled_move_status("role_not_legal")
    if role_type == "Nonnen":
        if temple_refill_blocked:
            return _make_disabled_move_status(
                "temple_refill_blocked",
                reason="Ein aktiver Aufklärer blockiert das Auffüllen deiner Tempel.",
            )
        if not player.nunnery_state.active:
            return _make_disabled_move_status("role_inactive")
        if not _has_free_slot(player, slot_kind="prepared_nuns"):
            return _make_disabled_move_status("role_slot_full")
        if int(player.meeples) <= 0:
            return _make_disabled_move_status("no_free_meeples")
        return _make_disabled_move_status("role_not_legal")

    return _make_disabled_move_status("role_not_legal")


def _get_disabled_stored_power_move_status(
    state: GameState,
    *,
    player_id: str,
    move: dict[str, Any],
) -> dict[str, Any]:
    player = state.players[player_id]
    phenomenon_id = str(move.get("phenomenon_card_id") or move.get("phenomenon_id") or "")
    if phenomenon_id not in player.stored_phenomena:
        return _make_disabled_move_status("stored_power_not_stored")
    if phenomenon_id in player.used_phenomenon_powers:
        return _make_disabled_move_status("stored_power_already_used")
    effective_additional_cost = _get_stored_power_unleash_effective_additional_cost(state, player_id=player_id)
    if effective_additional_cost > int(player.meeples):
        return _make_disabled_move_status(
            "stored_power_cost_unpayable",
            reason=(
                f"Benötigt {effective_additional_cost} geopferte Gläubige; "
                f"frei verfügbar: {int(player.meeples)}."
            ),
        )
    if _get_stored_power_default_payload(state, player_id=player_id, phenomenon_id=phenomenon_id) is None and (
        _get_stored_power_required_choice(state, player_id=player_id, phenomenon_id=phenomenon_id) is None
    ):
        return _make_disabled_move_status("stored_power_no_valid_target")
    return _make_disabled_move_status("stored_power_not_legal")


def _get_disabled_prophet_move_status(
    state: GameState,
    *,
    player_id: str,
    move: dict[str, Any],
) -> dict[str, Any]:
    player = state.players[player_id]
    if not player.prophet_owner:
        return _make_disabled_move_status("not_prophet_owner")
    if len(state.active_commandments) >= MAX_ACTIVE_COMMANDMENTS:
        return _make_disabled_move_status("commandment_limit_reached")
    target_player_id = str(move.get("target_player_id") or "")
    if target_player_id not in get_legal_prophet_target_player_ids(state, player_id=player_id):
        return _make_disabled_move_status("invalid_prophet_target")
    return _make_disabled_move_status("prophet_not_legal")


def _get_disabled_grenade_move_status(
    state: GameState,
    *,
    player_id: str,
    move: dict[str, Any],
) -> dict[str, Any]:
    player = state.players[player_id]
    grenade_state = player.hand_grenade_state
    if grenade_state.grenade is None:
        return _make_disabled_move_status("grenade_missing")
    if grenade_state.used:
        return _make_disabled_move_status("grenade_used")
    if player.meeples < 1:
        return _make_disabled_move_status("insufficient_meeples")
    requested_level = max(0, int(move.get("level") or 0))
    next_level = max(0, int(grenade_state.meeples_committed or 0)) + 1
    if next_level > 3:
        return _make_disabled_move_status("grenade_fully_loaded")
    if requested_level != next_level:
        return _make_disabled_move_status("grenade_not_legal")
    if requested_level == 3 and bool(move.get("detonate", False)):
        return _make_disabled_move_status("grenade_auto_detonates_level_3")
    return _make_disabled_move_status("grenade_not_legal")


def _resolve_legal_move_player_id(
    state: GameState,
    *,
    player_id: str | None,
    phase: str,
    contest_state: ContestState | None,
) -> str | None:
    if isinstance(player_id, str):
        return player_id
    if phase == "contest" and contest_state is not None and contest_state.player_order:
        return contest_state.player_order[contest_state.current_player_idx]
    if not state.player_order:
        return None
    return state.player_order[state.current_player_index]


def _get_blind_monument_attempt(state: GameState, *, player_id: str) -> dict[str, Any]:
    # The decision to spend an action may use the public tableau, but never
    # the identities, order or buildability of still-hidden draw options.
    monument = next(
        (card for card in state.players[player_id].tableau if card.category == "Monument"),
        None,
    )
    group_key = _get_monument_group_key_from_card(monument) if monument is not None else ""
    starter_id = (
        _get_monument_starter_player_id(monument, fallback_owner_id=player_id)
        if monument is not None else ""
    )
    return _finalize_legal_move({
        "phase": "turn",
        "action": "role",
        "type": "monument",
        "player_id": player_id,
        "role_type": "Monumente",
        "group_key": group_key,
        "continued_line": starter_id == player_id,
        "building_other_player_monument": bool(starter_id and starter_id != player_id),
        "completion_blocked": bool(group_key and _is_monument_line_completion_blocked(state, group_key=group_key)),
    })


def _get_legal_turn_moves(
    state: GameState,
    *,
    player_id: str,
    actions_available: int,
    planned_action_intents: list[dict[str, Any] | str] | None,
    include_monument_choices: bool = True,
) -> list[dict[str, Any]]:
    projected_state, remaining_normal_actions = _project_turn_state_for_action_intents(
        state,
        player_id=player_id,
        actions_available=actions_available,
        planned_action_intents=planned_action_intents,
    )
    if projected_state is None or player_id not in projected_state.players:
        return []

    state = projected_state
    player = state.players[player_id]
    legal_action_cards = get_legal_action_hand_cards(state, player_id=player_id)
    legal_role_types, _ = get_legal_action_role_types(state, player_id=player_id)
    projected_grenade_level = max(0, int(player.hand_grenade_state.meeples_committed))
    projected_grenade_used = bool(player.hand_grenade_state.used)

    moves: list[dict[str, Any]] = []
    if player.stored_monument_bonus_actions > 0:
        moves.append(_finalize_legal_move({
            "phase": "turn", "action": "use_monument_bonus",
            "type": "monument_bonus", "player_id": player_id,
        }))
    if remaining_normal_actions > 0:
        for card in legal_action_cards:
            move = {
                "phase": "turn",
                "action": "play_hand_card",
                "type": "play_card",
                "player_id": player_id,
                "card_id": card.card_id,
                "card_name": card.name,
                "card_category": card.category,
            }
            effect_payload = _get_default_action_card_effect_payload(state, player_id=player_id, card=card)
            if effect_payload is not None:
                move["effect_payload"] = effect_payload
            moves.append(
                _finalize_legal_move(
                    move,
                    default_payload=_get_play_hand_card_default_payload(state, player_id=player_id, card=card),
                    required_choice=_get_play_hand_card_required_choice(state, player_id=player_id, card=card),
                )
            )

        for role_type in ("Monumente", "Missionare", "Mönche", "Nonnen"):
            if role_type not in legal_role_types:
                continue
            if role_type == "Monumente":
                if not include_monument_choices:
                    moves.append(_get_blind_monument_attempt(state, player_id=player_id))
                    continue
                forge_choices = get_forge_monument_choices(state, player_id=player_id)
                enabled_forge_choices = [choice for choice in forge_choices if bool(choice["enabled"])]
                if not enabled_forge_choices and forge_choices:
                    moves.append(
                        _finalize_legal_move(
                            {
                                "phase": "turn",
                                "action": "role",
                                "type": "monument",
                                "player_id": player_id,
                                "role_type": "Monumente",
                                "monument_card_id": "",
                                "card_id": "",
                                "card_name": "",
                                "group_key": "",
                                "part": 0,
                                "continued_line": False,
                                "building_other_player_monument": False,
                                "completion_blocked": False,
                                "dead_draw": True,
                            }
                        )
                    )
                for choice in enabled_forge_choices:
                    moves.append(
                        _finalize_legal_move(
                            {
                                "phase": "turn",
                                "action": "role",
                                "type": "monument",
                                "player_id": player_id,
                                "role_type": "Monumente",
                                "monument_card_id": str(choice["card_id"]),
                                "card_id": str(choice["card_id"]),
                                "card_name": str(choice["card_name"]),
                                "group_key": str(choice["group_key"]),
                                "part": int(choice["part"]),
                                "continued_line": str(choice.get("started_by_player_id") or "") == player_id,
                                "building_other_player_monument": bool(choice["building_other_player_monument"]),
                                "completion_blocked": bool(choice["completion_blocked"]),
                            }
                        )
                    )
                continue
            move = {
                "phase": "turn",
                "action": "role",
                "type": "temple",
                "player_id": player_id,
                "role_type": role_type,
            }
            role_default_payload = None
            role_required_choice = None
            if role_type == "Missionare":
                role_default_payload, role_required_choice = _get_missionary_role_move_metadata(
                    state,
                    player_id=player_id,
                )
            moves.append(
                _finalize_legal_move(
                    move,
                    default_payload=role_default_payload,
                    required_choice=role_required_choice,
                )
            )

        slot_pressure = len(player.stored_phenomena) >= max(1, int(player.phenomena_slots))
        stored_power_effective_cost = _get_stored_power_unleash_effective_additional_cost(state, player_id=player_id)
        for phenomenon_id in player.stored_phenomena:
            if stored_power_effective_cost > int(player.meeples):
                continue
            moves.append(
                _finalize_legal_move(
                    {
                        "phase": "turn",
                        "action": "unleash_stored_power",
                        "type": "phenomenon",
                        "player_id": player_id,
                        "phenomenon_id": phenomenon_id,
                        "phenomenon_card_id": phenomenon_id,
                        "slot_pressure": slot_pressure,
                    },
                    default_payload=_get_stored_power_default_payload(
                        state,
                        player_id=player_id,
                        phenomenon_id=phenomenon_id,
                    ),
                    required_choice=_get_stored_power_required_choice(
                        state,
                        player_id=player_id,
                        phenomenon_id=phenomenon_id,
                    ),
                )
            )

        if player.prophet_owner:
            for target_player_id in get_legal_prophet_target_player_ids(state, player_id=player_id):
                moves.append(
                    _finalize_legal_move(
                        {
                            "phase": "turn",
                            "action": "prophet_send",
                            "type": "prophet",
                            "player_id": player_id,
                            "target_player_id": target_player_id,
                        },
                        default_payload={"target_player_id": target_player_id},
                    )
                )

        if player.hand_grenade_state.grenade is not None and not projected_grenade_used and player.meeples >= 1:
            next_level = projected_grenade_level + 1
            if 1 <= next_level <= 3:
                detonate_options = [False] if next_level >= 3 else [False, True]
                for detonate in detonate_options:
                    moves.append(
                        _finalize_legal_move(
                            {
                                "phase": "turn",
                                "action": "grenade",
                                "type": "grenade",
                                "player_id": player_id,
                                "level": next_level,
                                "detonate": detonate,
                            },
                            default_payload=_get_grenade_auto_default_payload(
                                state,
                                player_id=player_id,
                                level=next_level,
                            ),
                            required_choice=_get_grenade_required_choice(
                                state,
                                player_id=player_id,
                                level=next_level,
                            ),
                        )
                    )

        moves.append(
            _finalize_legal_move(
                {
                    "phase": "turn",
                    "action": "skip",
                    "type": "pass",
                    "player_id": player_id,
                }
            )
        )
        return moves

    return moves


def _project_turn_state_for_action_intents(
    state: GameState,
    *,
    player_id: str,
    actions_available: int,
    planned_action_intents: list[dict[str, Any] | str] | None,
) -> tuple[GameState | None, int]:
    if player_id not in state.players:
        return None, 0

    remaining_actions = max(0, int(actions_available))
    if not planned_action_intents:
        return state, remaining_actions

    projected_state = copy.deepcopy(state)
    try:
        take_actions(
            projected_state,
            player_id=player_id,
            actions_available=remaining_actions,
            action_intents=planned_action_intents,
            require_explicit_action_intents=True,
        )
    except ValueError:
        return None, 0

    take_actions_event = next(
        (
            event
            for event in reversed(projected_state.event_log)
            if event.get("type") == "take_actions_resolved" and str(event.get("player_id") or "") == player_id
        ),
        None,
    )
    if take_actions_event is None:
        return None, 0
    remaining_actions = max(0, int(take_actions_event.get("remaining_actions") or 0))
    return projected_state, remaining_actions


def _finalize_legal_move(
    move: dict[str, Any],
    *,
    default_payload: dict[str, Any] | None = None,
    required_choice: dict[str, Any] | None = None,
) -> dict[str, Any]:
    move["enabled"] = True
    move["reason"] = ""
    if isinstance(default_payload, dict):
        move["default_payload"] = copy.deepcopy(default_payload)
        default_target_player_id = default_payload.get("target_player_id")
        if isinstance(default_target_player_id, str) and default_target_player_id:
            move.setdefault("default_target_player_id", default_target_player_id)
    if isinstance(required_choice, dict) and required_choice:
        move["required_choice"] = copy.deepcopy(required_choice)
    return move


def _make_required_choice(
    *,
    field: str,
    kind: str,
    options: list[Any],
    min_selected: int = 1,
    max_selected: int = 1,
) -> dict[str, Any] | None:
    normalized_options: list[Any] = []
    for option in options:
        if isinstance(option, (str, int, bool)):
            normalized_options.append(option)
            continue
        if isinstance(option, dict) and option:
            normalized_options.append(copy.deepcopy(option))
    if not field or not kind or not normalized_options:
        return None
    return {
        "field": field,
        "kind": kind,
        "options": normalized_options,
        "min": max(0, int(min_selected)),
        "max": max(0, int(max_selected)),
    }


def _get_play_hand_card_default_payload(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
) -> dict[str, Any] | None:
    default_payload = dict(_get_default_action_card_effect_payload(state, player_id=player_id, card=card) or {})

    if card.category == "Reliquie":
        rules_text = _get_card_rules_text(card)
        if RELIC_RECOVER_SHUFFLED_TOP_THREE_HEAVENLY_FROM_DISCARD_TEXT in rules_text:
            preview_cards = get_relic_recovery_top_three_preview_cards(state, player_id=player_id, card=card)
            if preview_cards:
                default_payload.setdefault("target_card_id", preview_cards[0].card_id)

    if card.category in {"Aufklärer", "Reliquie"} and not (
        is_card_cost_currently_waived(state, player_id=player_id, card=card)
        or _is_intrinsic_cost_waived_by_tableau(state, player_id=player_id, card=card)
    ):
        intrinsic_cost = _get_effective_hand_card_intrinsic_cost(
            state,
            player_id=player_id,
            card=card,
        )
        payment_choice = _build_auto_grenade_payment_choice(
            state,
            player_id=player_id,
            amount=intrinsic_cost,
        )
        if payment_choice is not None:
            default_payload["intrinsic_cost_payment_choice"] = payment_choice

    return default_payload or None


def _get_play_hand_card_required_choice(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
) -> dict[str, Any] | None:
    if card.category != "Reliquie":
        return None

    player = state.players[player_id]
    if _has_free_slot(player, slot_kind="relics"):
        return None

    own_relic_ids = [
        tableau_card.card_id
        for tableau_card in player.tableau
        if tableau_card.category == "Reliquie"
    ]
    if len(own_relic_ids) <= 1:
        return None

    return _make_required_choice(
        field="replaced_card_id",
        kind="relic_overwrite",
        options=own_relic_ids,
    )


def _get_missionary_role_move_metadata(
    state: GameState,
    *,
    player_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    del state, player_id
    return None, None


def _get_stored_power_default_payload(
    state: GameState,
    *,
    player_id: str,
    phenomenon_id: str,
) -> dict[str, Any] | None:
    opponent_ids = _get_opponent_player_ids_in_turn_order(state, player_id=player_id)

    if phenomenon_id in (
        PHENOMENON_EFFECT_NEXT_CONTEST_BLOCK
        | PHENOMENON_EFFECT_NEXT_TURN_SKIP
        | PHENOMENON_EFFECT_NEXT_TURN_ACTION_PENALTY
    ):
        return {"target_player_id": opponent_ids[0]} if opponent_ids else None

    if phenomenon_id == "eichhoernchenplage__Phänomene__1":
        return {"target_player_id": opponent_ids[0], "missionaries_to_steal": 2} if opponent_ids else None

    if phenomenon_id in PHENOMENON_EFFECT_DESTROY_RELIC_OR_SHATTER_COMMANDMENT:
        candidate_owner_ids = [
            candidate_player_id
            for candidate_player_id in opponent_ids
            if any(card.category == "Reliquie" for card in state.players[candidate_player_id].tableau)
        ]
        if candidate_owner_ids:
            target_player_id = candidate_owner_ids[0]
            target_card_id = next(
                card.card_id
                for card in state.players[target_player_id].tableau
                if card.category == "Reliquie"
            )
            return {
                "mode": "destroy_relic",
                "target_player_id": target_player_id,
                "target_card_id": target_card_id,
            }
        if state.active_commandments:
            return {
                "mode": "shatter_commandment",
                "commandment_card_id": state.active_commandments[0].card_id,
            }
        return None

    if phenomenon_id == "pest__Phänomene__1":
        target_player_id = _resolve_stored_power_target_player_id_with_predicate(
            state,
            source_player_id=player_id,
            effect_payload={},
            effect_label=phenomenon_id,
            predicate=lambda candidate_player: sum(
                candidate_player.assigned_role_meeples.get(role, 0)
                for role in ROLE_TYPES
            ) > 0,
        )
        if target_player_id is None:
            return None
        target_player = state.players[target_player_id]
        _sync_role_slot_assignments(state, player_id=target_player_id)
        remaining = 3
        role_sacrifice_plan: dict[str, int] = {}
        for role_type in ROLE_TYPES:
            if remaining <= 0:
                break
            available = int(target_player.assigned_role_meeples.get(role_type, 0))
            removed = min(available, remaining)
            if removed > 0:
                role_sacrifice_plan[role_type] = removed
            remaining -= removed
        return {
            "target_player_id": target_player_id,
            "role_sacrifice_plan": role_sacrifice_plan,
        }

    if phenomenon_id == "tsunami__Phänomene__1":
        target_player_id = _resolve_stored_power_target_player_id_with_predicate(
            state,
            source_player_id=player_id,
            effect_payload={},
            effect_label=phenomenon_id,
            predicate=lambda candidate_player: any(
                candidate_player.assigned_role_meeples.get(role_type, 0) > 0 for role_type in ROLE_TYPES
            ) or candidate_player.nunnery_state.prepared_nuns > 0,
        )
        if target_player_id is None:
            return None
        target_player = state.players[target_player_id]
        _sync_role_slot_assignments(state, player_id=target_player_id)
        role_options = [
            role_type
            for role_type in ROLE_TYPES
            if target_player.assigned_role_meeples.get(role_type, 0) > 0
            or (role_type == "Nonnen" and target_player.nunnery_state.prepared_nuns > 0)
        ]
        if not role_options:
            return {"target_player_id": target_player_id}
        return {
            "target_player_id": target_player_id,
            "temple_role_type": role_options[0],
        }

    if phenomenon_id == "sonnenfinsternis__Phänomene__1":
        target_player_id = _resolve_stored_power_target_player_id_with_predicate(
            state,
            source_player_id=player_id,
            effect_payload={},
            effect_label=phenomenon_id,
            predicate=lambda candidate_player: any(card.category != "Wahrheit" for card in candidate_player.hand_cards),
        )
        if target_player_id is not None:
            return {
                "mode": "take_heavenly_from_fellow",
                "target_player_id": target_player_id,
            }
        if state.active_commandments:
            return {
                "mode": "shatter_commandment",
                "commandment_card_id": state.active_commandments[0].card_id,
            }
        return None

    if phenomenon_id == "kornkreise__Phänomene__1":
        if opponent_ids:
            return {
                "mode": "swap_all_heavenly_hand",
                "target_player_id": opponent_ids[0],
            }
        if state.active_commandments:
            return {
                "mode": "shatter_commandment",
                "commandment_card_id": state.active_commandments[0].card_id,
            }
        return None

    if phenomenon_id == "froschregen__Phänomene__1":
        if state.active_commandments:
            return {
                "mode": "shatter_commandment",
                "commandment_card_id": state.active_commandments[0].card_id,
            }
        required_monument_group_keys = _collect_player_monument_group_keys(state.players[player_id])
        for monument_card in state.monument_draw_pile:
            if required_monument_group_keys and _monument_group_key_from_card_id(monument_card.card_id) not in required_monument_group_keys:
                continue
            return {
                "mode": "search_monument",
                "monument_card_id": monument_card.card_id,
                "monument_part": _infer_monument_part_from_card_id(monument_card.card_id),
            }
        return None

    if phenomenon_id == "kugelblitz__Phänomene__1":
        target_player_id = _resolve_stored_power_target_player_id_with_predicate(
            state,
            source_player_id=player_id,
            effect_payload={},
            effect_label=phenomenon_id,
            predicate=lambda candidate_player: bool(candidate_player.stored_phenomena),
        )
        if target_player_id is None:
            return None
        target_player = state.players[target_player_id]
        if not target_player.stored_phenomena:
            return {"target_player_id": target_player_id}
        return {
            "target_player_id": target_player_id,
            "target_phenomenon_card_id": target_player.stored_phenomena[0],
        }

    return None


def _get_stored_power_required_choice(
    state: GameState,
    *,
    player_id: str,
    phenomenon_id: str,
) -> dict[str, Any] | None:
    opponent_ids = _get_opponent_player_ids_in_turn_order(state, player_id=player_id)
    if phenomenon_id in (
        PHENOMENON_EFFECT_NEXT_CONTEST_BLOCK
        | PHENOMENON_EFFECT_NEXT_TURN_SKIP
        | PHENOMENON_EFFECT_NEXT_TURN_ACTION_PENALTY
    ) and len(opponent_ids) > 1:
        return _make_required_choice(
            field="target_player_id",
            kind="stored_power_target_player",
            options=opponent_ids,
        )
    if phenomenon_id == "eichhoernchenplage__Phänomene__1" and len(opponent_ids) > 1:
        return _make_required_choice(
            field="target_player_id",
            kind="stored_power_target_player",
            options=opponent_ids,
        )
    if phenomenon_id == "kornkreise__Phänomene__1":
        if len(opponent_ids) > 1:
            return _make_required_choice(
                field="target_player_id",
                kind="stored_power_target_player",
                options=opponent_ids,
            )
        if len(opponent_ids) == 1 and state.active_commandments:
            return _make_required_choice(
                field="mode",
                kind="stored_power_mode",
                options=["swap_all_heavenly_hand", "shatter_commandment"],
            )
    return None


def _resolve_grenade_play_free_enlighteners_default_payload(
    state: GameState,
    *,
    player_id: str,
    count: int,
    require_overwrite: bool,
    distributed: bool,
) -> dict[str, Any] | None:
    source_player = state.players[player_id]
    placements: list[dict[str, Any]] = []
    used_target_player_ids: set[str] = set()
    while len(placements) < count:
        next_hand_card_id = next(
            (card.card_id for card in source_player.hand_cards if card.category == "Aufklärer"),
            None,
        )
        if next_hand_card_id is None:
            break
        legal_target_player_ids = _get_grenade_enlightener_target_player_ids(
            state,
            player_id=player_id,
            require_overwrite=require_overwrite,
        )
        if distributed and used_target_player_ids:
            preferred_target_player_ids = [
                target_player_id
                for target_player_id in legal_target_player_ids
                if target_player_id not in used_target_player_ids
            ]
            if preferred_target_player_ids:
                legal_target_player_ids = preferred_target_player_ids
        chosen_target_player_id = None
        chosen_replaced_card_id = None
        for target_player_id in legal_target_player_ids:
            target_enlighteners = [
                card
                for card in state.players[target_player_id].tableau
                if card.category == "Aufklärer"
            ]
            if require_overwrite and not target_enlighteners and not _has_relic_immunity_against_next_enlightener(
                state,
                protected_player_id=target_player_id,
            ):
                continue
            if not require_overwrite and not _can_receive_enlightener(
                state,
                source_player_id=player_id,
                target_player_id=target_player_id,
            ):
                continue
            chosen_target_player_id = target_player_id
            chosen_replaced_card_id = target_enlighteners[0].card_id if require_overwrite and target_enlighteners else None
            break
        if chosen_target_player_id is None:
            break
        placement: dict[str, Any] = {
            "hand_card_id": next_hand_card_id,
            "target_player_id": chosen_target_player_id,
        }
        if isinstance(chosen_replaced_card_id, str) and chosen_replaced_card_id:
            placement["replaced_card_id"] = chosen_replaced_card_id
        placements.append(placement)
        try:
            _place_free_enlightener_from_grenade(
                state,
                source_player_id=player_id,
                hand_card_id=next_hand_card_id,
                target_player_id=chosen_target_player_id,
                require_overwrite=require_overwrite,
                replaced_card_id=chosen_replaced_card_id,
            )
        except ValueError:
            break
        used_target_player_ids.add(chosen_target_player_id)
        if not distributed:
            break
    return {"placements": placements} if placements else None


def _get_grenade_auto_default_payload(
    state: GameState,
    *,
    player_id: str,
    level: int,
) -> dict[str, Any] | None:
    grenade_state = state.players[player_id].hand_grenade_state
    grenade = grenade_state.grenade
    if grenade is None:
        return None
    effect = dict(grenade.tier_effects.get(level) or {})
    effect_kind = str(effect.get("effect") or "")
    opponent_ids = _get_opponent_player_ids_in_turn_order(state, player_id=player_id)

    if effect_kind == "forced_total_sacrifice":
        return {"target_player_ids": list(opponent_ids)} if opponent_ids else None

    if effect_kind == "forced_temple_role_wipe":
        target_player_id = _resolve_stored_power_target_player_id_with_predicate(
            state,
            source_player_id=player_id,
            effect_payload={},
            effect_label=grenade.card_id,
            predicate=lambda candidate_player: any(
                candidate_player.assigned_role_meeples.get(role_type, 0) > 0
                or (role_type == "Nonnen" and candidate_player.nunnery_state.prepared_nuns > 0)
                for role_type in tuple(str(role_type) for role_type in effect.get("role_types", ()))
            ),
        )
        return {"target_player_id": target_player_id} if isinstance(target_player_id, str) and target_player_id else None

    if effect_kind == "destroy_stored_phenomena":
        count = int(effect.get("count") or 0)
        targets: list[dict[str, str]] = []
        for target_player_id in opponent_ids:
            for phenomenon_card_id in state.players[target_player_id].stored_phenomena:
                targets.append(
                    {
                        "target_player_id": target_player_id,
                        "phenomenon_card_id": phenomenon_card_id,
                    }
                )
        return {"targets": targets[:count]} if targets else None

    if effect_kind == "shatter_commandments":
        count = int(effect.get("count") or 0)
        commandment_card_ids = [commandment.card_id for commandment in state.active_commandments[:count]]
        result: dict[str, Any] = {"commandment_card_ids": commandment_card_ids} if commandment_card_ids else {}
        if effect.get("award_prophet") and opponent_ids:
            result["target_player_id"] = opponent_ids[0]
        return result or None

    if effect_kind == "destroy_relics":
        count = int(effect.get("count") or 0)
        targets: list[dict[str, str]] = []
        for target_player_id in opponent_ids:
            for candidate_card in state.players[target_player_id].tableau:
                if candidate_card.category != "Reliquie":
                    continue
                targets.append(
                    {
                        "target_player_id": target_player_id,
                        "target_card_id": candidate_card.card_id,
                    }
                )
        return {"targets": targets[:count]} if targets else None

    if effect_kind == "next_turn_action_penalty":
        return {"target_player_id": opponent_ids[0]} if opponent_ids else None

    if effect_kind == "discard_truth":
        target_player_id = _resolve_stored_power_target_player_id_with_predicate(
            state,
            source_player_id=player_id,
            effect_payload={},
            effect_label=grenade.card_id,
            predicate=lambda candidate_player: bool(candidate_player.truth_pool),
        )
        if target_player_id is None:
            return None
        target_truth_pool = sorted(int(value) for value in state.players[target_player_id].truth_pool)
        discard_all = bool(effect.get("discard_all", False))
        truth_values = target_truth_pool if discard_all else target_truth_pool[: max(0, int(effect.get("count") or 0))]
        return {
            "target_player_id": target_player_id,
            "truth_values": truth_values,
        }

    if effect_kind == "discard_heavenly":
        count = int(effect.get("count") or 0)
        distributed = bool(effect.get("distributed", False))
        if distributed:
            discard_card_ids_by_player: dict[str, list[str]] = {}
            target_player_ids: list[str] = []
            remaining = count
            for target_player_id in opponent_ids:
                if remaining <= 0:
                    break
                heavenly_cards = [
                    card
                    for card in state.players[target_player_id].hand_cards
                    if card.category in ACTION_PLAYABLE_HAND_CATEGORIES
                ]
                if not heavenly_cards:
                    continue
                discard_card_ids = [
                    card.card_id
                    for card in sorted(
                        heavenly_cards,
                        key=lambda card: (int(card.truth_value or 99), state.players[target_player_id].hand_cards.index(card)),
                    )[:remaining]
                ]
                if not discard_card_ids:
                    continue
                target_player_ids.append(target_player_id)
                discard_card_ids_by_player[target_player_id] = discard_card_ids
                remaining -= len(discard_card_ids)
            if not discard_card_ids_by_player:
                return None
            return {
                "target_player_ids": target_player_ids,
                "discard_card_ids_by_player": discard_card_ids_by_player,
            }
        target_player_id = _resolve_stored_power_target_player_id_with_predicate(
            state,
            source_player_id=player_id,
            effect_payload={},
            effect_label=grenade.card_id,
            predicate=lambda candidate_player: any(
                card.category in ACTION_PLAYABLE_HAND_CATEGORIES for card in candidate_player.hand_cards
            ),
        )
        if target_player_id is None:
            return None
        heavenly_cards = [
            card
            for card in state.players[target_player_id].hand_cards
            if card.category in ACTION_PLAYABLE_HAND_CATEGORIES
        ]
        discard_card_ids = [
            card.card_id
            for card in sorted(
                heavenly_cards,
                key=lambda card: (int(card.truth_value or 99), state.players[target_player_id].hand_cards.index(card)),
            )[:count]
        ]
        return {
            "target_player_id": target_player_id,
            "discard_card_ids": discard_card_ids,
        } if discard_card_ids else None

    if effect_kind == "play_free_enlighteners":
        simulated_state = copy.deepcopy(state)
        return _resolve_grenade_play_free_enlighteners_default_payload(
            simulated_state,
            player_id=player_id,
            count=int(effect.get("count") or 0),
            require_overwrite=bool(effect.get("require_overwrite", False)),
            distributed=bool(effect.get("distributed", False)),
        )

    return None


def _get_grenade_required_choice(
    state: GameState,
    *,
    player_id: str,
    level: int,
) -> dict[str, Any] | None:
    grenade_state = state.players[player_id].hand_grenade_state
    grenade = grenade_state.grenade
    if grenade is None:
        return None
    effect = dict(grenade.tier_effects.get(level) or {})
    effect_kind = str(effect.get("effect") or "")

    if effect_kind == "next_turn_action_penalty" or (effect_kind == "shatter_commandments" and effect.get("award_prophet")):
        opponent_ids = _get_opponent_player_ids_in_turn_order(state, player_id=player_id)
        if len(opponent_ids) > 1:
            return _make_required_choice(
                field="target_player_id",
                kind="grenade_target_player",
                options=opponent_ids,
            )

    if effect_kind == "forced_temple_role_wipe":
        target_player_ids = [
            candidate_player_id
            for candidate_player_id in _get_opponent_player_ids_in_turn_order(state, player_id=player_id)
            if any(
                state.players[candidate_player_id].assigned_role_meeples.get(role_type, 0) > 0
                or (role_type == "Nonnen" and state.players[candidate_player_id].nunnery_state.prepared_nuns > 0)
                for role_type in tuple(str(role_type) for role_type in effect.get("role_types", ()))
            )
        ]
        if len(target_player_ids) > 1:
            return _make_required_choice(
                field="target_player_id",
                kind="grenade_target_player",
                options=target_player_ids,
            )
    return None


def _get_default_action_card_effect_payload(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
) -> dict[str, Any] | None:
    if card.category == "Segen" and card.name.startswith("Mantra"):
        target_player_ids = _get_mantra_target_player_ids(state, player_id=player_id)
        if not target_player_ids:
            return None
        target_player_id = target_player_ids[0]
        available_truth_values = _get_mantra_available_truth_values(
            state,
            target_player_id=target_player_id,
        )
        if not available_truth_values:
            return None
        return {
            "target_player_id": target_player_id,
            "truth_value": max(available_truth_values),
        }

    if card.category == "Reliquie":
        player = state.players[player_id]
        if _has_free_slot(player, slot_kind="relics"):
            return None
        own_relics = [tableau_card for tableau_card in player.tableau if tableau_card.category == "Reliquie"]
        if not own_relics:
            return None
        return {"replaced_card_id": own_relics[0].card_id}

    if card.category != "Heiliges Heer":
        return None

    profile = _get_holy_army_profile(card)
    if profile["mode"] == "schleifer":
        target_entries = _get_schleifer_target_entries(state, player_id=player_id)
        if not target_entries:
            return None
        target_entry = target_entries[0]
        destination_player_ids = list(target_entry.get("destination_player_ids") or [])
        if not destination_player_ids:
            return None
        return {
            "target_card_id": str(target_entry["target_card_id"]),
            "destination_player_id": str(destination_player_ids[0]),
        }

    own_enlighteners = [
        tableau_card
        for tableau_card in state.players[player_id].tableau
        if tableau_card.category == "Aufklärer"
    ]
    if not own_enlighteners:
        return None

    specialized_targets = [
        tableau_card
        for tableau_card in own_enlighteners
        if any(
            _holy_army_target_matches_card(tableau_card, target_fragment)
            for target_fragment in profile["specialized_targets"]
        )
    ]
    if specialized_targets:
        return {
            "mode": "specialized",
            "target_card_id": specialized_targets[0].card_id,
        }
    return {
        "mode": "any_own",
        "target_card_id": own_enlighteners[0].card_id,
    }


def _get_legal_contest_moves(
    state: GameState,
    *,
    player_id: str,
    contest_state: ContestState | None,
    eligible_player_ids: list[str] | None,
) -> list[dict[str, Any]]:
    if player_id not in state.players:
        return []

    if eligible_player_ids is None:
        eligible_player_ids, _ = compute_eligible_players(state)
    if player_id not in set(eligible_player_ids):
        return []

    bid_options = get_bid_options(state, player_id, contest_state)
    moves: list[dict[str, Any]] = []
    for bid_choice in bid_options:
        try:
            validate_contest_bid_choice(
                state,
                player_id=player_id,
                bid_choice=bid_choice,
                contest_state=contest_state,
            )
        except ValueError:
            continue
        bid_card_id = (
            bid_choice.truth_card_ids[0]
            if bid_choice.truth_card_ids
            else bid_choice.heavenly_card_ids[0]
            if bid_choice.heavenly_card_ids
            else ""
        )
        bid_card = next(
            (card for card in state.players[player_id].hand_cards if card.card_id == bid_card_id),
            None,
        )
        estimated_value = estimate_bid_choice_total(
            state,
            player_id,
            bid_choice,
            contest_state=contest_state,
        )
        moves.append(
            _finalize_legal_move(
                {
                    "phase": "contest",
                    "action": "bid",
                    "type": "bid",
                    "player_id": player_id,
                    "card_id": bid_card_id,
                    "card_category": None if bid_card is None else bid_card.category,
                    "bid_choice": {
                        "truth_card_ids": list(bid_choice.truth_card_ids),
                        "heavenly_card_ids": list(bid_choice.heavenly_card_ids),
                    },
                    "bid_value_estimate": estimated_value,
                }
            )
        )

    bid_required = (
        contest_state is not None
        and must_bid_before_pass(
            state,
            contest_state,
            player_id=player_id,
            has_legal_bid=bool(moves),
        )
    )
    if not bid_required:
        moves.append(
            _finalize_legal_move(
                {
                    "phase": "contest",
                    "action": "pass",
                    "type": "pass",
                    "player_id": player_id,
                }
            )
        )
    return moves


def _legal_move_signature(move: dict[str, Any]) -> tuple[Any, ...]:
    action = str(move.get("action"))
    if action == "play_hand_card":
        return ("play_hand_card", str(move.get("card_id")))
    if action == "prophet_send":
        return ("prophet_send", str(move.get("target_player_id") or ""))
    if action == "role":
        return ("role", str(move.get("role_type")), str(move.get("monument_card_id") or ""))
    if action == "unleash_stored_power":
        return (
            "unleash_stored_power",
            str(move.get("phenomenon_card_id") or move.get("phenomenon_id") or ""),
        )
    if action == "play_stored_phenomenon_action":
        return ("play_stored_phenomenon_action", str(move.get("phenomenon_id") or ""))
    if action == "grenade":
        return ("grenade", int(move.get("level") or 0), bool(move.get("detonate", False)))
    if action == "bid":
        bid_choice = move.get("bid_choice") or {}
        return (
            "bid",
            tuple(str(card_id) for card_id in bid_choice.get("truth_card_ids", [])),
            tuple(str(card_id) for card_id in bid_choice.get("heavenly_card_ids", [])),
        )
    return (action,)


def _is_hand_card_action_currently_legal(state: GameState, *, player_id: str, card: CardRef) -> bool:
    if card.category == "Segen":
        if card.name.startswith("Mantra"):
            return bool(_get_mantra_target_player_ids(state, player_id=player_id))
        return True

    player = state.players[player_id]
    additional_cost = 0 if is_card_cost_currently_waived(state, player_id=player_id, card=card) else get_effective_additional_cost(
        state,
        player_id=player_id,
        card=card,
    )
    intrinsic_cost = (
        _get_effective_hand_card_intrinsic_cost(state, player_id=player_id, card=card)
        if card.category in {"Aufklärer", "Reliquie"}
        else 0
    )
    if card.category == "Heiliges Heer":
        intrinsic_cost = _apply_sacrifice_cost_reduction(
            state, player_id=player_id,
            amount=_get_minimum_holy_army_intrinsic_cost_before_sacrifice_reduction(
                state, player_id=player_id, card=card,
            ),
        )
    # Hand-card legality must use the total payable pool, not only free meeples,
    # because explicit payment choices may bind assigned role meeples or prepared
    # nuns for both intrinsic and additional card costs.
    available_payable_meeples = _count_payable_meeples(player)
    if additional_cost + intrinsic_cost > available_payable_meeples:
        return False

    if card.category == "Aufklärer":
        return bool(get_legal_enlightener_target_player_ids(state, player_id=player_id))

    if card.category == "Reliquie":
        if _has_free_slot(player, slot_kind="relics"):
            return True
        return any(tableau_card.category == "Reliquie" for tableau_card in player.tableau)

    if card.category != "Heiliges Heer":
        return False

    own_enlighteners = [tableau_card for tableau_card in player.tableau if tableau_card.category == "Aufklärer"]
    profile = _get_holy_army_profile(card)
    if profile["mode"] == "schleifer":
        return bool(_get_schleifer_target_entries(state, player_id=player_id))

    if not own_enlighteners:
        return False

    specialized_targets = [
        tableau_card
        for tableau_card in own_enlighteners
        if any(
            _holy_army_target_matches_card(tableau_card, target_fragment)
            for target_fragment in profile["specialized_targets"]
        )
    ]
    if specialized_targets and available_payable_meeples >= 0:
        return True
    return True


def get_legal_enlightener_target_player_ids(state: GameState, *, player_id: str) -> list[str]:
    if player_id not in state.players:
        return []
    # Placement occupies the recipient's tableau, not the sender's slots.
    target_player_ids: list[str] = []
    opponent_player_ids = set(_get_opponent_player_ids_in_turn_order(state, player_id=player_id))
    for candidate_player_id in _get_turn_order_from_player(state, player_id=player_id):
        if candidate_player_id not in opponent_player_ids:
            continue
        if _can_receive_enlightener(state, source_player_id=player_id, target_player_id=candidate_player_id):
            target_player_ids.append(candidate_player_id)
    return target_player_ids


def _get_grenade_enlightener_target_player_ids(
    state: GameState,
    *,
    player_id: str,
    require_overwrite: bool,
) -> list[str]:
    if not require_overwrite:
        return get_legal_enlightener_target_player_ids(state, player_id=player_id)
    target_player_ids: list[str] = []
    opponent_player_ids = set(_get_opponent_player_ids_in_turn_order(state, player_id=player_id))
    for candidate_player_id in _get_turn_order_from_player(state, player_id=player_id):
        if candidate_player_id not in opponent_player_ids:
            continue
        candidate_player = state.players[candidate_player_id]
        target_enlighteners = [card for card in candidate_player.tableau if card.category == "Aufklärer"]
        if target_enlighteners or _has_relic_immunity_against_next_enlightener(
            state,
            protected_player_id=candidate_player_id,
        ):
            target_player_ids.append(candidate_player_id)
    return target_player_ids


def _resolve_next_role_action(
    state: GameState,
    *,
    player_id: str,
    legal_role_types: list[str],
    already_used_role_types: list[str],
) -> str | None:
    for role_type in ACTION_ROLE_TYPES:
        if role_type not in legal_role_types:
            continue
        if role_type == "Missionare" and role_type in already_used_role_types:
            continue

        if role_type == "Missionare" and _resolve_missionary_role_action(
            state,
            player_id=player_id,
        ):
            return role_type
        if role_type == "Nonnen":
            if _resolve_nun_role_action(state, player_id=player_id):
                return role_type
            # If nuns are a legal option but cannot resolve (for example due to
            # dynamic full-slot state after a prior action), stop auto-fallback.
            return None

    if "Missionare" not in already_used_role_types and _resolve_missionary_role_action(
        state,
        player_id=player_id,
    ):
        return "Missionare"

    if "Monumente" in legal_role_types and _resolve_forge_role_action(state, player_id=player_id):
        return "Monumente"

    return None


def _resolve_specific_role_action(
    state: GameState,
    *,
    player_id: str,
    role_type: str,
    legal_role_types: list[str],
    already_used_role_types: list[str],
    role_action_intent: dict[str, Any] | None = None,
) -> str | None:
    if role_type not in legal_role_types and role_type not in {"Mönche", "Missionare"}:
        return None

    if role_type == "Mönche" and _resolve_monk_role_action(state, player_id=player_id):
        return role_type
    if role_type == "Missionare":
        if role_type not in legal_role_types:
            return None
        if _resolve_missionary_role_action(
            state,
            player_id=player_id,
            role_action_intent=role_action_intent if role_action_intent is not None else {},
        ):
            return role_type
        raise ValueError(f"Player {player_id} cannot ordain Missionare right now.")
    if role_type == "Monumente" and _resolve_forge_role_action(
        state,
        player_id=player_id,
        role_action_intent=role_action_intent,
    ):
        return role_type
    if role_type == "Nonnen" and _resolve_nun_role_action(state, player_id=player_id):
        return role_type

    return None


def _resolve_missionary_role_action(
    state: GameState,
    *,
    player_id: str,
    role_action_intent: dict[str, Any] | None = None,
) -> bool:
    player = state.players[player_id]
    _sync_role_slot_assignments(state, player_id=player_id)
    if not is_role_active(state, player_id=player_id, role_type="Missionare"):
        return False
    missionary_status = _get_missionary_role_status(state, player_id=player_id)
    assigned_missionaries = int(missionary_status["assigned_missionaries"])
    missionaries_slot_limit = int(missionary_status["missionaries_slot_limit"])
    ordain_count = int(missionary_status["ordain_count"])
    if ordain_count > 0:
        player.meeples -= ordain_count
        next_assigned_missionaries = assigned_missionaries + ordain_count
        player.assigned_role_meeples["Missionare"] = next_assigned_missionaries
        if missionaries_slot_limit > 0 and assigned_missionaries < missionaries_slot_limit <= next_assigned_missionaries:
            player.missionaries_ready_from_round = state.round_number + 1
        elif next_assigned_missionaries < missionaries_slot_limit:
            player.missionaries_ready_from_round = None
        append_event(
            state.event_log,
            "role_action_resolved",
            player_id=player_id,
            role_type="Missionare",
            action="ordain_missionary",
            meeples_transferred=ordain_count,
            ordained_count=ordain_count,
            assigned_role_meeples_after=next_assigned_missionaries,
            slot_limit=missionaries_slot_limit,
            missionaries_ready_from_round=player.missionaries_ready_from_round,
            player_meeples_after=player.meeples,
        )
        return True

    return False


def _resolve_monk_role_action(
    state: GameState,
    *,
    player_id: str,
) -> bool:
    player = state.players[player_id]
    _sync_role_slot_assignments(state, player_id=player_id)
    if not is_role_active(state, player_id=player_id, role_type="Mönche"):
        return False
    if _player_has_active_enlightener_rule_text(
        state,
        player_id=player_id,
        text=ENLIGHTENER_CANNOT_REFILL_TEMPLES_TEXT,
    ):
        return False
    assigned_monks = max(0, int(player.assigned_role_meeples.get("Mönche", 0)))
    monks_slot_limit = max(0, int(player.monks_slots))
    if assigned_monks >= monks_slot_limit:
        return False
    if player.meeples <= 0:
        return False

    player.meeples -= 1
    next_assigned_monks = assigned_monks + 1
    player.assigned_role_meeples["Mönche"] = next_assigned_monks
    append_event(
        state.event_log,
        "role_action_resolved",
        player_id=player_id,
        role_type="Mönche",
        action="ordain_monk",
        meeples_transferred=1,
        assigned_role_meeples_after=next_assigned_monks,
        slot_limit=monks_slot_limit,
        player_meeples_after=player.meeples,
    )
    return True


def _shuffle_returned_monument_cards(
    state: GameState,
    *,
    player_id: str,
    returned_cards: list[CardRef],
    selected_card_ids: list[str],
    action: str,
) -> None:
    original_order = list(returned_cards) + list(state.monument_draw_pile)
    shuffle_seed = (
        f"monument-return-shuffle|seed={state.seed}|player={player_id}|round={state.round_number}|"
        f"turn={state.turn_number}|action={action}|drawn={','.join(card.card_id for card in returned_cards)}|"
        f"selected={','.join(selected_card_ids)}|pile={','.join(card.card_id for card in original_order)}"
    )
    state.monument_draw_pile = SeededRNG(seed=shuffle_seed).shuffle(original_order)


def _validate_second_forge_monument_card(*, first_card: CardRef, second_card: CardRef) -> None:
    first_group_key = _monument_group_key_from_card_id(first_card.card_id)
    second_group_key = _monument_group_key_from_card_id(second_card.card_id)
    if first_group_key != second_group_key:
        raise ValueError(
            "Zacharias can only build two same-line monument cards."
        )


def _count_available_truth_value(state: GameState, *, player_id: str, value: int) -> int:
    player = state.players[player_id]
    return (
        sum(1 for truth_value in player.truth_pool if int(truth_value) == value)
        + sum(1 for truth_value in player.used_truth if int(truth_value) == value)
        + sum(
            1
            for card in player.truth_discard
            if card.category == "Wahrheit" and int(card.truth_value or -1) == value
        )
        + sum(
            1
            for card in player.hand_cards
            if card.category == "Wahrheit" and int(card.truth_value or -1) == value
        )
    )


def _find_zacharias_second_forge_card(
    state: GameState,
    *,
    player_id: str,
    selected_card: CardRef,
    drawn_options: list[CardRef],
    selected_index: int,
    legal_option_ids: set[str],
    explicit_second_card_id: str | None,
) -> CardRef | None:
    forge_free_slots = max(
        0,
        _get_slot_limit(state.players[player_id], slot_kind="forge")
        - _get_slot_occupancy(state.players[player_id], slot_kind="forge"),
    )
    if forge_free_slots < 2:
        if explicit_second_card_id is not None:
            raise ValueError(f"Player {player_id} has only one free Monumente slot.")
        return None

    if not _player_has_zacharias_double_monument_relic(state, player_id=player_id):
        if explicit_second_card_id is not None:
            raise ValueError(
                f"Player {player_id} cannot build a second monument card in one action without the Zacharias relic effect."
            )
        return None

    if explicit_second_card_id is not None:
        matching_index = next(
            (idx for idx, card in enumerate(drawn_options) if card.card_id == explicit_second_card_id),
            None,
        )
        if matching_index is None:
            raise ValueError(
                f"Second monument card {explicit_second_card_id} is not in drawn monument options "
                f"{[card.card_id for card in drawn_options]}."
            )
        candidate_indexes = [matching_index]
    else:
        candidate_indexes = [
            idx
            for idx, card in enumerate(drawn_options)
            if idx != selected_index and card.card_id in legal_option_ids
        ]

    for candidate_index in candidate_indexes:
        if candidate_index == selected_index:
            continue
        candidate_card = drawn_options[candidate_index]
        try:
            _validate_second_forge_monument_card(first_card=selected_card, second_card=candidate_card)
        except ValueError:
            if explicit_second_card_id is not None:
                raise
            continue
        selected_group_key = _monument_group_key_from_card_id(selected_card.card_id)
        line_progress_before = _get_player_monument_line_card_count(
            state,
            player_id=player_id,
            group_key=selected_group_key,
        )
        required_truth_twos = sum(1 for progress_after in (line_progress_before + 1, line_progress_before + 2) if progress_after in {1, 2})
        if required_truth_twos > _count_available_truth_value(state, player_id=player_id, value=2):
            if explicit_second_card_id is not None:
                raise ValueError(f"Player {player_id} has not enough available Truth 2 sources for two monument builds.")
            continue
        if candidate_card.card_id not in legal_option_ids:
            raise ValueError(
                _get_monument_build_reason(state, player_id=player_id, card_id=candidate_card.card_id) or ""
            )
        return candidate_card
    return None


def _resolve_forge_role_action(
    state: GameState,
    *,
    player_id: str,
    role_action_intent: dict[str, Any] | None = None,
) -> bool:
    player = state.players[player_id]
    if _player_has_active_enlightener_rule_text(
        state,
        player_id=player_id,
        text=ENLIGHTENER_BLOCKS_MONUMENTS_TEXT,
    ):
        return False
    if not _has_free_slot(player, slot_kind="forge"):
        return False
    if not state.monument_draw_pile:
        return False

    forge_choices = get_forge_monument_choices(state, player_id=player_id)
    enabled_choice_by_card_id = {
        str(choice["card_id"]): {
            **choice,
            "bot_priority": _forge_monument_bot_priority(state, player_id=player_id, choice=choice),
        }
        for choice in forge_choices
        if bool(choice["enabled"])
    }
    legal_option_ids = set(enabled_choice_by_card_id)
    options_to_draw = min(get_forge_monument_reveal_count(state, player_id=player_id), len(state.monument_draw_pile))
    drawn_options = [state.monument_draw_pile.pop(0) for _ in range(options_to_draw)]
    selected_index = _select_default_forge_monument_card(
        drawn_options=drawn_options,
        choice_by_card_id=enabled_choice_by_card_id,
    )
    selected_truth_source: str | None = None
    selected_second_card_id: str | None = None
    declined = False
    if role_action_intent is not None:
        declined = bool(role_action_intent.get("decline", False))
        selected_card_id = role_action_intent.get("monument_card_id")
        selected_truth_source = role_action_intent.get("truth_source")
        selected_second_card_id = role_action_intent.get("second_monument_card_id")
        if selected_second_card_id is None:
            selected_second_card_id = role_action_intent.get("second_card_id")
        if selected_card_id is not None:
            if not isinstance(selected_card_id, str):
                raise ValueError("Monument action intent monument_card_id must be a string.")
            if not selected_card_id.strip():
                selected_card_id = None
        if selected_second_card_id is not None:
            if not isinstance(selected_second_card_id, str):
                raise ValueError("Monument action intent second_monument_card_id must be a string.")
            if not selected_second_card_id.strip():
                selected_second_card_id = None
        if selected_truth_source is not None:
            if not isinstance(selected_truth_source, str):
                raise ValueError("Monument action intent truth_source must be a string.")
            if not selected_truth_source.strip():
                selected_truth_source = None
        if selected_card_id is not None:
            matching_index = next(
                (idx for idx, card in enumerate(drawn_options) if card.card_id == selected_card_id),
                None,
            )
            if matching_index is None:
                if state.require_explicit_action_intents:
                    raise ValueError(
                        f"Monument card {selected_card_id} is not in drawn monument options "
                        f"{[card.card_id for card in drawn_options]}."
                    )
                append_event(
                    state.event_log,
                    "forge_monument_intent_fallback",
                    player_id=player_id,
                    requested_monument_card_id=selected_card_id,
                    drawn_monument_card_ids=[card.card_id for card in drawn_options],
                    reason="requested_card_not_revealed_after_shuffle",
                    fallback_policy="first_legal_revealed_option_or_dead_draw",
                )
                selected_card_id = None
                selected_second_card_id = None
                selected_truth_source = None
            elif selected_card_id not in legal_option_ids:
                raise ValueError(_get_monument_build_reason(state, player_id=player_id, card_id=selected_card_id) or "")
            else:
                selected_index = matching_index

    if declined:
        selected_index = None
        selected_truth_source = None
        selected_second_card_id = None

    if selected_index is None:
        resolution_action = "forge_monument_declined" if declined else "forge_monument_dead_draw"
        _shuffle_returned_monument_cards(
            state,
            player_id=player_id,
            returned_cards=drawn_options,
            selected_card_ids=[],
            action=resolution_action,
        )
        append_event(
            state.event_log,
            "role_action_resolved",
            player_id=player_id,
            role_type="Monumente",
            action=resolution_action,
            display_role="Monumente",
            display_action=(
                "Kein Monument gezogen"
                if declined
                else "Monumente geprüft, keine baubare Karte"
            ),
            source_zone="monument_middle_tableau",
            card_category="Monument",
            monument_draw_count=len(drawn_options),
            monument_draw_options=[card.card_id for card in drawn_options],
            selected_monument_card_ids=[],
            monument_card_id=None,
            monument_part=None,
            monument_group_key=None,
            started_by_player_id=None,
            building_other_player_monument=False,
            monument_draw_pile_size=len(state.monument_draw_pile),
            dead_draw=not declined,
            declined=declined,
        )
        return True

    selected_card = drawn_options[selected_index]
    second_card = _find_zacharias_second_forge_card(
        state,
        player_id=player_id,
        selected_card=selected_card,
        drawn_options=drawn_options,
        selected_index=selected_index,
        legal_option_ids=legal_option_ids,
        explicit_second_card_id=selected_second_card_id,
    )
    selected_cards = [selected_card] + ([second_card] if second_card is not None else [])
    selected_card_ids = [card.card_id for card in selected_cards]
    selected_card_id_set = set(selected_card_ids)
    unselected_cards = [card for card in drawn_options if card.card_id not in selected_card_id_set]
    _shuffle_returned_monument_cards(
        state,
        player_id=player_id,
        returned_cards=unselected_cards,
        selected_card_ids=selected_card_ids,
        action="forge_monument",
    )
    monument_part = _infer_monument_part_from_card_id(selected_card.card_id)
    if monument_part not in {1, 2, 3}:
        raise ValueError(f"Monument card {selected_card.card_id} does not encode part 1-3.")

    build_monument_part(
        state,
        player_id=player_id,
        part=monument_part,
        card_id=selected_card.card_id,
        card_name=selected_card.name,
        truth_source=selected_truth_source,
        second_card_id=second_card.card_id if second_card is not None else None,
        second_card_name=second_card.name if second_card is not None else None,
    )
    append_event(
        state.event_log,
        "role_action_resolved",
        player_id=player_id,
        role_type="Monumente",
        action="forge_monument",
        display_role="Monumente",
        display_action="Monument bauen (aus Mitteltableau)",
        source_zone="monument_middle_tableau",
        card_category="Monument",
        monument_draw_count=len(drawn_options),
        monument_draw_options=[card.card_id for card in drawn_options],
        selected_monument_card_ids=selected_card_ids,
        monument_card_id=selected_card.card_id,
        monument_part=monument_part,
        monument_group_key=_monument_group_key_from_card_id(selected_card.card_id),
        started_by_player_id=_find_existing_monument_line_starter_player_id(
            state,
            group_key=_monument_group_key_from_card_id(selected_card.card_id),
        ),
        building_other_player_monument=(
            _find_existing_monument_line_starter_player_id(
                state,
                group_key=_monument_group_key_from_card_id(selected_card.card_id),
            )
            != player_id
        ),
        monument_draw_pile_size=len(state.monument_draw_pile),
    )
    return True


def resolve_reserved_forge_monument_action(
    state: GameState,
    *,
    player_id: str,
    monument_card_id: str | None = None,
    truth_source: str | None = None,
    decline: bool = False,
) -> GameState:
    """Resolve a Monumente action whose action slot was already consumed by its picker."""
    role_action_intent: dict[str, Any] = {"decline": bool(decline)}
    if monument_card_id is not None:
        role_action_intent["monument_card_id"] = monument_card_id
    if truth_source is not None:
        role_action_intent["truth_source"] = truth_source
    if not _resolve_forge_role_action(
        state,
        player_id=player_id,
        role_action_intent=role_action_intent,
    ):
        raise ValueError(f"Player {player_id} could not resolve reserved Monumente action.")
    return state


def _resolve_turn_start_missionary_steal(
    state: GameState,
    *,
    player_id: str,
    effect_intent: dict[str, Any] | None,
) -> None:
    bonus_missionary_steal = max(0, int(get_turn_start_missionary_steal(state, player_id=player_id)))
    missionary_steal = get_tableau_missionary_resolution_count(state, player_id=player_id)
    if missionary_steal <= 0 and bonus_missionary_steal <= 0:
        return

    if missionary_steal <= 0:
        player = state.players[player_id]
        readiness_reason = "missing_active_missionary_pair"
        if _has_filled_missionary_pair(player):
            readiness_reason = "missionary_pair_not_ready"
        append_event(
            state.event_log,
            "turn_start_missionary_steal_unavailable",
            player_id=player_id,
            amount=bonus_missionary_steal,
            reason=readiness_reason,
            missionaries_ready_from_round=player.missionaries_ready_from_round,
            round_number=state.round_number,
        )
        return

    payload = effect_intent or {}
    raw_target_player_ids = payload.get("target_player_ids")
    explicit_target_player_ids: list[str] = []
    if raw_target_player_ids is not None:
        if not isinstance(raw_target_player_ids, list) or any(
            not isinstance(target_player_id, str) for target_player_id in raw_target_player_ids
        ):
            raise ValueError("turn_start_missionary_steal intent target_player_ids must be a list of player-id strings.")
        if len(raw_target_player_ids) > missionary_steal:
            raise ValueError(
                f"turn_start_missionary_steal received {len(raw_target_player_ids)} explicit targets for amount {missionary_steal}."
            )
        explicit_target_player_ids = list(raw_target_player_ids)

    player = state.players[player_id]
    transferred_total = 0
    for trigger_index in range(missionary_steal):
        explicit_target_player_id = (
            explicit_target_player_ids[trigger_index]
            if trigger_index < len(explicit_target_player_ids)
            else None
        )
        target_player_id, selection_reason = _get_next_missionary_target_player_id(
            state,
            player_id=player_id,
            target_player_id=explicit_target_player_id,
        )
        if target_player_id is None:
            append_event(
                state.event_log,
                "turn_start_missionary_steal_unresolved",
                player_id=player_id,
                trigger_index=trigger_index + 1,
                amount=missionary_steal,
                reason="no_valid_target",
            )
            continue

        target_player = state.players[target_player_id]
        target_player.meeples -= 1
        player.meeples += 1
        transferred_total += 1
        state.last_meeple_taker_by_victim[target_player_id] = player_id
        append_event(
            state.event_log,
            "turn_start_missionary_steal_resolved",
            player_id=player_id,
            trigger_index=trigger_index + 1,
            amount=missionary_steal,
            target_player_id=target_player_id,
            selection_reason=selection_reason,
            meeples_transferred=1,
            player_meeples_after=player.meeples,
            target_meeples_after=target_player.meeples,
        )

    append_event(
        state.event_log,
        "turn_start_missionary_steal_completed",
        player_id=player_id,
        amount=missionary_steal,
        explicit_targets_provided=len(explicit_target_player_ids),
        total_transferred=transferred_total,
    )


def _has_filled_missionary_pair(player: PlayerState) -> bool:
    missionaries_slots = int(player.missionaries_slots)
    if missionaries_slots <= 0:
        return False
    return max(0, int(player.assigned_role_meeples.get("Missionare", 0))) >= missionaries_slots


def _has_active_missionary_pair(state: GameState, *, player_id: str) -> bool:
    player = state.players[player_id]
    if not _has_filled_missionary_pair(player):
        player.missionaries_ready_from_round = None
        return False
    ready_from_round = player.missionaries_ready_from_round
    if not isinstance(ready_from_round, int):
        return True
    return state.round_number >= ready_from_round


def _get_nun_preparation_count_for_action(player: PlayerState) -> int:
    nunnery_capacity = _get_slot_limit(player, slot_kind="prepared_nuns")
    prepared_nuns = max(0, int(player.nunnery_state.prepared_nuns))
    free_preparation_slots = max(0, nunnery_capacity - prepared_nuns)
    if free_preparation_slots <= 0:
        return 0

    max_preparations = free_preparation_slots
    if player.alignment != "<Unergründlich>":
        max_preparations = min(max_preparations, 1)

    assigned_nuns = max(0, int(player.assigned_role_meeples.get("Nonnen", 0)))
    reusable_assigned_nuns = max(0, assigned_nuns - prepared_nuns)
    available_nun_sources = reusable_assigned_nuns + max(0, int(player.meeples))
    return min(max_preparations, available_nun_sources)


def _resolve_nun_role_action(state: GameState, *, player_id: str) -> bool:
    player = state.players[player_id]
    _sync_role_slot_assignments(state, player_id=player_id)
    nunnery_state = player.nunnery_state
    if not nunnery_state.active:
        append_event(
            state.event_log,
            "nun_action_unavailable_before_gods_twilight",
            player_id=player_id,
            round_number=state.round_number,
        )
        return False

    nunnery_capacity = _get_slot_limit(player, slot_kind="prepared_nuns")
    if nunnery_capacity <= 0 or not _has_free_slot(player, slot_kind="prepared_nuns"):
        _append_slot_full_event(
            state,
            player_id=player_id,
            slot_kind="prepared_nuns",
            event_type="nun_preparation_expired_full_slot",
            prepared_nuns=nunnery_state.prepared_nuns,
            nunnery_capacity=nunnery_capacity,
        )
        return False

    assigned_nuns = max(0, int(player.assigned_role_meeples.get("Nonnen", 0)))
    prepared_nuns_before = max(0, int(nunnery_state.prepared_nuns))
    prepare_count = _get_nun_preparation_count_for_action(player)
    if prepare_count <= 0:
        append_event(
            state.event_log,
            "nun_action_unavailable_no_free_meeples",
            player_id=player_id,
            round_number=state.round_number,
            prepared_nuns=nunnery_state.prepared_nuns,
            assigned_nuns=assigned_nuns,
        )
        return False

    assigned_nuns_needed = max(0, prepared_nuns_before + prepare_count - assigned_nuns)
    if assigned_nuns_needed > 0:
        player.meeples -= assigned_nuns_needed
        player.assigned_role_meeples["Nonnen"] = assigned_nuns + assigned_nuns_needed

    nunnery_state.prepared_nuns = prepared_nuns_before + prepare_count

    append_event(
        state.event_log,
        "role_action_resolved",
        player_id=player_id,
        role_type="Nonnen",
        action="prepare_nun",
        prepared_nuns_added=prepare_count,
        prepared_nuns=nunnery_state.prepared_nuns,
        assigned_nuns_added=assigned_nuns_needed,
        assigned_nuns=player.assigned_role_meeples.get("Nonnen", 0),
        sacrificed_nuns=nunnery_state.sacrificed_nuns,
        nunnery_capacity=nunnery_capacity,
    )
    return True


def _add_truth_cards_to_hand(
    state: GameState,
    *,
    player_id: str,
    truth_values: list[int],
    source: str,
) -> list[CardRef]:
    player = state.players[player_id]
    if source == "manual-draw" and _is_player_in_active_draw_step(state, player_id=player_id):
        prior_manual_truth_draws = _count_manual_truth_draws_in_active_draw_window(state, player_id=player_id)
        if prior_manual_truth_draws + len(truth_values) > 2:
            raise ValueError(f"Player {player_id} cannot draw more than 2 truth cards in one draw step.")

    prepared_cards: list[CardRef] = []

    for index, truth_value in enumerate(truth_values):
        remaining_truth_counter = _available_truth_draw_counter_for_hand_preparation(
            state,
            player_id=player_id,
        )
        if not remaining_truth_counter:
            _maybe_reset_truth_for_hand_preparation(state, player_id=player_id)
            remaining_truth_counter = _available_truth_draw_counter_for_hand_preparation(
                state,
                player_id=player_id,
            )
        if remaining_truth_counter[truth_value] <= 0:
            raise ValueError(
                f"Player {player_id} cannot prepare truth value {truth_value}; not enough copies available."
            )
        prepared_card = make_truth_card(
            truth_value,
            card_id=f"{source}-truth-{player_id}-{state.turn_number}-{len(player.hand_cards) + index}-{truth_value}",
            metadata={"prepared_truth": True, "source": source},
        )
        player.hand_cards.append(prepared_card)
        prepared_cards.append(prepared_card)

    if prepared_cards:
        _maybe_reset_truth_for_hand_preparation(state, player_id=player_id)
    return prepared_cards


def _maybe_reset_truth_for_hand_preparation(state: GameState, *, player_id: str) -> bool:
    player = state.players[player_id]
    if _available_truth_draw_counter_for_hand_preparation(state, player_id=player_id):
        return False
    if not player.truth_discard and not player.used_truth:
        return False
    reset_truth(state, player_id=player_id)
    return True


def _count_manual_truth_draws_in_active_draw_window(state: GameState, *, player_id: str) -> int:
    draw_window_boundary_events = {
        "draw_step_started",
        "draw_step_resolved",
        "player_turn_started",
        "player_turn_completed",
        "round_started",
        "round_completed",
        "take_actions_started",
        "take_actions_completed",
    }
    manual_truth_draws = 0

    for event in reversed(state.event_log):
        event_type = event.get("type")
        if event_type in draw_window_boundary_events:
            break
        if event_type != "draw_choice_resolved":
            continue
        if event.get("player_id") != player_id or event.get("mode") != "truth":
            continue
        truth_values = event.get("truth_values")
        if isinstance(truth_values, list) and truth_values:
            manual_truth_draws += len(truth_values)
        else:
            manual_truth_draws += 1

    return manual_truth_draws


def _is_player_in_active_draw_step(state: GameState, *, player_id: str) -> bool:
    for event in reversed(state.event_log):
        if not isinstance(event, dict):
            continue
        if event.get("player_id") != player_id:
            continue
        event_type = str(event.get("type") or "")
        if event_type == "draw_step_resolved":
            return False
        if event_type == "draw_step_started":
            return True
        if event_type in {"player_turn_started", "player_turn_ended", "turn_advanced"}:
            return False
    return False


def _discard_forced_hand_card(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
) -> str:
    if card.category == "Wahrheit":
        truth_value = card.truth_value if card.truth_value is not None else _extract_first_integer(card.name) or _extract_first_integer(card.card_id) or 0
        player = state.players[player_id]
        if truth_value in player.truth_pool:
            _discard_truth_value_to_discard(
                state,
                player_id=player_id,
                value=truth_value,
                discard_card=card,
            )
        else:
            _append_truth_discard_card(
                state,
                player_id=player_id,
                card=card,
                counts_as_used_truth=False,
            )
            append_event(
                state.event_log,
                "truth_discarded",
                player_id=player_id,
                value=truth_value,
                card_id=card.card_id,
            )
        return "truth_discard"

    state.heavenly_discard_pile.append(card)
    append_event(
        state.event_log,
        "hand_card_discarded",
        player_id=player_id,
        card_id=card.card_id,
        card_name=card.name,
        category=card.category,
        discard_zone="heavenly_discard_pile",
        heavenly_discard_pile_size=len(state.heavenly_discard_pile),
    )
    return "heavenly_discard_pile"


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


def _clear_truth_discard_for_player(state: GameState, *, player_id: str) -> list[str]:
    player = state.players[player_id]
    discarded_card_ids = [discarded_card.card_id for discarded_card in player.truth_discard]
    if discarded_card_ids:
        discarded_card_id_set = set(discarded_card_ids)
        state.truth_discard = [
            discarded_card
            for discarded_card in state.truth_discard
            if discarded_card.card_id not in discarded_card_id_set
        ]
    player.truth_discard.clear()
    return discarded_card_ids


def _get_mantra_target_player_ids(state: GameState, *, player_id: str) -> list[str]:
    ordered_opponent_ids: list[str] = []
    opponent_player_ids = set(_get_opponent_player_ids_in_turn_order(state, player_id=player_id))
    for candidate_player_id in _get_turn_order_from_player(state, player_id=player_id):
        if candidate_player_id not in opponent_player_ids:
            continue
        if _get_mantra_available_truth_values(state, target_player_id=candidate_player_id):
            ordered_opponent_ids.append(candidate_player_id)
    return ordered_opponent_ids


def _get_mantra_available_truth_values(state: GameState, *, target_player_id: str) -> list[int]:
    player = state.players[target_player_id]
    if player.truth_pool:
        return sorted(player.truth_pool)
    if not player.used_truth:
        return []
    return sorted(_truth_pool_values_after_preparation_reset(state, player_id=target_player_id))


def _get_turn_order_from_player(state: GameState, *, player_id: str) -> list[str]:
    start_index = state.player_order.index(player_id)
    player_count = len(state.player_order)
    return [
        state.player_order[(start_index + offset) % player_count]
        for offset in range(player_count)
    ]


def _get_relative_player_id(state: GameState, *, player_id: str, offset: int) -> str:
    current_index = state.player_order.index(player_id)
    player_count = len(state.player_order)
    return state.player_order[(current_index + offset) % player_count]


def _choose_abdul_return_role_type(
    state: GameState,
    *,
    player_id: str,
    occupied_role_types: list[str],
) -> str:
    if (
        "Missionare" in occupied_role_types
        and _get_assigned_role_meeples(state, player_id=player_id, role_type="Missionare") == 1
        and not _has_active_missionary_pair(state, player_id=player_id)
    ):
        return "Missionare"

    for preferred_role_type in ("Mönche", "Nonnen"):
        if preferred_role_type in occupied_role_types:
            return preferred_role_type

    if "Missionare" in occupied_role_types:
        return "Missionare"

    return occupied_role_types[0]


def _validate_role_action_intents(
    state: GameState,
    *,
    player_id: str,
    legal_role_types: list[str],
    role_action_intents: dict[str, dict[str, Any]] | None,
) -> None:
    if not role_action_intents:
        return

    supported_role_types = {"Missionare", "Nonnen"}
    for role_type, role_action_intent in role_action_intents.items():
        if role_type not in supported_role_types:
            raise ValueError(f"Unsupported role action intent for role type {role_type}.")
        if role_type not in legal_role_types:
            raise ValueError(f"Player {player_id} cannot use {role_type} as an action right now.")
        if role_type == "Missionare" and not isinstance(role_action_intent, dict):
            raise ValueError("Missionary role action intent payload must be a dict.")


def _merge_legacy_role_action_intents(
    state: GameState,
    *,
    player_id: str,
    action_intents: list[dict[str, Any] | str] | None,
    role_action_intents: dict[str, dict[str, Any]] | None,
) -> list[dict[str, Any] | str] | None:
    if not role_action_intents:
        return action_intents

    if action_intents:
        append_event(
            state.event_log,
            "legacy_role_action_intents_ignored_due_to_explicit_action_intents",
            player_id=player_id,
            legacy_role_types=sorted(role_action_intents.keys()),
        )
        return action_intents

    merged_action_intents: list[dict[str, Any]] = []
    for role_type in ACTION_ROLE_TYPES:
        legacy_payload = role_action_intents.get(role_type)
        if legacy_payload is None:
            continue
        merged_action_intents.append(
            {
                "action": "role",
                "role_type": role_type,
                "role_action_intent": dict(legacy_payload),
            }
        )

    if merged_action_intents:
        append_event(
            state.event_log,
            "legacy_role_action_intents_migrated_to_action_intents",
            player_id=player_id,
            migrated_role_types=[str(intent["role_type"]) for intent in merged_action_intents],
        )
    return merged_action_intents


def _normalize_action_intents(
    state: GameState,
    *,
    player_id: str,
    legal_role_types: list[str],
    legal_action_card_ids: list[str],
    action_intents: list[dict[str, Any] | str] | None,
) -> list[dict[str, Any]]:
    if not action_intents:
        return []

    normalized_action_intents: list[dict[str, Any]] = []
    projected_grenade_level = max(0, int(state.players[player_id].hand_grenade_state.meeples_committed))
    projected_grenade_used = bool(state.players[player_id].hand_grenade_state.used)
    for raw_action_intent in action_intents:
        if isinstance(raw_action_intent, str):
            action = raw_action_intent
            payload: dict[str, Any] = {}
        elif isinstance(raw_action_intent, dict):
            action = raw_action_intent.get("action")
            payload = raw_action_intent
        else:
            raise ValueError(f"Action intent for player {player_id} must be a dict or string.")

        if action == "use_monument_bonus":
            normalized_action_intents.append({"action": "use_monument_bonus"})
            continue

        if action == "skip":
            # Skip is only allowed as a fallback if NO other actions are provided
            # We defer adding it until the end if needed
            continue

        if action == "play_hand_card":
            card_id = payload.get("card_id")
            if not isinstance(card_id, str):
                raise ValueError(f"Hand-card action intent for player {player_id} requires card_id.")
            if card_id not in set(legal_action_card_ids):
                raise ValueError(
                    f"Player {player_id} cannot play hand card {card_id} as an action right now."
                )

            effect_payload = payload.get("effect_payload")
            if effect_payload is not None and not isinstance(effect_payload, dict):
                raise ValueError(f"Hand-card effect payload for player {player_id} must be a dict.")

            normalized_action_intents.append(
                {
                    "action": "play_hand_card",
                    "card_id": card_id,
                    "effect_payload": effect_payload,
                }
            )
            continue

        if action == "unleash_stored_power":
            phenomenon_card_id = payload.get("phenomenon_card_id")
            if not isinstance(phenomenon_card_id, str):
                raise ValueError(f"Stored-power action intent for player {player_id} requires phenomenon_card_id.")
            if phenomenon_card_id not in state.players[player_id].stored_phenomena:
                raise ValueError(
                    f"Player {player_id} cannot unleash unknown stored phenomenon {phenomenon_card_id}."
                )
            payment_choice = payload.get("payment_choice")
            if payment_choice is not None and not isinstance(payment_choice, dict):
                raise ValueError(f"Stored-power payment choice for player {player_id} must be a dict.")
            effect_payload = payload.get("effect_payload")
            if effect_payload is not None and not isinstance(effect_payload, dict):
                raise ValueError(f"Stored-power effect payload for player {player_id} must be a dict.")
            normalized_action_intents.append(
                {
                    "action": "unleash_stored_power",
                    "phenomenon_card_id": phenomenon_card_id,
                    "payment_choice": payment_choice,
                    "effect_payload": effect_payload,
                }
            )
            continue

        if action == "prophet_send":
            target_player_id = payload.get("target_player_id")
            if not isinstance(target_player_id, str):
                raise ValueError(f"Prophet action intent for player {player_id} requires target_player_id.")
            if target_player_id not in get_legal_prophet_target_player_ids(state, player_id=player_id):
                raise ValueError(
                    f"Player {player_id} cannot pass the prophet to {target_player_id} right now."
                )
            squirrel_draw_counts = payload.get("squirrel_draw_counts")
            if squirrel_draw_counts is not None:
                if not isinstance(squirrel_draw_counts, dict):
                    raise ValueError(
                        f"Prophet action intent for player {player_id} must use dict squirrel_draw_counts."
                    )
                normalized_squirrel_draw_counts: dict[str, int] = {}
                for raw_bonus_player_id, raw_draw_count in squirrel_draw_counts.items():
                    if not isinstance(raw_bonus_player_id, str) or not raw_bonus_player_id.strip():
                        raise ValueError(
                            f"Prophet action intent for player {player_id} uses invalid squirrel draw player id."
                        )
                    if isinstance(raw_draw_count, bool) or not isinstance(raw_draw_count, int):
                        raise ValueError(
                            f"Prophet action intent for player {player_id} must use integer squirrel draw counts."
                        )
                    normalized_squirrel_draw_counts[raw_bonus_player_id] = max(0, min(2, int(raw_draw_count)))
                squirrel_draw_counts = normalized_squirrel_draw_counts
            normalized_action_intents.append(
                {
                    "action": "prophet_send",
                    "target_player_id": target_player_id,
                    **({"squirrel_draw_counts": squirrel_draw_counts} if squirrel_draw_counts is not None else {}),
                }
            )
            continue

        if action == "play_stored_phenomenon_action":
            raw_phenomenon_id = payload.get("phenomenon_id", payload.get("phenomenon_card_id"))
            phenomenon_id: str | None
            if raw_phenomenon_id is None:
                phenomenon_id = None
            elif isinstance(raw_phenomenon_id, str):
                phenomenon_id = raw_phenomenon_id
            else:
                raise ValueError(f"Stored-phenomenon action intent for player {player_id} must provide a string phenomenon_id.")

            if phenomenon_id is not None and phenomenon_id not in state.players[player_id].stored_phenomena:
                raise ValueError(
                    f"Player {player_id} cannot play unknown stored phenomenon {phenomenon_id}."
                )

            action_name = payload.get("action_name", "stored_phenomenon_action")
            if not isinstance(action_name, str) or not action_name.strip():
                raise ValueError(f"Stored-phenomenon action name for player {player_id} must be a non-empty string.")

            normalized_action_intents.append(
                {
                    "action": "play_stored_phenomenon_action",
                    "phenomenon_id": phenomenon_id,
                    "action_name": action_name,
                }
            )
            continue

        if action == "grenade":
            grenade_state = state.players[player_id].hand_grenade_state
            if grenade_state.grenade is None:
                raise ValueError(f"Player {player_id} has not drafted a hand grenade yet.")
            if projected_grenade_used:
                raise ValueError(f"Player {player_id} has already used their hand grenade.")

            detonate = payload.get("detonate", False)
            if not isinstance(detonate, bool):
                raise ValueError(f"Grenade action intent for player {player_id} detonate flag must be boolean.")

            level = payload.get("level")
            if level is None:
                level = projected_grenade_level + 1
            if not isinstance(level, int):
                raise ValueError(f"Grenade action intent for player {player_id} requires integer level.")
            if level < 1 or level > 3:
                raise ValueError(f"Player {player_id} grenade level must be between 1 and 3.")
            if level != projected_grenade_level + 1:
                raise ValueError(
                    f"Player {player_id} grenade action must advance exactly one level from "
                    f"{projected_grenade_level} to {projected_grenade_level + 1}."
                )
            effect_payload = payload.get("effect_payload")
            if effect_payload is not None and not isinstance(effect_payload, dict):
                raise ValueError(f"Grenade action intent for player {player_id} effect_payload must be a dict.")

            normalized_action_intents.append(
                {
                    "action": "grenade",
                    "level": level,
                    "detonate": detonate,
                    "effect_payload": effect_payload,
                }
            )
            projected_grenade_level = level
            if level >= 3 or detonate:
                projected_grenade_used = True
            continue

        if action != "role":
            raise ValueError(f"Unsupported action intent {action!r} for player {player_id}.")

        role_type = payload.get("role_type")
        if not isinstance(role_type, str):
            raise ValueError(f"Role action intent for player {player_id} requires role_type.")
        # Explicit temple intents must match a currently legal temple move, not just a valid role label.
        if role_type not in legal_role_types:
            raise ValueError(f"Player {player_id} cannot use {role_type} as an action right now.")

        role_action_intent = _extract_role_action_payload(
            player_id=player_id,
            role_type=role_type,
            payload=payload,
        )
        normalized_action_intents.append(
            {
                "action": "role",
                "role_type": role_type,
                "role_action_intent": role_action_intent,
            }
        )

    # Enforce skip as fallback ONLY if no other actions exist
    if not normalized_action_intents:
        return [{"action": "skip"}]

    # If there are real actions, ensure skip is NOT present
    filtered_actions = [a for a in normalized_action_intents if a.get("action") != "skip"]
    return filtered_actions if filtered_actions else [{"action": "skip"}]


def _extract_role_action_payload(
    *,
    player_id: str,
    role_type: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    raw_role_action_intent = payload.get("role_action_intent")
    if raw_role_action_intent is not None and not isinstance(raw_role_action_intent, dict):
        raise ValueError(f"Role action intent payload for player {player_id} must be a dict.")

    supported_flat_keys_by_role_type: dict[str, set[str]] = {
        # Legacy missionary target payloads are still accepted, but ignored.
        # Missionary target selection now happens only during tableau resolve.
        "Missionare": {"target_player_id"},
        "Monumente": {"monument_card_id", "truth_source", "second_monument_card_id", "second_card_id"},
        "Mönche": set(),
        "Nonnen": set(),
    }
    supported_flat_keys = supported_flat_keys_by_role_type.get(role_type, set())
    normalized_role_action_payload = dict(raw_role_action_intent or {})
    for key in supported_flat_keys:
        if key not in payload:
            continue
        flat_value = payload.get(key)
        if key in normalized_role_action_payload and normalized_role_action_payload[key] != flat_value:
            raise ValueError(
                f"Role action intent for player {player_id} has conflicting values for {key!r} on role {role_type}."
            )
        normalized_role_action_payload[key] = flat_value

    unexpected_flat_keys = sorted(
        key
        for key in payload
        if key not in {"action", "role_type", "role_action_intent"} and key not in supported_flat_keys
    )
    if unexpected_flat_keys:
        raise ValueError(
            f"Unsupported role action payload keys for player {player_id} and role {role_type}: {unexpected_flat_keys}."
        )

    return normalized_role_action_payload or None


def _get_hand_card(player: PlayerState, *, card_id: str) -> CardRef:
    for card in player.hand_cards:
        if card.card_id == card_id:
            return card
    raise ValueError(f"Player {player.player_id} does not have card {card_id} in hand.")


def _get_card_alignment_from_card(card: CardRef) -> str | None:
    metadata_alignment = card.metadata.get("alignment")
    if isinstance(metadata_alignment, str):
        return metadata_alignment
    return get_card_alignment(card.card_id)


def _get_stored_power_unleash_additional_cost(state: GameState, *, player_id: str) -> int:
    return 3 * _count_active_enlightener_rule_text(
        state,
        player_id=player_id,
        text=ENLIGHTENER_STORED_POWER_UNLEASH_COST_TEXT,
    )


def _get_stored_power_unleash_effective_additional_cost(state: GameState, *, player_id: str) -> int:
    additional_cost = _get_stored_power_unleash_additional_cost(state, player_id=player_id)
    return _apply_sacrifice_cost_reduction(
        state,
        player_id=player_id,
        amount=additional_cost,
    )


def unleash_stored_power(
    state: GameState,
    *,
    player_id: str,
    phenomenon_card_id: str,
    payment_choice: dict[str, Any] | None = None,
    effect_payload: dict[str, Any] | None = None,
    decision_source: str | None = None,
) -> GameState:
    if state.beginner_mode:
        require_beginner_phenomenon_payload(effect_payload or {})
    player = state.players[player_id]
    if phenomenon_card_id not in player.stored_phenomena:
        raise ValueError(f"Player {player_id} cannot unleash unknown stored phenomenon {phenomenon_card_id}.")
    if phenomenon_card_id not in SUPPORTED_STORED_POWER_PHENOMENA:
        raise ValueError(f"Stored phenomenon {phenomenon_card_id} has no modeled unleash effect.")

    _validate_stored_power_effect_choices(
        state, player_id=player_id, phenomenon_card_id=phenomenon_card_id, effect_payload=effect_payload or {},
    )
    additional_cost = _get_stored_power_unleash_additional_cost(state, player_id=player_id)
    payment_resolution = {
        "paid_total": 0,
        "free_meeples_paid": 0,
        "role_meeples_paid": {role_type: 0 for role_type in ROLE_TYPES},
        "prepared_nuns_paid": 0,
    }
    if additional_cost > 0:
        effective_additional_cost = _get_stored_power_unleash_effective_additional_cost(state, player_id=player_id)
        payment_resolution = _spend_player_meeples(
            state,
            player_id=player_id,
            amount=effective_additional_cost,
            strict=True,
            payment_choice=payment_choice,
            purpose="stored_power_unleash_cost",
        )

    played_phenomenon_id = play_stored_phenomenon_action(
        state,
        player_id=player_id,
        phenomenon_id=phenomenon_card_id,
        action_name="unleash_stored_power",
        decision_source=decision_source,
    )

    append_event(
        state.event_log,
        "stored_power_unleashed",
        player_id=player_id,
        phenomenon_card_id=played_phenomenon_id,
        additional_cost=additional_cost,
        effective_additional_cost=payment_resolution["paid_total"],
        paid_total=payment_resolution["paid_total"],
        free_meeples_paid=payment_resolution["free_meeples_paid"],
        role_meeples_paid=dict(payment_resolution["role_meeples_paid"]),
        prepared_nuns_paid=payment_resolution["prepared_nuns_paid"],
        consumed_stored_power=True,
        remaining_stored_phenomena=list(player.stored_phenomena),
        phenomenon_discard_size=len(state.phenomenon_discard),
        decision_source=decision_source,
        meeples_after=state.players[player_id].meeples,
    )
    _resolve_stored_power_effect(
        state,
        player_id=player_id,
        phenomenon_card_id=played_phenomenon_id,
        effect_payload=effect_payload,
        decision_source=decision_source,
    )
    return state


def _resolve_stored_power_effect(
    state: GameState,
    *,
    player_id: str,
    phenomenon_card_id: str,
    effect_payload: dict[str, Any] | None,
    decision_source: str | None,
) -> None:
    payload = effect_payload or {}

    if phenomenon_card_id in PHENOMENON_EFFECT_GAIN_MEEPLES:
        baptized_meeples = PHENOMENON_EFFECT_GAIN_MEEPLES[phenomenon_card_id]
        player = state.players[player_id]
        player.meeples += baptized_meeples
        append_event(
            state.event_log,
            "stored_power_effect_resolved",
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="baptize_self_meeples",
            baptized_meeples=baptized_meeples,
            meeples_after=player.meeples,
            decision_source=decision_source,
        )
        return

    if phenomenon_card_id == "kometeneinschlag__Phänomene__1":
        _resolve_stored_power_kometeneinschlag(
            state,
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_payload=payload,
            decision_source=decision_source,
        )
        return

    if phenomenon_card_id == "nordlichter__Phänomene__1":
        _resolve_stored_power_nordlichter(
            state,
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            decision_source=decision_source,
        )
        return

    if phenomenon_card_id in PHENOMENON_EFFECT_DESTROY_RELIC_OR_SHATTER_COMMANDMENT:
        _resolve_stored_power_destroy_relic_or_shatter_commandment(
            state,
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_payload=payload,
            decision_source=decision_source,
        )
        return

    if phenomenon_card_id in PHENOMENON_EFFECT_NEXT_CONTEST_BLOCK:
        _resolve_stored_power_hungersnot(
            state,
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_payload=payload,
            decision_source=decision_source,
        )
        return

    if phenomenon_card_id in PHENOMENON_EFFECT_NEXT_TURN_SKIP:
        _resolve_stored_power_yak(
            state,
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_payload=payload,
            decision_source=decision_source,
        )
        return

    if phenomenon_card_id in PHENOMENON_EFFECT_NEXT_TURN_ACTION_PENALTY:
        _resolve_stored_power_waldbrand(
            state,
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_payload=payload,
            decision_source=decision_source,
        )
        return

    if phenomenon_card_id == "eichhoernchenplage__Phänomene__1":
        _resolve_stored_power_eichhoernchenplage(
            state,
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_payload=payload,
            decision_source=decision_source,
        )
        return

    if phenomenon_card_id == "froschregen__Phänomene__1":
        _resolve_stored_power_froschregen(
            state,
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_payload=payload,
            decision_source=decision_source,
        )
        return

    if phenomenon_card_id == "kornkreise__Phänomene__1":
        _resolve_stored_power_kornkreise(
            state,
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_payload=payload,
            decision_source=decision_source,
        )
        return

    if phenomenon_card_id == "kugelblitz__Phänomene__1":
        _resolve_stored_power_kugelblitz(
            state,
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_payload=payload,
            decision_source=decision_source,
        )
        return

    if phenomenon_card_id == "mondfinsternis__Phänomene__1":
        _resolve_stored_power_mondfinsternis(
            state,
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            decision_source=decision_source,
        )
        return

    if phenomenon_card_id == "pest__Phänomene__1":
        _resolve_stored_power_pest(
            state,
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_payload=payload,
            decision_source=decision_source,
        )
        return

    if phenomenon_card_id == "sonnenfinsternis__Phänomene__1":
        _resolve_stored_power_sonnenfinsternis(
            state,
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_payload=payload,
            decision_source=decision_source,
        )
        return

    if phenomenon_card_id == "tornado__Phänomene__1":
        _resolve_stored_power_tornado(
            state,
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_payload=payload,
            decision_source=decision_source,
        )
        return

    if phenomenon_card_id == "tsunami__Phänomene__1":
        _resolve_stored_power_tsunami(
            state,
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_payload=payload,
            decision_source=decision_source,
        )
        return

    raise ValueError(f"Stored phenomenon {phenomenon_card_id} has no modeled unleash effect.")


def _validate_kometeneinschlag_payment_choices(
    state: GameState, *, player_id: str, effect_payload: dict[str, Any],
) -> None:
    _validate_free_believer_target_payments(
        state, player_id=player_id, effect_payload=effect_payload, context="Kometeneinschlag",
    )


def _validate_free_believer_target_payments(
    state: GameState, *, player_id: str, effect_payload: dict[str, Any], context: str,
) -> None:
    choices = effect_payload.get("target_payment_choices", {})
    if not isinstance(choices, dict):
        raise ValueError(f"{context} requires target_payment_choices to be a dict when provided.")
    for target_player_id in _get_opponent_player_ids_in_turn_order(state, player_id=player_id):
        choice = _normalize_meeple_payment_choice(
            choices.get(target_player_id), context=f"{context} target payment",
        )
        if _count_bound_meeples_in_payment_choice(choice) > 0:
            raise ValueError(f"{context} can sacrifice only free believers; monks, missionaries and nuns are excluded.")


def _resolve_stored_power_kometeneinschlag(
    state: GameState,
    *,
    player_id: str,
    phenomenon_card_id: str,
    effect_payload: dict[str, Any],
    decision_source: str | None,
) -> None:
    _validate_kometeneinschlag_payment_choices(state, player_id=player_id, effect_payload=effect_payload)

    opponent_ids = _get_opponent_player_ids_in_turn_order(state, player_id=player_id)
    if not opponent_ids:
        append_event(
            state.event_log,
            "stored_power_effect_fizzled",
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="forced_all_opponents_sacrifice",
            reason="no_opponents",
            decision_source=decision_source,
        )
        return

    total_sacrificed = 0
    for target_player_id in opponent_ids:
        requested_sacrifice = 4
        effective_sacrifice = _apply_sacrifice_cost_reduction(
            state,
            player_id=target_player_id,
            amount=requested_sacrifice,
        )
        payment_resolution = _spend_player_meeples(
            state,
            player_id=target_player_id,
            amount=effective_sacrifice,
            strict=False,
            payment_choice=None,
            purpose="stored_power_kometeneinschlag_sacrifice",
            trigger_large_sacrifice=False,
        )
        total_sacrificed += payment_resolution["paid_total"]
        append_event(
            state.event_log,
            "stored_power_effect_target_resolved",
            player_id=player_id,
            target_player_id=target_player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="forced_all_opponents_sacrifice",
            requested_sacrifice=requested_sacrifice,
            effective_sacrifice=effective_sacrifice,
            actual_sacrifice=payment_resolution["paid_total"],
            free_meeples_paid=payment_resolution["free_meeples_paid"],
            role_meeples_paid=dict(payment_resolution["role_meeples_paid"]),
            prepared_nuns_paid=payment_resolution["prepared_nuns_paid"],
            target_meeples_after=state.players[target_player_id].meeples,
            decision_source=decision_source,
        )
        _trigger_relic_large_sacrifice_missionize(
            state,
            sacrificing_player_id=target_player_id,
            paid_total=payment_resolution["paid_total"],
            purpose="stored_power_kometeneinschlag_sacrifice",
        )

    append_event(
        state.event_log,
        "stored_power_effect_resolved",
        player_id=player_id,
        phenomenon_card_id=phenomenon_card_id,
        effect_kind="forced_all_opponents_sacrifice",
        total_sacrificed=total_sacrificed,
        target_player_ids=opponent_ids,
        decision_source=decision_source,
    )


def _resolve_stored_power_nordlichter(
    state: GameState,
    *,
    player_id: str,
    phenomenon_card_id: str,
    decision_source: str | None,
) -> None:
    player = state.players[player_id]
    opponent_ids = _get_opponent_player_ids_in_turn_order(state, player_id=player_id)
    if not opponent_ids:
        append_event(
            state.event_log,
            "stored_power_effect_fizzled",
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="missionize_from_each_opponent",
            reason="no_opponents",
            decision_source=decision_source,
        )
        return

    total_transferred = 0
    for target_player_id in opponent_ids:
        target_player = state.players[target_player_id]
        if _is_player_immune_to_missionizing(state, player_id=target_player_id):
            transferred = 0
            resolution_reason = "target_is_pure_gentleness"
        else:
            transferred = min(3, target_player.meeples)
            resolution_reason = "resolved"
        if transferred > 0:
            target_player.meeples -= transferred
            player.meeples += transferred
            state.last_meeple_taker_by_victim[target_player_id] = player_id
            total_transferred += transferred
        append_event(
            state.event_log,
            "stored_power_effect_target_resolved",
            player_id=player_id,
            target_player_id=target_player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="missionize_from_each_opponent",
            requested_transfer=3,
            actual_transfer=transferred,
            resolution_reason=resolution_reason,
            player_meeples_after=player.meeples,
            target_meeples_after=target_player.meeples,
            decision_source=decision_source,
        )

    append_event(
        state.event_log,
        "stored_power_effect_resolved",
        player_id=player_id,
        phenomenon_card_id=phenomenon_card_id,
        effect_kind="missionize_from_each_opponent",
        total_transferred=total_transferred,
        target_player_ids=opponent_ids,
        meeples_after=player.meeples,
        decision_source=decision_source,
    )


def _resolve_stored_power_destroy_relic_or_shatter_commandment(
    state: GameState,
    *,
    player_id: str,
    phenomenon_card_id: str,
    effect_payload: dict[str, Any],
    decision_source: str | None,
) -> None:
    mode = effect_payload.get("mode")
    if mode is not None and mode not in {"destroy_relic", "shatter_commandment"}:
        raise ValueError(
            f"Stored power {phenomenon_card_id} mode must be 'destroy_relic' or 'shatter_commandment'."
        )

    has_relic_target = any(
        card.category == "Reliquie"
        for candidate_player_id in _get_opponent_player_ids_in_turn_order(state, player_id=player_id)
        for card in state.players[candidate_player_id].tableau
    )
    has_commandment_target = bool(state.active_commandments)

    resolved_mode = mode
    if resolved_mode is None:
        if has_relic_target:
            resolved_mode = "destroy_relic"
        elif has_commandment_target:
            resolved_mode = "shatter_commandment"

    if resolved_mode == "destroy_relic":
        _resolve_stored_power_destroy_relic(
            state,
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_payload=effect_payload,
            decision_source=decision_source,
        )
        return
    if resolved_mode == "shatter_commandment":
        _resolve_stored_power_shatter_commandment(
            state,
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_payload=effect_payload,
            decision_source=decision_source,
        )
        return

    append_event(
        state.event_log,
        "stored_power_effect_fizzled",
        player_id=player_id,
        phenomenon_card_id=phenomenon_card_id,
        effect_kind="destroy_relic_or_shatter_commandment",
        reason="no_valid_targets",
        decision_source=decision_source,
    )


def _resolve_stored_power_destroy_relic(
    state: GameState,
    *,
    player_id: str,
    phenomenon_card_id: str,
    effect_payload: dict[str, Any],
    decision_source: str | None,
) -> None:
    opponent_ids = _get_opponent_player_ids_in_turn_order(state, player_id=player_id)
    candidate_owner_ids = [
        candidate_player_id
        for candidate_player_id in opponent_ids
        if any(card.category == "Reliquie" for card in state.players[candidate_player_id].tableau)
    ]
    if not candidate_owner_ids:
        append_event(
            state.event_log,
            "stored_power_effect_fizzled",
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="destroy_relic",
            reason="no_relic_target",
            decision_source=decision_source,
        )
        return

    raw_target_player_id = effect_payload.get("target_player_id")
    if raw_target_player_id is not None and not isinstance(raw_target_player_id, str):
        raise ValueError(f"Stored power {phenomenon_card_id} target_player_id must be a string.")
    if raw_target_player_id is not None and raw_target_player_id not in candidate_owner_ids:
        raise ValueError(f"Stored power {phenomenon_card_id} cannot target player {raw_target_player_id}.")
    target_player_id = raw_target_player_id or candidate_owner_ids[0]

    target_owner = state.players[target_player_id]
    candidate_relics = [card for card in target_owner.tableau if card.category == "Reliquie"]
    raw_target_card_id = effect_payload.get("target_card_id")
    if raw_target_card_id is not None and not isinstance(raw_target_card_id, str):
        raise ValueError(f"Stored power {phenomenon_card_id} target_card_id must be a string.")
    if raw_target_card_id is not None and all(card.card_id != raw_target_card_id for card in candidate_relics):
        raise ValueError(
            f"Stored power {phenomenon_card_id} cannot target relic {raw_target_card_id} on player {target_player_id}."
        )
    target_relic = (
        next(card for card in candidate_relics if card.card_id == raw_target_card_id)
        if raw_target_card_id is not None
        else candidate_relics[0]
    )

    removed_relic = _pop_card_from_tableau(target_owner, card_id=target_relic.card_id)
    state.heavenly_discard_pile.append(removed_relic)
    append_event(
        state.event_log,
        "stored_power_effect_resolved",
        player_id=player_id,
        target_player_id=target_player_id,
        phenomenon_card_id=phenomenon_card_id,
        effect_kind="destroy_relic",
        target_card_id=removed_relic.card_id,
        target_card_name=removed_relic.name,
        heavenly_discard_pile_size=len(state.heavenly_discard_pile),
        decision_source=decision_source,
    )


def _resolve_stored_power_shatter_commandment(
    state: GameState,
    *,
    player_id: str,
    phenomenon_card_id: str,
    effect_payload: dict[str, Any],
    decision_source: str | None,
) -> None:
    if not state.active_commandments:
        append_event(
            state.event_log,
            "stored_power_effect_fizzled",
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="shatter_commandment",
            reason="no_active_commandments",
            decision_source=decision_source,
        )
        return

    raw_commandment_card_id = effect_payload.get("commandment_card_id")
    if raw_commandment_card_id is not None and not isinstance(raw_commandment_card_id, str):
        raise ValueError(f"Stored power {phenomenon_card_id} commandment_card_id must be a string.")
    if raw_commandment_card_id is not None and all(
        commandment.card_id != raw_commandment_card_id for commandment in state.active_commandments
    ):
        raise ValueError(
            f"Stored power {phenomenon_card_id} cannot shatter unknown commandment {raw_commandment_card_id}."
        )
    removed_index = -1
    if raw_commandment_card_id is not None:
        removed_index = next(
            index
            for index, commandment in enumerate(state.active_commandments)
            if commandment.card_id == raw_commandment_card_id
        )
    removed_commandment = state.active_commandments.pop(removed_index)
    recalculate_commandment_effects(state)
    append_event(
        state.event_log,
        "stored_power_effect_resolved",
        player_id=player_id,
        phenomenon_card_id=phenomenon_card_id,
        effect_kind="shatter_commandment",
        shattered_commandment_card_id=removed_commandment.card_id,
        shattered_commandment_name=removed_commandment.name,
        active_commandments_count=len(state.active_commandments),
        decision_source=decision_source,
    )


def _resolve_stored_power_hungersnot(
    state: GameState,
    *,
    player_id: str,
    phenomenon_card_id: str,
    effect_payload: dict[str, Any],
    decision_source: str | None,
) -> None:
    target_player_id = _resolve_stored_power_target_player_id(
        state,
        source_player_id=player_id,
        effect_payload=effect_payload,
        effect_label=phenomenon_card_id,
    )
    if target_player_id is None:
        append_event(
            state.event_log,
            "stored_power_effect_fizzled",
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="block_next_contest",
            reason="no_opponents",
            decision_source=decision_source,
        )
        return

    target_player = state.players[target_player_id]
    target_player.skip_next_contest = True
    append_event(
        state.event_log,
        "stored_power_effect_resolved",
        player_id=player_id,
        target_player_id=target_player_id,
        phenomenon_card_id=phenomenon_card_id,
        effect_kind="block_next_contest",
        target_skip_next_contest=target_player.skip_next_contest,
        decision_source=decision_source,
    )


def _resolve_stored_power_yak(
    state: GameState,
    *,
    player_id: str,
    phenomenon_card_id: str,
    effect_payload: dict[str, Any],
    decision_source: str | None,
) -> None:
    target_player_id = _resolve_stored_power_target_player_id(
        state,
        source_player_id=player_id,
        effect_payload=effect_payload,
        effect_label=phenomenon_card_id,
    )
    if target_player_id is None:
        append_event(
            state.event_log,
            "stored_power_effect_fizzled",
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="skip_next_turn",
            reason="no_opponents",
            decision_source=decision_source,
        )
        return

    target_player = state.players[target_player_id]
    target_player.skip_next_turn = True
    append_event(
        state.event_log,
        "stored_power_effect_resolved",
        player_id=player_id,
        target_player_id=target_player_id,
        phenomenon_card_id=phenomenon_card_id,
        effect_kind="skip_next_turn",
        target_skip_next_turn=target_player.skip_next_turn,
        decision_source=decision_source,
    )


def _resolve_stored_power_waldbrand(
    state: GameState,
    *,
    player_id: str,
    phenomenon_card_id: str,
    effect_payload: dict[str, Any],
    decision_source: str | None,
) -> None:
    target_player_id = _resolve_stored_power_target_player_id(
        state,
        source_player_id=player_id,
        effect_payload=effect_payload,
        effect_label=phenomenon_card_id,
    )
    if target_player_id is None:
        append_event(
            state.event_log,
            "stored_power_effect_fizzled",
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="extra_action_and_next_turn_action_penalty",
            reason="no_opponents",
            decision_source=decision_source,
        )
        return

    player = state.players[player_id]
    target_player = state.players[target_player_id]
    target_player.next_turn_action_modifier -= 1
    player.bonus_actions_this_turn += 1

    append_event(
        state.event_log,
        "stored_power_effect_resolved",
        player_id=player_id,
        target_player_id=target_player_id,
        phenomenon_card_id=phenomenon_card_id,
        effect_kind="extra_action_and_next_turn_action_penalty",
        target_next_turn_action_modifier=target_player.next_turn_action_modifier,
        bonus_actions_granted=1,
        player_bonus_actions_this_turn=player.bonus_actions_this_turn,
        decision_source=decision_source,
    )


def _resolve_stored_power_eichhoernchenplage(
    state: GameState,
    *,
    player_id: str,
    phenomenon_card_id: str,
    effect_payload: dict[str, Any],
    decision_source: str | None,
) -> None:
    target_player_id = _resolve_stored_power_target_player_id(
        state,
        source_player_id=player_id,
        effect_payload=effect_payload,
        effect_label=phenomenon_card_id,
    )
    if target_player_id is None:
        append_event(
            state.event_log,
            "stored_power_effect_fizzled",
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="steal_missionaries_if_possible",
            reason="no_opponents",
            decision_source=decision_source,
        )
        return

    raw_requested = effect_payload.get("missionaries_to_steal", 2)
    if not isinstance(raw_requested, int):
        raise ValueError(f"Stored power {phenomenon_card_id} missionaries_to_steal must be an integer.")
    if raw_requested < 1 or raw_requested > 2:
        raise ValueError(f"Stored power {phenomenon_card_id} missionaries_to_steal must be in [1,2].")

    _sync_role_slot_assignments(state, player_id=player_id)
    _sync_role_slot_assignments(state, player_id=target_player_id)
    player = state.players[player_id]
    target_player = state.players[target_player_id]
    own_assigned = player.assigned_role_meeples.get("Missionare", 0)
    own_max_assignable = min(player.missionaries_slots, _get_role_card_count(player, role_type="Missionare"))
    own_free_slots = max(0, own_max_assignable - own_assigned)
    target_assigned = target_player.assigned_role_meeples.get("Missionare", 0)
    actual_transfer = min(raw_requested, own_free_slots, target_assigned)

    if actual_transfer <= 0:
        append_event(
            state.event_log,
            "stored_power_effect_fizzled",
            player_id=player_id,
            target_player_id=target_player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="steal_missionaries_if_possible",
            reason="no_transfer_possible",
            decision_source=decision_source,
        )
        return

    target_player.assigned_role_meeples["Missionare"] = target_assigned - actual_transfer
    player.assigned_role_meeples["Missionare"] = own_assigned + actual_transfer
    append_event(
        state.event_log,
        "stored_power_effect_resolved",
        player_id=player_id,
        target_player_id=target_player_id,
        phenomenon_card_id=phenomenon_card_id,
        effect_kind="steal_missionaries_if_possible",
        requested_transfer=raw_requested,
        actual_transfer=actual_transfer,
        player_assigned_missionaries_after=player.assigned_role_meeples["Missionare"],
        target_assigned_missionaries_after=target_player.assigned_role_meeples["Missionare"],
        decision_source=decision_source,
    )


def _resolve_stored_power_froschregen(
    state: GameState,
    *,
    player_id: str,
    phenomenon_card_id: str,
    effect_payload: dict[str, Any],
    decision_source: str | None,
) -> None:
    mode = effect_payload.get("mode")
    if mode is not None and mode not in {"search_monument", "shatter_commandment"}:
        raise ValueError(
            f"Stored power {phenomenon_card_id} mode must be 'search_monument' or 'shatter_commandment'."
        )
    resolved_mode = mode or "search_monument"

    if resolved_mode == "shatter_commandment":
        _resolve_stored_power_shatter_commandment(
            state,
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_payload=effect_payload,
            decision_source=decision_source,
        )
        return

    raw_monument_part = effect_payload.get("monument_part")
    if raw_monument_part is not None and not isinstance(raw_monument_part, int):
        raise ValueError(f"Stored power {phenomenon_card_id} monument_part must be an integer.")
    if effect_payload.get("second_monument_card_id") is not None or effect_payload.get("second_card_id") is not None:
        raise ValueError(f"Stored power {phenomenon_card_id} can only search one monument card.")
    if not _has_free_slot(state.players[player_id], slot_kind="forge"):
        append_event(
            state.event_log,
            "stored_power_effect_fizzled",
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="search_monument_or_shatter_commandment",
            selected_mode="search_monument",
            reason="forge_slot_full",
            decision_source=decision_source,
        )
        return
    if _player_has_active_enlightener_rule_text(
        state,
        player_id=player_id,
        text=ENLIGHTENER_BLOCKS_MONUMENTS_TEXT,
    ):
        append_event(
            state.event_log,
            "stored_power_effect_fizzled",
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="search_monument_or_shatter_commandment",
            selected_mode="search_monument",
            reason="blocked_by_enlightener",
            decision_source=decision_source,
        )
        return

    raw_monument_card_id = effect_payload.get("monument_card_id")
    if raw_monument_card_id is not None and not isinstance(raw_monument_card_id, str):
        raise ValueError(f"Stored power {phenomenon_card_id} monument_card_id must be a string.")
    if not state.monument_draw_pile:
        append_event(
            state.event_log,
            "stored_power_effect_fizzled",
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="search_monument_or_shatter_commandment",
            selected_mode="search_monument",
            reason="monument_draw_pile_empty",
            decision_source=decision_source,
        )
        return

    required_monument_group_keys = _collect_player_monument_group_keys(state.players[player_id])
    selected_index: int | None = None
    if raw_monument_card_id is not None:
        selected_index = next(
            (index for index, card in enumerate(state.monument_draw_pile) if card.card_id == raw_monument_card_id),
            -1,
        )
        if selected_index < 0:
            raise ValueError(
                f"Stored power {phenomenon_card_id} cannot search unknown monument card {raw_monument_card_id}."
            )
        if (
            required_monument_group_keys
            and _monument_group_key_from_card_id(raw_monument_card_id) not in required_monument_group_keys
        ):
            raise ValueError(
                f"Stored power {phenomenon_card_id} selected monument card {raw_monument_card_id} "
                "must match an existing monument line."
            )
        build_reason = _get_monument_build_reason(state, player_id=player_id, card_id=raw_monument_card_id)
        if build_reason:
            raise ValueError(build_reason)
    else:
        matching_monument_indices = [
            index
            for index, card in enumerate(state.monument_draw_pile)
            if (
                (
                    not required_monument_group_keys
                    or _monument_group_key_from_card_id(card.card_id) in required_monument_group_keys
                )
                and _get_monument_build_reason(state, player_id=player_id, card_id=card.card_id) is None
            )
        ]
        if not matching_monument_indices:
            append_event(
                state.event_log,
                "stored_power_effect_fizzled",
                player_id=player_id,
                phenomenon_card_id=phenomenon_card_id,
                effect_kind="search_monument_or_shatter_commandment",
                selected_mode="search_monument",
                reason="no_matching_monument_available",
                required_monument_group_keys=sorted(required_monument_group_keys),
                monument_draw_pile_size=len(state.monument_draw_pile),
                decision_source=decision_source,
            )
            return
        selected_index = matching_monument_indices[0]

    assert selected_index is not None
    selected_card = state.monument_draw_pile.pop(selected_index)
    monument_card_id = selected_card.card_id
    monument_part = raw_monument_part if raw_monument_part is not None else _infer_monument_part_from_card_id(monument_card_id)
    if monument_part not in {1, 2, 3}:
        raise ValueError(f"Stored power {phenomenon_card_id} could not resolve monument part for card {monument_card_id}.")

    build_monument_part(
        state,
        player_id=player_id,
        part=monument_part,
        card_id=monument_card_id,
    )
    append_event(
        state.event_log,
        "stored_power_effect_resolved",
        player_id=player_id,
        phenomenon_card_id=phenomenon_card_id,
        effect_kind="search_monument_or_shatter_commandment",
        selected_mode="search_monument",
        monument_card_id=monument_card_id,
        monument_part=monument_part,
        required_monument_group_keys=sorted(required_monument_group_keys),
        selected_monument_group_key=_monument_group_key_from_card_id(monument_card_id),
        monument_draw_pile_size=len(state.monument_draw_pile),
        decision_source=decision_source,
    )


def _resolve_stored_power_kornkreise(
    state: GameState,
    *,
    player_id: str,
    phenomenon_card_id: str,
    effect_payload: dict[str, Any],
    decision_source: str | None,
) -> None:
    mode = effect_payload.get("mode")
    if mode is not None and mode not in {"swap_all_heavenly_hand", "shatter_commandment"}:
        raise ValueError(
            f"Stored power {phenomenon_card_id} mode must be 'swap_all_heavenly_hand' or 'shatter_commandment'."
        )

    resolved_mode = mode
    if resolved_mode is None:
        if _get_opponent_player_ids_in_turn_order(state, player_id=player_id):
            resolved_mode = "swap_all_heavenly_hand"
        elif state.active_commandments:
            resolved_mode = "shatter_commandment"

    if resolved_mode == "shatter_commandment":
        _resolve_stored_power_shatter_commandment(
            state,
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_payload=effect_payload,
            decision_source=decision_source,
        )
        return

    target_player_id = _resolve_stored_power_target_player_id(
        state,
        source_player_id=player_id,
        effect_payload=effect_payload,
        effect_label=phenomenon_card_id,
    )
    if target_player_id is None:
        append_event(
            state.event_log,
            "stored_power_effect_fizzled",
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="swap_all_heavenly_hand_or_shatter_commandment",
            selected_mode="swap_all_heavenly_hand",
            reason="no_opponents",
            decision_source=decision_source,
        )
        return

    player = state.players[player_id]
    target_player = state.players[target_player_id]
    player_heavenly = [card for card in player.hand_cards if card.category != "Wahrheit"]
    target_heavenly = [card for card in target_player.hand_cards if card.category != "Wahrheit"]
    player_truth = [card for card in player.hand_cards if card.category == "Wahrheit"]
    target_truth = [card for card in target_player.hand_cards if card.category == "Wahrheit"]
    player.hand_cards = player_truth + target_heavenly
    target_player.hand_cards = target_truth + player_heavenly
    append_event(
        state.event_log,
        "stored_power_effect_resolved",
        player_id=player_id,
        target_player_id=target_player_id,
        phenomenon_card_id=phenomenon_card_id,
        effect_kind="swap_all_heavenly_hand_or_shatter_commandment",
        selected_mode="swap_all_heavenly_hand",
        transferred_to_player_count=len(target_heavenly),
        transferred_to_target_count=len(player_heavenly),
        player_hand_size_after=len(player.hand_cards),
        target_hand_size_after=len(target_player.hand_cards),
        decision_source=decision_source,
    )


def _resolve_stored_power_kugelblitz(
    state: GameState,
    *,
    player_id: str,
    phenomenon_card_id: str,
    effect_payload: dict[str, Any],
    decision_source: str | None,
) -> None:
    target_player_id = _resolve_stored_power_target_player_id_with_predicate(
        state,
        source_player_id=player_id,
        effect_payload=effect_payload,
        effect_label=phenomenon_card_id,
        predicate=lambda candidate_player: bool(candidate_player.stored_phenomena),
    )
    if target_player_id is None:
        append_event(
            state.event_log,
            "stored_power_effect_fizzled",
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="trigger_foreign_stored_power_as_own",
            reason="no_stored_phenomenon_target",
            decision_source=decision_source,
        )
        return

    target_player = state.players[target_player_id]
    raw_target_phenomenon_card_id = effect_payload.get("target_phenomenon_card_id")
    if raw_target_phenomenon_card_id is not None and not isinstance(raw_target_phenomenon_card_id, str):
        raise ValueError(f"Stored power {phenomenon_card_id} target_phenomenon_card_id must be a string.")
    if raw_target_phenomenon_card_id is not None and raw_target_phenomenon_card_id not in target_player.stored_phenomena:
        raise ValueError(
            f"Stored power {phenomenon_card_id} cannot trigger unknown stored phenomenon {raw_target_phenomenon_card_id} on player {target_player_id}."
        )
    triggered_card_id = raw_target_phenomenon_card_id or target_player.stored_phenomena[0]
    if triggered_card_id == phenomenon_card_id:
        append_event(
            state.event_log,
            "stored_power_effect_fizzled",
            player_id=player_id,
            target_player_id=target_player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="trigger_foreign_stored_power_as_own",
            reason="self_recursive_target_not_supported",
            decision_source=decision_source,
        )
        return

    nested_effect_payload = effect_payload.get("nested_effect_payload")
    if nested_effect_payload is not None and not isinstance(nested_effect_payload, dict):
        raise ValueError(f"Stored power {phenomenon_card_id} nested_effect_payload must be a dict when provided.")
    _resolve_stored_power_effect(
        state,
        player_id=player_id,
        phenomenon_card_id=triggered_card_id,
        effect_payload=nested_effect_payload,
        decision_source="kugelblitz_proxy",
    )
    append_event(
        state.event_log,
        "stored_power_effect_resolved",
        player_id=player_id,
        target_player_id=target_player_id,
        phenomenon_card_id=phenomenon_card_id,
        effect_kind="trigger_foreign_stored_power_as_own",
        triggered_phenomenon_card_id=triggered_card_id,
        decision_source=decision_source,
    )


def _resolve_stored_power_mondfinsternis(
    state: GameState,
    *,
    player_id: str,
    phenomenon_card_id: str,
    decision_source: str | None,
) -> None:
    state.players[player_id].bonus_actions_this_turn += 3
    append_event(
        state.event_log,
        "stored_power_effect_resolved",
        player_id=player_id,
        phenomenon_card_id=phenomenon_card_id,
        effect_kind="gain_additional_actions_now",
        bonus_actions_granted=3,
        player_bonus_actions_this_turn=state.players[player_id].bonus_actions_this_turn,
        decision_source=decision_source,
    )


def _resolve_stored_power_pest(
    state: GameState,
    *,
    player_id: str,
    phenomenon_card_id: str,
    effect_payload: dict[str, Any],
    decision_source: str | None,
) -> None:
    target_player_id = _resolve_stored_power_target_player_id_with_predicate(
        state,
        source_player_id=player_id,
        effect_payload=effect_payload,
        effect_label=phenomenon_card_id,
        predicate=lambda candidate_player: sum(candidate_player.assigned_role_meeples.get(role, 0) for role in ROLE_TYPES) > 0,
    )
    if target_player_id is None:
        append_event(
            state.event_log,
            "stored_power_effect_fizzled",
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="fellow_sacrifice_total_role_units",
            reason="no_role_units_target",
            decision_source=decision_source,
        )
        return

    target_player = state.players[target_player_id]
    _sync_role_slot_assignments(state, player_id=target_player_id)
    requested_sacrifice_total = 3
    if _player_has_temple_loss_protection_relic(state, player_id=target_player_id):
        append_event(
            state.event_log,
            "stored_power_effect_resolved",
            player_id=player_id,
            target_player_id=target_player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="fellow_sacrifice_total_role_units",
            removed_by_role={role_type: 0 for role_type in ROLE_TYPES},
            requested_sacrifice_total=requested_sacrifice_total,
            effective_sacrifice_total=requested_sacrifice_total,
            total_removed=0,
            target_role_assignments_after=dict(target_player.assigned_role_meeples),
            decision_source="temple_protected",
        )
        return
    effective_sacrifice_total = _apply_sacrifice_cost_reduction(
        state,
        player_id=target_player_id,
        amount=requested_sacrifice_total,
    )
    raw_plan = effect_payload.get("role_sacrifice_plan")
    removed_by_role = {role_type: 0 for role_type in ROLE_TYPES}
    if raw_plan is not None:
        if not isinstance(raw_plan, dict):
            raise ValueError(f"Stored power {phenomenon_card_id} role_sacrifice_plan must be a dict.")
        requested_total = 0
        for role_type, amount in raw_plan.items():
            if role_type not in ROLE_TYPES:
                raise ValueError(f"Stored power {phenomenon_card_id} received unknown role type {role_type}.")
            if not isinstance(amount, int):
                raise ValueError(f"Stored power {phenomenon_card_id} role_sacrifice_plan values must be integers.")
            if amount < 0:
                raise ValueError(f"Stored power {phenomenon_card_id} role_sacrifice_plan values must be non-negative.")
            available = target_player.assigned_role_meeples.get(role_type, 0)
            if amount > available:
                raise ValueError(
                    f"Stored power {phenomenon_card_id} cannot remove {amount} {role_type} from player {target_player_id}; only {available} assigned."
                )
            removed_by_role[role_type] = amount
            requested_total += amount
        if requested_total > effective_sacrifice_total:
            raise ValueError(
                f"Stored power {phenomenon_card_id} role_sacrifice_plan cannot exceed "
                f"{effective_sacrifice_total} total units after sacrifice cost reduction."
            )
    else:
        remaining = effective_sacrifice_total
        for role_type in ROLE_TYPES:
            if remaining <= 0:
                break
            available = target_player.assigned_role_meeples.get(role_type, 0)
            removed = min(available, remaining)
            removed_by_role[role_type] = removed
            remaining -= removed

    total_removed = sum(removed_by_role.values())
    if total_removed <= 0:
        append_event(
            state.event_log,
            "stored_power_effect_fizzled",
            player_id=player_id,
            target_player_id=target_player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="fellow_sacrifice_total_role_units",
            reason="no_role_units_removed",
            decision_source=decision_source,
        )
        return

    for role_type, removed in removed_by_role.items():
        if removed > 0:
            _spend_assigned_role_meeples_from_player(target_player, role_type, removed)
    append_event(
        state.event_log,
        "stored_power_effect_resolved",
        player_id=player_id,
        target_player_id=target_player_id,
        phenomenon_card_id=phenomenon_card_id,
        effect_kind="fellow_sacrifice_total_role_units",
        removed_by_role=removed_by_role,
        requested_sacrifice_total=requested_sacrifice_total,
        effective_sacrifice_total=effective_sacrifice_total,
        total_removed=total_removed,
        target_role_assignments_after=dict(target_player.assigned_role_meeples),
        decision_source=decision_source,
    )


def _prepare_sonnenfinsternis_recipient_choice(
    state: GameState, *, player_id: str, phenomenon_card_id: str, effect_payload: dict[str, Any],
) -> tuple[str | None, str | None, list[str], str]:
    """Validate the recipient's own-card response without changing game state.

    recipient_choice is trusted controller data, never a source-player form field.
    """
    if "selected_heavenly_card_ids" in effect_payload:
        raise ValueError("Sonnenfinsternis source payload must not select the recipient's cards.")
    mode = effect_payload.get("mode")
    if mode is not None and mode not in {"take_heavenly_from_fellow", "shatter_commandment"}:
        raise ValueError(
            f"Stored power {phenomenon_card_id} mode must be 'take_heavenly_from_fellow' or 'shatter_commandment'."
        )

    resolved_mode = mode
    if resolved_mode is None:
        candidate_target_player_id = _resolve_stored_power_target_player_id_with_predicate(
            state,
            source_player_id=player_id,
            effect_payload=effect_payload,
            effect_label=phenomenon_card_id,
            predicate=lambda candidate_player: any(card.category != "Wahrheit" for card in candidate_player.hand_cards),
        )
        if candidate_target_player_id is not None:
            resolved_mode = "take_heavenly_from_fellow"
        elif state.active_commandments:
            resolved_mode = "shatter_commandment"

    if resolved_mode == "shatter_commandment":
        if "recipient_choice" in effect_payload:
            raise ValueError("Sonnenfinsternis shatter mode must not contain recipient_choice.")
        return resolved_mode, None, [], "recipient_auto_policy"
    target_player_id = _resolve_stored_power_target_player_id_with_predicate(
        state, source_player_id=player_id, effect_payload=effect_payload, effect_label=phenomenon_card_id,
        predicate=lambda candidate: any(card.category != "Wahrheit" for card in candidate.hand_cards),
    )
    candidates = [] if target_player_id is None else [
        card.card_id for card in state.players[target_player_id].hand_cards if card.category != "Wahrheit"
    ]
    required_count = min(3, len(candidates))
    if "recipient_choice" not in effect_payload:
        return resolved_mode, target_player_id, candidates[:required_count], "recipient_auto_policy"
    choice = effect_payload["recipient_choice"]
    if not isinstance(choice, dict) or target_player_id is None or choice.get("player_id") != target_player_id:
        raise ValueError("Sonnenfinsternis recipient_choice must belong to the selected fellow god.")
    selected = choice.get("selected_heavenly_card_ids")
    if not isinstance(selected, list) or any(not isinstance(card_id, str) for card_id in selected):
        raise ValueError("Sonnenfinsternis recipient selection must be a list of card-id strings.")
    if len(selected) != required_count or len(set(selected)) != len(selected):
        raise ValueError(f"Sonnenfinsternis recipient must choose exactly {required_count} distinct heavenly cards.")
    if any(card_id not in candidates for card_id in selected):
        raise ValueError("Sonnenfinsternis recipient may choose only their own heavenly hand cards.")
    return resolved_mode, target_player_id, list(selected), "recipient_explicit_choice"


def _validate_stored_power_effect_choices(
    state: GameState, *, player_id: str, phenomenon_card_id: str, effect_payload: dict[str, Any],
) -> None:
    """Preflight effect choices before paying or consuming the source power."""
    if phenomenon_card_id == "kometeneinschlag__Phänomene__1":
        _validate_kometeneinschlag_payment_choices(state, player_id=player_id, effect_payload=effect_payload)
    elif phenomenon_card_id == "sonnenfinsternis__Phänomene__1":
        _prepare_sonnenfinsternis_recipient_choice(
            state, player_id=player_id, phenomenon_card_id=phenomenon_card_id, effect_payload=effect_payload,
        )
    elif phenomenon_card_id == "kugelblitz__Phänomene__1":
        target = _resolve_stored_power_target_player_id_with_predicate(
            state, source_player_id=player_id, effect_payload=effect_payload, effect_label=phenomenon_card_id,
            predicate=lambda candidate: bool(candidate.stored_phenomena),
        )
        if target is None:
            return
        powers = state.players[target].stored_phenomena
        requested = effect_payload.get("target_phenomenon_card_id")
        if requested is not None and (not isinstance(requested, str) or requested not in powers):
            raise ValueError("Kugelblitz must trigger an available stored phenomenon of its target.")
        copied = requested or powers[0]
        if copied == phenomenon_card_id:
            return
        nested = effect_payload.get("nested_effect_payload")
        if nested is not None and not isinstance(nested, dict):
            raise ValueError("Kugelblitz nested_effect_payload must be a dict when provided.")
        _validate_stored_power_effect_choices(
            state, player_id=player_id, phenomenon_card_id=copied, effect_payload=nested or {},
        )


def _resolve_stored_power_sonnenfinsternis(
    state: GameState,
    *,
    player_id: str,
    phenomenon_card_id: str,
    effect_payload: dict[str, Any],
    decision_source: str | None,
) -> None:
    resolved_mode, target_player_id, selected_card_ids, card_choice_source = _prepare_sonnenfinsternis_recipient_choice(
        state, player_id=player_id, phenomenon_card_id=phenomenon_card_id, effect_payload=effect_payload,
    )

    if resolved_mode == "shatter_commandment":
        _resolve_stored_power_shatter_commandment(
            state,
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_payload=effect_payload,
            decision_source=decision_source,
        )
        return

    if target_player_id is None:
        append_event(
            state.event_log,
            "stored_power_effect_fizzled",
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="take_heavenly_from_fellow_or_shatter_commandment",
            selected_mode="take_heavenly_from_fellow",
            reason="no_heavenly_hand_target",
            decision_source=decision_source,
        )
        return

    target_player = state.players[target_player_id]
    player = state.players[player_id]
    transferred_cards: list[CardRef] = []
    for card_id in selected_card_ids:
        transferred_card = _pop_card_from_hand(target_player, card_id=card_id)
        transferred_cards.append(transferred_card)
    player.hand_cards.extend(transferred_cards)
    append_event(
        state.event_log,
        "stored_power_effect_resolved",
        player_id=player_id,
        target_player_id=target_player_id,
        phenomenon_card_id=phenomenon_card_id,
        effect_kind="take_heavenly_from_fellow_or_shatter_commandment",
        selected_mode="take_heavenly_from_fellow",
        chooser_player_id=target_player_id,
        card_choice_source=card_choice_source,
        transferred_card_ids=[card.card_id for card in transferred_cards],
        transferred_count=len(transferred_cards),
        player_hand_size_after=len(player.hand_cards),
        target_hand_size_after=len(target_player.hand_cards),
        decision_source=decision_source,
    )


def _resolve_stored_power_tornado(
    state: GameState,
    *,
    player_id: str,
    phenomenon_card_id: str,
    effect_payload: dict[str, Any] | None = None,
    decision_source: str | None,
) -> None:
    opponent_ids = _get_opponent_player_ids_in_turn_order(state, player_id=player_id)
    if not opponent_ids:
        append_event(
            state.event_log,
            "stored_power_effect_fizzled",
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="all_fellows_discard_and_draw",
            reason="no_opponents",
            decision_source=decision_source,
        )
        return

    raw_target_truth_draws = (effect_payload or {}).get("target_truth_draws", {})
    if raw_target_truth_draws is None:
        raw_target_truth_draws = {}
    if not isinstance(raw_target_truth_draws, dict):
        raise ValueError(f"Stored power {phenomenon_card_id} target_truth_draws must be a dict when provided.")
    target_truth_draws: dict[str, list[int]] = {}
    for target_player_id, raw_truth_values in raw_target_truth_draws.items():
        if target_player_id not in opponent_ids:
            raise ValueError(f"Stored power {phenomenon_card_id} received unknown tornado target {target_player_id}.")
        if not isinstance(raw_truth_values, list) or not all(isinstance(value, int) for value in raw_truth_values):
            raise ValueError(
                f"Stored power {phenomenon_card_id} target_truth_draws[{target_player_id}] must be a list of integers."
            )
        if len(raw_truth_values) > 2:
            raise ValueError(
                f"Stored power {phenomenon_card_id} target_truth_draws[{target_player_id}] may contain at most 2 truth values."
            )
        target_truth_draws[target_player_id] = list(raw_truth_values)

    for target_player_id in opponent_ids:
        target_player = state.players[target_player_id]
        discarded_count = 0
        while target_player.hand_cards:
            discarded_card = target_player.hand_cards.pop(0)
            _discard_forced_hand_card(
                state,
                player_id=target_player_id,
                card=discarded_card,
            )
            discarded_count += 1
        truth_values = target_truth_draws.get(target_player_id, [])
        prepared_truth_cards, drawn_cards = _refill_hand_to_size_with_optional_truth(
            state,
            player_id=target_player_id,
            target_hand_size=3,
            truth_values=truth_values,
            truth_source="stored-phenomenon-tornado",
        )
        append_event(
            state.event_log,
            "stored_power_effect_target_resolved",
            player_id=player_id,
            target_player_id=target_player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="all_fellows_discard_and_draw",
            discarded_count=discarded_count,
            truth_values=truth_values,
            prepared_truth_card_ids=[card.card_id for card in prepared_truth_cards],
            drawn_count=len(drawn_cards),
            drawn_card_ids=[card.card_id for card in drawn_cards],
            target_hand_size_after=len(target_player.hand_cards),
            decision_source=decision_source,
        )

    append_event(
        state.event_log,
        "stored_power_effect_resolved",
        player_id=player_id,
        phenomenon_card_id=phenomenon_card_id,
        effect_kind="all_fellows_discard_and_draw",
        target_player_ids=opponent_ids,
        decision_source=decision_source,
    )


def _resolve_stored_power_tsunami(
    state: GameState,
    *,
    player_id: str,
    phenomenon_card_id: str,
    effect_payload: dict[str, Any],
    decision_source: str | None,
) -> None:
    target_player_id = _resolve_stored_power_target_player_id_with_predicate(
        state,
        source_player_id=player_id,
        effect_payload=effect_payload,
        effect_label=phenomenon_card_id,
        predicate=lambda candidate_player: any(candidate_player.assigned_role_meeples.get(role_type, 0) > 0 for role_type in ROLE_TYPES)
        or candidate_player.nunnery_state.prepared_nuns > 0,
    )
    if target_player_id is None:
        append_event(
            state.event_log,
            "stored_power_effect_fizzled",
            player_id=player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="fellow_sacrifice_all_from_chosen_temple",
            reason="no_temple_target",
            decision_source=decision_source,
        )
        return

    target_player = state.players[target_player_id]
    _sync_role_slot_assignments(state, player_id=target_player_id)
    role_options = [
        role_type
        for role_type in ROLE_TYPES
        if target_player.assigned_role_meeples.get(role_type, 0) > 0
        or (role_type == "Nonnen" and target_player.nunnery_state.prepared_nuns > 0)
    ]
    if not role_options:
        append_event(
            state.event_log,
            "stored_power_effect_fizzled",
            player_id=player_id,
            target_player_id=target_player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="fellow_sacrifice_all_from_chosen_temple",
            reason="target_has_no_temple_meeples",
            decision_source=decision_source,
        )
        return

    raw_role_type = effect_payload.get("temple_role_type")
    if raw_role_type is not None and not isinstance(raw_role_type, str):
        raise ValueError(f"Stored power {phenomenon_card_id} temple_role_type must be a string.")
    if raw_role_type is not None and raw_role_type not in role_options:
        raise ValueError(f"Stored power {phenomenon_card_id} cannot target temple {raw_role_type} on player {target_player_id}.")
    role_type = raw_role_type or role_options[0]

    requested_role_meeples = target_player.assigned_role_meeples.get(role_type, 0)
    requested_prepared_nuns = target_player.nunnery_state.prepared_nuns if role_type == "Nonnen" else 0
    if role_type == "Nonnen":
        requested_role_meeples = max(requested_role_meeples, requested_prepared_nuns)
    requested_total = requested_role_meeples + requested_prepared_nuns
    if _player_has_temple_loss_protection_relic(state, player_id=target_player_id):
        append_event(
            state.event_log,
            "stored_power_effect_resolved",
            player_id=player_id,
            target_player_id=target_player_id,
            phenomenon_card_id=phenomenon_card_id,
            effect_kind="fellow_sacrifice_all_from_chosen_temple",
            temple_role_type=role_type,
            requested_sacrifice_total=requested_total,
            effective_sacrifice_total=requested_total,
            removed_role_meeples=0,
            removed_prepared_nuns=0,
            total_removed=0,
            target_role_assignments_after=dict(target_player.assigned_role_meeples),
            target_prepared_nuns_after=target_player.nunnery_state.prepared_nuns,
            decision_source="temple_protected",
        )
        return
    effective_total = _apply_sacrifice_cost_reduction(
        state,
        player_id=target_player_id,
        amount=requested_total,
    )

    removed_role_meeples = min(requested_role_meeples, effective_total)
    target_player.assigned_role_meeples[role_type] = max(0, requested_role_meeples - removed_role_meeples)
    removed_prepared_nuns = 0
    if role_type == "Nonnen":
        unprepared_nuns = max(0, requested_role_meeples - requested_prepared_nuns)
        removed_prepared_nuns = max(0, removed_role_meeples - unprepared_nuns)
        target_player.nunnery_state.prepared_nuns = max(0, requested_prepared_nuns - removed_prepared_nuns)
        target_player.nunnery_state.sacrificed_nuns += removed_prepared_nuns

    total_removed = removed_role_meeples + removed_prepared_nuns
    append_event(
        state.event_log,
        "stored_power_effect_resolved",
        player_id=player_id,
        target_player_id=target_player_id,
        phenomenon_card_id=phenomenon_card_id,
        effect_kind="fellow_sacrifice_all_from_chosen_temple",
        temple_role_type=role_type,
        requested_sacrifice_total=requested_total,
        effective_sacrifice_total=effective_total,
        removed_role_meeples=removed_role_meeples,
        removed_prepared_nuns=removed_prepared_nuns,
        total_removed=total_removed,
        target_role_assignments_after=dict(target_player.assigned_role_meeples),
        target_prepared_nuns_after=target_player.nunnery_state.prepared_nuns,
        decision_source=decision_source,
    )


def _infer_monument_part_from_card_id(card_id: str) -> int | None:
    match = re.search(r"-(\d{2})__Monument__", card_id)
    if match is None:
        return None
    raw_part = int(match.group(1))
    return raw_part if raw_part in {1, 2, 3} else None


def _collect_player_monument_group_keys(player: PlayerState) -> set[str]:
    return {
        _get_monument_group_key_from_card(card)
        for card in player.tableau
        if card.category == "Monument"
        and _get_monument_starter_player_id(card, fallback_owner_id=player.player_id) == player.player_id
    }


def _monument_group_key_from_card_id(card_id: str) -> str:
    raw_key = card_id.split("__", 1)[0]
    match = MONUMENT_GROUP_SUFFIX_PATTERN.search(raw_key)
    if match is None:
        return raw_key
    return raw_key[: match.start()]


def _resolve_stored_power_target_player_id(
    state: GameState,
    *,
    source_player_id: str,
    effect_payload: dict[str, Any],
    effect_label: str,
) -> str | None:
    opponent_ids = _get_opponent_player_ids_in_turn_order(state, player_id=source_player_id)
    if not opponent_ids:
        return None

    raw_target_player_id = effect_payload.get("target_player_id")
    if raw_target_player_id is not None and not isinstance(raw_target_player_id, str):
        raise ValueError(f"Stored power {effect_label} target_player_id must be a string.")
    if raw_target_player_id is not None and raw_target_player_id not in opponent_ids:
        raise ValueError(f"Stored power {effect_label} cannot target player {raw_target_player_id}.")
    return raw_target_player_id or opponent_ids[0]


def _resolve_stored_power_target_player_id_with_predicate(
    state: GameState,
    *,
    source_player_id: str,
    effect_payload: dict[str, Any],
    effect_label: str,
    predicate: Any,
) -> str | None:
    opponent_ids = _get_opponent_player_ids_in_turn_order(state, player_id=source_player_id)
    matching_opponent_ids = [
        candidate_player_id
        for candidate_player_id in opponent_ids
        if predicate(state.players[candidate_player_id])
    ]
    if not matching_opponent_ids:
        return None

    raw_target_player_id = effect_payload.get("target_player_id")
    if raw_target_player_id is not None and not isinstance(raw_target_player_id, str):
        raise ValueError(f"Stored power {effect_label} target_player_id must be a string.")
    if raw_target_player_id is not None and raw_target_player_id not in matching_opponent_ids:
        raise ValueError(f"Stored power {effect_label} cannot target player {raw_target_player_id}.")
    return raw_target_player_id or matching_opponent_ids[0]


def get_legal_prophet_target_player_ids(state: GameState, *, player_id: str) -> list[str]:
    if player_id not in state.players:
        return []
    if not state.players[player_id].prophet_owner:
        return []
    if len(state.active_commandments) >= MAX_ACTIVE_COMMANDMENTS:
        return []
    return _get_opponent_player_ids_in_turn_order(state, player_id=player_id)


def _get_opponent_player_ids_in_turn_order(state: GameState, *, player_id: str) -> list[str]:
    current_index = state.player_order.index(player_id)
    ordered_player_ids = [
        state.player_order[(current_index + offset) % len(state.player_order)]
        for offset in range(1, len(state.player_order))
    ]
    opponent_player_ids = set(get_opponent_player_ids(state, player_id=player_id))
    return [candidate_player_id for candidate_player_id in ordered_player_ids if candidate_player_id in opponent_player_ids]


def _get_hand_card_intrinsic_cost(card: CardRef) -> int:
    metadata_cost = card.metadata.get("cost_believers")
    if isinstance(metadata_cost, int):
        return metadata_cost
    record = get_card_record(card.card_id)
    if isinstance(record, dict) and isinstance(record.get("cost_believers"), int):
        return int(record["cost_believers"])
    return HAND_CARD_BASE_INTRINSIC_COSTS.get(card.category, 0)


def _get_hand_card_intrinsic_cost_before_sacrifice_reduction(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
    effect_payload: dict[str, Any] | None = None,
) -> int:
    if _is_intrinsic_cost_waived_by_tableau(state, player_id=player_id, card=card):
        return 0
    if card.category == "Reliquie" and is_card_cost_currently_waived(state, player_id=player_id, card=card):
        return 0
    if card.category == "Heiliges Heer":
        resolution = _prepare_holy_army_resolution(
            state,
            player_id=player_id,
            card=card,
            effect_payload=effect_payload,
        )
        return int(resolution["intrinsic_cost"])
    return _get_hand_card_intrinsic_cost(card)


def _get_minimum_holy_army_intrinsic_cost_before_sacrifice_reduction(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
) -> int:
    if _is_intrinsic_cost_waived_by_tableau(state, player_id=player_id, card=card):
        return 0
    profile = _get_holy_army_profile(card)
    if profile["mode"] == "schleifer":
        intrinsic_cost = 5
    else:
        own_enlighteners = [
            tableau_card
            for tableau_card in state.players[player_id].tableau
            if tableau_card.category == "Aufklärer"
        ]
        specialized_targets = [
            tableau_card
            for tableau_card in own_enlighteners
            if any(
                _holy_army_target_matches_card(tableau_card, target_fragment)
                for target_fragment in profile["specialized_targets"]
            )
        ]
        intrinsic_cost = 0 if specialized_targets else 4
    return intrinsic_cost


def _get_card_rules_text(card: CardRef) -> str:
    metadata_rules_text = card.metadata.get("rules_text")
    if isinstance(metadata_rules_text, str):
        return metadata_rules_text
    record = get_card_record(card.card_id)
    if isinstance(record, dict) and isinstance(record.get("rules_text"), str):
        return str(record["rules_text"])
    return ""


def _count_active_enlightener_rule_text(state: GameState, *, player_id: str, text: str) -> int:
    count = 0
    for card in state.players[player_id].tableau:
        if card.category != "Aufklärer":
            continue
        if is_tableau_card_disabled(state, player_id=player_id, card=card):
            continue
        if text in _get_card_rules_text(card):
            count += 1
    return count


def _count_active_relic_rule_text(state: GameState, *, player_id: str, text: str) -> int:
    return _count_active_relic_rule_fragments(state, player_id=player_id, texts=(text,))


def _count_active_relic_rule_fragments(
    state: GameState,
    *,
    player_id: str,
    texts: tuple[str, ...],
) -> int:
    return len(_active_relic_cards_with_rule_fragments(state, player_id=player_id, texts=texts))


def _active_relic_cards_with_rule_fragments(
    state: GameState,
    *,
    player_id: str,
    texts: tuple[str, ...],
) -> list[CardRef]:
    matching_cards: list[CardRef] = []
    for card in state.players[player_id].tableau:
        if card.category != "Reliquie":
            continue
        if not is_tableau_card_active(state, player_id=player_id, card=card):
            continue
        rules_text = _get_card_rules_text(card)
        if any(text in rules_text for text in texts):
            matching_cards.append(card)
    return matching_cards


def _get_active_relic_names_with_rule_fragments(
    state: GameState,
    *,
    player_id: str,
    texts: tuple[str, ...],
) -> list[str]:
    names: list[str] = []
    for card in state.players[player_id].tableau:
        if card.category != "Reliquie":
            continue
        if not is_tableau_card_active(state, player_id=player_id, card=card):
            continue
        rules_text = _get_card_rules_text(card)
        if any(text in rules_text for text in texts):
            names.append(str(card.name or card.card_id))
    return names


def _player_has_active_enlightener_rule_text(state: GameState, *, player_id: str, text: str) -> bool:
    return _count_active_enlightener_rule_text(state, player_id=player_id, text=text) > 0


def _player_has_active_relic_rule_text(state: GameState, *, player_id: str, text: str) -> bool:
    return _count_active_relic_rule_text(state, player_id=player_id, text=text) > 0


def _player_has_temple_loss_protection_relic(state: GameState, *, player_id: str) -> bool:
    return _player_has_active_relic_rule_text(
        state,
        player_id=player_id,
        text=RELIC_TEMPLES_CANNOT_LOSE_ROLE_MEEPLES_TEXT,
    )


def _get_local_hand_limit_modifier(state: GameState, *, player_id: str) -> int:
    modifier = 0
    if _player_has_defined_head(state.players[player_id]):
        modifier += 1
    modifier -= _count_active_enlightener_rule_text(
        state,
        player_id=player_id,
        text=ENLIGHTENER_REDUCES_HAND_LIMIT_TEXT,
    )
    modifier += _count_active_relic_rule_fragments(
        state,
        player_id=player_id,
        texts=(
            RELIC_EXTRA_DRAW_TEXT,
            RELIC_INCREASES_HAND_LIMIT_TEXT,
        ),
    )
    return modifier


def _is_intrinsic_cost_waived_by_tableau(state: GameState, *, player_id: str, card: CardRef) -> bool:
    if card.category == "Heiliges Heer":
        return _player_has_active_relic_rule_text(
            state,
            player_id=player_id,
            text=RELIC_WAIVES_HOLY_ARMY_COST_TEXT,
        )
    if card.category == "Aufklärer":
        return _player_has_active_relic_rule_text(
            state,
            player_id=player_id,
            text=RELIC_WAIVES_ENLIGHTENER_COST_TEXT,
        )
    return False


def _get_effective_hand_card_intrinsic_cost(state: GameState, *, player_id: str, card: CardRef) -> int:
    return _apply_sacrifice_cost_reduction(
        state,
        player_id=player_id,
        amount=_get_hand_card_intrinsic_cost_before_sacrifice_reduction(
            state,
            player_id=player_id,
            card=card,
        ),
    )


def _is_supported_blessing_card(card: CardRef) -> bool:
    return card.category == "Segen" and (
        card.name in SUPPORTED_BLESSING_CARD_NAMES
        or any(card.name.startswith(prefix) for prefix in SUPPORTED_BLESSING_NAME_PREFIXES)
    )


def _is_hand_card_action_implemented(card: CardRef) -> bool:
    if card.category in {"Heiliges Heer", "Aufklärer", "Reliquie"}:
        return True
    if card.category == "Segen":
        return _is_supported_blessing_card(card)
    return False


def _validate_hand_card_action(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
    effect_payload: dict[str, Any] | None,
) -> None:
    if not can_play_card(state, player_id=player_id, card=card):
        blocked_reason = "card is currently blocked."
        player = state.players[player_id]
        if card.category in player.commandment_state.blocked_card_categories:
            blocked_reason = f"category {card.category} is blocked by an active commandment."
        elif is_tableau_card_disabled(state, player_id=player_id, card=card):
            blocked_reason = f"category {card.category} is disabled by an active commandment."
        elif card.category == "Reliquie" and _player_has_active_enlightener_rule_text(
            state,
            player_id=player_id,
            text=ENLIGHTENER_BLOCKS_RELICS_TEXT,
        ):
            blocked_reason = "Reliquien are blocked by an active Aufklärer effect."
        raise ValueError(f"Player {player_id} cannot play card {card.card_id} right now: {blocked_reason}")
    if not _is_hand_card_action_implemented(card):
        raise ValueError(
            f"Playing hand card {card.card_id} ({card.category}) as a normal action is not implemented in the current MVP."
        )
    if effect_payload is not None and not isinstance(effect_payload, dict):
        raise ValueError(f"Effect payload for hand card {card.card_id} must be a dict.")

    if card.category == "Segen":
        _prepare_blessing_resolution(
            state,
            player_id=player_id,
            card=card,
            effect_payload=effect_payload,
        )
    if card.category == "Heiliges Heer":
        _prepare_holy_army_resolution(
            state,
            player_id=player_id,
            card=card,
            effect_payload=effect_payload,
        )


def _prepare_blessing_resolution(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
    effect_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    effect_payload = effect_payload or {}
    card_alignment = _get_card_alignment_from_card(card)
    aligned_with_player = card_alignment is not None and card_alignment == state.players[player_id].alignment

    if card.name == "Gloria":
        draw_count = 2 if aligned_with_player else 1
        explicit_truth_values = effect_payload.get("truth_values")
        if explicit_truth_values is None:
            truth_values = _get_default_gloria_truth_values(
                state,
                player_id=player_id,
                count=draw_count,
            )
        else:
            if not isinstance(explicit_truth_values, list) or not all(
                isinstance(value, int) for value in explicit_truth_values
            ):
                raise ValueError("Gloria requires truth_values as a list of integers.")
            if len(explicit_truth_values) != draw_count:
                raise ValueError(
                    f"Gloria for player {player_id} requires exactly {draw_count} truth values in this alignment state."
                )
            truth_values = list(explicit_truth_values)

        _validate_truth_values_can_be_prepared(state, player_id=player_id, truth_values=truth_values)
        return {
            "effect_name": "Gloria",
            "card_alignment": card_alignment,
            "aligned_with_player": aligned_with_player,
            "truth_values": truth_values,
        }

    if card.name == "Klagelied":
        return {
            "effect_name": "Klagelied",
            "card_alignment": card_alignment,
            "aligned_with_player": aligned_with_player,
            "sacrifice_amount": 3 if aligned_with_player else 2,
        }

    if card.name == "Huldigung":
        return {
            "effect_name": "Huldigung",
            "card_alignment": card_alignment,
            "aligned_with_player": aligned_with_player,
            "hand_limit_override": 10 if aligned_with_player else 9,
        }

    if card.name == "Loblied":
        return {
            "effect_name": "Loblied",
            "card_alignment": card_alignment,
            "aligned_with_player": aligned_with_player,
            "reward_amount": 4 if aligned_with_player else 3,
        }

    if card.name == "Wahrsagung":
        reveal_count = 4 if aligned_with_player else 3
        preview_cards = state.phenomenon_draw_pile[:reveal_count]
        preview_ids = [preview_card.card_id for preview_card in preview_cards]
        reordered_card_ids = effect_payload.get("reordered_card_ids")
        if reordered_card_ids is None:
            reordered_ids = list(preview_ids)
        else:
            if not isinstance(reordered_card_ids, list) or not all(
                isinstance(candidate_card_id, str) for candidate_card_id in reordered_card_ids
            ):
                raise ValueError("Wahrsagung requires reordered_card_ids as a list of card ids.")
            if sorted(reordered_card_ids) != sorted(preview_ids):
                raise ValueError(
                    f"Wahrsagung for player {player_id} must reorder exactly the currently revealed phenomenon ids."
                )
            reordered_ids = list(reordered_card_ids)

        return {
            "effect_name": "Wahrsagung",
            "card_alignment": card_alignment,
            "aligned_with_player": aligned_with_player,
            "preview_ids": preview_ids,
            "reordered_ids": reordered_ids,
        }

    if card.name.startswith("Mantra"):
        target_player_id = effect_payload.get("target_player_id")
        if target_player_id is None:
            eligible_target_player_ids = _get_mantra_target_player_ids(state, player_id=player_id)
            if not eligible_target_player_ids:
                raise ValueError(f"Player {player_id} cannot resolve {card.name}; no opponent has truth available.")
            target_player_id = eligible_target_player_ids[0]
        if not isinstance(target_player_id, str):
            raise ValueError("Mantra requires target_player_id as a string when provided.")
        if target_player_id == player_id:
            raise ValueError("Mantra must target a different player.")
        if target_player_id not in state.players:
            raise ValueError(f"Unknown Mantra target player {target_player_id}.")

        available_truth_values = _get_mantra_available_truth_values(state, target_player_id=target_player_id)
        if not available_truth_values:
            raise ValueError(f"Player {target_player_id} has no truth available for Mantra.")

        explicit_truth_value = effect_payload.get("truth_value")
        if explicit_truth_value is None:
            truth_value = max(available_truth_values)
        else:
            if not isinstance(explicit_truth_value, int):
                raise ValueError("Mantra requires truth_value as an integer when provided.")
            truth_value = explicit_truth_value
        if truth_value not in available_truth_values:
            raise ValueError(
                f"Player {target_player_id} does not currently have truth value {truth_value} available for Mantra."
            )

        return {
            "effect_name": "Mantra",
            "card_alignment": card_alignment,
            "aligned_with_player": aligned_with_player,
            "target_player_id": target_player_id,
            "truth_value": truth_value,
        }

    if card.name.startswith("Preisung"):
        return {
            "effect_name": "Preisung",
            "card_alignment": card_alignment,
            "aligned_with_player": aligned_with_player,
        }

    raise ValueError(f"Blessing {card.card_id} ({card.name}) is not implemented in the current MVP.")


def _resolve_blessing_play(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
    effect_payload: dict[str, Any] | None,
) -> None:
    resolution = _prepare_blessing_resolution(
        state,
        player_id=player_id,
        card=card,
        effect_payload=effect_payload,
    )
    player = state.players[player_id]

    append_event(
        state.event_log,
        "blessing_resolved",
        player_id=player_id,
        card_id=card.card_id,
        card_name=card.name,
        card_alignment=resolution["card_alignment"],
        aligned_with_player=resolution["aligned_with_player"],
        effect_name=resolution["effect_name"],
    )

    blessing_bonus_relics = _active_relic_cards_with_rule_fragments(
        state,
        player_id=player_id,
        texts=(RELIC_BLESSING_BAPTISM_TEXT,),
    )
    blessing_bonus = 2 * len(blessing_bonus_relics)
    if blessing_bonus > 0:
        player.meeples += blessing_bonus
        append_event(
            state.event_log,
            "relic_blessing_bonus_applied",
            player_id=player_id,
            card_id=card.card_id,
            blessing_bonus=blessing_bonus,
            relic_card_ids=[relic.card_id for relic in blessing_bonus_relics],
            relic_card_names=[relic.name for relic in blessing_bonus_relics],
            meeples_after=player.meeples,
        )

    if resolution["effect_name"] == "Gloria":
        prepared_cards = _add_truth_cards_to_hand(
            state,
            player_id=player_id,
            truth_values=resolution["truth_values"],
            source="blessing-gloria",
        )
        append_event(
            state.event_log,
            "blessing_gloria_resolved",
            player_id=player_id,
            card_id=card.card_id,
            truth_values=resolution["truth_values"],
            prepared_truth_card_ids=[prepared_card.card_id for prepared_card in prepared_cards],
        )
        return

    if resolution["effect_name"] == "Klagelied":
        sacrifice_amount = resolution["sacrifice_amount"]
        _validate_free_believer_target_payments(
            state, player_id=player_id, effect_payload=effect_payload or {}, context="Klagelied",
        )
        affected_player_ids: list[str] = []
        for other_player_id in _get_opponent_player_ids_in_turn_order(state, player_id=player_id):
            other_player = state.players[other_player_id]
            effective_sacrifice_amount = _apply_sacrifice_cost_reduction(
                state,
                player_id=other_player_id,
                amount=sacrifice_amount,
            )
            payment_resolution = _spend_player_meeples(
                state,
                player_id=other_player_id,
                amount=effective_sacrifice_amount,
                strict=False,
                payment_choice=None,
                purpose="blessing_klagelied",
            )
            affected_player_ids.append(other_player_id)
            append_event(
                state.event_log,
                "blessing_klagelied_applied",
                player_id=player_id,
                target_player_id=other_player_id,
                card_id=card.card_id,
                sacrifice_amount=sacrifice_amount,
                effective_sacrifice_amount=effective_sacrifice_amount,
                actual_sacrifice=payment_resolution["paid_total"],
                free_meeples_paid=payment_resolution["free_meeples_paid"],
                role_meeples_paid=dict(payment_resolution["role_meeples_paid"]),
                prepared_nuns_paid=payment_resolution["prepared_nuns_paid"],
                meeples_after=other_player.meeples,
            )
        append_event(
            state.event_log,
            "blessing_klagelied_resolved",
            player_id=player_id,
            card_id=card.card_id,
            sacrifice_amount=sacrifice_amount,
            affected_player_ids=affected_player_ids,
        )
        return

    if resolution["effect_name"] == "Huldigung":
        player.temporary_draw_hand_limit_override = resolution["hand_limit_override"]
        append_event(
            state.event_log,
            "blessing_huldigung_resolved",
            player_id=player_id,
            card_id=card.card_id,
            hand_limit_override=resolution["hand_limit_override"],
        )
        return

    if resolution["effect_name"] == "Loblied":
        player.meeples += resolution["reward_amount"]
        append_event(
            state.event_log,
            "blessing_loblied_resolved",
            player_id=player_id,
            card_id=card.card_id,
            reward_amount=resolution["reward_amount"],
            reward_source="heathen_pile",
            meeples_after=player.meeples,
        )
        return

    if resolution["effect_name"] == "Wahrsagung":
        preview_ids = resolution["preview_ids"]
        reordered_ids = resolution["reordered_ids"]
        preview_cards = state.phenomenon_draw_pile[:len(preview_ids)]
        preview_by_id = {preview_card.card_id: preview_card for preview_card in preview_cards}
        reordered_preview_cards = [preview_by_id[card_id] for card_id in reordered_ids]
        state.phenomenon_draw_pile = reordered_preview_cards + state.phenomenon_draw_pile[len(preview_ids):]
        append_event(
            state.event_log,
            "blessing_wahrsagung_resolved",
            player_id=player_id,
            card_id=card.card_id,
            revealed_card_ids=preview_ids,
            reordered_card_ids=reordered_ids,
        )
        return

    if resolution["effect_name"] == "Mantra":
        target_player_id = resolution["target_player_id"]
        truth_value = resolution["truth_value"]
        _maybe_reset_truth_after_exhaustion(state, player_id=target_player_id)
        discarded_truth_card = make_truth_card(
            truth_value,
            card_id=f"mantra-discard-{target_player_id}-{state.turn_number}-{len(state.players[target_player_id].truth_discard)}-{truth_value}",
            metadata={
                "source": "blessing-mantra",
                "owner_player_id": target_player_id,
                "discarded_by_player_id": player_id,
            },
        )
        _discard_truth_value_to_discard(
            state,
            player_id=target_player_id,
            value=truth_value,
            discard_card=discarded_truth_card,
        )
        append_event(
            state.event_log,
            "blessing_mantra_resolved",
            player_id=player_id,
            card_id=card.card_id,
            target_player_id=target_player_id,
            truth_value=truth_value,
            discarded_truth_card_id=discarded_truth_card.card_id,
        )
        return

    if resolution["effect_name"] == "Preisung":
        restored_truth_card_ids = [discarded_card.card_id for discarded_card in player.truth_discard]
        reset_truth(state, player_id=player_id)
        append_event(
            state.event_log,
            "blessing_preisung_resolved",
            player_id=player_id,
            card_id=card.card_id,
            restored_truth_card_ids=restored_truth_card_ids,
            truth_pool=list(player.truth_pool),
        )
        return


def _resolve_enlightener_play(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
    effect_payload: dict[str, Any] | None,
) -> int:
    player = state.players[player_id]
    effect_payload = effect_payload or {}
    target_player_id = effect_payload.get("target_player_id")
    if target_player_id is not None and not isinstance(target_player_id, str):
        raise ValueError(f"Aufklärer {card.card_id} requires target_player_id as a string when provided.")
    legal_target_player_ids = get_legal_enlightener_target_player_ids(state, player_id=player_id)
    if not legal_target_player_ids:
        raise ValueError(f"Player {player_id} has no legal opponent target for Aufklärer {card.card_id}.")
    resolved_target_player_id = target_player_id or legal_target_player_ids[0]
    if resolved_target_player_id not in legal_target_player_ids:
        raise ValueError(
            f"Player {player_id} cannot target {resolved_target_player_id} with Aufklärer {card.card_id}."
        )
    target_player = state.players[resolved_target_player_id]
    base_intrinsic_cost = _get_hand_card_intrinsic_cost_before_sacrifice_reduction(
        state,
        player_id=player_id,
        card=card,
    )
    intrinsic_cost = _get_effective_hand_card_intrinsic_cost(state, player_id=player_id, card=card)
    if intrinsic_cost > player.meeples:
        payment_choice = effect_payload.get("intrinsic_cost_payment_choice", {})
        normalized_payment_choice = _normalize_meeple_payment_choice(
            payment_choice,
            context=f"Aufklärer {card.card_id} intrinsic_cost_payment_choice",
        )
        if player.meeples + _count_bound_meeples_in_payment_choice(normalized_payment_choice) < intrinsic_cost:
            raise ValueError(
                f"Player {player_id} cannot play Aufklärer {card.card_id}; intrinsic cost {intrinsic_cost} exceeds available meeples {player.meeples}."
            )

    if intrinsic_cost > 0:
        payment_resolution = _spend_player_meeples(
            state,
            player_id=player_id,
            amount=intrinsic_cost,
            strict=True,
            payment_choice=effect_payload.get("intrinsic_cost_payment_choice"),
            purpose="enlightener_intrinsic_cost",
        )
        append_event(
            state.event_log,
            "hand_card_intrinsic_cost_paid",
            player_id=player_id,
            card_id=card.card_id,
            card_name=card.name,
            category=card.category,
            intrinsic_cost=intrinsic_cost,
            **_sacrifice_cost_reduction_event_fields(
                state,
                player_id=player_id,
                base_amount=base_intrinsic_cost,
                effective_amount=intrinsic_cost,
                prefix="intrinsic_cost",
            ),
            free_meeples_paid=payment_resolution["free_meeples_paid"],
            role_meeples_paid=dict(payment_resolution["role_meeples_paid"]),
            prepared_nuns_paid=payment_resolution["prepared_nuns_paid"],
            meeples_after=player.meeples,
        )

    immunity_resolution = _consume_relic_immunity_against_next_enlightener(
        state,
        source_player_id=player_id,
        target_player_id=resolved_target_player_id,
    )
    if immunity_resolution is not None:
        protected_player_id, consumed_relic = immunity_resolution
        state.heavenly_discard_pile.append(card)
        recalculate_commandment_effects(state)
        append_event(
            state.event_log,
            "enlightener_play_negated_by_relic_immunity",
            player_id=player_id,
            card_id=card.card_id,
            card_name=card.name,
            protected_player_id=protected_player_id,
            consumed_relic_card_id=consumed_relic.card_id,
            consumed_relic_card_name=consumed_relic.name,
            heavenly_discard_pile_size=len(state.heavenly_discard_pile),
        )
        return intrinsic_cost

    card.metadata = dict(card.metadata)
    card.metadata["played_by_player_id"] = player_id
    card.metadata["attached_to_player_id"] = resolved_target_player_id
    target_player.tableau.append(card)
    recalculate_commandment_effects(state)
    append_event(
        state.event_log,
        "tableau_card_placed",
        player_id=resolved_target_player_id,
        source_player_id=player_id,
        card_id=card.card_id,
        card_name=card.name,
        category=card.category,
        slot_kind="enlighteners",
        slot_occupancy=_get_slot_occupancy(target_player, slot_kind="enlighteners"),
        slot_limit=_get_slot_limit(target_player, slot_kind="enlighteners"),
    )
    _apply_friedrich_alignment_override_if_active(state, player_id=resolved_target_player_id)
    return intrinsic_cost


def _can_receive_enlightener(
    state: GameState,
    *,
    source_player_id: str,
    target_player_id: str,
) -> bool:
    if target_player_id == source_player_id:
        return False
    if target_player_id not in state.players:
        return False
    target_player = state.players[target_player_id]
    if _has_relic_immunity_against_next_enlightener(state, protected_player_id=target_player_id):
        return True
    return _has_free_slot(target_player, slot_kind="enlighteners")


def _get_schleifer_target_entries(
    state: GameState,
    *,
    player_id: str,
) -> list[dict[str, Any]]:
    if player_id not in state.players:
        return []
    entries: list[dict[str, Any]] = []
    opponent_player_ids = set(_get_opponent_player_ids_in_turn_order(state, player_id=player_id))
    for source_player_id in state.player_order:
        source_player = state.players[source_player_id]
        for tableau_card in source_player.tableau:
            if tableau_card.category != "Aufklärer":
                continue
            destination_options: list[dict[str, Any]] = []
            for candidate_player_id in state.player_order:
                if candidate_player_id not in opponent_player_ids:
                    continue
                enabled = _can_receive_enlightener(
                    state,
                    source_player_id=source_player_id,
                    target_player_id=candidate_player_id,
                )
                reason = ""
                if not enabled:
                    if candidate_player_id == source_player_id:
                        reason = "Aufklärer muss den Spieler wechseln."
                    else:
                        reason = "Aufklärer-Slots voll."
                destination_options.append(
                    {
                        "player_id": candidate_player_id,
                        "enabled": enabled,
                        "reason": reason,
                    }
                )
            destination_player_ids = [
                str(option["player_id"])
                for option in destination_options
                if bool(option.get("enabled"))
            ]
            entries.append(
                {
                    "source_player_id": source_player_id,
                    "target_card_id": tableau_card.card_id,
                    "destination_player_ids": destination_player_ids,
                    "destination_options": destination_options,
                }
            )
    return entries


def _player_has_free_enlightener_slot(state: GameState, *, player_id: str) -> bool:
    # Slots belong to the tableau receiving the card, regardless of who played it.
    return _has_free_slot(state.players[player_id], slot_kind="enlighteners")


def _has_relic_immunity_against_next_enlightener(
    state: GameState,
    *,
    protected_player_id: str,
) -> bool:
    return _find_relic_immunity_against_next_enlightener(
        state,
        protected_player_id=protected_player_id,
    ) is not None


def _find_relic_immunity_against_next_enlightener(
    state: GameState,
    *,
    protected_player_id: str,
) -> CardRef | None:
    protected_player = state.players[protected_player_id]
    for candidate_relic in protected_player.tableau:
        if candidate_relic.category != "Reliquie":
            continue
        if not is_tableau_card_active(state, player_id=protected_player_id, card=candidate_relic):
            continue
        rules_text = _get_card_rules_text(candidate_relic)
        if (
            RELIC_IMMUNE_NEXT_ENLIGHTENER_TEXT not in rules_text
            and RELIC_IMMUNE_NEXT_ENLIGHTENER_BEFORE_PLACEMENT_TEXT not in rules_text
            and RELIC_DISCARD_NEXT_INCOMING_ENLIGHTENER_TEXT not in rules_text
        ):
            continue
        return candidate_relic
    return None


def _consume_relic_immunity_against_next_enlightener(
    state: GameState,
    *,
    source_player_id: str,
    target_player_id: str,
) -> tuple[str, CardRef] | None:
    if target_player_id == source_player_id:
        return None
    protected_player = state.players[target_player_id]
    candidate_relic = _find_relic_immunity_against_next_enlightener(
        state,
        protected_player_id=target_player_id,
    )
    if candidate_relic is None:
        return None
    consumed_relic = _pop_card_from_tableau(protected_player, card_id=candidate_relic.card_id)
    state.heavenly_discard_pile.append(consumed_relic)
    return target_player_id, consumed_relic


def _resolve_relic_play(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
    effect_payload: dict[str, Any] | None,
) -> int:
    effect_payload = effect_payload or {}
    player = state.players[player_id]
    base_intrinsic_cost = _get_hand_card_intrinsic_cost_before_sacrifice_reduction(
        state,
        player_id=player_id,
        card=card,
    )
    intrinsic_cost = _get_effective_hand_card_intrinsic_cost(state, player_id=player_id, card=card)
    if intrinsic_cost > player.meeples:
        payment_choice = effect_payload.get("intrinsic_cost_payment_choice", {})
        normalized_payment_choice = _normalize_meeple_payment_choice(
            payment_choice,
            context=f"Reliquie {card.card_id} intrinsic_cost_payment_choice",
        )
        if player.meeples + _count_bound_meeples_in_payment_choice(normalized_payment_choice) < intrinsic_cost:
            raise ValueError(
                f"Player {player_id} cannot play Reliquie {card.card_id}; intrinsic cost {intrinsic_cost} exceeds available meeples {player.meeples}."
            )

    own_relics = [tableau_card for tableau_card in player.tableau if tableau_card.category == "Reliquie"]
    replaced_card_id = effect_payload.get("replaced_card_id")
    if replaced_card_id is not None and not isinstance(replaced_card_id, str):
        raise ValueError("Reliquie requires replaced_card_id as a string when provided.")

    replacing_existing_relic = False
    replaced_card: CardRef | None = None
    if not _has_free_slot(player, slot_kind="relics"):
        if not own_relics:
            raise ValueError(f"Player {player_id} cannot play Reliquie {card.card_id}; no reliquie slot is free.")
        if replaced_card_id is None:
            if len(own_relics) != 1:
                raise ValueError(
                    f"Player {player_id} must specify replaced_card_id when multiple own Reliquien can be overwritten."
                )
            replaced_card_id = own_relics[0].card_id
        replaced_card = next((tableau_card for tableau_card in own_relics if tableau_card.card_id == replaced_card_id), None)
        if replaced_card is None:
            raise ValueError(f"Player {player_id} can only overwrite own Reliquien with a new Reliquie.")
        replacing_existing_relic = True
    elif replaced_card_id is not None:
        raise ValueError("replaced_card_id is only valid when all Reliquien slots are occupied.")

    if intrinsic_cost > 0:
        payment_resolution = _spend_player_meeples(
            state,
            player_id=player_id,
            amount=intrinsic_cost,
            strict=True,
            payment_choice=effect_payload.get("intrinsic_cost_payment_choice"),
            purpose="relic_intrinsic_cost",
        )
        append_event(
            state.event_log,
            "hand_card_intrinsic_cost_paid",
            player_id=player_id,
            card_id=card.card_id,
            card_name=card.name,
            category=card.category,
            intrinsic_cost=intrinsic_cost,
            **_sacrifice_cost_reduction_event_fields(
                state,
                player_id=player_id,
                base_amount=base_intrinsic_cost,
                effective_amount=intrinsic_cost,
                prefix="intrinsic_cost",
            ),
            free_meeples_paid=payment_resolution["free_meeples_paid"],
            role_meeples_paid=dict(payment_resolution["role_meeples_paid"]),
            prepared_nuns_paid=payment_resolution["prepared_nuns_paid"],
            meeples_after=player.meeples,
        )

    if replaced_card is not None:
        removed_relic = _pop_card_from_tableau(player, card_id=replaced_card.card_id)
        state.heavenly_discard_pile.append(removed_relic)
        append_event(
            state.event_log,
            "relic_overwritten",
            player_id=player_id,
            card_id=card.card_id,
            replaced_card_id=removed_relic.card_id,
            replaced_card_name=removed_relic.name,
            heavenly_discard_pile_size=len(state.heavenly_discard_pile),
        )

    card.metadata = dict(card.metadata)
    player.tableau.append(card)
    recalculate_commandment_effects(state)
    append_event(
        state.event_log,
        "tableau_card_placed",
        player_id=player_id,
        card_id=card.card_id,
        card_name=card.name,
        category=card.category,
        slot_kind="relics",
        replaced_existing=replacing_existing_relic,
        slot_occupancy=_get_slot_occupancy(player, slot_kind="relics"),
        slot_limit=_get_slot_limit(player, slot_kind="relics"),
    )
    if is_tableau_card_active(state, player_id=player_id, card=card) and not _relic_resolves_during_tableau(card):
        _resolve_relic_on_play_effect(
            state,
            player_id=player_id,
            card=card,
            effect_payload=effect_payload,
        )
    return intrinsic_cost


def _relic_resolves_during_tableau(card: CardRef) -> bool:
    rules_text = _get_card_rules_text(card)
    if "Beim Abhandeln:" not in rules_text:
        return False
    return (
        RELIC_RECOVER_SHUFFLED_TOP_THREE_HEAVENLY_FROM_DISCARD_TEXT in rules_text
        or _rules_text_has_nasenhaar_truth_draw(rules_text)
        or RELIC_SWAP_HEAVENLY_HAND_CARDS_TEXT in rules_text
        or RELIC_MISSIONIZE_PER_AFFECTING_COMMANDMENT_TEXT in rules_text
        or RELIC_OPPONENT_CHOICE_DISCARD_OR_BAPTISM_TEXT in rules_text
    )


def _rules_text_has_nasenhaar_truth_draw(rules_text: str) -> bool:
    return (
        RELIC_DRAW_TRUTH_AFTER_THREE_HAND_DISCARDS_TEXT in rules_text
        or RELIC_DRAW_TRUTH_AFTER_THREE_HAND_DISCARDS_VARIANT_TEXT in rules_text
    )


def _resolve_relic_tableau_effect(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
    effect_intent: dict[str, Any] | None,
) -> None:
    if not _relic_resolves_during_tableau(card):
        return
    rules_text = _get_card_rules_text(card)
    if RELIC_RECOVER_SHUFFLED_TOP_THREE_HEAVENLY_FROM_DISCARD_TEXT in rules_text:
        _resolve_relic_recover_heavenly_from_discard_top_three(
            state,
            player_id=player_id,
            card=card,
            effect_payload=effect_intent,
            event_type="relic_tableau_effect_resolved",
        )
    elif _rules_text_has_nasenhaar_truth_draw(rules_text):
        _resolve_relic_draw_truth_after_three_hand_discards(
            state,
            player_id=player_id,
            card=card,
            effect_payload=effect_intent,
            event_type="relic_tableau_effect_resolved",
        )
    elif RELIC_SWAP_HEAVENLY_HAND_CARDS_TEXT in rules_text:
        _resolve_relic_swap_heavenly_hand_cards(
            state,
            player_id=player_id,
            card=card,
            effect_payload=effect_intent,
            event_type="relic_tableau_effect_resolved",
        )
    elif RELIC_MISSIONIZE_PER_AFFECTING_COMMANDMENT_TEXT in rules_text:
        _resolve_relic_missionize_per_affecting_commandment(
            state,
            player_id=player_id,
            card=card,
            effect_payload=effect_intent,
            event_type="relic_tableau_effect_resolved",
        )
    elif RELIC_OPPONENT_CHOICE_DISCARD_OR_BAPTISM_TEXT in rules_text:
        _resolve_relic_opponent_choice_discard_or_baptism(
            state,
            player_id=player_id,
            card=card,
            effect_payload=effect_intent,
            event_type="relic_tableau_effect_resolved",
        )


def _resolve_relic_on_play_effect(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
    effect_payload: dict[str, Any] | None,
) -> None:
    rules_text = _get_card_rules_text(card)
    if RELIC_RECOVER_SHUFFLED_TOP_THREE_HEAVENLY_FROM_DISCARD_TEXT in rules_text:
        _resolve_relic_recover_heavenly_from_discard_top_three(
            state,
            player_id=player_id,
            card=card,
            effect_payload=effect_payload,
            event_type="relic_on_play_effect_resolved",
        )
    elif (
        RELIC_RECOVER_HEAVENLY_FROM_DISCARD_TEXT in rules_text
        or RELIC_RECOVER_TOP_HEAVENLY_FROM_DISCARD_TEXT in rules_text
    ):
        _resolve_relic_recover_heavenly_from_discard(state, player_id=player_id, card=card)
    if RELIC_SWAP_HEAVENLY_HAND_CARDS_TEXT in rules_text:
        _resolve_relic_swap_heavenly_hand_cards(
            state,
            player_id=player_id,
            card=card,
            effect_payload=effect_payload,
        )
    if RELIC_OPPONENT_CHOICE_DISCARD_OR_BAPTISM_TEXT in rules_text:
        _resolve_relic_opponent_choice_discard_or_baptism(
            state,
            player_id=player_id,
            card=card,
            effect_payload=effect_payload,
        )


def _resolve_relic_recover_heavenly_from_discard(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
) -> None:
    if not state.heavenly_discard_pile:
        append_event(
            state.event_log,
            "relic_on_play_effect_resolved",
            player_id=player_id,
            card_id=card.card_id,
            effect_kind="recover_heavenly_from_discard",
            recovered_card_id=None,
            recovered_card_name=None,
            decision_source="no_heavenly_discard_cards",
            hand_size_after=len(state.players[player_id].hand_cards),
            heavenly_discard_pile_size=0,
        )
        return

    recovered_card = state.heavenly_discard_pile.pop(0)
    state.players[player_id].hand_cards.append(recovered_card)
    append_event(
        state.event_log,
        "relic_on_play_effect_resolved",
        player_id=player_id,
        card_id=card.card_id,
        effect_kind="recover_heavenly_from_discard",
        recovered_card_id=recovered_card.card_id,
        recovered_card_name=recovered_card.name,
        decision_source="auto_policy",
        hand_size_after=len(state.players[player_id].hand_cards),
        heavenly_discard_pile_size=len(state.heavenly_discard_pile),
    )


def _resolve_relic_recover_heavenly_from_discard_top_three(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
    effect_payload: dict[str, Any] | None,
    event_type: str = "relic_on_play_effect_resolved",
) -> None:
    if not state.heavenly_discard_pile:
        append_event(
            state.event_log,
            event_type,
            player_id=player_id,
            card_id=card.card_id,
            effect_kind="recover_heavenly_from_discard_top_two",
            preview_card_ids=[],
            recovered_card_id=None,
            recovered_card_name=None,
            decision_source="no_heavenly_discard_cards",
            hand_size_after=len(state.players[player_id].hand_cards),
            heavenly_discard_pile_size=0,
        )
        return

    shuffled_discard = _shuffle_relic_recovery_discard_pile(state, player_id=player_id, card=card)
    preview_cards = shuffled_discard[:2]
    preview_card_ids = [preview_card.card_id for preview_card in preview_cards]

    payload = effect_payload or {}
    raw_target_card_id = payload.get("target_card_id")
    if raw_target_card_id is not None and not isinstance(raw_target_card_id, str):
        raise ValueError(f"Reliquie {card.card_id} target_card_id must be a string.")
    if raw_target_card_id is not None and raw_target_card_id not in preview_card_ids:
        raise ValueError(f"Reliquie {card.card_id} cannot recover card {raw_target_card_id} from the current top-two preview.")

    recovered_card_id = raw_target_card_id or preview_card_ids[0]
    recovered_card = next(preview_card for preview_card in preview_cards if preview_card.card_id == recovered_card_id)
    state.players[player_id].hand_cards.append(recovered_card)
    state.heavenly_discard_pile = [discarded_card for discarded_card in shuffled_discard if discarded_card.card_id != recovered_card_id]

    append_event(
        state.event_log,
        event_type,
        player_id=player_id,
        card_id=card.card_id,
        effect_kind="recover_heavenly_from_discard_top_two",
        preview_card_ids=preview_card_ids,
        recovered_card_id=recovered_card.card_id,
        recovered_card_name=recovered_card.name,
        decision_source="explicit_intent" if raw_target_card_id is not None else "auto_policy",
        hand_size_after=len(state.players[player_id].hand_cards),
        heavenly_discard_pile_size=len(state.heavenly_discard_pile),
    )


def _resolve_relic_draw_truth_after_three_hand_discards(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
    effect_payload: dict[str, Any] | None,
    event_type: str = "relic_on_play_effect_resolved",
) -> None:
    payload = effect_payload or {}
    if bool(payload.get("skip")):
        append_event(
            state.event_log,
            event_type,
            player_id=player_id,
            card_id=card.card_id,
            effect_kind="draw_truth_after_three_hand_discards",
            decision_source="explicit_intent",
            skipped=True,
            discarded_card_ids=[],
            discarded_card_names=[],
            truth_values=[],
            prepared_truth_card_ids=[],
            hand_size_after=len(state.players[player_id].hand_cards),
            heavenly_discard_pile_size=len(state.heavenly_discard_pile),
        )
        return
    raw_discard_ids = payload.get("discard_card_ids")
    player = state.players[player_id]
    if raw_discard_ids is None:
        legal_discard_cards = [
            hand_card
            for hand_card in player.hand_cards
            if hand_card.category in ACTION_PLAYABLE_HAND_CATEGORIES
        ]
        available_discards = len(legal_discard_cards)
        if available_discards < 3:
            append_event(
                state.event_log,
                "relic_effect_skipped_insufficient_heavenly_discards",
                player_id=player_id,
                card_id=card.card_id,
                card_name=card.name,
                effect_kind="draw_truth_after_three_hand_discards",
                required_discards=3,
                available_discards=available_discards,
            )
            return
        discard_card_ids = [hand_card.card_id for hand_card in legal_discard_cards[:3]]
        decision_source = "auto_policy"
    else:
        if not isinstance(raw_discard_ids, list) or any(not isinstance(value, str) for value in raw_discard_ids):
            raise ValueError(f"Reliquie {card.card_id} requires discard_card_ids as a list of card-id strings.")
        if len(raw_discard_ids) != 3:
            raise ValueError(f"Reliquie {card.card_id} requires exactly 3 Himmelreichskarten.")
        if len(set(raw_discard_ids)) != len(raw_discard_ids):
            raise ValueError(f"Reliquie {card.card_id} discard_card_ids must not contain duplicates.")
        discard_card_ids = list(raw_discard_ids)
        decision_source = "explicit_intent"

    before_truth_card_ids = {
        hand_card.card_id
        for hand_card in player.hand_cards
        if hand_card.category == "Wahrheit"
    }
    hand_by_id = {hand_card.card_id: hand_card for hand_card in player.hand_cards}
    for discard_card_id in discard_card_ids:
        hand_card = hand_by_id.get(discard_card_id)
        if hand_card is None:
            raise ValueError(f"Player {player_id} cannot discard card {discard_card_id}; not in hand.")
        if hand_card.category not in ACTION_PLAYABLE_HAND_CATEGORIES:
            raise ValueError(
                f"Reliquie {card.card_id} can only discard Himmelreichskarten; got {hand_card.category} ({discard_card_id})."
            )

    discarded_card_ids: list[str] = []
    discarded_card_names: list[str] = []
    for discard_card_id in discard_card_ids:
        discarded_card = _pop_card_from_hand(player, card_id=discard_card_id)
        state.heavenly_discard_pile.append(discarded_card)
        discarded_card_ids.append(discarded_card.card_id)
        discarded_card_names.append(discarded_card.name)

    _register_heavenly_hand_discards_for_relic_effect(
        state,
        player_id=player_id,
        discarded_count=len(discarded_card_ids),
        source="relic_nasenhaar_discard_three_draw_truth",
    )

    append_event(
        state.event_log,
        event_type,
        player_id=player_id,
        card_id=card.card_id,
        effect_kind="draw_truth_after_three_hand_discards",
        decision_source=decision_source,
        discarded_card_ids=discarded_card_ids,
        discarded_card_names=discarded_card_names,
        truth_values=[
            hand_card.truth_value
            for hand_card in player.hand_cards
            if hand_card.category == "Wahrheit" and hand_card.card_id not in before_truth_card_ids
        ],
        prepared_truth_card_ids=[
            hand_card.card_id
            for hand_card in player.hand_cards
            if hand_card.category == "Wahrheit" and hand_card.card_id not in before_truth_card_ids
        ],
        hand_size_after=len(player.hand_cards),
        heavenly_discard_pile_size=len(state.heavenly_discard_pile),
    )


def _shuffle_relic_recovery_discard_pile(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
) -> list[CardRef]:
    rng = SeededRNG(
        seed=(
            f"relic-discard-top-two|{player_id}|{card.card_id}|r{state.round_number}|t{state.turn_number}|"
            f"{'|'.join(discarded.card_id for discarded in state.heavenly_discard_pile)}"
        )
    )
    return list(rng.shuffle(state.heavenly_discard_pile))


def get_relic_recovery_top_three_preview_cards(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
) -> list[CardRef]:
    if not state.heavenly_discard_pile:
        return []
    return _shuffle_relic_recovery_discard_pile(state, player_id=player_id, card=card)[:2]


def _resolve_relic_swap_heavenly_hand_cards(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
    effect_payload: dict[str, Any] | None,
    event_type: str = "relic_on_play_effect_resolved",
) -> None:
    payload = effect_payload or {}
    raw_discard_ids = payload.get("discard_card_ids")
    if raw_discard_ids is None:
        discard_card_ids: list[str] = []
        decision_source = "explicit_intent" if "glasauge_choice" in payload else "auto_policy"
    else:
        if not isinstance(raw_discard_ids, list) or any(not isinstance(value, str) for value in raw_discard_ids):
            raise ValueError(f"Reliquie {card.card_id} requires discard_card_ids as a list of card-id strings.")
        if len(raw_discard_ids) > 2:
            raise ValueError(f"Reliquie {card.card_id} can discard at most 2 Himmelreichskarten.")
        if len(set(raw_discard_ids)) != len(raw_discard_ids):
            raise ValueError(f"Reliquie {card.card_id} discard_card_ids must not contain duplicates.")
        discard_card_ids = list(raw_discard_ids)
        decision_source = "explicit_intent"

    player = state.players[player_id]
    hand_by_id = {hand_card.card_id: hand_card for hand_card in player.hand_cards}
    for discard_card_id in discard_card_ids:
        hand_card = hand_by_id.get(discard_card_id)
        if hand_card is None:
            raise ValueError(f"Player {player_id} cannot discard card {discard_card_id}; not in hand.")
        if hand_card.category not in ACTION_PLAYABLE_HAND_CATEGORIES:
            raise ValueError(
                f"Reliquie {card.card_id} can only discard Himmelreichskarten; got {hand_card.category} ({discard_card_id})."
            )

    discarded_card_ids: list[str] = []
    for discard_card_id in discard_card_ids:
        discarded_card = _pop_card_from_hand(player, card_id=discard_card_id)
        state.heavenly_discard_pile.append(discarded_card)
        discarded_card_ids.append(discarded_card.card_id)

    drawn_card_ids: list[str] = []
    for _ in discarded_card_ids:
        if not state.heavenly_draw_pile:
            break
        drawn_card = state.heavenly_draw_pile.pop(0)
        player.hand_cards.append(drawn_card)
        drawn_card_ids.append(drawn_card.card_id)

    append_event(
        state.event_log,
        event_type,
        player_id=player_id,
        card_id=card.card_id,
        effect_kind="swap_heavenly_hand_cards",
        decision_source=decision_source,
        discarded_card_ids=discarded_card_ids,
        drawn_card_ids=drawn_card_ids,
        hand_size_after=len(player.hand_cards),
        heavenly_discard_pile_size=len(state.heavenly_discard_pile),
        heavenly_draw_pile_size=len(state.heavenly_draw_pile),
    )


def _resolve_relic_missionize_per_affecting_commandment(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
    effect_payload: dict[str, Any] | None,
    event_type: str = "relic_on_play_effect_resolved",
) -> None:
    player = state.players[player_id]
    affecting_commandments = len(player.commandment_state.active_effect_sources)
    if affecting_commandments <= 0:
        append_event(
            state.event_log,
            event_type,
            player_id=player_id,
            card_id=card.card_id,
            effect_kind="missionize_per_affecting_commandment",
            affecting_commandments=0,
            target_player_id=None,
            target_player_ids=[],
            actual_transfer=0,
            decision_source="no_affecting_commandments",
            player_meeples_after=player.meeples,
        )
        return

    payload = effect_payload or {}
    raw_target_player_ids = payload.get("target_player_ids")
    explicit_target_player_ids: list[str] = []
    if raw_target_player_ids is not None:
        if not isinstance(raw_target_player_ids, list) or any(
            not isinstance(target_player_id, str) for target_player_id in raw_target_player_ids
        ):
            raise ValueError(
                f"Reliquie {card.card_id} target_player_ids must be a list of player-id strings."
            )
        if len(raw_target_player_ids) > affecting_commandments:
            raise ValueError(
                f"Reliquie {card.card_id} received {len(raw_target_player_ids)} explicit targets for {affecting_commandments} transfers."
            )
        explicit_target_player_ids = list(raw_target_player_ids)

    actual_transfer = 0
    transferred_target_player_ids: list[str] = []
    for trigger_index in range(affecting_commandments):
        explicit_target_player_id = (
            explicit_target_player_ids[trigger_index]
            if trigger_index < len(explicit_target_player_ids)
            else None
        )
        target_player_id, _selection_reason = _get_next_missionary_target_player_id(
            state,
            player_id=player_id,
            target_player_id=explicit_target_player_id,
        )
        if target_player_id is None:
            continue
        target_player = state.players[target_player_id]
        target_player.meeples -= 1
        player.meeples += 1
        actual_transfer += 1
        transferred_target_player_ids.append(target_player_id)
        state.last_meeple_taker_by_victim[target_player_id] = player_id

    append_event(
        state.event_log,
        event_type,
        player_id=player_id,
        card_id=card.card_id,
        effect_kind="missionize_per_affecting_commandment",
        affecting_commandments=affecting_commandments,
        target_player_id=(transferred_target_player_ids[0] if transferred_target_player_ids else None),
        target_player_ids=transferred_target_player_ids,
        actual_transfer=actual_transfer,
        decision_source="explicit_intent" if explicit_target_player_ids else "auto_policy",
        player_meeples_after=player.meeples,
        target_meeples_after=(
            None
            if not transferred_target_player_ids
            else state.players[transferred_target_player_ids[-1]].meeples
        ),
    )


def _resolve_relic_opponent_choice_discard_or_baptism(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
    effect_payload: dict[str, Any] | None,
    event_type: str = "relic_on_play_effect_resolved",
) -> None:
    payload = effect_payload or {}
    raw_target_player_id = payload.get("target_player_id")
    if raw_target_player_id is not None and not isinstance(raw_target_player_id, str):
        raise ValueError(f"Reliquie {card.card_id} target_player_id must be a string.")
    raw_choice = payload.get("choice")
    if raw_choice is not None and not isinstance(raw_choice, str):
        raise ValueError(f"Reliquie {card.card_id} choice must be a string.")
    raw_discarded_card_id = payload.get("target_discarded_card_id")
    if raw_discarded_card_id is not None and not isinstance(raw_discarded_card_id, str):
        raise ValueError(f"Reliquie {card.card_id} target_discarded_card_id must be a string.")

    candidate_player_ids = [
        candidate_player_id
        for candidate_player_id in _get_turn_order_from_player(state, player_id=player_id)
        if candidate_player_id in set(_get_opponent_player_ids_in_turn_order(state, player_id=player_id))
    ]
    if raw_target_player_id is not None and raw_target_player_id not in candidate_player_ids:
        raise ValueError(f"Reliquie {card.card_id} cannot target player {raw_target_player_id}.")

    if raw_target_player_id is not None:
        target_player_id = raw_target_player_id
        decision_source = "explicit_intent"
    else:
        target_player_id = candidate_player_ids[0] if candidate_player_ids else None
        decision_source = "auto_policy"

    if target_player_id is None:
        append_event(
            state.event_log,
            event_type,
            player_id=player_id,
            card_id=card.card_id,
            effect_kind="opponent_choice_discard_or_baptism",
            target_player_id=None,
            chosen_mode=None,
            discarded_card_id=None,
            actual_baptism=0,
            decision_source="no_target_player",
            player_meeples_after=state.players[player_id].meeples,
        )
        return

    target_player = state.players[target_player_id]
    target_heavenly_cards = [
        hand_card
        for hand_card in target_player.hand_cards
        if hand_card.category in ACTION_PLAYABLE_HAND_CATEGORIES
    ]

    if raw_choice is not None and raw_choice not in {"discard_heavenly", "baptize_owner"}:
        raise ValueError(f"Reliquie {card.card_id} choice must be 'discard_heavenly' or 'baptize_owner'.")

    if raw_choice is not None:
        chosen_mode = raw_choice
    else:
        chosen_mode = "discard_heavenly" if target_heavenly_cards else "baptize_owner"

    discarded_card_id: str | None = None
    actual_baptism = 0
    if chosen_mode == "discard_heavenly":
        if not target_heavenly_cards:
            raise ValueError(
                f"Reliquie {card.card_id} cannot force discard_heavenly; player {target_player_id} has no Himmelreichskarte."
            )
        if raw_discarded_card_id is not None:
            target_card = next(
                (candidate for candidate in target_heavenly_cards if candidate.card_id == raw_discarded_card_id),
                None,
            )
            if target_card is None:
                raise ValueError(
                    f"Reliquie {card.card_id} cannot discard card {raw_discarded_card_id} from player {target_player_id}."
                )
            discarded_card = _pop_card_from_hand(target_player, card_id=target_card.card_id)
        else:
            discarded_card = _pop_card_from_hand(target_player, card_id=target_heavenly_cards[0].card_id)
        state.heavenly_discard_pile.append(discarded_card)
        discarded_card_id = discarded_card.card_id
    else:
        state.players[player_id].meeples += 2
        actual_baptism = 2

    append_event(
        state.event_log,
        event_type,
        player_id=player_id,
        card_id=card.card_id,
        effect_kind="opponent_choice_discard_or_baptism",
        target_player_id=target_player_id,
        chosen_mode=chosen_mode,
        discarded_card_id=discarded_card_id,
        actual_baptism=actual_baptism,
        decision_source=decision_source,
        player_meeples_after=state.players[player_id].meeples,
        target_meeples_after=target_player.meeples,
        heavenly_discard_pile_size=len(state.heavenly_discard_pile),
    )


def _register_heavenly_hand_discards_for_relic_effect(
    state: GameState,
    *,
    player_id: str,
    discarded_count: int,
    source: str,
) -> None:
    if discarded_count <= 0:
        return
    if not _player_has_active_relic_rule_text(
        state,
        player_id=player_id,
        text=RELIC_DRAW_TRUTH_AFTER_THREE_HAND_DISCARDS_TEXT,
    ) and not _player_has_active_relic_rule_text(
        state,
        player_id=player_id,
        text=RELIC_DRAW_TRUTH_AFTER_THREE_HAND_DISCARDS_VARIANT_TEXT,
    ):
        return

    player = state.players[player_id]
    player.heavenly_hand_discard_tally += discarded_count
    append_event(
        state.event_log,
        "relic_hand_discard_tally_updated",
        player_id=player_id,
        source=source,
        discarded_count=discarded_count,
        tally_after=player.heavenly_hand_discard_tally,
    )

    while player.heavenly_hand_discard_tally >= 3:
        player.heavenly_hand_discard_tally -= 3
        try:
            truth_values = _get_default_gloria_truth_values(
                state,
                player_id=player_id,
                count=1,
            )
        except ValueError:
            append_event(
                state.event_log,
                "relic_truth_draw_after_three_hand_discards_unresolved",
                player_id=player_id,
                source=source,
                tally_after=player.heavenly_hand_discard_tally,
            )
            continue

        prepared_cards = _add_truth_cards_to_hand(
            state,
            player_id=player_id,
            truth_values=truth_values,
            source="relic-nasenhaar",
        )
        append_event(
            state.event_log,
            "relic_truth_draw_after_three_hand_discards_resolved",
            player_id=player_id,
            source=source,
            truth_values=truth_values,
            prepared_truth_card_ids=[card.card_id for card in prepared_cards],
            hand_size_after=len(player.hand_cards),
            tally_after=player.heavenly_hand_discard_tally,
        )


def _available_truth_draw_counter_for_hand_preparation(
    state: GameState,
    *,
    player_id: str,
    extra_prepared_truth: Counter[int] | None = None,
    truth_pool_values: list[int] | None = None,
) -> Counter[int]:
    player = state.players[player_id]
    prepared_truth_counter = Counter(
        card.truth_value
        for card in player.hand_cards
        if card.category == "Wahrheit" and card.truth_value is not None
    )
    if extra_prepared_truth:
        prepared_truth_counter.update(extra_prepared_truth)
    pool_values = player.truth_pool if truth_pool_values is None else truth_pool_values
    available_truth_counter = Counter(int(value) for value in pool_values)
    remaining_truth_counter: Counter[int] = Counter()
    for truth_value, available_count in available_truth_counter.items():
        remaining_copies = int(available_count - prepared_truth_counter[truth_value])
        if remaining_copies > 0:
            remaining_truth_counter[int(truth_value)] = remaining_copies
    if _player_has_defined_head(player):
        remaining_truth_counter.pop(7, None)
    return remaining_truth_counter


def _truth_pool_values_after_preparation_reset(state: GameState, *, player_id: str) -> list[int]:
    player = state.players[player_id]
    restored_truth_values = [
        _get_truth_card_pool_value(discarded_card)
        for discarded_card in player.truth_discard
        if not _truth_discard_card_counts_as_used_truth(discarded_card)
    ]
    return [*player.truth_pool, *player.used_truth, *restored_truth_values]


def _available_truth_draw_counter_for_hand_preparation_after_auto_reset(
    state: GameState,
    *,
    player_id: str,
    extra_prepared_truth: Counter[int] | None = None,
) -> Counter[int]:
    remaining_truth_counter = _available_truth_draw_counter_for_hand_preparation(
        state,
        player_id=player_id,
        extra_prepared_truth=extra_prepared_truth,
    )
    if remaining_truth_counter:
        return remaining_truth_counter

    player = state.players[player_id]
    if not player.truth_discard and not player.used_truth:
        return remaining_truth_counter

    return _available_truth_draw_counter_for_hand_preparation(
        state,
        player_id=player_id,
        extra_prepared_truth=extra_prepared_truth,
        truth_pool_values=_truth_pool_values_after_preparation_reset(state, player_id=player_id),
    )


def _available_truth_draw_values_for_hand_preparation(
    state: GameState,
    *,
    player_id: str,
) -> list[int]:
    remaining_truth_counter = _available_truth_draw_counter_for_hand_preparation(
        state,
        player_id=player_id,
    )
    available_truth_values: list[int] = []
    for truth_value in sorted(remaining_truth_counter):
        available_truth_values.extend([int(truth_value)] * int(remaining_truth_counter[truth_value]))
    return available_truth_values


def _get_default_gloria_truth_values(
    state: GameState,
    *,
    player_id: str,
    count: int,
) -> list[int]:
    available_truth_values: list[int] = []
    extra_prepared_truth: Counter[int] = Counter()
    for _ in range(count):
        remaining_truth_counter = _available_truth_draw_counter_for_hand_preparation_after_auto_reset(
            state,
            player_id=player_id,
            extra_prepared_truth=extra_prepared_truth,
        )
        if not remaining_truth_counter:
            break
        truth_value = max(remaining_truth_counter)
        available_truth_values.append(int(truth_value))
        extra_prepared_truth[int(truth_value)] += 1

    if len(available_truth_values) < count:
        raise ValueError(
            f"Player {player_id} cannot prepare {count} truth card(s) for Gloria; only {len(available_truth_values)} remain available."
        )
    return available_truth_values[:count]


def _validate_truth_values_can_be_prepared(
    state: GameState,
    *,
    player_id: str,
    truth_values: list[int],
) -> None:
    extra_prepared_truth: Counter[int] = Counter()

    for truth_value in truth_values:
        if not isinstance(truth_value, int):
            raise ValueError("Truth values must be integers.")
        remaining_truth_counter = _available_truth_draw_counter_for_hand_preparation_after_auto_reset(
            state,
            player_id=player_id,
            extra_prepared_truth=extra_prepared_truth,
        )
        if remaining_truth_counter[truth_value] <= 0:
            raise ValueError(
                f"Player {player_id} cannot prepare truth value {truth_value}; not enough copies available."
            )
        extra_prepared_truth[int(truth_value)] += 1


def _prepare_holy_army_resolution(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
    effect_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    effect_payload = effect_payload or {}
    player = state.players[player_id]
    target_card_id = effect_payload.get("target_card_id")
    if target_card_id is not None and not isinstance(target_card_id, str):
        raise ValueError("Heiliges Heer requires target_card_id as a string when provided.")

    profile = _get_holy_army_profile(card)
    if profile["mode"] == "schleifer":
        destination_player_id = effect_payload.get("destination_player_id")
        if not isinstance(destination_player_id, str):
            raise ValueError("Schleifer requires destination_player_id.")
        if destination_player_id not in state.players:
            raise ValueError(f"Unknown Schleifer destination player {destination_player_id}.")
        if destination_player_id == player_id:
            raise ValueError("Schleifer must move the Aufklärer to a different player.")
        if target_card_id is None:
            raise ValueError("Schleifer requires target_card_id.")

        source_player_id, target_card = _find_tableau_card_owner(
            state,
            card_id=target_card_id,
            category="Aufklärer",
        )
        legal_destination_player_ids = next(
            (
                list(entry.get("destination_player_ids") or [])
                for entry in _get_schleifer_target_entries(state, player_id=player_id)
                if str(entry.get("target_card_id") or "") == target_card_id
            ),
            [],
        )
        if destination_player_id not in legal_destination_player_ids:
            raise ValueError("Schleifer must move the Aufklärer to a different legal target player.")
        intrinsic_cost = 5
        return {
            "effect_name": "Heiliges Heer",
            "mode": "schleifer",
            "intrinsic_cost": intrinsic_cost,
            "source_player_id": source_player_id,
            "destination_player_id": destination_player_id,
            "target_card": target_card,
        }

    own_enlighteners = [
        tableau_card
        for tableau_card in player.tableau
        if tableau_card.category == "Aufklärer"
    ]
    if target_card_id is not None and not any(tableau_card.card_id == target_card_id for tableau_card in own_enlighteners):
        for other_owner_id, other_owner in state.players.items():
            if other_owner_id == player_id:
                continue
            if any(tableau_card.card_id == target_card_id and tableau_card.category == "Aufklärer" for tableau_card in other_owner.tableau):
                raise ValueError(f"Player {player_id} can only target own Aufklärer with this Heiliges Heer.")
    if not own_enlighteners:
        raise ValueError(f"Player {player_id} has no own Aufklärer that can be targeted by Heiliges Heer.")

    specialized_targets = [
        tableau_card
        for tableau_card in own_enlighteners
        if any(
            _holy_army_target_matches_card(tableau_card, target_fragment)
            for target_fragment in profile["specialized_targets"]
        )
    ]

    requested_mode = effect_payload.get("mode")
    if requested_mode is not None and requested_mode not in {"specialized", "any_own"}:
        raise ValueError("Heiliges Heer mode must be 'specialized' or 'any_own'.")

    if requested_mode is None:
        if target_card_id is None:
            if len(specialized_targets) == 1:
                requested_mode = "specialized"
                target_card_id = specialized_targets[0].card_id
            elif not specialized_targets and len(own_enlighteners) == 1:
                requested_mode = "any_own"
                target_card_id = own_enlighteners[0].card_id
            else:
                raise ValueError(
                    f"Player {player_id} must specify Heiliges Heer mode and target_card_id when multiple legal targets exist."
                )
        else:
            requested_mode = (
                "specialized"
                if any(tableau_card.card_id == target_card_id for tableau_card in specialized_targets)
                else "any_own"
            )

    if target_card_id is None:
        raise ValueError("Heiliges Heer requires target_card_id.")

    target_card = next((tableau_card for tableau_card in own_enlighteners if tableau_card.card_id == target_card_id), None)
    if target_card is None:
        raise ValueError(f"Player {player_id} can only target own Aufklärer with this Heiliges Heer.")

    if requested_mode == "specialized":
        if not any(tableau_card.card_id == target_card_id for tableau_card in specialized_targets):
            raise ValueError(
                f"Heiliges Heer {card.card_id} cannot discard Aufklärer {target_card_id} for 0 cost; target is not specialized."
            )
        intrinsic_cost = 0
    else:
        intrinsic_cost = 4

    return {
        "effect_name": "Heiliges Heer",
        "mode": requested_mode,
        "intrinsic_cost": intrinsic_cost,
        "source_player_id": player_id,
        "target_card": target_card,
    }


def _resolve_holy_army_play(
    state: GameState,
    *,
    player_id: str,
    card: CardRef,
    effect_payload: dict[str, Any] | None,
) -> None:
    resolution = _prepare_holy_army_resolution(
        state,
        player_id=player_id,
        card=card,
        effect_payload=effect_payload,
    )
    player = state.players[player_id]
    base_intrinsic_cost = 0 if _is_intrinsic_cost_waived_by_tableau(
        state,
        player_id=player_id,
        card=card,
    ) else int(resolution["intrinsic_cost"])
    intrinsic_cost = _apply_sacrifice_cost_reduction(
        state,
        player_id=player_id,
        amount=base_intrinsic_cost,
    )
    if intrinsic_cost > player.meeples:
        payment_choice = {} if effect_payload is None else effect_payload.get("intrinsic_cost_payment_choice", {})
        normalized_payment_choice = _normalize_meeple_payment_choice(
            payment_choice,
            context=f"Heiliges Heer {card.card_id} intrinsic_cost_payment_choice",
        )
        if player.meeples + _count_bound_meeples_in_payment_choice(normalized_payment_choice) < intrinsic_cost:
            raise ValueError(
                f"Player {player_id} cannot resolve Heiliges Heer {card.card_id}; intrinsic cost {intrinsic_cost} exceeds available meeples {player.meeples}."
            )

    if intrinsic_cost > 0:
        payment_resolution = _spend_player_meeples(
            state,
            player_id=player_id,
            amount=intrinsic_cost,
            strict=True,
            payment_choice=None if effect_payload is None else effect_payload.get("intrinsic_cost_payment_choice"),
            purpose="holy_army_intrinsic_cost",
        )
        append_event(
            state.event_log,
            "hand_card_intrinsic_cost_paid",
            player_id=player_id,
            card_id=card.card_id,
            card_name=card.name,
            category=card.category,
            intrinsic_cost=intrinsic_cost,
            **_sacrifice_cost_reduction_event_fields(
                state,
                player_id=player_id,
                base_amount=base_intrinsic_cost,
                effective_amount=intrinsic_cost,
                prefix="intrinsic_cost",
            ),
            free_meeples_paid=payment_resolution["free_meeples_paid"],
            role_meeples_paid=dict(payment_resolution["role_meeples_paid"]),
            prepared_nuns_paid=payment_resolution["prepared_nuns_paid"],
            meeples_after=player.meeples,
        )

    if resolution["mode"] == "schleifer":
        source_player = state.players[resolution["source_player_id"]]
        moved_card = _pop_card_from_tableau(source_player, card_id=resolution["target_card"].card_id)
        state.players[resolution["destination_player_id"]].tableau.append(moved_card)
        append_event(
            state.event_log,
            "holy_army_resolved",
            player_id=player_id,
            card_id=card.card_id,
            card_name=card.name,
            mode="schleifer",
            intrinsic_cost=intrinsic_cost,
            source_player_id=resolution["source_player_id"],
            destination_player_id=resolution["destination_player_id"],
            target_card_id=moved_card.card_id,
            target_card_name=moved_card.name,
        )
        return

    source_player = state.players[resolution["source_player_id"]]
    removed_card = _pop_card_from_tableau(source_player, card_id=resolution["target_card"].card_id)
    state.heavenly_discard_pile.append(removed_card)
    append_event(
        state.event_log,
        "holy_army_resolved",
        player_id=player_id,
        card_id=card.card_id,
        card_name=card.name,
        mode=resolution["mode"],
        intrinsic_cost=intrinsic_cost,
        source_player_id=resolution["source_player_id"],
        target_card_id=removed_card.card_id,
        target_card_name=removed_card.name,
        heavenly_discard_pile_size=len(state.heavenly_discard_pile),
    )


def _get_holy_army_profile(card: CardRef) -> dict[str, Any]:
    rules_text = _get_holy_army_rules_text(card)
    if re.search(r"Bewege einen (?:irgendwo angelegten|beliebigen) Aufklärer zu einem Mitgott\.", rules_text):
        return {"mode": "schleifer", "specialized_targets": []}

    match = re.search(
        r"0 <CULTISTS>:\s*Lege (?:die|den) (.+?) oder (?:den|die) (.+?) ab\.",
        rules_text,
    )
    if match is None:
        raise ValueError(f"Heiliges Heer {card.card_id} uses unsupported rules text for the current MVP.")

    return {
        "mode": "discard",
        "specialized_targets": [match.group(1), match.group(2)],
    }


def _get_holy_army_rules_text(card: CardRef) -> str:
    metadata_rules_text = card.metadata.get("rules_text")
    if isinstance(metadata_rules_text, str) and metadata_rules_text:
        return metadata_rules_text
    record = get_card_record(card.card_id)
    if isinstance(record, dict):
        record_rules_text = record.get("rules_text")
        if isinstance(record_rules_text, str) and record_rules_text:
            return record_rules_text
    raise ValueError(f"Heiliges Heer {card.card_id} is missing rules text metadata.")


def _holy_army_target_matches_fragment(target_name: str, fragment: str) -> bool:
    normalized_target = _normalize_holy_army_lookup_text(target_name)
    normalized_fragment = _normalize_holy_army_lookup_text(fragment)
    variants = {
        normalized_fragment,
        normalized_fragment.removesuffix("en"),
        normalized_fragment.removesuffix("n"),
        normalized_fragment.removesuffix("e"),
    }
    return any(variant and variant in normalized_target for variant in variants)


def _holy_army_target_matches_card(target_card: CardRef, fragment: str) -> bool:
    canonical_record = get_card_record(target_card.card_id)
    canonical_name = (
        str(canonical_record.get("name") or "")
        if isinstance(canonical_record, dict)
        else ""
    )
    slug_name = str(target_card.card_id).split("__", 1)[0].replace("-", " ")
    return any(
        _holy_army_target_matches_fragment(candidate_name, fragment)
        for candidate_name in {str(target_card.name or ""), canonical_name, slug_name}
        if candidate_name
    )


def _normalize_holy_army_lookup_text(value: str) -> str:
    normalized = (
        value.lower()
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _find_tableau_card_owner(
    state: GameState,
    *,
    card_id: str,
    category: str | None = None,
) -> tuple[str, CardRef]:
    for owner_id, owner in state.players.items():
        for tableau_card in owner.tableau:
            if tableau_card.card_id != card_id:
                continue
            if category is not None and tableau_card.category != category:
                continue
            return owner_id, tableau_card
    raise ValueError(f"Could not find tableau card {card_id} matching category {category}.")


def _pop_card_from_tableau(player: PlayerState, *, card_id: str) -> CardRef:
    for index, tableau_card in enumerate(player.tableau):
        if tableau_card.card_id == card_id:
            return player.tableau.pop(index)
    raise ValueError(f"Player {player.player_id} does not have tableau card {card_id}.")


def _get_next_missionary_target_player_id(
    state: GameState,
    *,
    player_id: str,
    target_player_id: str | None = None,
) -> tuple[str | None, str | None]:
    current_index = state.player_order.index(player_id)
    candidates = [
        candidate_player_id
        for candidate_player_id in _get_opponent_player_ids_in_turn_order(state, player_id=player_id)
        if (
            state.players[candidate_player_id].meeples > 0
            and not _is_player_immune_to_missionizing(state, player_id=candidate_player_id)
        )
    ]
    if not candidates:
        return None, None

    if target_player_id is not None:
        if target_player_id not in state.players:
            raise ValueError(f"Unknown missionary target player {target_player_id}.")
        if target_player_id == player_id:
            raise ValueError(f"Player {player_id} cannot missionize themselves.")
        if target_player_id not in candidates:
            raise ValueError(
                f"Player {player_id} cannot missionize {target_player_id} right now."
            )
        return target_player_id, "explicit_intent"

    highest_meeple_count = max(state.players[candidate_player_id].meeples for candidate_player_id in candidates)
    top_candidates = [
        candidate_player_id
        for candidate_player_id in candidates
        if state.players[candidate_player_id].meeples == highest_meeple_count
    ]
    if len(top_candidates) == 1:
        return top_candidates[0], "most_meeples"

    last_aggressor = state.last_meeple_taker_by_victim.get(player_id)
    if last_aggressor in top_candidates:
        return last_aggressor, "last_aggressor_tiebreak"

    ordered_candidates = sorted(
        top_candidates,
        key=lambda candidate_player_id: (state.player_order.index(candidate_player_id) - current_index) % len(state.player_order),
    )
    return ordered_candidates[0], "turn_order_tiebreak"


def reveal_god(state: GameState, *, player_id: str) -> GameState:
    player = state.players[player_id]
    if not _player_has_defined_body(player):
        raise ValueError(f"Player {player_id} cannot reveal a god before defining head, chest, and legs.")

    if not player.god_revealed:
        player.god_revealed = True
        player.meeples += 3
        append_event(
            state.event_log,
            "god_revealed",
            player_id=player_id,
            round_number=state.round_number,
            turn_number=state.turn_number,
        )
        append_event(
            state.event_log,
            "god_reveal_reward_resolved",
            player_id=player_id,
            reward_amount=3,
            reward_source="god_reveal",
            meeples_after=player.meeples,
            round_number=state.round_number,
            turn_number=state.turn_number,
        )

    if state.gods_twilight_triggered:
        return state

    state.gods_twilight_triggered = True
    state.gods_twilight_trigger_round = state.round_number
    state.nunnery_active = True
    for current_player in state.players.values():
        current_player.nunnery_state.active = True
        current_player.nuns_slots = 2 if current_player.alignment == "<Unergründlich>" else 1
        _sync_role_slot_assignments(state, player_id=current_player.player_id)
    _start_endgame_countdown(
        state,
        trigger_player_id=player_id,
        trigger_source="god_reveal",
    )
    append_event(
        state.event_log,
        "gods_twilight_triggered",
        player_id=player_id,
        round_number=state.round_number,
        remaining_final_rounds=state.remaining_final_rounds,
        nunnery_active=state.nunnery_active,
    )
    return state


def _draw_to_hand_limit(state: GameState, *, player_id: str, cards_needed: int) -> list[CardRef]:
    player = state.players[player_id]
    drawn_cards: list[CardRef] = []

    for _ in range(cards_needed):
        if not state.heavenly_draw_pile:
            if not _reshuffle_heavenly_discard_into_draw_pile(state):
                break

        drawn_card = state.heavenly_draw_pile.pop(0)
        player.hand_cards.append(drawn_card)
        drawn_cards.append(drawn_card)
        append_event(
            state.event_log,
            "card_drawn",
            player_id=player_id,
            card_id=drawn_card.card_id,
            category=drawn_card.category,
            heavenly_draw_pile_size=len(state.heavenly_draw_pile),
        )

    return drawn_cards


def _refill_hand_to_size_with_optional_truth(
    state: GameState,
    *,
    player_id: str,
    target_hand_size: int,
    truth_values: list[int],
    truth_source: str,
) -> tuple[list[CardRef], list[CardRef]]:
    if target_hand_size < 0:
        raise ValueError("target_hand_size must not be negative.")
    if len(truth_values) > target_hand_size:
        raise ValueError(
            f"Player {player_id} cannot prepare {len(truth_values)} truth card(s) for hand size {target_hand_size}."
        )
    _validate_truth_values_can_be_prepared(state, player_id=player_id, truth_values=truth_values)
    prepared_truth_cards = _add_truth_cards_to_hand(
        state,
        player_id=player_id,
        truth_values=truth_values,
        source=truth_source,
    )
    heavenly_cards_needed = target_hand_size - len(state.players[player_id].hand_cards)
    if heavenly_cards_needed < 0:
        raise ValueError(f"Player {player_id} exceeds target hand size {target_hand_size}.")
    drawn_cards = _draw_to_hand_limit(
        state,
        player_id=player_id,
        cards_needed=heavenly_cards_needed,
    )
    return prepared_truth_cards, drawn_cards


def _reshuffle_heavenly_discard_into_draw_pile(state: GameState) -> bool:
    if not state.heavenly_discard_pile:
        append_event(
            state.event_log,
            "heavenly_draw_pile_empty",
            heavenly_draw_pile_size=0,
            heavenly_discard_pile_size=0,
        )
        return False

    reshuffled_card_ids = [card.card_id for card in state.heavenly_discard_pile]
    rng = SeededRNG(
        seed=(
            f"heavenly-reshuffle|r{state.round_number}|t{state.turn_number}|"
            f"{'|'.join(reshuffled_card_ids)}"
        )
    )
    state.heavenly_draw_pile = list(rng.shuffle(list(state.heavenly_discard_pile)))
    state.heavenly_discard_pile.clear()
    append_event(
        state.event_log,
        "heavenly_draw_pile_reshuffled",
        heavenly_draw_pile_size=len(state.heavenly_draw_pile),
        heavenly_discard_pile_size=len(state.heavenly_discard_pile),
        reshuffled_card_count=len(reshuffled_card_ids),
        reshuffled_card_ids=reshuffled_card_ids,
        heavenly_draw_pile_order=[card.card_id for card in state.heavenly_draw_pile],
    )
    return True


def _get_cyclic_turn_order(state: GameState) -> list[str]:
    player_count = len(state.player_order)
    return [
        state.player_order[(state.start_player_idx + offset) % player_count]
        for offset in range(player_count)
    ]


def _get_effective_hand_card_truth_value(state: GameState, *, player_id: str, card: CardRef) -> int:
    if card.category == "Wahrheit":
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
    elif card.category in ACTION_PLAYABLE_HAND_CATEGORIES:
        base_truth = 1
    else:
        base_truth = card.truth_value or 0

    if state.players[player_id].commandment_state.heavenly_cards_zero_truth:
        return 0
    return base_truth


def _extract_first_integer(value: str) -> int | None:
    match = re.search(r"(\d+)", value)
    return int(match.group(1)) if match else None


def _get_truth_card_pool_value(card: CardRef) -> int:
    if card.truth_value is not None:
        return card.truth_value
    return _extract_first_integer(card.name) or _extract_first_integer(card.card_id) or 0


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


def _player_has_defined_body(player: PlayerState) -> bool:
    return has_complete_trinity(player)


def _player_has_defined_head(player: PlayerState) -> bool:
    return any(card.category == "Körperteil Kopf" for card in player.tableau)


def _player_has_defined_legs(player: PlayerState) -> bool:
    return any(card.category == "Körperteil Beine" for card in player.tableau)


def _player_has_defined_chest(player: PlayerState) -> bool:
    return any(card.category == "Körperteil Brust" for card in player.tableau)


def _pop_card_from_hand(player: PlayerState, *, card_id: str) -> CardRef:
    for index, card in enumerate(player.hand_cards):
        if card.card_id == card_id:
            return player.hand_cards.pop(index)
    raise ValueError(f"Player {player.player_id} does not have card {card_id} in hand.")


def _award_contested_card(
    state: GameState,
    *,
    player_id: str,
    card_id: str,
    card_name: str | None = None,
    card_category: str | None = None,
    manifest_requested: bool = False,
    manifest_body_part_category: str | None = None,
) -> GameState:
    if card_category == "Gebote":
        return claim_commandment(
            state,
            player_id=player_id,
            card_id=card_id,
            card_name=card_name,
        )

    return claim_phenomenon(
        state,
        player_id=player_id,
        card_id=card_id,
        card_name=card_name,
        manifest_requested=manifest_requested,
        manifest_body_part_category=manifest_body_part_category,
    )


def _choose_baseline_manifestation_body_part_category(
    state: GameState,
    *,
    player_id: str,
    phenomenon_alignment: str | None,
) -> str | None:
    valid_categories = get_manifestable_body_part_categories(
        state,
        player_id=player_id,
        phenomenon_alignment=phenomenon_alignment,
    )
    if not valid_categories:
        return None
    player = state.players[player_id]
    rng = SeededRNG(
        seed=(
            f"baseline-manifest|{player_id}|r{state.round_number}|t{state.turn_number}|"
            f"e{len(state.event_log)}|p{len(player.stored_phenomena)}"
        )
    )
    return rng.shuffle(list(valid_categories))[0]


def get_manifestable_body_part_categories(
    state: GameState,
    *,
    player_id: str,
    phenomenon_alignment: str | None,
) -> list[str]:
    if player_id not in state.players:
        raise ValueError(f"Unknown player for manifestation lookup: {player_id}.")
    if not isinstance(phenomenon_alignment, str) or not phenomenon_alignment:
        return []

    player = state.players[player_id]
    owned_body_parts = _get_player_body_parts(player)
    categories_by_part_name = {
        part_name: category for category, part_name in MANIFESTABLE_BODY_PART_CATEGORIES.items()
    }
    manifestable_categories: list[str] = []
    for part_name in BODY_PART_BASELINE_ORDER:
        if part_name in owned_body_parts:
            continue
        category = categories_by_part_name[part_name]
        if not _has_free_slot(player, slot_kind="body_part", body_part_category=category):
            continue
        if not any(
            card.category == category and _get_body_part_card_alignment(card) == phenomenon_alignment
            for card in state.body_part_draw_pile
        ):
            continue
        manifestable_categories.append(category)
    return manifestable_categories


def _get_player_body_parts(player: PlayerState) -> set[str]:
    normalized_body_parts = {body_part for body_part in player.body_parts if body_part in BODY_PART_NAME_TO_CATEGORY}
    for card in player.tableau:
        body_part_name = MANIFESTABLE_BODY_PART_CATEGORIES.get(card.category)
        if body_part_name is not None:
            normalized_body_parts.add(body_part_name)
    player.body_parts = set(normalized_body_parts)
    return set(normalized_body_parts)


def _record_manifested_body_part(player: PlayerState, *, body_part_category: str) -> None:
    body_part_name = MANIFESTABLE_BODY_PART_CATEGORIES.get(body_part_category)
    if body_part_name is None:
        return
    body_parts = _get_player_body_parts(player)
    body_parts.add(body_part_name)
    player.body_parts = body_parts


def _get_body_part_card_alignment(card: CardRef) -> str | None:
    alignment = card.metadata.get("alignment")
    if isinstance(alignment, str) and alignment:
        return alignment
    return None


def _get_body_part_alignment_draw_entries(
    state: GameState,
    *,
    alignment: str,
) -> list[tuple[int, CardRef]]:
    return [
        (index, card)
        for index, card in enumerate(state.body_part_draw_pile)
        if _get_body_part_card_alignment(card) == alignment
    ]


def _reshuffle_body_part_alignment_cards(
    cards: list[CardRef],
    *,
    state: GameState,
    player_id: str,
    card_id: str,
    body_part_category: str,
    phenomenon_alignment: str,
    search_event_count: int,
) -> list[CardRef]:
    if len(cards) <= 1:
        return list(cards)
    rng = SeededRNG(
        seed=(
            f"body-part-reshuffle|seed={state.seed}|player={player_id}|card={card_id}|"
            f"part={body_part_category}|alignment={phenomenon_alignment}|"
            f"round={state.round_number}|turn={state.turn_number}|event={search_event_count}"
        )
    )
    return list(rng.shuffle(list(cards)))


def _rewrite_body_part_alignment_draw_pile(
    state: GameState,
    *,
    alignment: str,
    replacement_cards: list[CardRef],
    removed_global_index: int | None = None,
) -> None:
    new_draw_pile: list[CardRef] = []
    replacement_iter = iter(replacement_cards)
    for index, card in enumerate(state.body_part_draw_pile):
        if removed_global_index is not None and index == removed_global_index:
            continue
        if _get_body_part_card_alignment(card) == alignment:
            replacement_card = next(replacement_iter, None)
            if replacement_card is None:
                raise AssertionError("Body-part alignment rewrite ran out of replacement cards.")
            new_draw_pile.append(replacement_card)
            continue
        new_draw_pile.append(card)
    extra_card = next(replacement_iter, None)
    if extra_card is not None:
        raise AssertionError("Body-part alignment rewrite left unused replacement cards.")
    state.body_part_draw_pile = new_draw_pile


def _resolve_phenomenon_manifestation(
    state: GameState,
    *,
    player_id: str,
    card_id: str,
    card_name: str,
    body_part_category: str | None,
    phenomenon_alignment: str | None = None,
) -> GameState:
    if body_part_category is None:
        append_event(
            state.event_log,
            "phenomenon_manifestation_requested",
            player_id=player_id,
            card_id=card_id,
            card_name=card_name,
            phenomenon_alignment=phenomenon_alignment,
        )
        return state

    if body_part_category not in MANIFESTABLE_BODY_PART_CATEGORIES:
        raise ValueError(
            f"Cannot manifest unsupported body part category {body_part_category} for player {player_id}."
        )

    player = state.players[player_id]
    if not _has_free_slot(player, slot_kind="body_part", body_part_category=body_part_category):
        existing_same_part = any(card.category == body_part_category for card in player.tableau)
        if existing_same_part:
            illegal_code = ILLEGAL_STATE_DUPLICATE_BODY_PART_MANIFEST
            state.illegal_states.append(illegal_code)
            append_event(
                state.event_log,
                illegal_code,
                round=state.round_number,
                current_round=state.round_number,
                player_id=player_id,
                card_id=card_id,
                body_part_category=body_part_category,
                phenomenon_alignment=phenomenon_alignment,
            )
        _append_slot_full_event(
            state,
            player_id=player_id,
            slot_kind="body_part",
            event_type="phenomenon_manifestation_expired_full_slot",
            card_id=card_id,
            card_name=card_name,
            body_part_category=body_part_category,
            phenomenon_alignment=phenomenon_alignment,
        )
        return state

    if phenomenon_alignment is None:
        raise ValueError(f"Cannot manifest phenomenon {card_id} without alignment metadata.")

    search_event_count = len(state.event_log)
    alignment_draw_entries = _get_body_part_alignment_draw_entries(
        state,
        alignment=phenomenon_alignment,
    )
    append_event(
        state.event_log,
        "phenomenon_manifestation_search_started",
        player_id=player_id,
        card_id=card_id,
        card_name=card_name,
        body_part_category=body_part_category,
        phenomenon_alignment=phenomenon_alignment,
        available_body_part_cards=len(alignment_draw_entries),
    )

    revealed_miss_global_indices: set[int] = set()
    revealed_misses: list[CardRef] = []
    matched_global_index: int | None = None
    matched_card: CardRef | None = None
    for reveal_index, (global_index, revealed_card) in enumerate(alignment_draw_entries, start=1):
        revealed_alignment = revealed_card.metadata.get("alignment")
        matches_requested_card = (
            revealed_card.category == body_part_category and revealed_alignment == phenomenon_alignment
        )
        append_event(
            state.event_log,
            "body_part_revealed_for_manifestation",
            player_id=player_id,
            card_id=card_id,
            requested_body_part_category=body_part_category,
            phenomenon_alignment=phenomenon_alignment,
            revealed_card_id=revealed_card.card_id,
            revealed_card_category=revealed_card.category,
            revealed_card_alignment=revealed_alignment,
            matches_requested_card=matches_requested_card,
            remaining_body_part_draw_pile=max(0, len(alignment_draw_entries) - reveal_index),
        )
        if not matches_requested_card:
            revealed_miss_global_indices.add(global_index)
            revealed_misses.append(revealed_card)
            continue
        matched_global_index = global_index
        matched_card = revealed_card
        break

    if matched_card is not None and matched_global_index is not None:
        remaining_alignment_cards = [
            card
            for entry_global_index, card in alignment_draw_entries
            if entry_global_index != matched_global_index and entry_global_index not in revealed_miss_global_indices
        ]
        replacement_alignment_cards = _reshuffle_body_part_alignment_cards(
            revealed_misses + remaining_alignment_cards,
            state=state,
            player_id=player_id,
            card_id=card_id,
            body_part_category=body_part_category,
            phenomenon_alignment=phenomenon_alignment,
            search_event_count=search_event_count,
        )
        _rewrite_body_part_alignment_draw_pile(
            state,
            alignment=phenomenon_alignment,
            replacement_cards=replacement_alignment_cards,
            removed_global_index=matched_global_index,
        )

        matched_card.metadata = dict(matched_card.metadata)
        matched_card.metadata["manifested"] = True
        matched_card.metadata["manifested_from_phenomenon_id"] = card_id
        player.tableau.append(matched_card)
        _record_manifested_body_part(player, body_part_category=body_part_category)
        _apply_body_part_entry_effects(
            state,
            player_id=player_id,
            body_part_category=body_part_category,
            source="phenomenon_manifestation",
        )
        append_event(
            state.event_log,
            "phenomenon_body_part_manifested",
            player_id=player_id,
            card_id=card_id,
            card_name=card_name,
            body_part_category=body_part_category,
            manifested_card_id=matched_card.card_id,
            phenomenon_alignment=phenomenon_alignment,
            manifestation_source="draw_pile",
            template_card_id=matched_card.card_id,
            tableau_size=len(player.tableau),
        )
        _apply_manifested_part_alignment_update(
            state,
            player_id=player_id,
            card_id=card_id,
            body_part_category=body_part_category,
            manifestation_alignment=phenomenon_alignment,
        )
        maybe_start_endgame_countdown(
            state,
            trigger_source="phenomenon_manifestation",
            preferred_player_id=player_id,
        )
        return state

    replacement_alignment_cards = _reshuffle_body_part_alignment_cards(
        revealed_misses,
        state=state,
        player_id=player_id,
        card_id=card_id,
        body_part_category=body_part_category,
        phenomenon_alignment=phenomenon_alignment,
        search_event_count=search_event_count,
    )
    _rewrite_body_part_alignment_draw_pile(
        state,
        alignment=phenomenon_alignment,
        replacement_cards=replacement_alignment_cards,
    )
    append_event(
        state.event_log,
        "phenomenon_manifestation_expired_no_matching_card",
        player_id=player_id,
        card_id=card_id,
        card_name=card_name,
        body_part_category=body_part_category,
        phenomenon_alignment=phenomenon_alignment,
        body_part_discard_size=len(state.body_part_discard_pile),
    )
    return state


def _apply_manifested_part_alignment_update(
    state: GameState,
    *,
    player_id: str,
    card_id: str,
    body_part_category: str,
    manifestation_alignment: str,
) -> None:
    player = state.players[player_id]
    _ensure_manifested_part_counters(player)
    existing_manifested_counts = {
        alignment: max(0, int(player.manifested_parts_counts.get(alignment, 0) or 0))
        for alignment in MANIFEST_ALIGNMENT_KEYS
    }

    previous_alignment = player.alignment
    manifest_alignment_supported = manifestation_alignment in MANIFEST_ALIGNMENT_KEYS
    tableau_manifested_counts = _count_manifested_part_counters_from_tableau(player)
    existing_manifested_total = sum(existing_manifested_counts.values())
    if existing_manifested_total <= 0 and sum(tableau_manifested_counts.values()) > 0:
        player.manifested_parts_counts = tableau_manifested_counts
    else:
        player.manifested_parts_counts = existing_manifested_counts
        if manifest_alignment_supported:
            player.manifested_parts_counts[manifestation_alignment] += 1

    computed_alignment, alignment_resolution = _compute_alignment_with_resolution(player.manifested_parts_counts)
    alignment_update_applied = False
    if computed_alignment != player.alignment:
        apply_alignment_change(
            state,
            player_id=player_id,
            new_alignment=computed_alignment,
        )
        alignment_update_applied = True
    append_event(
        state.event_log,
        "alignment_updated",
        player=player_id,
        player_id=player_id,
        source="phenomenon_manifestation",
        card_id=card_id,
        previous_alignment=previous_alignment,
        computed_alignment=computed_alignment,
        new_alignment=player.alignment,
        alignment_update_applied=alignment_update_applied,
        alignment_resolution=alignment_resolution,
        manifested_counts=dict(player.manifested_parts_counts),
        manifested_parts_counts=dict(player.manifested_parts_counts),
    )

    append_event(
        state.event_log,
        "body_part_manifested",
        player_id=player_id,
        card_id=card_id,
        body_part_category=body_part_category,
        part_type=MANIFESTABLE_BODY_PART_CATEGORIES.get(body_part_category, body_part_category),
        manifestation_alignment=manifestation_alignment,
        part_alignment=manifestation_alignment,
        manifested_parts_counts=dict(player.manifested_parts_counts),
        body_parts=sorted(_get_player_body_parts(player)),
        previous_alignment=previous_alignment,
        computed_alignment=computed_alignment,
        new_alignment=player.alignment,
        manifest_alignment_supported=manifest_alignment_supported,
        alignment_update_applied=alignment_update_applied,
        alignment_resolution=alignment_resolution,
    )


def _apply_body_part_entry_effects(
    state: GameState,
    *,
    player_id: str,
    body_part_category: str,
    source: str,
) -> None:
    if body_part_category == "Körperteil Kopf":
        _enforce_head_truth_seven_invariant(
            state,
            player_id=player_id,
            source=source,
            assume_head_defined=True,
        )


def _ensure_manifested_part_counters(player: PlayerState) -> None:
    for alignment in MANIFEST_ALIGNMENT_KEYS:
        if alignment not in player.manifested_parts_counts:
            player.manifested_parts_counts[alignment] = 0


def _count_manifested_part_counters_from_tableau(player: PlayerState) -> dict[str, int]:
    rebuilt_counts = {alignment: 0 for alignment in MANIFEST_ALIGNMENT_KEYS}
    for card in player.tableau:
        if card.category not in MANIFESTABLE_BODY_PART_CATEGORIES:
            continue
        card_alignment = _get_card_alignment_from_card(card)
        if card_alignment in rebuilt_counts:
            rebuilt_counts[card_alignment] += 1
    return rebuilt_counts


def has_free_phenomenon_slot(state: GameState, *, player_id: str) -> bool:
    return _has_free_slot(state.players[player_id], slot_kind="phenomena")


def _get_role_card_count(player: PlayerState, *, role_type: str) -> int:
    return sum(1 for card in player.tableau if card.category == role_type)


def _get_role_slot_limit(player: PlayerState, *, role_type: str) -> int:
    if role_type == "Mönche":
        return player.monks_slots
    if role_type == "Missionare":
        return player.missionaries_slots
    if role_type == "Nonnen":
        return player.nuns_slots
    raise ValueError(f"Unsupported role type {role_type}.")


def _sync_role_slot_assignments(
    state: GameState,
    *,
    player_id: str,
    log_slot_loss: bool = False,
    reason: str | None = None,
) -> GameState:
    player = state.players[player_id]

    for role_type in ROLE_TYPES:
        role_card_count = _get_role_card_count(player, role_type=role_type)
        tracked_role_card_count = max(0, player.tracked_role_card_counts.get(role_type, 0))
        assigned_role_meeples = max(0, player.assigned_role_meeples.get(role_type, 0))
        slot_limit = _get_role_slot_limit(player, role_type=role_type)
        max_assignable_meeples = slot_limit
        next_assigned_role_meeples = min(assigned_role_meeples, max_assignable_meeples)
        returned_meeples = max(0, assigned_role_meeples - next_assigned_role_meeples)
        # Capacity loss returns surplus figures even when a relic protects
        # temple figures from effect-driven loss (D-012).
        if returned_meeples > 0:
            player.meeples += returned_meeples

        newly_added_role_cards = max(0, role_card_count - tracked_role_card_count)
        temple_refill_blocked = _player_has_active_enlightener_rule_text(
            state,
            player_id=player_id,
            text=ENLIGHTENER_CANNOT_REFILL_TEMPLES_TEXT,
        )
        assignable_free_meeples = max(0, player.meeples)
        assignable_new_role_meeples = 0
        if not temple_refill_blocked:
            assignable_new_role_meeples = min(
                newly_added_role_cards,
                max(0, max_assignable_meeples - next_assigned_role_meeples),
                assignable_free_meeples,
            )
        if assignable_new_role_meeples > 0:
            next_assigned_role_meeples += assignable_new_role_meeples
            player.meeples -= assignable_new_role_meeples

        player.assigned_role_meeples[role_type] = next_assigned_role_meeples
        player.tracked_role_card_counts[role_type] = role_card_count

        if log_slot_loss and returned_meeples > 0:
            append_event(
                state.event_log,
                "role_slot_meeples_returned_due_to_slot_loss",
                player_id=player_id,
                role_type=role_type,
                returned_meeples=returned_meeples,
                remaining_assigned_role_meeples=next_assigned_role_meeples,
                role_card_count=role_card_count,
                slot_limit=slot_limit,
                reason=reason or "slot_loss",
            )

    assigned_nuns = max(0, int(player.assigned_role_meeples.get("Nonnen", 0)))
    prepared_nuns = max(0, int(player.nunnery_state.prepared_nuns))
    prepared_nun_limit = min(assigned_nuns, max(0, int(player.nuns_slots)))
    if assigned_nuns > 0 and prepared_nuns > prepared_nun_limit:
        removed_prepared_nuns = prepared_nuns - prepared_nun_limit
        player.nunnery_state.prepared_nuns = prepared_nun_limit
        player.nunnery_state.sacrificed_nuns += removed_prepared_nuns
        if log_slot_loss:
            append_event(
                state.event_log,
                "role_slot_meeples_returned_due_to_slot_loss",
                player_id=player_id,
                role_type="Nonnen",
                returned_meeples=0,
                remaining_assigned_role_meeples=assigned_nuns,
                role_card_count=_get_role_card_count(player, role_type="Nonnen"),
                slot_limit=max(0, int(player.nuns_slots)),
                reason=reason or "slot_loss",
                removed_prepared_nuns=removed_prepared_nuns,
            )

    return state


def _get_assigned_role_meeples(state: GameState, *, player_id: str, role_type: str) -> int:
    _sync_role_slot_assignments(state, player_id=player_id)
    return state.players[player_id].assigned_role_meeples.get(role_type, 0)


def _normalize_meeple_payment_choice(
    payment_choice: dict[str, Any] | None,
    *,
    context: str,
) -> dict[str, Any]:
    if payment_choice is None:
        return {
            "role_meeples": {role_type: 0 for role_type in ROLE_TYPES},
            "prepared_nuns": 0,
        }
    if not isinstance(payment_choice, dict):
        raise ValueError(f"{context} must be a dict when provided.")

    raw_role_meeples = payment_choice.get("role_meeples", {})
    if raw_role_meeples is None:
        raw_role_meeples = {}
    if not isinstance(raw_role_meeples, dict):
        raise ValueError(f"{context}.role_meeples must be a dict when provided.")

    normalized_role_meeples = {role_type: 0 for role_type in ROLE_TYPES}
    for role_type, raw_amount in raw_role_meeples.items():
        if role_type not in ROLE_TYPES:
            raise ValueError(f"{context} uses unsupported role_type {role_type}.")
        if not isinstance(raw_amount, int) or raw_amount < 0:
            raise ValueError(f"{context}.role_meeples[{role_type}] must be a non-negative integer.")
        normalized_role_meeples[role_type] = raw_amount

    prepared_nuns = payment_choice.get("prepared_nuns", 0)
    if not isinstance(prepared_nuns, int) or prepared_nuns < 0:
        raise ValueError(f"{context}.prepared_nuns must be a non-negative integer.")

    return {
        "role_meeples": normalized_role_meeples,
        "prepared_nuns": prepared_nuns,
    }


def _count_bound_meeples_in_payment_choice(payment_choice: dict[str, Any]) -> int:
    return int(payment_choice.get("prepared_nuns", 0)) + sum(
        int(amount) for amount in payment_choice.get("role_meeples", {}).values()
    )


def _sacrifice_prepared_nuns_from_player(
    player: PlayerState,
    amount: int,
    *,
    context: str,
) -> None:
    if amount < 0:
        raise ValueError(f"{context} cannot sacrifice a negative number of prepared nuns.")
    prepared_nuns = max(0, int(player.nunnery_state.prepared_nuns))
    assigned_nuns = max(0, int(player.assigned_role_meeples.get("Nonnen", 0)))
    if amount > prepared_nuns or amount > assigned_nuns:
        raise ValueError(
            f"{context} cannot sacrifice {amount} prepared nun(s); "
            f"only {prepared_nuns} prepared and {assigned_nuns} assigned."
        )
    player.nunnery_state.prepared_nuns = prepared_nuns - amount
    player.nunnery_state.sacrificed_nuns += amount
    player.assigned_role_meeples["Nonnen"] = assigned_nuns - amount


def _spend_assigned_role_meeples_from_player(
    player: PlayerState,
    role_type: str,
    amount: int,
) -> None:
    if amount <= 0:
        return
    assigned_amount = max(0, int(player.assigned_role_meeples.get(role_type, 0)))
    if amount > assigned_amount:
        raise ValueError(
            f"Cannot spend {amount} bound meeple(s) from role {role_type}; only {assigned_amount} available."
        )
    if role_type != "Nonnen":
        player.assigned_role_meeples[role_type] = assigned_amount - amount
        return

    prepared_nuns = max(0, int(player.nunnery_state.prepared_nuns))
    unprepared_nuns = max(0, assigned_amount - prepared_nuns)
    prepared_nuns_removed = max(0, amount - unprepared_nuns)
    player.assigned_role_meeples["Nonnen"] = assigned_amount - amount
    if prepared_nuns_removed > 0:
        player.nunnery_state.prepared_nuns = prepared_nuns - prepared_nuns_removed
        player.nunnery_state.sacrificed_nuns += prepared_nuns_removed


def _spend_player_meeples(
    state: GameState,
    *,
    player_id: str,
    amount: int,
    strict: bool,
    payment_choice: dict[str, Any] | None,
    purpose: str,
    trigger_large_sacrifice: bool = True,
) -> dict[str, Any]:
    if amount < 0:
        raise ValueError(f"{purpose} cannot spend a negative meeple amount.")

    player = state.players[player_id]
    _sync_role_slot_assignments(state, player_id=player_id)
    normalized_payment_choice = _normalize_meeple_payment_choice(payment_choice, context=purpose)
    requested_role_meeples = dict(normalized_payment_choice["role_meeples"])
    requested_prepared_nuns = int(normalized_payment_choice["prepared_nuns"])
    requested_bound_total = _count_bound_meeples_in_payment_choice(normalized_payment_choice)
    if (
        _player_has_temple_loss_protection_relic(state, player_id=player_id)
        and (requested_bound_total > 0 or requested_prepared_nuns > 0)
    ):
        raise ValueError(
            f"Player {player_id} cannot spend temple-bound meeples for {purpose}; temples are protected by relic effect."
        )
    if requested_bound_total > amount:
        raise ValueError(f"{purpose} cannot spend more bound meeples than the required amount {amount}.")

    for role_type, requested_amount in requested_role_meeples.items():
        available_amount = player.assigned_role_meeples.get(role_type, 0)
        if requested_amount > available_amount:
            raise ValueError(
                f"Player {player_id} cannot spend {requested_amount} bound meeple(s) from role {role_type} for {purpose}; only {available_amount} available."
            )

    if requested_prepared_nuns > player.nunnery_state.prepared_nuns:
        raise ValueError(
            f"Player {player_id} cannot spend {requested_prepared_nuns} prepared nun(s) for {purpose}; only {player.nunnery_state.prepared_nuns} available."
        )
    requested_nun_role_meeples = int(requested_role_meeples.get("Nonnen", 0))
    assigned_nuns = max(0, int(player.assigned_role_meeples.get("Nonnen", 0)))
    if requested_nun_role_meeples + requested_prepared_nuns > assigned_nuns:
        raise ValueError(
            f"Player {player_id} cannot spend {requested_nun_role_meeples} bound nun(s) and "
            f"{requested_prepared_nuns} prepared nun(s) for {purpose}; only {assigned_nuns} assigned nun(s) available."
        )

    free_meeples_available = player.meeples
    total_available = free_meeples_available + requested_bound_total
    if strict and total_available < amount:
        raise ValueError(
            f"Player {player_id} cannot pay {amount} meeple(s) for {purpose}; only {total_available} available including explicit bound selections."
        )

    paid_total = amount if strict else min(amount, total_available)
    free_meeples_paid = max(0, paid_total - requested_bound_total)
    player.meeples -= free_meeples_paid

    for role_type, requested_amount in requested_role_meeples.items():
        _spend_assigned_role_meeples_from_player(player, role_type, requested_amount)

    if requested_prepared_nuns > 0:
        _sacrifice_prepared_nuns_from_player(player, requested_prepared_nuns, context=purpose)

    if trigger_large_sacrifice:
        _trigger_relic_large_sacrifice_missionize(
            state,
            sacrificing_player_id=player_id,
            paid_total=paid_total,
            purpose=purpose,
        )

    return {
        "paid_total": paid_total,
        "free_meeples_paid": free_meeples_paid,
        "role_meeples_paid": requested_role_meeples,
        "prepared_nuns_paid": requested_prepared_nuns,
    }


def _trigger_relic_large_sacrifice_missionize(
    state: GameState,
    *,
    sacrificing_player_id: str,
    paid_total: int,
    purpose: str,
) -> None:
    if paid_total < 3:
        return

    for candidate_player_id in state.player_order:
        if get_player_relation(
            state,
            source_player_id=candidate_player_id,
            target_player_id=sacrificing_player_id,
        ) != "opponent":
            continue
        if not _player_has_active_relic_rule_text(
            state,
            player_id=candidate_player_id,
            text=RELIC_MISSIONIZE_ON_OPPONENT_LARGE_SACRIFICE_TEXT,
        ):
            continue

        beneficiary = state.players[candidate_player_id]
        beneficiary.meeples += 1
        append_event(
            state.event_log,
            "relic_large_sacrifice_triggered",
            player_id=candidate_player_id,
            source_player_id=sacrificing_player_id,
            paid_total=paid_total,
            purpose=purpose,
            actual_transfer=1,
            decision_source="auto_policy",
            player_meeples_after=beneficiary.meeples,
        )


def _has_free_slot(
    player: PlayerState,
    *,
    slot_kind: str,
    body_part_category: str | None = None,
) -> bool:
    return _get_slot_occupancy(
        player,
        slot_kind=slot_kind,
        body_part_category=body_part_category,
    ) < _get_slot_limit(
        player,
        slot_kind=slot_kind,
        body_part_category=body_part_category,
    )


def _get_slot_occupancy(
    player: PlayerState,
    *,
    slot_kind: str,
    body_part_category: str | None = None,
) -> int:
    if slot_kind == "phenomena":
        return len(player.stored_phenomena)
    if slot_kind == "prepared_nuns":
        return player.nunnery_state.prepared_nuns
    if slot_kind == "forge":
        return sum(1 for card in player.tableau if card.category == "Monument")
    if slot_kind == "enlighteners":
        return sum(1 for card in player.tableau if card.category == "Aufklärer")
    if slot_kind == "relics":
        return sum(1 for card in player.tableau if card.category == "Reliquie")
    if slot_kind == "body_part":
        if body_part_category is None:
            raise ValueError("body_part_category is required for body part slot checks.")
        return sum(1 for card in player.tableau if card.category == body_part_category)
    raise ValueError(f"Unsupported slot kind {slot_kind}.")


def _get_slot_limit(
    player: PlayerState,
    *,
    slot_kind: str,
    body_part_category: str | None = None,
) -> int:
    if slot_kind == "phenomena":
        return 3 if player.alignment == "<Zorn>" else 2
    if slot_kind == "prepared_nuns":
        return max(0, int(player.nuns_slots))
    if slot_kind == "forge":
        return player.forge_slots
    if slot_kind == "enlighteners":
        return 2
    if slot_kind == "relics":
        return 2 if _player_has_defined_chest(player) else 1
    if slot_kind == "body_part":
        if body_part_category is None:
            raise ValueError("body_part_category is required for body part slot checks.")
        return 1
    raise ValueError(f"Unsupported slot kind {slot_kind}.")


def _get_phenomena_slot_limit(player: PlayerState) -> int:
    return _get_slot_limit(player, slot_kind="phenomena")


def _append_slot_full_event(
    state: GameState,
    *,
    player_id: str,
    slot_kind: str,
    event_type: str,
    **payload: Any,
) -> None:
    player = state.players[player_id]
    body_part_category = payload.get("body_part_category")
    append_event(
        state.event_log,
        event_type,
        player_id=player_id,
        slot_kind=slot_kind,
        slot_occupancy=_get_slot_occupancy(
            player,
            slot_kind=slot_kind,
            body_part_category=body_part_category if isinstance(body_part_category, str) else None,
        ),
        slot_limit=_get_slot_limit(
            player,
            slot_kind=slot_kind,
            body_part_category=body_part_category if isinstance(body_part_category, str) else None,
        ),
        reason="slot_occupied",
        **payload,
    )


def _activate_commandment(
    state: GameState,
    *,
    card_id: str,
    card_name: str | None = None,
) -> CardRef:
    if len(state.active_commandments) >= MAX_ACTIVE_COMMANDMENTS:
        raise ValueError(
            f"Cannot activate commandment {card_id}: maximum of {MAX_ACTIVE_COMMANDMENTS} active commandments reached."
        )
    if any(active.card_id == card_id for active in state.active_commandments):
        raise ValueError(f"Cannot activate duplicate commandment {card_id} while it is already active.")

    draw_pile_index = next(
        (index for index, available in enumerate(state.commandment_draw_pile) if available.card_id == card_id),
        None,
    )
    if draw_pile_index is not None:
        drawn_commandment = state.commandment_draw_pile.pop(draw_pile_index)
        resolved_name = card_name or drawn_commandment.name
        metadata = dict(drawn_commandment.metadata)
    else:
        resolved_name = card_name or card_id
        metadata = {}

    commandment = CardRef(
        card_id=card_id,
        name=resolved_name,
        category="Gebote",
        metadata=metadata,
    )
    state.active_commandments.append(commandment)
    recalculate_commandment_effects(state)
    return commandment


def _discard_unselected_commandment_offers(
    state: GameState,
    *,
    offered_cards: list[CardRef],
    selected_card_id: str,
) -> list[str]:
    discarded_card_ids: list[str] = []
    for offered_card in offered_cards:
        if offered_card.card_id == selected_card_id:
            continue
        draw_pile_index = next(
            (
                index
                for index, draw_pile_card in enumerate(state.commandment_draw_pile)
                if draw_pile_card.card_id == offered_card.card_id
            ),
            None,
        )
        if draw_pile_index is None:
            continue
        discarded_card = state.commandment_draw_pile.pop(draw_pile_index)
        state.commandment_discard_pile.append(discarded_card)
        discarded_card_ids.append(discarded_card.card_id)
    return discarded_card_ids


def use_truth(state: GameState, *, player_id: str, value: int) -> GameState:
    player = state.players[player_id]
    if value not in player.truth_pool:
        raise ValueError(f"Truth value {value} is not currently available for player {player_id}.")

    player.truth_pool.remove(value)
    player.used_truth.append(value)
    player.truth_pool.sort()
    player.used_truth.sort()
    append_event(state.event_log, "truth_used", player_id=player_id, value=value)
    _maybe_reset_truth_after_exhaustion(state, player_id=player_id)
    return state


def _discard_truth_value_to_discard(
    state: GameState,
    *,
    player_id: str,
    value: int,
    discard_card: CardRef,
) -> GameState:
    player = state.players[player_id]
    if value not in player.truth_pool:
        raise ValueError(f"Truth value {value} is not currently available for player {player_id}.")

    player.truth_pool.remove(value)
    player.used_truth.append(value)
    player.truth_pool.sort()
    player.used_truth.sort()
    _append_truth_discard_card(state, player_id=player_id, card=discard_card)
    append_event(
        state.event_log,
        "truth_discarded",
        player_id=player_id,
        value=value,
        card_id=discard_card.card_id,
    )
    _maybe_reset_truth_after_exhaustion(state, player_id=player_id)
    return state


def reset_truth(state: GameState, *, player_id: str) -> GameState:
    player = state.players[player_id]
    _enforce_head_truth_seven_invariant(
        state,
        player_id=player_id,
        source="truth_reset",
    )
    restored_truth_values = [
        _get_truth_card_pool_value(discarded_card)
        for discarded_card in player.truth_discard
        if not _truth_discard_card_counts_as_used_truth(discarded_card)
    ]
    restored_truth_card_ids = _clear_truth_discard_for_player(state, player_id=player_id)
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


def _enforce_head_truth_seven_invariant(
    state: GameState,
    *,
    player_id: str,
    source: str,
    assume_head_defined: bool = False,
) -> int:
    player = state.players[player_id]
    if not assume_head_defined and not _player_has_defined_head(player):
        return 0

    removal_count = 0
    removal_predicates: tuple[tuple[str, Any], ...] = (
        ("truth_pool", lambda: 7 in player.truth_pool),
        ("used_truth", lambda: 7 in player.used_truth),
        (
            "truth_discard",
            lambda: any(
                card.category == "Wahrheit" and int(card.truth_value or -1) == 7
                for card in player.truth_discard
            ),
        ),
        (
            "hand",
            lambda: any(
                card.category == "Wahrheit" and int(card.truth_value or -1) == 7
                for card in player.hand_cards
            ),
        ),
    )

    for preferred_source, has_truth_seven in removal_predicates:
        while has_truth_seven():
            _remove_truth_value(
                state,
                player_id=player_id,
                value=7,
                source=source,
                preferred_source=preferred_source,
            )
            removal_count += 1

    return removal_count


def _enforce_head_truth_seven_invariants(
    state: GameState,
    *,
    source: str,
) -> None:
    for player_id in state.players:
        _enforce_head_truth_seven_invariant(
            state,
            player_id=player_id,
            source=source,
        )


def _maybe_reset_truth_after_exhaustion(state: GameState, *, player_id: str) -> GameState:
    player = state.players[player_id]
    if player.truth_pool:
        return state
    if not player.used_truth:
        return state
    return reset_truth(state, player_id=player_id)


def commit_grenade_meeple(
    state: GameState,
    *,
    player_id: str,
    detonate: bool = False,
    effect_payload: dict[str, Any] | None = None,
    decision_source: str | None = None,
) -> GameState:
    if state.beginner_mode:
        raise ValueError("Hand grenades are disabled in beginner mode.")
    player = state.players[player_id]
    grenade_state = player.hand_grenade_state

    if grenade_state.grenade is None:
        raise ValueError(f"Player {player_id} has not drafted a hand grenade yet.")
    if grenade_state.used:
        raise ValueError(f"Player {player_id} has already used their hand grenade.")
    if player.meeples < 1:
        raise ValueError(f"Player {player_id} needs one free believer to charge their hand grenade.")

    next_tier = min(3, grenade_state.meeples_committed + 1)
    next_effect = grenade_state.grenade.tier_effects.get(next_tier, {})
    if (detonate or next_tier == 3) and next_effect.get("effect") == "forced_total_sacrifice":
        _validate_free_believer_target_payments(
            state, player_id=player_id, effect_payload=effect_payload or {}, context="Kalte Rache",
        )
    if (detonate or next_tier == 3) and next_effect.get("effect") == "shatter_commandments":
        _grenade_commandment_choices(
            state, player_id=player_id, grenade_id=grenade_state.grenade.card_id,
            count=int(next_effect.get("count") or 0),
            play_prophet=bool(next_effect.get("award_prophet")), effect_payload=effect_payload or {},
        )
    player.meeples -= 1
    grenade_state.meeples_committed += 1
    current_tier = grenade_state.meeples_committed
    append_event(
        state.event_log,
        "grenade_meeple_committed",
        player_id=player_id,
        committed=current_tier,
        free_meeples_after=player.meeples,
        grenade_id=grenade_state.grenade.card_id,
        detonation_window_open=current_tier in {1, 2},
        detonation_required=current_tier >= 3,
        manual_detonation_requested=detonate,
        decision_source=decision_source,
    )

    if current_tier >= 3:
        return _detonate_grenade(
            state,
            player_id=player_id,
            tier=3,
            automatic=True,
            effect_payload=effect_payload,
            decision_source=decision_source,
        )
    if detonate:
        return _detonate_grenade(
            state,
            player_id=player_id,
            tier=current_tier,
            automatic=False,
            effect_payload=effect_payload,
            decision_source=decision_source,
        )

    return state


def _resolve_grenade_action(
    state: GameState,
    *,
    player_id: str,
    target_level: int,
    detonate: bool,
    effect_payload: dict[str, Any] | None = None,
    decision_source: str | None = None,
) -> int:
    grenade_state = state.players[player_id].hand_grenade_state
    current_level = max(0, int(grenade_state.meeples_committed))

    if target_level != current_level + 1:
        raise ValueError(
            f"Player {player_id} grenade action must advance exactly one level from {current_level} to {current_level + 1}."
        )

    commit_grenade_meeple(
        state,
        player_id=player_id,
        detonate=detonate,
        effect_payload=effect_payload,
        decision_source=decision_source,
    )
    return max(0, int(grenade_state.detonated_tier or grenade_state.meeples_committed))


def _detonate_grenade(
    state: GameState,
    *,
    player_id: str,
    tier: int,
    automatic: bool,
    effect_payload: dict[str, Any] | None = None,
    decision_source: str | None = None,
) -> GameState:
    player = state.players[player_id]
    grenade_state = player.hand_grenade_state
    grenade = grenade_state.grenade
    if grenade is None:
        raise ValueError(f"Player {player_id} has no grenade to detonate.")

    if grenade.tier_effects.get(tier, {}).get("effect") == "forced_total_sacrifice":
        _validate_free_believer_target_payments(
            state, player_id=player_id, effect_payload=effect_payload or {}, context="Kalte Rache",
        )
    grenade_state.used = True
    grenade_state.detonated_tier = tier

    append_event(
        state.event_log,
        "grenade_detonated",
        player_id=player_id,
        grenade_id=grenade.card_id,
        tier=tier,
        automatic=automatic,
        decision_source=decision_source,
    )

    effect = grenade.tier_effects.get(tier, {"effect": "log_only", "label": f"tier-{tier}"})
    append_event(
        state.event_log,
        "grenade_tier_effect_applied",
        player_id=player_id,
        grenade_id=grenade.card_id,
        tier=tier,
        effect=effect,
    )
    if effect.get("effect") != "log_only":
        _resolve_grenade_tier_effect(
            state,
            player_id=player_id,
            grenade_id=grenade.card_id,
            tier=tier,
            effect=effect,
            effect_payload=effect_payload or {},
            decision_source=decision_source,
        )
    return state


def _resolve_grenade_tier_effect(
    state: GameState,
    *,
    player_id: str,
    grenade_id: str,
    tier: int,
    effect: dict[str, Any],
    effect_payload: dict[str, Any],
    decision_source: str | None,
) -> None:
    effect_kind = str(effect.get("effect") or "log_only")
    if effect_kind == "forced_total_sacrifice":
        _resolve_grenade_forced_total_sacrifice(
            state,
            player_id=player_id,
            grenade_id=grenade_id,
            tier=tier,
            total_sacrifice=int(effect.get("total_sacrifice") or 0),
            effect_payload=effect_payload,
            decision_source=decision_source,
        )
        return
    if effect_kind == "forced_temple_role_wipe":
        _resolve_grenade_forced_temple_role_wipe(
            state,
            player_id=player_id,
            grenade_id=grenade_id,
            tier=tier,
            role_types=tuple(str(role_type) for role_type in effect.get("role_types", ())),
            effect_payload=effect_payload,
            decision_source=decision_source,
        )
        return
    if effect_kind == "destroy_stored_phenomena":
        _resolve_grenade_destroy_stored_phenomena(
            state,
            player_id=player_id,
            grenade_id=grenade_id,
            tier=tier,
            count=int(effect.get("count") or 0),
            same_owner_only=bool(effect.get("same_owner_only", False)),
            effect_payload=effect_payload,
            decision_source=decision_source,
        )
        return
    if effect_kind == "shatter_commandments":
        _resolve_grenade_shatter_commandments(
            state,
            player_id=player_id,
            grenade_id=grenade_id,
            tier=tier,
            count=int(effect.get("count") or 0),
            award_prophet_after=bool(effect.get("award_prophet", False)),
            effect_payload=effect_payload,
            decision_source=decision_source,
        )
        return
    if effect_kind == "destroy_relics":
        _resolve_grenade_destroy_relics(
            state,
            player_id=player_id,
            grenade_id=grenade_id,
            tier=tier,
            count=int(effect.get("count") or 0),
            same_owner_only=bool(effect.get("same_owner_only", False)),
            effect_payload=effect_payload,
            decision_source=decision_source,
        )
        return
    if effect_kind == "next_turn_action_penalty":
        _resolve_grenade_next_turn_penalty(
            state,
            player_id=player_id,
            grenade_id=grenade_id,
            tier=tier,
            penalty=int(effect.get("penalty") or 0),
            bonus_actions_granted=int(effect.get("bonus_actions_granted") or 0),
            skip_next_turn=bool(effect.get("skip_next_turn", False)),
            effect_payload=effect_payload,
            decision_source=decision_source,
        )
        return
    if effect_kind == "discard_truth":
        _resolve_grenade_discard_truth(
            state,
            player_id=player_id,
            grenade_id=grenade_id,
            tier=tier,
            count=None if bool(effect.get("discard_all", False)) else int(effect.get("count") or 0),
            discard_all=bool(effect.get("discard_all", False)),
            effect_payload=effect_payload,
            decision_source=decision_source,
        )
        return
    if effect_kind == "discard_heavenly":
        _resolve_grenade_discard_heavenly(
            state,
            player_id=player_id,
            grenade_id=grenade_id,
            tier=tier,
            count=int(effect.get("count") or 0),
            distributed=bool(effect.get("distributed", False)),
            effect_payload=effect_payload,
            decision_source=decision_source,
        )
        return
    if effect_kind == "play_free_enlighteners":
        _resolve_grenade_play_free_enlighteners(
            state,
            player_id=player_id,
            grenade_id=grenade_id,
            tier=tier,
            count=int(effect.get("count") or 0),
            require_overwrite=bool(effect.get("require_overwrite", False)),
            distributed=bool(effect.get("distributed", False)),
            effect_payload=effect_payload,
            decision_source=decision_source,
        )
        return

    raise ValueError(f"Grenade {grenade_id} tier {tier} uses unsupported effect {effect_kind}.")


def _build_auto_grenade_payment_choice(
    state: GameState,
    *,
    player_id: str,
    amount: int,
) -> dict[str, Any] | None:
    if amount <= 0:
        return None
    if _player_has_temple_loss_protection_relic(state, player_id=player_id):
        return None

    player = state.players[player_id]
    remaining = max(0, amount - player.meeples)
    if remaining <= 0:
        return None

    choice = {
        "role_meeples": {role_type: 0 for role_type in ROLE_TYPES},
        "prepared_nuns": 0,
    }
    for role_type in ("Mönche", "Missionare", "Nonnen"):
        available_amount = player.assigned_role_meeples.get(role_type, 0)
        chosen_amount = min(remaining, available_amount)
        choice["role_meeples"][role_type] = chosen_amount
        remaining -= chosen_amount
        if remaining <= 0:
            break
    if remaining > 0:
        choice["prepared_nuns"] = min(remaining, player.nunnery_state.prepared_nuns)
    return choice if _count_bound_meeples_in_payment_choice(choice) > 0 else None


def _remove_role_units_from_target_player(
    state: GameState,
    *,
    target_player_id: str,
    role_types: tuple[str, ...],
) -> dict[str, Any]:
    target_player = state.players[target_player_id]
    removed_by_role = {role_type: 0 for role_type in ROLE_TYPES}
    removed_prepared_nuns = 0

    if _player_has_temple_loss_protection_relic(state, player_id=target_player_id):
        return {
            "decision_source": "temple_protected",
            "removed_by_role": removed_by_role,
            "removed_prepared_nuns": 0,
            "total_removed": 0,
        }

    requested_total = sum(target_player.assigned_role_meeples.get(role_type, 0) for role_type in role_types)
    if "Nonnen" in role_types:
        requested_total += target_player.nunnery_state.prepared_nuns
    effective_total = _apply_sacrifice_cost_reduction(
        state,
        player_id=target_player_id,
        amount=requested_total,
    )
    if effective_total < requested_total:
        remaining = effective_total
        for role_type in role_types:
            if remaining <= 0:
                break
            assigned_amount = target_player.assigned_role_meeples.get(role_type, 0)
            if role_type != "Nonnen":
                removed = min(assigned_amount, remaining)
                if removed > 0:
                    target_player.assigned_role_meeples[role_type] = assigned_amount - removed
                    removed_by_role[role_type] = removed
                    remaining -= removed
                continue

            prepared_nuns = target_player.nunnery_state.prepared_nuns
            unprepared_nuns = max(0, assigned_amount - prepared_nuns)
            removed_unprepared = min(unprepared_nuns, remaining)
            removed_prepared = min(prepared_nuns, max(0, remaining - removed_unprepared))
            removed = removed_unprepared + removed_prepared
            if removed > 0:
                target_player.assigned_role_meeples["Nonnen"] = assigned_amount - removed
                target_player.nunnery_state.prepared_nuns = prepared_nuns - removed_prepared
                target_player.nunnery_state.sacrificed_nuns += removed_prepared
                removed_by_role["Nonnen"] = removed
                removed_prepared_nuns = removed_prepared
                remaining -= removed

        total_removed = sum(removed_by_role.values()) + removed_prepared_nuns
        return {
            "decision_source": "effect_applied",
            "removed_by_role": removed_by_role,
            "removed_prepared_nuns": removed_prepared_nuns,
            "requested_sacrifice_total": requested_total,
            "effective_sacrifice_total": effective_total,
            "total_removed": total_removed,
        }

    for role_type in role_types:
        assigned_amount = target_player.assigned_role_meeples.get(role_type, 0)
        if assigned_amount > 0:
            target_player.assigned_role_meeples[role_type] = 0
            removed_by_role[role_type] = assigned_amount
        if role_type == "Nonnen" and target_player.nunnery_state.prepared_nuns > 0:
            removed_prepared_nuns = target_player.nunnery_state.prepared_nuns
            target_player.nunnery_state.prepared_nuns = 0
            target_player.nunnery_state.sacrificed_nuns += removed_prepared_nuns

    total_removed = sum(removed_by_role.values()) + removed_prepared_nuns
    return {
        "decision_source": "effect_applied",
        "removed_by_role": removed_by_role,
        "removed_prepared_nuns": removed_prepared_nuns,
        "requested_sacrifice_total": requested_total,
        "effective_sacrifice_total": effective_total,
        "total_removed": total_removed,
    }


def _destroy_relic_for_grenade(
    state: GameState,
    *,
    target_player_id: str,
    target_card_id: str,
) -> CardRef:
    removed_relic = _pop_card_from_tableau(state.players[target_player_id], card_id=target_card_id)
    state.heavenly_discard_pile.append(removed_relic)
    return removed_relic


def _discard_stored_phenomenon_for_grenade(
    state: GameState,
    *,
    target_player_id: str,
    phenomenon_card_id: str,
    grenade_id: str,
) -> None:
    target_player = state.players[target_player_id]
    if phenomenon_card_id not in target_player.stored_phenomena:
        raise ValueError(f"Player {target_player_id} does not have stored phenomenon {phenomenon_card_id}.")
    stored_before = list(target_player.stored_phenomena)
    target_player.stored_phenomena.remove(phenomenon_card_id)
    if phenomenon_card_id in target_player.used_phenomenon_powers:
        target_player.used_phenomenon_powers = [
            used_card_id
            for used_card_id in target_player.used_phenomenon_powers
            if used_card_id != phenomenon_card_id
        ]
    state.phenomenon_discard.append(phenomenon_card_id)
    append_event(
        state.event_log,
        "stored_phenomenon_removed_by_grenade",
        player_id=target_player_id,
        grenade_id=grenade_id,
        phenomenon_id=phenomenon_card_id,
        card_id=phenomenon_card_id,
        stored_before=stored_before,
        stored_after=list(target_player.stored_phenomena),
        remaining_stored_phenomena=list(target_player.stored_phenomena),
        phenomenon_discard_size=len(state.phenomenon_discard),
    )


def _resolve_grenade_forced_total_sacrifice(
    state: GameState,
    *,
    player_id: str,
    grenade_id: str,
    tier: int,
    total_sacrifice: int,
    effect_payload: dict[str, Any],
    decision_source: str | None,
) -> None:
    opponent_ids = _get_opponent_player_ids_in_turn_order(state, player_id=player_id)
    raw_target_player_ids = effect_payload.get("target_player_ids")
    if raw_target_player_ids is not None:
        if not isinstance(raw_target_player_ids, list) or not all(isinstance(entry, str) for entry in raw_target_player_ids):
            raise ValueError(f"Grenade {grenade_id} target_player_ids must be a list of strings.")
        if any(target_player_id not in opponent_ids for target_player_id in raw_target_player_ids):
            raise ValueError(f"Grenade {grenade_id} target_player_ids must be opponents of {player_id}.")
        target_player_ids = list(raw_target_player_ids)
        target_decision_source = "explicit_intent"
    else:
        target_player_ids = list(opponent_ids)
        target_decision_source = "auto_policy"

    if not target_player_ids:
        append_event(
            state.event_log,
            "grenade_tier_effect_fizzled",
            player_id=player_id,
            grenade_id=grenade_id,
            tier=tier,
            effect_kind="forced_total_sacrifice",
            reason="no_opponents",
            decision_source=decision_source,
        )
        return

    _validate_free_believer_target_payments(
        state, player_id=player_id, effect_payload=effect_payload, context="Kalte Rache",
    )
    raw_target_sacrifice_amounts = effect_payload.get("target_sacrifice_amounts", {})
    if not isinstance(raw_target_sacrifice_amounts, dict):
        raise ValueError(f"Grenade {grenade_id} target_sacrifice_amounts must be a dict when provided.")
    target_sacrifice_amounts: dict[str, int] = {}
    for target_player_id, raw_amount in raw_target_sacrifice_amounts.items():
        if target_player_id not in opponent_ids:
            raise ValueError(f"Grenade {grenade_id} target_sacrifice_amounts contains non-opponent {target_player_id}.")
        if not isinstance(raw_amount, int) or raw_amount < 0:
            raise ValueError(f"Grenade {grenade_id} sacrifice amount for target {target_player_id} must be a non-negative integer.")
        target_sacrifice_amounts[str(target_player_id)] = raw_amount
    explicit_sacrifice_amounts = bool(target_sacrifice_amounts)

    remaining = total_sacrifice
    total_sacrificed = 0
    for target_player_id in target_player_ids:
        if remaining <= 0:
            break
        requested_target_sacrifice = remaining
        if explicit_sacrifice_amounts:
            requested_target_sacrifice = min(remaining, target_sacrifice_amounts.get(target_player_id, 0))
            if requested_target_sacrifice <= 0:
                continue
        effective_target_sacrifice = _apply_sacrifice_cost_reduction(
            state,
            player_id=target_player_id,
            amount=requested_target_sacrifice,
        )
        payment_resolution = _spend_player_meeples(
            state,
            player_id=target_player_id,
            amount=effective_target_sacrifice,
            strict=False,
            payment_choice=None,
            purpose=f"grenade_{grenade_id}_forced_total_sacrifice",
        )
        actual_sacrifice = int(payment_resolution["paid_total"])
        remaining = max(0, remaining - actual_sacrifice)
        total_sacrificed += actual_sacrifice
        append_event(
            state.event_log,
            "grenade_tier_effect_target_resolved",
            player_id=player_id,
            target_player_id=target_player_id,
            grenade_id=grenade_id,
            tier=tier,
            effect_kind="forced_total_sacrifice",
            requested_sacrifice=requested_target_sacrifice,
            effective_sacrifice=effective_target_sacrifice,
            actual_sacrifice=actual_sacrifice,
            remaining_total_sacrifice=remaining,
            free_meeples_paid=payment_resolution["free_meeples_paid"],
            role_meeples_paid=dict(payment_resolution["role_meeples_paid"]),
            prepared_nuns_paid=payment_resolution["prepared_nuns_paid"],
            target_meeples_after=state.players[target_player_id].meeples,
            decision_source=target_decision_source,
        )

    append_event(
        state.event_log,
        "grenade_tier_effect_resolved",
        player_id=player_id,
        grenade_id=grenade_id,
        tier=tier,
        effect_kind="forced_total_sacrifice",
        requested_total_sacrifice=total_sacrifice,
        total_sacrificed=total_sacrificed,
        unresolved_sacrifice=max(0, total_sacrifice - total_sacrificed),
        target_player_ids=target_player_ids,
        decision_source=decision_source,
    )


def _resolve_grenade_forced_temple_role_wipe(
    state: GameState,
    *,
    player_id: str,
    grenade_id: str,
    tier: int,
    role_types: tuple[str, ...],
    effect_payload: dict[str, Any],
    decision_source: str | None,
) -> None:
    target_player_id = _resolve_stored_power_target_player_id_with_predicate(
        state,
        source_player_id=player_id,
        effect_payload=effect_payload,
        effect_label=grenade_id,
        predicate=lambda candidate_player: any(
            candidate_player.assigned_role_meeples.get(role_type, 0) > 0
            or (role_type == "Nonnen" and candidate_player.nunnery_state.prepared_nuns > 0)
            for role_type in role_types
        ),
    )
    if target_player_id is None:
        append_event(
            state.event_log,
            "grenade_tier_effect_fizzled",
            player_id=player_id,
            grenade_id=grenade_id,
            tier=tier,
            effect_kind="forced_temple_role_wipe",
            reason="no_target_with_matching_role_units",
            decision_source=decision_source,
        )
        return

    removal = _remove_role_units_from_target_player(
        state,
        target_player_id=target_player_id,
        role_types=role_types,
    )
    append_event(
        state.event_log,
        "grenade_tier_effect_resolved",
        player_id=player_id,
        target_player_id=target_player_id,
        grenade_id=grenade_id,
        tier=tier,
        effect_kind="forced_temple_role_wipe",
        role_types=list(role_types),
        removed_by_role=dict(removal["removed_by_role"]),
        removed_prepared_nuns=removal["removed_prepared_nuns"],
        requested_sacrifice_total=removal.get("requested_sacrifice_total", removal["total_removed"]),
        effective_sacrifice_total=removal.get("effective_sacrifice_total", removal["total_removed"]),
        total_removed=removal["total_removed"],
        target_role_assignments_after=dict(state.players[target_player_id].assigned_role_meeples),
        target_prepared_nuns_after=state.players[target_player_id].nunnery_state.prepared_nuns,
        decision_source=removal["decision_source"],
    )


def _resolve_grenade_destroy_stored_phenomena(
    state: GameState,
    *,
    player_id: str,
    grenade_id: str,
    tier: int,
    count: int,
    same_owner_only: bool,
    effect_payload: dict[str, Any],
    decision_source: str | None,
) -> None:
    opponent_ids = _get_opponent_player_ids_in_turn_order(state, player_id=player_id)
    destroyed_targets: list[dict[str, str]] = []

    if same_owner_only:
        target_player_id = _resolve_stored_power_target_player_id_with_predicate(
            state,
            source_player_id=player_id,
            effect_payload=effect_payload,
            effect_label=grenade_id,
            predicate=lambda candidate_player: bool(candidate_player.stored_phenomena),
        )
        if target_player_id is None:
            append_event(
                state.event_log,
                "grenade_tier_effect_fizzled",
                player_id=player_id,
                grenade_id=grenade_id,
                tier=tier,
                effect_kind="destroy_stored_phenomena",
                reason="no_stored_phenomena_target",
                decision_source=decision_source,
            )
            return
        target_player = state.players[target_player_id]
        raw_target_ids = effect_payload.get("target_phenomenon_card_ids")
        if raw_target_ids is not None:
            if not isinstance(raw_target_ids, list) or not all(isinstance(entry, str) for entry in raw_target_ids):
                raise ValueError(f"Grenade {grenade_id} target_phenomenon_card_ids must be a list of strings.")
            if any(target_id not in target_player.stored_phenomena for target_id in raw_target_ids):
                raise ValueError(f"Grenade {grenade_id} cannot target unknown stored phenomenon on player {target_player_id}.")
            target_ids = list(raw_target_ids[:count])
        else:
            target_ids = list(target_player.stored_phenomena[:count])
        for target_id in target_ids:
            _discard_stored_phenomenon_for_grenade(
                state,
                target_player_id=target_player_id,
                phenomenon_card_id=target_id,
                grenade_id=grenade_id,
            )
            destroyed_targets.append({"target_player_id": target_player_id, "phenomenon_card_id": target_id})
    else:
        raw_targets = effect_payload.get("targets")
        if raw_targets is not None:
            if not isinstance(raw_targets, list):
                raise ValueError(f"Grenade {grenade_id} targets must be a list when provided.")
            target_entries = []
            for raw_target in raw_targets:
                if not isinstance(raw_target, dict):
                    raise ValueError(f"Grenade {grenade_id} targets must contain dict entries.")
                target_player_id = raw_target.get("target_player_id")
                phenomenon_card_id = raw_target.get("phenomenon_card_id")
                if not isinstance(target_player_id, str) or not isinstance(phenomenon_card_id, str):
                    raise ValueError(f"Grenade {grenade_id} target entries require target_player_id and phenomenon_card_id.")
                if target_player_id not in opponent_ids:
                    raise ValueError(f"Grenade {grenade_id} cannot target non-opponent player {target_player_id}.")
                if phenomenon_card_id not in state.players[target_player_id].stored_phenomena:
                    raise ValueError(f"Grenade {grenade_id} cannot target unknown stored phenomenon {phenomenon_card_id}.")
                target_entries.append((target_player_id, phenomenon_card_id))
        else:
            target_entries = []
            for candidate_player_id in opponent_ids:
                for phenomenon_card_id in state.players[candidate_player_id].stored_phenomena:
                    target_entries.append((candidate_player_id, phenomenon_card_id))
        for target_player_id, phenomenon_card_id in target_entries[:count]:
            if phenomenon_card_id not in state.players[target_player_id].stored_phenomena:
                continue
            _discard_stored_phenomenon_for_grenade(
                state,
                target_player_id=target_player_id,
                phenomenon_card_id=phenomenon_card_id,
                grenade_id=grenade_id,
            )
            destroyed_targets.append({"target_player_id": target_player_id, "phenomenon_card_id": phenomenon_card_id})

    if not destroyed_targets:
        append_event(
            state.event_log,
            "grenade_tier_effect_fizzled",
            player_id=player_id,
            grenade_id=grenade_id,
            tier=tier,
            effect_kind="destroy_stored_phenomena",
            reason="no_matching_targets_destroyed",
            decision_source=decision_source,
        )
        return

    append_event(
        state.event_log,
        "grenade_tier_effect_resolved",
        player_id=player_id,
        grenade_id=grenade_id,
        tier=tier,
        effect_kind="destroy_stored_phenomena",
        destroyed_targets=destroyed_targets,
        destroyed_count=len(destroyed_targets),
        decision_source=decision_source,
    )


def _grenade_commandment_choices(
    state: GameState,
    *,
    player_id: str,
    grenade_id: str,
    count: int,
    play_prophet: bool,
    effect_payload: dict[str, Any],
) -> tuple[list[str], str | None]:
    """Validate before consuming the grenade or removing any commandments."""
    raw_commandment_card_ids = effect_payload.get("commandment_card_ids")
    if raw_commandment_card_ids is not None:
        if not isinstance(raw_commandment_card_ids, list) or not all(isinstance(entry, str) for entry in raw_commandment_card_ids):
            raise ValueError(f"Grenade {grenade_id} commandment_card_ids must be a list of strings.")
        if any(
            commandment_card_id not in {commandment.card_id for commandment in state.active_commandments}
            for commandment_card_id in raw_commandment_card_ids
        ):
            raise ValueError(f"Grenade {grenade_id} cannot shatter an unknown commandment.")
        if len(raw_commandment_card_ids) > count or len(set(raw_commandment_card_ids)) != len(raw_commandment_card_ids):
            raise ValueError(f"Grenade {grenade_id} requires at most {count} distinct commandments.")
        target_commandment_ids = list(raw_commandment_card_ids)
    else:
        target_commandment_ids = [commandment.card_id for commandment in state.active_commandments[:count]]

    prophet_target_id = None
    if play_prophet:
        opponent_ids = _get_opponent_player_ids_in_turn_order(state, player_id=player_id)
        prophet_target_id = effect_payload.get("target_player_id")
        if prophet_target_id is None and opponent_ids:
            prophet_target_id = opponent_ids[0]
        if not isinstance(prophet_target_id, str) or prophet_target_id not in opponent_ids:
            raise ValueError("Choose another player for the Prophet.")
        if state.active_commandments and not target_commandment_ids:
            raise ValueError("Choose a commandment to shatter before playing the Prophet.")
    return target_commandment_ids, prophet_target_id


def _resolve_grenade_shatter_commandments(
    state: GameState,
    *,
    player_id: str,
    grenade_id: str,
    tier: int,
    count: int,
    award_prophet_after: bool,
    effect_payload: dict[str, Any],
    decision_source: str | None,
) -> None:
    target_commandment_ids, prophet_target_id = _grenade_commandment_choices(
        state, player_id=player_id, grenade_id=grenade_id, count=count,
        play_prophet=award_prophet_after, effect_payload=effect_payload,
    )

    shattered_commandment_ids: list[str] = []
    for commandment_card_id in target_commandment_ids:
        removed_index = next(
            index
            for index, commandment in enumerate(state.active_commandments)
            if commandment.card_id == commandment_card_id
        )
        removed_commandment = state.active_commandments.pop(removed_index)
        shattered_commandment_ids.append(removed_commandment.card_id)
    if shattered_commandment_ids:
        recalculate_commandment_effects(state)
    if prophet_target_id is not None:
        _play_prophet_on_opponent(state, from_player_id=player_id, to_player_id=prophet_target_id)

    append_event(
        state.event_log,
        "grenade_tier_effect_resolved",
        player_id=player_id,
        grenade_id=grenade_id,
        tier=tier,
        effect_kind="shatter_commandments",
        shattered_commandment_ids=shattered_commandment_ids,
        shattered_count=len(shattered_commandment_ids),
        award_prophet=False,
        prophet_played=prophet_target_id is not None,
        prophet_target_player_id=prophet_target_id,
        active_commandments_count=len(state.active_commandments),
        decision_source=decision_source,
    )


def _resolve_grenade_destroy_relics(
    state: GameState,
    *,
    player_id: str,
    grenade_id: str,
    tier: int,
    count: int,
    same_owner_only: bool,
    effect_payload: dict[str, Any],
    decision_source: str | None,
) -> None:
    opponent_ids = _get_opponent_player_ids_in_turn_order(state, player_id=player_id)
    destroyed_targets: list[dict[str, str]] = []

    if same_owner_only:
        target_player_id = _resolve_stored_power_target_player_id_with_predicate(
            state,
            source_player_id=player_id,
            effect_payload=effect_payload,
            effect_label=grenade_id,
            predicate=lambda candidate_player: any(card.category == "Reliquie" for card in candidate_player.tableau),
        )
        if target_player_id is None:
            append_event(
                state.event_log,
                "grenade_tier_effect_fizzled",
                player_id=player_id,
                grenade_id=grenade_id,
                tier=tier,
                effect_kind="destroy_relics",
                reason="no_relic_target",
                decision_source=decision_source,
            )
            return
        target_player = state.players[target_player_id]
        candidate_relic_ids = [card.card_id for card in target_player.tableau if card.category == "Reliquie"]
        raw_target_ids = effect_payload.get("target_card_ids")
        if raw_target_ids is not None:
            if not isinstance(raw_target_ids, list) or not all(isinstance(entry, str) for entry in raw_target_ids):
                raise ValueError(f"Grenade {grenade_id} target_card_ids must be a list of strings.")
            if any(target_id not in candidate_relic_ids for target_id in raw_target_ids):
                raise ValueError(f"Grenade {grenade_id} cannot target an unknown relic on player {target_player_id}.")
            target_ids = list(raw_target_ids[:count])
        else:
            target_ids = list(candidate_relic_ids[:count])
        for target_id in target_ids:
            removed_relic = _destroy_relic_for_grenade(
                state,
                target_player_id=target_player_id,
                target_card_id=target_id,
            )
            destroyed_targets.append({"target_player_id": target_player_id, "target_card_id": removed_relic.card_id})
    else:
        raw_targets = effect_payload.get("targets")
        if raw_targets is not None:
            if not isinstance(raw_targets, list):
                raise ValueError(f"Grenade {grenade_id} targets must be a list when provided.")
            target_entries = []
            for raw_target in raw_targets:
                if not isinstance(raw_target, dict):
                    raise ValueError(f"Grenade {grenade_id} targets must contain dict entries.")
                target_player_id = raw_target.get("target_player_id")
                target_card_id = raw_target.get("target_card_id")
                if not isinstance(target_player_id, str) or not isinstance(target_card_id, str):
                    raise ValueError(f"Grenade {grenade_id} target entries require target_player_id and target_card_id.")
                if target_player_id not in opponent_ids:
                    raise ValueError(f"Grenade {grenade_id} cannot target non-opponent player {target_player_id}.")
                if all(card.card_id != target_card_id or card.category != "Reliquie" for card in state.players[target_player_id].tableau):
                    raise ValueError(f"Grenade {grenade_id} cannot target unknown relic {target_card_id}.")
                target_entries.append((target_player_id, target_card_id))
        else:
            target_entries = []
            for candidate_player_id in opponent_ids:
                for candidate_card in state.players[candidate_player_id].tableau:
                    if candidate_card.category == "Reliquie":
                        target_entries.append((candidate_player_id, candidate_card.card_id))
        for target_player_id, target_card_id in target_entries[:count]:
            if all(card.card_id != target_card_id or card.category != "Reliquie" for card in state.players[target_player_id].tableau):
                continue
            removed_relic = _destroy_relic_for_grenade(
                state,
                target_player_id=target_player_id,
                target_card_id=target_card_id,
            )
            destroyed_targets.append({"target_player_id": target_player_id, "target_card_id": removed_relic.card_id})

    if not destroyed_targets:
        append_event(
            state.event_log,
            "grenade_tier_effect_fizzled",
            player_id=player_id,
            grenade_id=grenade_id,
            tier=tier,
            effect_kind="destroy_relics",
            reason="no_matching_targets_destroyed",
            decision_source=decision_source,
        )
        return

    append_event(
        state.event_log,
        "grenade_tier_effect_resolved",
        player_id=player_id,
        grenade_id=grenade_id,
        tier=tier,
        effect_kind="destroy_relics",
        destroyed_targets=destroyed_targets,
        destroyed_count=len(destroyed_targets),
        heavenly_discard_pile_size=len(state.heavenly_discard_pile),
        decision_source=decision_source,
    )


def _resolve_grenade_next_turn_penalty(
    state: GameState,
    *,
    player_id: str,
    grenade_id: str,
    tier: int,
    penalty: int,
    bonus_actions_granted: int,
    skip_next_turn: bool,
    effect_payload: dict[str, Any],
    decision_source: str | None,
) -> None:
    target_player_id = _resolve_stored_power_target_player_id(
        state,
        source_player_id=player_id,
        effect_payload=effect_payload,
        effect_label=grenade_id,
    )
    if target_player_id is None:
        append_event(
            state.event_log,
            "grenade_tier_effect_fizzled",
            player_id=player_id,
            grenade_id=grenade_id,
            tier=tier,
            effect_kind="next_turn_action_penalty",
            reason="no_opponents",
            decision_source=decision_source,
        )
        return

    target_player = state.players[target_player_id]
    if skip_next_turn:
        target_player.skip_next_turn = True
    if penalty > 0:
        target_player.next_turn_action_modifier -= penalty
    if bonus_actions_granted > 0:
        state.players[player_id].bonus_actions_this_turn += bonus_actions_granted

    append_event(
        state.event_log,
        "grenade_tier_effect_resolved",
        player_id=player_id,
        target_player_id=target_player_id,
        grenade_id=grenade_id,
        tier=tier,
        effect_kind="next_turn_action_penalty",
        penalty=penalty,
        bonus_actions_granted=bonus_actions_granted,
        skip_next_turn=skip_next_turn,
        target_next_turn_action_modifier=target_player.next_turn_action_modifier,
        target_skip_next_turn=target_player.skip_next_turn,
        player_bonus_actions_this_turn=state.players[player_id].bonus_actions_this_turn,
        decision_source=decision_source,
    )


def _resolve_grenade_discard_truth(
    state: GameState,
    *,
    player_id: str,
    grenade_id: str,
    tier: int,
    count: int | None,
    discard_all: bool,
    effect_payload: dict[str, Any],
    decision_source: str | None,
) -> None:
    target_player_id = _resolve_stored_power_target_player_id_with_predicate(
        state,
        source_player_id=player_id,
        effect_payload=effect_payload,
        effect_label=grenade_id,
        predicate=lambda candidate_player: bool(candidate_player.truth_pool),
    )
    if target_player_id is None:
        append_event(
            state.event_log,
            "grenade_tier_effect_fizzled",
            player_id=player_id,
            grenade_id=grenade_id,
            tier=tier,
            effect_kind="discard_truth",
            reason="no_truth_target",
            decision_source=decision_source,
        )
        return

    target_player = state.players[target_player_id]
    raw_truth_values = effect_payload.get("truth_values")
    if raw_truth_values is not None:
        if not isinstance(raw_truth_values, list) or not all(isinstance(value, int) for value in raw_truth_values):
            raise ValueError(f"Grenade {grenade_id} truth_values must be a list of integers.")
        if any(value not in target_player.truth_pool for value in raw_truth_values):
            raise ValueError(f"Grenade {grenade_id} cannot discard unavailable truth values from player {target_player_id}.")
        selected_truth_values = list(raw_truth_values)
    else:
        sorted_truth_values = sorted(target_player.truth_pool)
        selected_truth_values = sorted_truth_values if discard_all else sorted_truth_values[: max(0, int(count or 0))]

    discarded_truth_values: list[int] = []
    for truth_value in selected_truth_values:
        if truth_value not in target_player.truth_pool:
            continue
        discard_card = make_truth_card(
            truth_value,
            card_id=f"grenade-truth-discard-{grenade_id}-{target_player_id}-{len(discarded_truth_values)}-{truth_value}",
            metadata={
                "source": "grenade",
                "grenade_id": grenade_id,
                "owner_player_id": target_player_id,
                "discarded_by_player_id": player_id,
            },
        )
        _discard_truth_value_to_discard(
            state,
            player_id=target_player_id,
            value=truth_value,
            discard_card=discard_card,
        )
        discarded_truth_values.append(truth_value)

    append_event(
        state.event_log,
        "grenade_tier_effect_resolved",
        player_id=player_id,
        target_player_id=target_player_id,
        grenade_id=grenade_id,
        tier=tier,
        effect_kind="discard_truth",
        discard_all=discard_all,
        discarded_truth_values=discarded_truth_values,
        target_truth_pool_after=list(target_player.truth_pool),
        target_used_truth_after=list(target_player.used_truth),
        decision_source=decision_source,
    )


def _resolve_grenade_discard_heavenly(
    state: GameState,
    *,
    player_id: str,
    grenade_id: str,
    tier: int,
    count: int,
    distributed: bool,
    effect_payload: dict[str, Any],
    decision_source: str | None,
) -> None:
    opponent_ids = _get_opponent_player_ids_in_turn_order(state, player_id=player_id)
    discarded_targets: list[dict[str, str]] = []

    if distributed:
        raw_target_player_ids = effect_payload.get("target_player_ids")
        if raw_target_player_ids is not None:
            if not isinstance(raw_target_player_ids, list) or not all(isinstance(entry, str) for entry in raw_target_player_ids):
                raise ValueError(f"Grenade {grenade_id} target_player_ids must be a list of strings.")
            if any(target_player_id not in opponent_ids for target_player_id in raw_target_player_ids):
                raise ValueError(f"Grenade {grenade_id} target_player_ids must be opponents of {player_id}.")
            target_player_ids = list(raw_target_player_ids)
        else:
            target_player_ids = list(opponent_ids)
        raw_discard_card_ids_by_player = effect_payload.get("discard_card_ids_by_player", {})
        if not isinstance(raw_discard_card_ids_by_player, dict):
            raise ValueError(f"Grenade {grenade_id} discard_card_ids_by_player must be a dict when provided.")
        remaining = count
        for target_player_id in target_player_ids:
            if remaining <= 0:
                break
            target_player = state.players[target_player_id]
            heavenly_cards = [card for card in target_player.hand_cards if card.category in ACTION_PLAYABLE_HAND_CATEGORIES]
            if not heavenly_cards:
                continue
            requested_card_ids = raw_discard_card_ids_by_player.get(target_player_id)
            if requested_card_ids is not None:
                if not isinstance(requested_card_ids, list) or not all(isinstance(card_id, str) for card_id in requested_card_ids):
                    raise ValueError(f"Grenade {grenade_id} discard ids for player {target_player_id} must be a list of strings.")
                discard_card_ids = list(requested_card_ids[:remaining])
            else:
                discard_card_ids = [
                    card.card_id
                    for card in sorted(
                        heavenly_cards,
                        key=lambda card: (int(card.truth_value or 99), target_player.hand_cards.index(card)),
                    )[:remaining]
                ]
            for discard_card_id in discard_card_ids:
                if all(card.card_id != discard_card_id or card.category not in ACTION_PLAYABLE_HAND_CATEGORIES for card in target_player.hand_cards):
                    continue
                discarded_card = _pop_card_from_hand(target_player, card_id=discard_card_id)
                state.heavenly_discard_pile.append(discarded_card)
                discarded_targets.append({"target_player_id": target_player_id, "card_id": discarded_card.card_id})
                remaining -= 1
                if remaining <= 0:
                    break
    else:
        target_player_id = _resolve_stored_power_target_player_id_with_predicate(
            state,
            source_player_id=player_id,
            effect_payload=effect_payload,
            effect_label=grenade_id,
            predicate=lambda candidate_player: any(
                card.category in ACTION_PLAYABLE_HAND_CATEGORIES for card in candidate_player.hand_cards
            ),
        )
        if target_player_id is None:
            append_event(
                state.event_log,
                "grenade_tier_effect_fizzled",
                player_id=player_id,
                grenade_id=grenade_id,
                tier=tier,
                effect_kind="discard_heavenly",
                reason="no_heavenly_target",
                decision_source=decision_source,
            )
            return
        target_player = state.players[target_player_id]
        heavenly_cards = [card for card in target_player.hand_cards if card.category in ACTION_PLAYABLE_HAND_CATEGORIES]
        raw_discard_card_ids = effect_payload.get("discard_card_ids")
        if raw_discard_card_ids is not None:
            if not isinstance(raw_discard_card_ids, list) or not all(isinstance(card_id, str) for card_id in raw_discard_card_ids):
                raise ValueError(f"Grenade {grenade_id} discard_card_ids must be a list of strings.")
            discard_card_ids = list(raw_discard_card_ids[:count])
        else:
            discard_card_ids = [
                card.card_id
                for card in sorted(
                    heavenly_cards,
                    key=lambda card: (int(card.truth_value or 99), target_player.hand_cards.index(card)),
                )[:count]
            ]
        for discard_card_id in discard_card_ids:
            if all(card.card_id != discard_card_id or card.category not in ACTION_PLAYABLE_HAND_CATEGORIES for card in target_player.hand_cards):
                continue
            discarded_card = _pop_card_from_hand(target_player, card_id=discard_card_id)
            state.heavenly_discard_pile.append(discarded_card)
            discarded_targets.append({"target_player_id": target_player_id, "card_id": discarded_card.card_id})

    if not discarded_targets:
        append_event(
            state.event_log,
            "grenade_tier_effect_fizzled",
            player_id=player_id,
            grenade_id=grenade_id,
            tier=tier,
            effect_kind="discard_heavenly",
            reason="no_cards_discarded",
            decision_source=decision_source,
        )
        return

    append_event(
        state.event_log,
        "grenade_tier_effect_resolved",
        player_id=player_id,
        grenade_id=grenade_id,
        tier=tier,
        effect_kind="discard_heavenly",
        distributed=distributed,
        discarded_targets=discarded_targets,
        discarded_count=len(discarded_targets),
        heavenly_discard_pile_size=len(state.heavenly_discard_pile),
        decision_source=decision_source,
    )


def _place_free_enlightener_from_grenade(
    state: GameState,
    *,
    source_player_id: str,
    hand_card_id: str,
    target_player_id: str,
    require_overwrite: bool,
    replaced_card_id: str | None,
) -> dict[str, Any]:
    source_player = state.players[source_player_id]
    if target_player_id not in _get_grenade_enlightener_target_player_ids(
        state,
        player_id=source_player_id,
        require_overwrite=require_overwrite,
    ):
        raise ValueError(f"Player {source_player_id} cannot target {target_player_id} with grenade Aufklaerer placement.")

    card = _pop_card_from_hand(source_player, card_id=hand_card_id)
    if card.category != "Aufklärer":
        raise ValueError(f"Grenade can only place Aufklaerer from hand, got {card.category}.")

    immunity_resolution = _consume_relic_immunity_against_next_enlightener(
        state,
        source_player_id=source_player_id,
        target_player_id=target_player_id,
    )
    if immunity_resolution is not None:
        protected_player_id, consumed_relic = immunity_resolution
        state.heavenly_discard_pile.append(card)
        recalculate_commandment_effects(state)
        return {
            "resolved": False,
            "negated_by_immunity": True,
            "protected_player_id": protected_player_id,
            "consumed_relic_card_id": consumed_relic.card_id,
            "placed_card_id": card.card_id,
            "replaced_card_id": None,
            "target_player_id": target_player_id,
        }

    target_player = state.players[target_player_id]
    replaced_card: CardRef | None = None
    target_enlighteners = [tableau_card for tableau_card in target_player.tableau if tableau_card.category == "Aufklärer"]
    if require_overwrite:
        if not target_enlighteners:
            source_player.hand_cards.append(card)
            raise ValueError(f"Grenade placement requires an Aufklaerer to overwrite on player {target_player_id}.")
        if replaced_card_id is None:
            replaced_card_id = target_enlighteners[0].card_id
        if all(tableau_card.card_id != replaced_card_id for tableau_card in target_enlighteners):
            source_player.hand_cards.append(card)
            raise ValueError(f"Grenade cannot overwrite unknown Aufklaerer {replaced_card_id} on player {target_player_id}.")
        replaced_card = _pop_card_from_tableau(target_player, card_id=replaced_card_id)
        state.heavenly_discard_pile.append(replaced_card)
    elif not _has_free_slot(target_player, slot_kind="enlighteners"):
        source_player.hand_cards.append(card)
        raise ValueError(f"Player {target_player_id} has no free Aufklaerer slot for grenade placement.")

    card.metadata = dict(card.metadata)
    card.metadata["played_by_player_id"] = source_player_id
    card.metadata["attached_to_player_id"] = target_player_id
    target_player.tableau.append(card)
    recalculate_commandment_effects(state)
    append_event(
        state.event_log,
        "tableau_card_placed",
        player_id=target_player_id,
        source_player_id=source_player_id,
        card_id=card.card_id,
        card_name=card.name,
        category=card.category,
        slot_kind="enlighteners",
        slot_occupancy=_get_slot_occupancy(target_player, slot_kind="enlighteners"),
        slot_limit=_get_slot_limit(target_player, slot_kind="enlighteners"),
    )
    _apply_friedrich_alignment_override_if_active(state, player_id=target_player_id)
    return {
        "resolved": True,
        "negated_by_immunity": False,
        "protected_player_id": None,
        "consumed_relic_card_id": None,
        "placed_card_id": card.card_id,
        "replaced_card_id": None if replaced_card is None else replaced_card.card_id,
        "target_player_id": target_player_id,
    }


def _resolve_grenade_play_free_enlighteners(
    state: GameState,
    *,
    player_id: str,
    grenade_id: str,
    tier: int,
    count: int,
    require_overwrite: bool,
    distributed: bool,
    effect_payload: dict[str, Any],
    decision_source: str | None,
) -> None:
    source_player = state.players[player_id]
    candidate_hand_card_ids = [card.card_id for card in source_player.hand_cards if card.category == "Aufklärer"]
    used_target_player_ids: set[str] = set()
    if not candidate_hand_card_ids:
        append_event(
            state.event_log,
            "grenade_tier_effect_fizzled",
            player_id=player_id,
            grenade_id=grenade_id,
            tier=tier,
            effect_kind="play_free_enlighteners",
            reason="no_enlightener_in_hand",
            decision_source=decision_source,
        )
        return

    raw_placements = effect_payload.get("placements")
    resolved_placements: list[dict[str, Any]] = []
    if raw_placements is not None:
        if not isinstance(raw_placements, list):
            raise ValueError(f"Grenade {grenade_id} placements must be a list when provided.")
        planned_placements = []
        for raw_placement in raw_placements:
            if not isinstance(raw_placement, dict):
                raise ValueError(f"Grenade {grenade_id} placements must contain dict entries.")
            hand_card_id = raw_placement.get("hand_card_id")
            target_player_id = raw_placement.get("target_player_id")
            replaced_card_id = raw_placement.get("replaced_card_id")
            if not isinstance(hand_card_id, str) or not isinstance(target_player_id, str):
                raise ValueError(f"Grenade {grenade_id} placements require hand_card_id and target_player_id.")
            if replaced_card_id is not None and not isinstance(replaced_card_id, str):
                raise ValueError(f"Grenade {grenade_id} replaced_card_id must be a string when provided.")
            planned_placements.append((hand_card_id, target_player_id, replaced_card_id))
        for hand_card_id, target_player_id, replaced_card_id in planned_placements[:count]:
            if hand_card_id not in [card.card_id for card in source_player.hand_cards]:
                continue
            result = _place_free_enlightener_from_grenade(
                state,
                source_player_id=player_id,
                hand_card_id=hand_card_id,
                target_player_id=target_player_id,
                require_overwrite=require_overwrite,
                replaced_card_id=replaced_card_id,
            )
            resolved_placements.append(result)
    else:
        while len(resolved_placements) < count:
            next_hand_card_id = next(
                (card.card_id for card in source_player.hand_cards if card.category == "Aufklärer"),
                None,
            )
            if next_hand_card_id is None:
                break
            legal_target_player_ids = _get_grenade_enlightener_target_player_ids(
                state,
                player_id=player_id,
                require_overwrite=require_overwrite,
            )
            if distributed and used_target_player_ids:
                preferred_target_player_ids = [
                    target_player_id
                    for target_player_id in legal_target_player_ids
                    if target_player_id not in used_target_player_ids
                ]
                if preferred_target_player_ids:
                    legal_target_player_ids = preferred_target_player_ids
            chosen_target_player_id = None
            chosen_replaced_card_id = None
            for target_player_id in legal_target_player_ids:
                target_enlighteners = [card for card in state.players[target_player_id].tableau if card.category == "Aufklärer"]
                if require_overwrite and not target_enlighteners and not _has_relic_immunity_against_next_enlightener(state, protected_player_id=target_player_id):
                    continue
                if not require_overwrite and not _can_receive_enlightener(
                    state,
                    source_player_id=player_id,
                    target_player_id=target_player_id,
                ):
                    continue
                chosen_target_player_id = target_player_id
                chosen_replaced_card_id = target_enlighteners[0].card_id if require_overwrite and target_enlighteners else None
                break
            if chosen_target_player_id is None:
                break
            result = _place_free_enlightener_from_grenade(
                state,
                source_player_id=player_id,
                hand_card_id=next_hand_card_id,
                target_player_id=chosen_target_player_id,
                require_overwrite=require_overwrite,
                replaced_card_id=chosen_replaced_card_id,
            )
            resolved_placements.append(result)
            used_target_player_ids.add(chosen_target_player_id)
            if not distributed:
                break

    if not resolved_placements:
        append_event(
            state.event_log,
            "grenade_tier_effect_fizzled",
            player_id=player_id,
            grenade_id=grenade_id,
            tier=tier,
            effect_kind="play_free_enlighteners",
            reason="no_placements_resolved",
            decision_source=decision_source,
        )
        return

    append_event(
        state.event_log,
        "grenade_tier_effect_resolved",
        player_id=player_id,
        grenade_id=grenade_id,
        tier=tier,
        effect_kind="play_free_enlighteners",
        require_overwrite=require_overwrite,
        distributed=distributed,
        placements=resolved_placements,
        placement_count=len(resolved_placements),
        decision_source=decision_source,
    )


def _get_available_truth_sources(
    state: GameState,
    *,
    player_id: str,
    value: int | None,
) -> list[str]:
    if value is None:
        return []
    player = state.players[player_id]
    sources: list[str] = []
    if value in player.truth_pool:
        sources.append("truth_pool")
    if value in player.used_truth:
        sources.append("used_truth")
    if any(card.category == "Wahrheit" and int(card.truth_value or -1) == value for card in player.truth_discard):
        sources.append("truth_discard")
    if any(card.category == "Wahrheit" and int(card.truth_value or -1) == value for card in player.hand_cards):
        sources.append("hand")
    return sources


def reconcile_prepared_truth_hand(
    state: GameState,
    *,
    player_id: str | None = None,
    value: int | None = None,
    source: str = "truth_hand_recovery",
) -> list[str]:
    """Prepared cards represent available pool copies, never an extra supply."""
    removed_ids: list[str] = []
    player_ids = [player_id] if player_id is not None else list(state.player_order)
    for current_player_id in player_ids:
        player = state.players[current_player_id]
        available = Counter(int(pool_value) for pool_value in player.truth_pool)
        kept: list[CardRef] = []
        removed: list[CardRef] = []
        for card in player.hand_cards:
            if card.category != "Wahrheit":
                kept.append(card)
                continue
            pool_value = _get_truth_card_pool_value(card)
            if value is not None and pool_value != value:
                kept.append(card)
                continue
            if available[pool_value] > 0:
                available[pool_value] -= 1
                kept.append(card)
            else:
                removed.append(card)
        if removed:
            player.hand_cards[:] = kept
            card_ids = [card.card_id for card in removed]
            removed_ids.extend(card_ids)
            append_event(
                state.event_log, "truth_hand_reconciled",
                player_id=current_player_id, source=source,
                removed_hand_card_ids=card_ids,
                removed_truth_values=[_get_truth_card_pool_value(card) for card in removed],
                hand_size_after=len(player.hand_cards),
            )
    return removed_ids


def _remove_truth_value(
    state: GameState,
    *,
    player_id: str,
    value: int,
    source: str,
    preferred_source: str | None = None,
) -> GameState:
    player = state.players[player_id]
    removed_hand_card_id = None
    removed_discard_card_id = None
    available_sources = _get_available_truth_sources(state, player_id=player_id, value=value)
    if preferred_source is not None and preferred_source not in {"truth_pool", "used_truth", "truth_discard", "hand"}:
        raise ValueError(f"Unknown truth source {preferred_source!r} for player {player_id}.")
    if preferred_source is not None and preferred_source not in available_sources:
        raise ValueError(
            f"Truth value {value} is unavailable for player {player_id} from source {preferred_source}."
        )

    removal_order = [preferred_source] if preferred_source is not None else ["truth_pool", "used_truth", "truth_discard", "hand"]
    removed_from: str | None = None
    for source_name in removal_order:
        if source_name == "truth_pool" and value in player.truth_pool:
            player.truth_pool.remove(value)
            removed_from = "truth_pool"
            break
        if source_name == "used_truth" and value in player.used_truth:
            player.used_truth.remove(value)
            removed_from = "used_truth"
            break
        if source_name == "truth_discard":
            matching_discard_index = next(
                (
                    index
                    for index, card in enumerate(player.truth_discard)
                    if card.category == "Wahrheit" and int(card.truth_value or -1) == value
                ),
                None,
            )
            if matching_discard_index is not None:
                removed_discard_card = player.truth_discard.pop(matching_discard_index)
                removed_discard_card_id = removed_discard_card.card_id
                state.truth_discard = [
                    discarded_card
                    for discarded_card in state.truth_discard
                    if discarded_card.card_id != removed_discard_card.card_id
                ]
                removed_from = "truth_discard"
                break
        if source_name == "hand":
            matching_hand_index = next(
                (
                    index
                    for index, card in enumerate(player.hand_cards)
                    if card.category == "Wahrheit" and int(card.truth_value or -1) == value
                ),
                None,
            )
            if matching_hand_index is not None:
                removed_hand_card_id = player.hand_cards.pop(matching_hand_index).card_id
                # Removing the prepared representation also removes its pool copy.
                if value in player.truth_pool:
                    player.truth_pool.remove(value)
                removed_from = "hand"
                break
    if removed_from is None:
        raise ValueError(f"Truth value {value} is unavailable for player {player_id}.")

    reconciled_hand_ids = reconcile_prepared_truth_hand(
        state, player_id=player_id, value=value, source=source,
    )
    if removed_hand_card_id is None and reconciled_hand_ids:
        removed_hand_card_id = reconciled_hand_ids[0]
    player.truth_pool.sort()
    player.used_truth.sort()
    append_event(
        state.event_log,
        "truth_removed",
        player_id=player_id,
        value=value,
        source=source,
        removed_from=removed_from,
        preferred_source=preferred_source,
        removed_hand_card_id=removed_hand_card_id,
        removed_discard_card_id=removed_discard_card_id,
        truth_pool=list(player.truth_pool),
        used_truth=list(player.used_truth),
    )
    return state


def _add_truth_value(
    state: GameState,
    *,
    player_id: str,
    value: int,
    source: str,
    prepare_to_hand_source: str | None = None,
) -> GameState:
    player = state.players[player_id]
    player.truth_pool.append(value)
    player.truth_pool.sort()
    prepared_cards: list[CardRef] = []
    if isinstance(prepare_to_hand_source, str) and prepare_to_hand_source:
        prepared_cards = _add_truth_cards_to_hand(
            state,
            player_id=player_id,
            truth_values=[value],
            source=prepare_to_hand_source,
        )
    append_event(
        state.event_log,
        "truth_added",
        player_id=player_id,
        value=value,
        source=source,
        truth_pool=list(player.truth_pool),
        prepared_truth_card_ids=[card.card_id for card in prepared_cards],
        hand_size_after=len(player.hand_cards),
    )
    return state
