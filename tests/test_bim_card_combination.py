"""Regression checks for Ansgard's skull followed by Loblied in the mini-match.

Exercise the exported browser command API without replacing engine decisions.
The prepared player has Chaos alignment: Loblied grants four believers, and an
already placed skull adds two. Placing the skull costs two and one action.
These checks cover this opening combination, not bidding or a complete match.
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
from ui.ekona_demo.model import IDS  # noqa: E402


class MiniMatchCardCombinationTests(unittest.TestCase):
    def setUp(self) -> None:
        bridge.browser_initialize(json.dumps({"commands": []}))
        self.addCleanup(bridge.browser_initialize, json.dumps({"commands": []}))
        self.commands: list[dict] = []
        self.view = self.send("start_mini", starting_believers=6)

    def send(self, action: str, **payload: object) -> dict:
        command = {"action": action, "revision": bridge.session.revision, **payload}
        result = json.loads(bridge.browser_action(json.dumps(command)))
        self.commands.append(command)
        return result

    def play(self, art: str) -> dict:
        options = [option for option in self.view["match"]["options"]
                   if option.get("kind") == "play" and option.get("art") == art]
        self.assertEqual(len(options), 1, f"Expected exactly one legal {art} play")
        self.view = self.send("mini_move", move_index=options[0]["index"])
        return self.view

    def assert_rejected_without_change(self, command: dict) -> None:
        before_view = copy.deepcopy(bridge.browser_view())
        before_state = copy.deepcopy(bridge.session.state)
        before_trace = copy.deepcopy(bridge.session.trace)
        with self.assertRaises(ValueError):
            bridge.browser_action(json.dumps(command))
        self.assertEqual(bridge.browser_view(), before_view)
        self.assertEqual(bridge.session.state, before_state)
        self.assertEqual(bridge.session.trace, before_trace)

    def test_skull_cost_and_blessing_bonus_consume_exactly_two_actions(self) -> None:
        opponents = copy.deepcopy({pid: bridge.session.state.players[pid]
                                   for pid in ("p2", "p3")})
        self.assertEqual(self.view["players"][0]["alignment"], "<Chaos>")
        self.play("skull")
        self.assertEqual(self.view["players"][0]["believers"], 4)
        self.assertEqual(self.view["actions"], 1)
        self.assertIn("skull", self.view["tableau"])
        self.assertNotIn("skull", [card["art"] for card in self.view["match"]["hand"]])

        self.play("song")
        # Six starting believers - two cost + four Chaos reward + two bonus.
        self.assertEqual(self.view["players"][0]["believers"], 10)
        self.assertEqual(self.view["actions"], 0)
        self.assertEqual(self.view["match"]["options"], [])
        self.assertIn("skull", self.view["tableau"])
        self.assertNotIn("song", [card["art"] for card in self.view["match"]["hand"]])
        self.assertEqual([card.card_id for card in bridge.session.state.heavenly_discard_pile],
                         [IDS["song"]])
        bonuses = [event for event in bridge.session.state.event_log
                   if event["type"] == "relic_blessing_bonus_applied"]
        self.assertEqual(len(bonuses), 1)
        self.assertEqual(bonuses[0]["blessing_bonus"], 2)
        self.assertEqual(bonuses[0]["card_id"], IDS["song"])
        self.assertEqual(bonuses[0]["relic_card_ids"], [IDS["skull"]])
        self.assertEqual({pid: bridge.session.state.players[pid] for pid in opponents},
                         opponents)

    def test_skull_does_not_retroactively_boost_an_earlier_blessing(self) -> None:
        self.play("song")
        self.assertEqual(self.view["players"][0]["believers"], 10)
        self.assertEqual(self.view["actions"], 1)
        self.play("skull")
        self.assertEqual(self.view["players"][0]["believers"], 8)
        self.assertEqual(self.view["actions"], 0)
        self.assertFalse(any(event["type"] == "relic_blessing_bonus_applied"
                             for event in bridge.session.state.event_log))

    def test_third_action_is_rejected_without_changing_the_completed_combo(self) -> None:
        self.play("skull")
        ash_index = next(option["index"] for option in self.view["match"]["options"]
                         if option.get("art") == "ash")
        self.play("song")
        self.assert_rejected_without_change({"action": "mini_move",
                                            "revision": self.view["revision"],
                                            "move_index": ash_index})
        # Rejection leaves a usable session: ending the turn remains possible.
        self.view = self.send("mini_end_turn")
        self.assertEqual(self.view["match"]["phase"], "draw")

    def test_duplicate_blessing_command_cannot_award_the_bonus_twice(self) -> None:
        self.play("skull")
        self.play("song")
        self.assert_rejected_without_change(self.commands[-1])
        self.assertEqual(bridge.session.state.players["p1"].meeples, 10)

    def test_replay_restores_combo_without_duplicating_rewards_or_discards(self) -> None:
        self.play("skull")
        self.play("song")
        expected_view = copy.deepcopy(self.view)
        expected_state = copy.deepcopy(bridge.session.state)
        # Replay twice, so restoration must replace rather than accumulate state.
        for _ in range(2):
            restored = json.loads(bridge.browser_initialize(json.dumps({"commands": self.commands})))
            self.assertEqual(restored, expected_view)
            self.assertEqual(bridge.session.state, expected_state)
        self.view = self.send("mini_end_turn")
        self.assertEqual(self.view["match"]["phase"], "draw")
        self.assertEqual(self.view["players"][0]["believers"], 10)


if __name__ == "__main__":
    unittest.main()
