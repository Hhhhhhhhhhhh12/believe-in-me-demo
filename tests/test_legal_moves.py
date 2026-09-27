from dataclasses import replace
import unittest

from believe_engine.legal_moves import LegalMove, legal_moves
from believe_engine.rules import apply_move, create_game
from believe_engine.state import replace_player


class LegalMoveTests(unittest.TestCase):
    def test_actions_match_available_resources(self):
        state = create_game()
        self.assertEqual({move.action for move in legal_moves(state)}, {"gather", "draw", "pass"})
        state = replace_player(state, replace(state.active_player, resources=3))
        self.assertEqual(
            {move.action for move in legal_moves(state)},
            {"gather", "draw", "pass", "convert", "play_card"},
        )

    def test_move_reason_does_not_affect_legality(self):
        state = create_game()
        result = apply_move(state, LegalMove("gather", reason="A different label"))
        self.assertEqual(result.players[0].resources, 2)

    def test_illegal_moves_are_rejected_without_mutation(self):
        state = create_game()
        for move in (
            LegalMove("convert"), LegalMove("play_card", "missing"),
            LegalMove("play_card", state.active_player.hand[0].card_id),
            LegalMove("gather", "unexpected-id"), LegalMove("unknown"),
        ):
            with self.subTest(move=move), self.assertRaises(ValueError):
                apply_move(state, move)
        self.assertEqual(state.players[0].resources, 1)
        self.assertEqual(state.events, ())

    def test_play_card_accounts_for_cost_progress_and_discard(self):
        state = create_game()
        state = replace_player(state, replace(state.active_player, resources=3))
        card = state.active_player.hand[0]
        result = apply_move(state, LegalMove("play_card", card.card_id))
        player = result.players[0]
        self.assertEqual((player.resources, player.progress, player.discard_count), (1, 2, 1))
        self.assertEqual(player.hand, ())
        self.assertEqual(result.events[0].player_id, "p1")
        self.assertEqual(result.turn_index, 1)

    def test_convert_accounts_for_resources(self):
        state = create_game()
        state = replace_player(state, replace(state.active_player, resources=3))
        result = apply_move(state, LegalMove("convert"))
        self.assertEqual((result.players[0].resources, result.players[0].progress), (0, 2))

    def test_draw_moves_one_card_from_pile_to_hand(self):
        state = create_game()
        card = state.draw_pile[0]
        result = apply_move(state, LegalMove("draw"))
        self.assertEqual(result.players[0].hand[-1], card)
        self.assertEqual(result.draw_pile, state.draw_pile[1:])
        self.assertEqual(len(state.players[0].hand), 1)
        self.assertEqual(result.events[0].event_type, "card_drawn")

    def test_draw_unavailable_at_hand_limit_or_empty_pile(self):
        state = create_game()
        player = replace(state.active_player, hand=state.draw_pile[:3])
        full_hand = replace_player(state, player)
        self.assertNotIn("draw", {move.action for move in legal_moves(full_hand)})
        empty_pile = replace(state, draw_pile=())
        self.assertNotIn("draw", {move.action for move in legal_moves(empty_pile)})

    def test_pass_advances_round_without_changing_players(self):
        state = create_game(player_count=2)
        result = apply_move(apply_move(state, LegalMove("pass")), LegalMove("pass"))
        self.assertEqual(result.players, state.players)
        self.assertEqual((result.turn_index, result.round_number), (0, 2))
        self.assertEqual([event.player_id for event in result.events], ["p1", "p2"])

    def test_win_stops_turn_and_disallows_further_moves(self):
        state = create_game()
        state = replace_player(state, replace(state.active_player, resources=3, progress=9))
        result = apply_move(state, LegalMove("convert"))
        self.assertEqual(result.winner_id, "p1")
        self.assertEqual(result.turn_index, 0)
        self.assertEqual(result.events[-1].event_type, "match_finished")
        self.assertEqual(legal_moves(result), ())
        with self.assertRaises(ValueError):
            apply_move(result, LegalMove("pass"))
