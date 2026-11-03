"""The new curated setup has a real ready nun; old histories keep their setup."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docs" / "source"))
import bridge  # noqa: E402
from ui.ekona_demo.model import TRUTH_IDS  # noqa: E402


class StartingBattleNunTests(unittest.TestCase):
    def setUp(self) -> None:
        bridge.browser_initialize(json.dumps({"commands": []}))
        self.addCleanup(bridge.browser_initialize, json.dumps({"commands": []}))
        self.commands: list[dict] = []

    def send(self, action: str, **payload: object) -> dict:
        command = {"action": action, "revision": bridge.session.revision, **payload}
        view = json.loads(bridge.browser_action(json.dumps(command)))
        self.commands.append(command)
        return view

    def test_new_browser_setup_has_one_ready_nun_without_triggering_twilight(self) -> None:
        view = json.loads(bridge.browser_initialize(json.dumps({"mini": True})))
        self.assertEqual(view["players"][0]["believers"], 6)
        self.assertEqual(view["players"][0]["bound"], 1)
        self.assertEqual(view["match"]["nun_ready"], 1)
        self.assertTrue(view["match"]["nun_active"])
        self.assertEqual(next(role for role in view["match"]["roles"] if role["type"] == "Nonnen")["assigned"], 1)
        self.assertFalse(view["endgame"])
        self.assertEqual(view["body_count"], 2)
        self.assertIsNone(view["match"]["prophet_holder"])

    def test_old_history_does_not_retroactively_receive_a_nun(self) -> None:
        command = {"action": "start_mini", "revision": 0, "starting_believers": 6}
        view = json.loads(bridge.browser_initialize(json.dumps({"commands": [command]})))
        self.assertEqual(view["match"]["nun_ready"], 0)
        self.assertFalse(view["match"]["nun_active"])
        self.assertEqual(view["players"][0]["bound"], 0)
        self.assertEqual(view["players"][0]["believers"], 6)

    def test_invalid_starting_nuns_are_rejected_atomically(self) -> None:
        before = copy.deepcopy((bridge.browser_view(), bridge.session.state))
        for value in (True, -1, 2, 1.0, "1", None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    bridge.browser_action(json.dumps({"action": "start_mini", "revision": 0,
                                                      "starting_nuns": value}))
                self.assertEqual((bridge.browser_view(), bridge.session.state), before)

    def test_ready_nun_can_be_sacrificed_or_kept_and_replayed(self) -> None:
        for sacrifice in (True, False):
            with self.subTest(sacrifice=sacrifice):
                bridge.browser_initialize(json.dumps({"commands": []}))
                self.commands = []
                view = self.send("start_mini", starting_believers=6, starting_nuns=1)
                view = self.send("mini_end_turn")
                if view["match"]["phase"] == "draw":
                    view = self.send("mini_draw_rest")
                for _ in range(30):
                    match = view["match"]
                    if match["phase"] == "nun":
                        break
                    if match["actor"] in {"p2", "p3"}:
                        view = self.send("mini_advance")
                    elif match["phase"] == "contest":
                        value = 4 if match["own_bid_total"] == 0 else 6
                        card_id = TRUTH_IDS["p1"][value]
                        if any(card["id"] == card_id and card["can_bid"] for card in match["hand"]):
                            view = self.send("mini_bid", card_id=card_id)
                        else:
                            view = self.send("mini_pass")
                    else:
                        self.fail(f"Unexpected phase {match['phase']}")
                else:
                    self.fail("No nun decision window reached")
                view = self.send("mini_nun", sacrifice=sacrifice)
                self.assertEqual(view["match"]["phase"], "claim")
                self.assertEqual(view["match"]["score"]["p1"], 14 if sacrifice else 10)
                self.assertEqual(view["match"]["nun_ready"], 0 if sacrifice else 1)
                self.assertEqual(view["players"][0]["bound"], 0 if sacrifice else 1)
                view = self.send("mini_claim", manifest=False)
                self.assertTrue(view["match"]["prophet"])
                self.assertEqual(view["match"]["prophet_holder"], "p1")
                state = copy.deepcopy(bridge.session.state)
                restored = json.loads(bridge.browser_initialize(json.dumps({"commands": self.commands})))
                self.assertEqual(restored, view)
                self.assertEqual(bridge.session.state, state)


if __name__ == "__main__":
    unittest.main()
