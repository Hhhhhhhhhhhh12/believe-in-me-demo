from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable

from .state import CardRef, GameState, PlayerState, has_complete_trinity, is_pure_alignment


CommandmentHandler = Callable[[GameState, CardRef], None]
MONUMENT_PART_PATTERN = re.compile(r"-(\d{2})$")


def recalculate_commandment_effects(state: GameState) -> GameState:
    for player in state.players.values():
        player.commandment_state.effective_hand_limit = player.commandment_state.base_hand_limit
        player.commandment_state.blocked_card_categories.clear()
        player.commandment_state.disabled_tableau_categories.clear()
        player.commandment_state.inactive_role_types.clear()
        player.commandment_state.contest_disabled_role_types.clear()
        player.commandment_state.zero_cost_card_categories.clear()
        player.commandment_state.forced_revealed_truth_values.clear()
        player.commandment_state.heavenly_cards_zero_truth = False
        player.commandment_state.contest_truth_card_value_modifier_per_card = 0
        player.commandment_state.max_cards_per_contest = None
        player.commandment_state.global_sacrifice_cost_modifier = 0
        player.commandment_state.category_cost_modifiers.clear()
        player.commandment_state.role_production_modifiers.clear()
        player.commandment_state.turn_start_missionary_steal = 0
        player.commandment_state.active_effect_sources.clear()

    for commandment in state.active_commandments:
        handler = COMMANDMENT_REGISTRY.get(commandment.card_id)
        if handler is not None:
            handler(state, commandment)

    return state


def is_card_play_blocked(state: GameState, *, player_id: str, card: CardRef) -> bool:
    player = state.players[player_id]
    return card.category in player.commandment_state.blocked_card_categories


def is_tableau_card_disabled(state: GameState, *, player_id: str, card: CardRef) -> bool:
    player = state.players[player_id]
    return card.category in player.commandment_state.disabled_tableau_categories


def get_additional_cost_for_card(state: GameState, *, player_id: str, card: CardRef) -> int:
    player = state.players[player_id]
    return player.commandment_state.global_sacrifice_cost_modifier + player.commandment_state.category_cost_modifiers.get(
        card.category,
        0,
    )


def is_card_cost_waived(state: GameState, *, player_id: str, card: CardRef) -> bool:
    player = state.players[player_id]
    return card.category in player.commandment_state.zero_cost_card_categories


def is_role_active(state: GameState, *, player_id: str, role_type: str) -> bool:
    player = state.players[player_id]
    return role_type not in player.commandment_state.inactive_role_types


def can_use_role_in_contest(state: GameState, *, player_id: str, role_type: str) -> bool:
    player = state.players[player_id]
    return role_type not in player.commandment_state.contest_disabled_role_types


def get_role_production_modifier(state: GameState, *, player_id: str, role_type: str) -> int:
    player = state.players[player_id]
    return player.commandment_state.role_production_modifiers.get(role_type, 0)


def get_turn_start_missionary_steal(state: GameState, *, player_id: str) -> int:
    player = state.players[player_id]
    return player.commandment_state.turn_start_missionary_steal


def _is_immune_to_negative_commandments(player: PlayerState) -> bool:
    return player.alignment == "<Sanftmut>" and is_pure_alignment(player, "<Sanftmut>")


def _apply_essen(state: GameState, commandment: CardRef) -> None:
    for player in state.players.values():
        if _has_completed_monument(player):
            player.commandment_state.effective_hand_limit += 1
            _record_effect_source(player, commandment.card_id)


def _apply_eltern(state: GameState, commandment: CardRef) -> None:
    for player in state.players.values():
        if _is_immune_to_negative_commandments(player):
            continue
        if any(card.category == "Aufklärer" for card in player.tableau):
            continue
        _block_card_category(player, "Segen")
        _record_effect_source(player, commandment.card_id)


def _apply_gaehnen(state: GameState, commandment: CardRef) -> None:
    for player in state.players.values():
        if _is_immune_to_negative_commandments(player):
            continue
        if not has_complete_trinity(player):
            continue
        player.commandment_state.effective_hand_limit -= 1
        _record_effect_source(player, commandment.card_id)


def _apply_bildnis(state: GameState, commandment: CardRef) -> None:
    for player in state.players.values():
        if _is_immune_to_negative_commandments(player):
            continue
        if not _player_has_attribute(player, "<Bart>"):
            continue
        _block_card_category(player, "Segen")
        _record_effect_source(player, commandment.card_id)


def _apply_brechen(state: GameState, commandment: CardRef) -> None:
    for player in state.players.values():
        if _is_immune_to_negative_commandments(player):
            continue
        if not _player_has_attribute(player, "<Zehen>"):
            continue
        player.commandment_state.contest_truth_card_value_modifier_per_card -= 1
        _record_effect_source(player, commandment.card_id)


def _apply_boden(state: GameState, commandment: CardRef) -> None:
    for player in state.players.values():
        if player.alignment != "<Unergründlich>":
            continue
        _waive_card_cost(player, "Reliquie")
        _record_effect_source(player, commandment.card_id)


def _apply_kaennchen(state: GameState, commandment: CardRef) -> None:
    for player in state.players.values():
        if _is_immune_to_negative_commandments(player):
            continue
        if not _player_has_attribute(player, "<Kopfbedeckung>"):
            continue
        if 6 not in player.commandment_state.forced_revealed_truth_values:
            player.commandment_state.forced_revealed_truth_values.append(6)
        _record_effect_source(player, commandment.card_id)


def _apply_klabumsel(state: GameState, commandment: CardRef) -> None:
    for player in state.players.values():
        if _is_immune_to_negative_commandments(player):
            continue
        if not _player_has_attribute(player, "<Geschmeide>"):
            continue
        player.commandment_state.heavenly_cards_zero_truth = True
        _record_effect_source(player, commandment.card_id)


def _apply_eichhoernchen(state: GameState, commandment: CardRef) -> None:
    for player in state.players.values():
        monk_temple_occupied = max(0, player.assigned_role_meeples.get("Mönche", 0)) > 0
        missionary_temple_occupied = max(0, player.assigned_role_meeples.get("Missionare", 0)) > 0
        nun_temple_occupied = player.nunnery_state.prepared_nuns > 0
        if not monk_temple_occupied:
            continue
        if missionary_temple_occupied or nun_temple_occupied:
            continue
        _add_role_production_modifier(player, "Mönche", 1)
        _record_effect_source(player, commandment.card_id)


def _apply_putzig(state: GameState, commandment: CardRef) -> None:
    for player in state.players.values():
        if _is_immune_to_negative_commandments(player):
            continue
        if not _player_has_attribute(player, "<Schweif>"):
            continue
        _block_card_category(player, "Aufklärer")
        _record_effect_source(player, commandment.card_id)


def _apply_quellen(state: GameState, commandment: CardRef) -> None:
    for player in state.players.values():
        if _is_immune_to_negative_commandments(player):
            continue
        if not _player_has_attribute(player, "<Waffe>"):
            continue
        player.commandment_state.max_cards_per_contest = 3
        _record_effect_source(player, commandment.card_id)


def _apply_mittagsschlaefchen(state: GameState, commandment: CardRef) -> None:
    for player in state.players.values():
        if _is_immune_to_negative_commandments(player):
            continue
        if not _player_has_attribute(player, "<Brusthaare>"):
            continue
        player.commandment_state.global_sacrifice_cost_modifier += 1
        _record_effect_source(player, commandment.card_id)


def _apply_schnarchen(state: GameState, commandment: CardRef) -> None:
    for player in state.players.values():
        if _is_immune_to_negative_commandments(player):
            continue
        if not _player_has_attribute(player, "<Socken>"):
            continue
        _add_category_cost_modifier(player, "Heiliges Heer", 3)
        _record_effect_source(player, commandment.card_id)


def _apply_singen(state: GameState, commandment: CardRef) -> None:
    for player in state.players.values():
        if _is_immune_to_negative_commandments(player):
            continue
        if not _player_has_attribute(player, "<Hörnern>"):
            continue
        _add_category_cost_modifier(player, "Aufklärer", 2)
        _record_effect_source(player, commandment.card_id)


def _apply_piepen(state: GameState, commandment: CardRef) -> None:
    _disable_relics_for_alignment(state, commandment, "<Zorn>")


def _apply_sterne(state: GameState, commandment: CardRef) -> None:
    _disable_relics_for_alignment(state, commandment, "<Chaos>")


def _apply_verflossene(state: GameState, commandment: CardRef) -> None:
    _disable_relics_for_alignment(state, commandment, "<Sanftmut>")


def _apply_leibeswinde(state: GameState, commandment: CardRef) -> None:
    _disable_role_for_alignment(state, commandment, "<Sanftmut>", "Mönche")


def _apply_signalfarben(state: GameState, commandment: CardRef) -> None:
    _disable_role_for_alignment(state, commandment, "<Chaos>", "Mönche")


def _apply_tuch(state: GameState, commandment: CardRef) -> None:
    _disable_role_for_alignment(state, commandment, "<Zorn>", "Mönche")


def _apply_socken(state: GameState, commandment: CardRef) -> None:
    _disable_role_in_contest_for_alignment(state, commandment, "<Sanftmut>", "Nonnen")


def _apply_orange(state: GameState, commandment: CardRef) -> None:
    _disable_role_in_contest_for_alignment(state, commandment, "<Chaos>", "Nonnen")


def _apply_niesen(state: GameState, commandment: CardRef) -> None:
    for player in state.players.values():
        if player.alignment != "<Unergründlich>":
            continue
        _add_role_production_modifier(player, "Mönche", 1)
        _record_effect_source(player, commandment.card_id)


def _apply_schweigen(state: GameState, commandment: CardRef) -> None:
    for player in state.players.values():
        if player.alignment != "<Unergründlich>":
            continue
        player.commandment_state.turn_start_missionary_steal += 1
        _record_effect_source(player, commandment.card_id)


def _apply_sonne(state: GameState, commandment: CardRef) -> None:
    _disable_role_in_contest_for_alignment(state, commandment, "<Zorn>", "Nonnen")


def _has_completed_monument(player: PlayerState) -> bool:
    grouped_parts: dict[str, set[int | str]] = defaultdict(set)
    blocked_group_keys: set[str] = set()

    for card in player.tableau:
        if card.category != "Monument":
            continue

        group_key = _monument_group_key(card)
        starter_player_id = card.metadata.get("monument_started_by_player_id", player.player_id)
        if starter_player_id != player.player_id:
            continue
        if bool(card.metadata.get("monument_completion_blocked")):
            blocked_group_keys.add(group_key)
            continue
        part = card.metadata.get("monument_part")
        if isinstance(part, int):
            grouped_parts[group_key].add(part)
        else:
            grouped_parts[group_key].add(card.card_id)

    for group_key, part_set in grouped_parts.items():
        if group_key in blocked_group_keys:
            continue
        if {1, 2, 3}.issubset(part_set):
            return True
        if len(part_set) >= 3:
            return True

    return False


def _monument_group_key(card: CardRef) -> str:
    raw_key = card.card_id.split("__", 1)[0]
    match = MONUMENT_PART_PATTERN.search(raw_key)
    if match:
        return raw_key[: match.start()]
    return raw_key


def _record_effect_source(player: PlayerState, commandment_id: str) -> None:
    if commandment_id not in player.commandment_state.active_effect_sources:
        player.commandment_state.active_effect_sources.append(commandment_id)


def _block_card_category(player: PlayerState, category: str) -> None:
    if category not in player.commandment_state.blocked_card_categories:
        player.commandment_state.blocked_card_categories.append(category)


def _disable_tableau_category(player: PlayerState, category: str) -> None:
    if category not in player.commandment_state.disabled_tableau_categories:
        player.commandment_state.disabled_tableau_categories.append(category)


def _add_category_cost_modifier(player: PlayerState, category: str, amount: int) -> None:
    player.commandment_state.category_cost_modifiers[category] = (
        player.commandment_state.category_cost_modifiers.get(category, 0) + amount
    )


def _mark_role_inactive(player: PlayerState, role_type: str) -> None:
    if role_type not in player.commandment_state.inactive_role_types:
        player.commandment_state.inactive_role_types.append(role_type)


def _block_role_in_contest(player: PlayerState, role_type: str) -> None:
    if role_type not in player.commandment_state.contest_disabled_role_types:
        player.commandment_state.contest_disabled_role_types.append(role_type)


def _waive_card_cost(player: PlayerState, category: str) -> None:
    if category not in player.commandment_state.zero_cost_card_categories:
        player.commandment_state.zero_cost_card_categories.append(category)


def _add_role_production_modifier(player: PlayerState, role_type: str, amount: int) -> None:
    player.commandment_state.role_production_modifiers[role_type] = (
        player.commandment_state.role_production_modifiers.get(role_type, 0) + amount
    )


def _disable_relics_for_alignment(state: GameState, commandment: CardRef, alignment: str) -> None:
    for player in state.players.values():
        if _is_immune_to_negative_commandments(player):
            continue
        if player.alignment != alignment:
            continue
        _disable_tableau_category(player, "Reliquie")
        _record_effect_source(player, commandment.card_id)


def _disable_role_for_alignment(
    state: GameState,
    commandment: CardRef,
    alignment: str,
    role_type: str,
) -> None:
    for player in state.players.values():
        if _is_immune_to_negative_commandments(player):
            continue
        if player.alignment != alignment:
            continue
        _mark_role_inactive(player, role_type)
        _record_effect_source(player, commandment.card_id)


def _disable_role_in_contest_for_alignment(
    state: GameState,
    commandment: CardRef,
    alignment: str,
    role_type: str,
) -> None:
    for player in state.players.values():
        if _is_immune_to_negative_commandments(player):
            continue
        if player.alignment != alignment:
            continue
        _block_role_in_contest(player, role_type)
        _record_effect_source(player, commandment.card_id)


def _player_has_attribute(player: PlayerState, attribute: str) -> bool:
    for card in player.tableau:
        card_attribute = card.metadata.get("attribute")
        if card_attribute == attribute:
            return True
        if isinstance(card_attribute, list) and attribute in card_attribute:
            return True
    return False


COMMANDMENT_REGISTRY: dict[str, CommandmentHandler] = {
    "bildnis__Gebote__1": _apply_bildnis,
    "brechen__Gebote__1": _apply_brechen,
    "boden__Gebote__1": _apply_boden,
    "eichhoernchen__Gebote__1": _apply_eichhoernchen,
    "essen__Gebote__1": _apply_essen,
    "eltern__Gebote__1": _apply_eltern,
    "gaehnen__Gebote__1": _apply_gaehnen,
    "kaennchen__Gebote__1": _apply_kaennchen,
    "klabumsel__Gebote__1": _apply_klabumsel,
    "leibeswinde__Gebote__1": _apply_leibeswinde,
    "mittagsschlaefchen__Gebote__1": _apply_mittagsschlaefchen,
    "niesen__Gebote__1": _apply_niesen,
    "orange__Gebote__1": _apply_orange,
    "piepen__Gebote__1": _apply_piepen,
    "putzig__Gebote__1": _apply_putzig,
    "quellen__Gebote__1": _apply_quellen,
    "schnarchen__Gebote__1": _apply_schnarchen,
    "schweigen__Gebote__1": _apply_schweigen,
    "signalfarben__Gebote__1": _apply_signalfarben,
    "singen__Gebote__1": _apply_singen,
    "socken__Gebote__1": _apply_socken,
    "sonne__Gebote__1": _apply_sonne,
    "sterne__Gebote__1": _apply_sterne,
    "tuch__Gebote__1": _apply_tuch,
    "verflossene__Gebote__1": _apply_verflossene,
}
