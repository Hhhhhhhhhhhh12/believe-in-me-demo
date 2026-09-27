from __future__ import annotations

from dataclasses import replace

from .legal_moves import LegalMove, legal_moves
from .state import DemoCard, Event, GameState, PlayerState, replace_player, require_integer


def build_sample_deck() -> tuple[DemoCard, ...]:
    return (
        DemoCard("advance-1", "Advance", cost=2, progress=2),
        DemoCard("advance-2", "Advance", cost=2, progress=2),
        DemoCard("boost-1", "Boost", cost=3, progress=4),
        DemoCard("boost-2", "Boost", cost=3, progress=4),
        DemoCard("focus-1", "Focus", cost=1, progress=1),
        DemoCard("focus-2", "Focus", cost=1, progress=1),
        DemoCard("sprint-1", "Sprint", cost=4, progress=5),
        DemoCard("sprint-2", "Sprint", cost=4, progress=5),
    )


def create_game(*, player_count: int = 3, deck: tuple[DemoCard, ...] | None = None) -> GameState:
    require_integer("player_count", player_count, minimum=2)
    cards = build_sample_deck() if deck is None else deck
    if not isinstance(cards, tuple) or not all(isinstance(card, DemoCard) for card in cards):
        raise ValueError("deck must be a tuple of DemoCard objects.")
    if len(cards) < player_count:
        raise ValueError("The deck must contain at least one card per player.")
    if len({card.card_id for card in cards}) != len(cards):
        raise ValueError("Card IDs must be unique.")
    players = tuple(
        PlayerState(player_id=f"p{index + 1}", hand=(cards[index],))
        for index in range(player_count)
    )
    return GameState(players=players, draw_pile=cards[player_count:])


def apply_move(state: GameState, move: LegalMove) -> GameState:
    if move not in legal_moves(state):
        raise ValueError(f"Illegal move: {move}.")
    player = state.active_player

    if move.action == "gather":
        updated = replace(player, resources=player.resources + 1)
        next_state = _append_event(replace_player(state, updated), "resource_gained", amount=1)
    elif move.action == "draw":
        card = state.draw_pile[0]
        updated = replace(player, hand=(*player.hand, card))
        drawn = replace(replace_player(state, updated), draw_pile=state.draw_pile[1:])
        next_state = _append_event(drawn, "card_drawn", card_id=card.card_id, card_name=card.name)
    elif move.action == "convert":
        updated = replace(player, resources=player.resources - 3, progress=player.progress + 2)
        next_state = _append_event(
            replace_player(state, updated), "resources_converted", cost=3, progress=2,
        )
    elif move.action == "play_card":
        card = next(card for card in player.hand if card.card_id == move.card_id)
        updated = replace(
            player,
            resources=player.resources - card.cost,
            progress=player.progress + card.progress,
            hand=tuple(current for current in player.hand if current.card_id != card.card_id),
            discard_count=player.discard_count + 1,
        )
        next_state = _append_event(
            replace_player(state, updated), "card_played",
            card_id=card.card_id, card_name=card.name, cost=card.cost, progress=card.progress,
        )
    else:
        next_state = _append_event(state, "turn_passed")

    if next_state.active_player.progress >= next_state.target_progress:
        return _append_event(
            replace(next_state, winner_id=player.player_id),
            "match_finished", winner_id=player.player_id,
        )
    next_index = (state.turn_index + 1) % len(state.players)
    return replace(
        next_state, turn_index=next_index,
        round_number=state.round_number + (next_index == 0),
    )


def _append_event(state: GameState, event_type: str, **payload: str | int) -> GameState:
    event = Event(
        state.round_number, state.turn_index, state.active_player.player_id,
        event_type, tuple(payload.items()),
    )
    return replace(state, events=(*state.events, event))
