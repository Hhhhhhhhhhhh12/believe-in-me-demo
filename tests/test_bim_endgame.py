"""Complete the published mini-match using commands, not edited game state.

Cover the three-round countdown after manifestation, collective loss without a
complete Trinity, and terminal replay/rejection/restart. These are integration
checks; the corresponding Chromium scenario checks the actual winner display.
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

PUBLISHED_SOURCE = Path(__file__).resolve().parents[1] / "docs" / "source"
sys.path.insert(0, str(PUBLISHED_SOURCE))

import bridge  # noqa: E402


class MiniMatchEndgameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.view = json.loads(bridge.browser_initialize(json.dumps({"commands": []})))
        self.addCleanup(bridge.browser_initialize, json.dumps({"commands": []}))
        self.commands: list[dict] = []
        self.transitions: list[tuple] = []
        self.claims: list[dict] = []
        self.send("start_mini", starting_believers=6)

    def send(self, action: str, **payload: object) -> None:
        command = {"action": action, "revision": self.view["revision"], **payload}
        self.view = json.loads(bridge.browser_action(json.dumps(command)))
        self.commands.append(command)

    def complete_match(self, *, manifest: bool) -> None:
        # Win the first contest with 4 + 6, then contribute only the mandatory
        # opening card and pass when permitted. No roles or powers are scripted.
        for _ in range(150):
            match = self.view["match"]
            phase = match["phase"]
            if phase == "finished":
                return
            self.assertFalse(match["game_over"], "A terminal state must finish the UI phase")
            self.assertEqual(match["winner_ids"], [])
            if phase == "round_end":
                current_round, remaining = self.view["round"], match["rounds_left"]
                self.send("mini_next_round")
                self.transitions.append((current_round, remaining, self.view["match"]["rounds_left"]))
            elif phase == "claim":
                self.send("mini_claim", manifest=manifest and match["can_manifest"])
                self.claims.append(copy.deepcopy(self.view))
            elif phase == "nun":
                self.send("mini_nun", sacrifice=False)
            elif match["actor"] in {"p2", "p3"}:
                self.send("mini_advance")
            elif phase == "turn":
                self.send("mini_end_turn")
            elif phase == "draw":
                self.send("mini_draw_rest")
            elif phase == "contest":
                desired = "truth_p1_4" if match["own_bid_total"] == 0 else "truth_p1_6"
                bid = next((card for card in match["hand"]
                            if card["art"] == desired and card["can_bid"]), None) if self.view["round"] == 1 else None
                if bid is not None:
                    self.send("mini_bid", card_id=bid["id"])
                elif match["can_pass"]:
                    self.send("mini_pass")
                else:
                    bid = next(card for card in match["hand"] if card["can_bid"])
                    self.send("mini_bid", card_id=bid["id"])
            else:
                self.fail(f"Unexpected mini-match phase: {phase}")
        self.fail("The mini-match did not finish within 150 commands")

    def terminal_events(self) -> list[dict]:
        return [event for event in bridge.session.state.event_log
                if event["type"] in {"game_over_terminal", "game_over_endgame"}]

    def test_manifestation_starts_three_final_rounds_and_complete_god_wins(self) -> None:
        self.complete_match(manifest=True)
        first_claim = self.claims[0]
        self.assertEqual(first_claim["round"], 1)
        self.assertEqual(first_claim["body_count"], 3)
        self.assertIn("legs", first_claim["tableau"])
        self.assertTrue(first_claim["revealed"])
        self.assertTrue(first_claim["endgame"])
        self.assertEqual(first_claim["match"]["rounds_left"], 3)
        # The trigger round must not use up one of the three final rounds.
        self.assertEqual(self.transitions, [(1, 3, 3), (2, 3, 2), (3, 2, 1), (4, 1, 0)])
        match = self.view["match"]
        self.assertTrue(match["game_over"])
        self.assertEqual(match["end_reason"], "game_over_endgame")
        self.assertEqual(match["winner_ids"], ["p1"])
        self.assertIsNone(match["actor"])
        self.assertEqual(match["options"], [])
        events = self.terminal_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["completed_round"], 4)
        self.assertEqual(events[0]["winner_ids"], ["p1"])
        scores = events[0]["score_by_player"]
        self.assertTrue(scores["p1"]["has_complete_trinity"])
        self.assertFalse(scores["p3"]["has_complete_trinity"])
        self.assertLess(scores["p1"]["total_believers"], scores["p3"]["total_believers"])
        countdowns = [event["endgame_rounds_left"] for event in bridge.session.state.event_log
                      if event["type"] == "endgame_round_completed"]
        self.assertEqual(countdowns, [2, 1, 0])

    def test_empty_phenomenon_pile_without_a_complete_god_has_no_winner(self) -> None:
        self.complete_match(manifest=False)
        self.assertEqual(self.transitions, [(number, None, None) for number in range(1, 5)])
        self.assertFalse(self.view["endgame"])
        self.assertEqual(self.view["body_count"], 2)
        self.assertFalse(any(player["complete"] for player in self.view["players"]))
        match = self.view["match"]
        self.assertTrue(match["game_over"])
        self.assertEqual(match["end_reason"], "phenomenon_draw_pile_empty")
        self.assertEqual(match["winner_ids"], [])
        self.assertEqual(bridge.session.state.phenomenon_draw_pile, [])
        events = self.terminal_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "game_over_terminal")
        self.assertEqual(events[0]["completed_round"], 4)
        self.assertIsNone(events[0]["winner_id"])

    def test_finished_match_rejects_moves_replays_exactly_and_can_restart(self) -> None:
        self.complete_match(manifest=True)
        def snapshot() -> tuple:
            return copy.deepcopy((bridge.browser_view(), bridge.session.state,
                                  bridge.session.match.__dict__, bridge.session.trace))
        expected = snapshot()
        for action, payload in (("mini_next_round", {}), ("mini_end_turn", {}),
                                ("mini_advance", {}), ("mini_move", {"move_index": 0}),
                                ("mini_claim", {"manifest": False})):
            with self.subTest(action=action):
                with self.assertRaises(ValueError):
                    bridge.browser_action(json.dumps({"action": action, "revision": self.view["revision"], **payload}))
                self.assertEqual(snapshot(), expected)
        for _ in range(2):
            self.view = json.loads(bridge.browser_initialize(json.dumps({"commands": self.commands})))
            self.assertEqual(snapshot(), expected)
            self.assertIs(bridge.session.match.state, bridge.session.state)
        self.send("restart")
        self.assertEqual(self.view["stage"], "intro")
        self.send("start_mini", starting_believers=6)
        self.assertEqual(self.view["round"], 1)
        self.assertEqual(self.view["body_count"], 2)
        self.assertEqual(self.view["players"][0]["believers"], 6)
        self.assertEqual(self.view["match"]["phase"], "turn")
        self.assertFalse(self.view["match"]["game_over"])
        self.assertEqual(self.terminal_events(), [])


if __name__ == "__main__":
    unittest.main()
