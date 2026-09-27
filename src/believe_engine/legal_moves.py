from __future__ import annotations

from dataclasses import dataclass, field

from .state import ActionType, GameState


@dataclass(frozen=True, slots=True)
class LegalMove:
    action: ActionType
    card_id: str | None = None
    reason: str = field(default="", compare=False)


def legal_moves(state: GameState) -> tuple[LegalMove, ...]:
    if state.is_finished:
        return ()
    player = state.active_player
    moves = [
        LegalMove("gather", reason="Gain one resource."),
        LegalMove("pass", reason="End the turn."),
    ]
    if state.draw_pile and len(player.hand) < 3:
        moves.append(LegalMove("draw", reason="Draw one card (hand limit: three)."))
    if player.resources >= 3:
        moves.append(LegalMove("convert", reason="Spend three resources for two progress."))
    for card in player.hand:
        if player.resources >= card.cost:
            moves.append(LegalMove(
                "play_card", card.card_id,
                reason=f"Spend {card.cost} resources for {card.progress} progress.",
            ))
    return tuple(moves)
