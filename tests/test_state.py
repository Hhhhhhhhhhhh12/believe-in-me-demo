from dataclasses import FrozenInstanceError, replace
import unittest

from believe_engine.legal_moves import LegalMove
from believe_engine.rules import apply_move, build_sample_deck, create_game
from believe_engine.state import DemoCard


class StateTests(unittest.TestCase):
    def test_deal_preserves_every_card_once(self):
        state = create_game(player_count=3)
        cards = tuple(card for player in state.players for card in player.hand) + state.draw_pile
        self.assertEqual(cards, build_sample_deck())
        self.assertTrue(all(len(player.hand) == 1 for player in state.players))
        self.assertEqual(state.active_player.player_id, "p1")

    def test_transition_does_not_mutate_input(self):
        state = create_game()
        next_state = apply_move(state, LegalMove("gather"))
        self.assertEqual(state.players[0].resources, 1)
        self.assertEqual(state.events, ())
        self.assertEqual(next_state.players[0].resources, 2)
        with self.assertRaises(FrozenInstanceError):
            next_state.events[0].event_type = "changed"
        with self.assertRaises(TypeError):
            next_state.events[0].data[0] = ("amount", 999)

    def test_rejects_invalid_player_counts(self):
        for count in (0, 1, 9, True, 2.5, "3"):
            with self.subTest(count=count), self.assertRaises(ValueError):
                create_game(player_count=count)

    def test_explicit_empty_deck_is_not_replaced_with_default(self):
        with self.assertRaises(ValueError):
            create_game(deck=())

    def test_duplicate_ids_are_rejected(self):
        card = build_sample_deck()[0]
        with self.assertRaises(ValueError):
            create_game(player_count=2, deck=(card, replace(card, name="Another")))

    def test_deck_requires_immutable_card_sequence(self):
        for deck in (list(build_sample_deck()), ("card", "another")):
            with self.subTest(deck=deck), self.assertRaises(ValueError):
                create_game(player_count=2, deck=deck)

    def test_card_values_are_validated(self):
        for changes in ({"cost": -1}, {"cost": True}, {"progress": 0}, {"card_id": ""}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                DemoCard(**({"card_id": "a", "name": "Advance", "cost": 2, "progress": 2} | changes))
