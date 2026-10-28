"""Smoke tests for the exported, browser-playable BiM rules engine.

These intentionally use the same bridge API that the Pyodide Web Worker calls,
rather than the separate earlier example under src/believe_engine/.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

PUBLISHED_SOURCE = Path(__file__).resolve().parents[1] / "docs" / "source"
sys.path.insert(0, str(PUBLISHED_SOURCE))

import bridge  # noqa: E402  # Imports the actual exported browser adapter.


class BrowserMiniMatchSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        # The browser bridge holds the active session at module level.
        bridge.browser_initialize(json.dumps({"commands": []}))

    @staticmethod
    def send(command: dict) -> dict:
        return json.loads(bridge.browser_action(json.dumps(command)))

    def start_match(self) -> tuple[dict, dict]:
        command = {"action": "start_mini", "revision": 0, "starting_believers": 6}
        return command, self.send(command)

    def test_starts_a_real_mini_match(self) -> None:
        _, state = self.start_match()

        self.assertEqual(state["stage"], "mini")
        self.assertEqual(state["revision"], 1)
        self.assertEqual(state["match"]["phase"], "turn")
        self.assertEqual(state["match"]["actor"], "p1")
        self.assertEqual({player["id"] for player in state["players"]}, {"p1", "p2", "p3"})
        self.assertGreater(len(state["match"]["hand"]), 0)

    def test_invalid_move_does_not_change_state(self) -> None:
        self.start_match()
        before = json.loads(json.dumps(bridge.browser_view()))

        with self.assertRaises(ValueError):
            self.send({"action": "mini_move", "revision": 1, "move_index": -1})

        self.assertEqual(bridge.browser_view(), before)

    def test_replaying_the_same_commands_is_deterministic(self) -> None:
        start_command, started = self.start_match()
        options = started["match"]["options"]
        self.assertTrue(options, "The real engine should provide legal opening moves")

        move_command = {
            "action": "mini_move",
            "revision": started["revision"],
            "move_index": options[0]["index"],
        }
        expected = self.send(move_command)

        # The browser uses precisely this replay path to restore local progress.
        replayed = json.loads(
            bridge.browser_initialize(
                json.dumps({"commands": [start_command, move_command]})
            )
        )
        self.assertEqual(replayed, expected)


if __name__ == "__main__":
    unittest.main()
