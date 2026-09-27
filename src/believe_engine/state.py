from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

ActionType = Literal["gather", "play_card", "convert", "pass"]


def require_integer(name: str, value: int, *, minimum: int | None = None) -> None:
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer.")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}.")


@dataclass(frozen=True, slots=True)
class DemoCard:
    card_id: str
    name: str
    cost: int
    progress: int

    def __post_init__(self) -> None:
        if not isinstance(self.card_id, str) or not self.card_id.strip():
            raise ValueError("card_id must be a nonempty string.")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name must be a nonempty string.")
        require_integer("cost", self.cost, minimum=0)
        require_integer("progress", self.progress, minimum=1)


@dataclass(frozen=True, slots=True)
class PlayerState:
    player_id: str
    resources: int = 1
    progress: int = 0
    hand: tuple[DemoCard, ...] = ()
    discard_count: int = 0


@dataclass(frozen=True, slots=True)
class Event:
    round_number: int
    turn_index: int
    player_id: str
    event_type: str
    data: tuple[tuple[str, str | int], ...] = ()


@dataclass(frozen=True, slots=True)
class GameState:
    players: tuple[PlayerState, ...]
    draw_pile: tuple[DemoCard, ...]
    turn_index: int = 0
    round_number: int = 1
    target_progress: int = 10
    winner_id: str | None = None
    events: tuple[Event, ...] = ()

    @property
    def active_player(self) -> PlayerState:
        return self.players[self.turn_index]

    @property
    def is_finished(self) -> bool:
        return self.winner_id is not None


def replace_player(state: GameState, player: PlayerState) -> GameState:
    if player.player_id not in {current.player_id for current in state.players}:
        raise ValueError(f"Unknown player: {player.player_id}.")
    players = tuple(
        player if current.player_id == player.player_id else current
        for current in state.players
    )
    return replace(state, players=players)
