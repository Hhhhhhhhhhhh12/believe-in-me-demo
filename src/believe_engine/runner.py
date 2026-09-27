from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .legal_moves import LegalMove, legal_moves
from .rng import SeededRng
from .rules import apply_move, build_sample_deck, create_game
from .state import GameState, require_integer


@dataclass(frozen=True, slots=True)
class RunResult:
    seed: int
    final_state: GameState
    turn_count: int

    @property
    def winner_id(self) -> str | None:
        return self.final_state.winner_id

    @property
    def status(self) -> Literal["finished", "turn_limit"]:
        return "finished" if self.final_state.is_finished else "turn_limit"


def run_match(*, seed: int, player_count: int = 3, max_turns: int = 200) -> RunResult:
    require_integer("max_turns", max_turns, minimum=0)
    deck = SeededRng(seed).shuffled(build_sample_deck())
    state = create_game(player_count=player_count, deck=deck)
    turn_count = 0
    while not state.is_finished and turn_count < max_turns:
        state = apply_move(state, choose_demo_move(state))
        turn_count += 1
    return RunResult(seed, state, turn_count)


def choose_demo_move(state: GameState) -> LegalMove:
    moves = legal_moves(state)
    if not moves:
        raise ValueError("Cannot choose a move after the match has finished.")
    cards = {card.card_id: card for card in state.active_player.hand}
    playable = [move for move in moves if move.action == "play_card"]
    winning = [
        move for move in playable
        if state.active_player.progress + cards[move.card_id].progress >= state.target_progress
    ]
    if winning:
        return winning[0]
    conversions = [move for move in moves if move.action == "convert"]
    if conversions and state.active_player.progress + 2 >= state.target_progress:
        return conversions[0]
    if playable:
        return max(playable, key=lambda move: cards[move.card_id].progress)
    draws = [move for move in moves if move.action == "draw"]
    if draws and not state.active_player.hand:
        return draws[0]
    if conversions:
        return conversions[0]
    return next(move for move in moves if move.action == "gather")
