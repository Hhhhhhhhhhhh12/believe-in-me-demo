"""Exercise the first mini-match contest through the exported browser API.

Use real turns and opponent decisions to reach the contest, without editing the
prepared state or replacing engine functions. Scope: bidding, permanent passes,
reveal/scoring, the fewest-believers tie-break, storage and history restoration.
Nun sacrifices, manifestation and the final tie-break are outside this suite.
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from collections import Counter
from pathlib import Path

PUBLISHED_SOURCE = Path(__file__).resolve().parents[1] / "docs" / "source"
sys.path.insert(0, str(PUBLISHED_SOURCE))

import bridge  # noqa: E402
from ui.ekona_demo.model import IDS, TRUTH_IDS  # noqa: E402


class MiniMatchContestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.view = json.loads(bridge.browser_initialize(json.dumps({"commands": []})))
        self.addCleanup(bridge.browser_initialize, json.dumps({"commands": []}))
        self.commands: list[dict] = []
        self.send("start_mini", starting_believers=6)
        self.send("mini_end_turn")
        if self.view["match"]["phase"] == "draw":
            self.send("mini_draw_rest")
        self.advance_opponents()
        self.assertEqual(self.view["match"]["phase"], "contest")
        self.assertEqual(self.view["match"]["actor"], "p1")
        self.assertEqual(self.view["match"]["prize"], "yak")

    def send(self, action: str, **payload: object) -> dict:
        command = {"action": action, "revision": self.view["revision"], **payload}
        self.view = json.loads(bridge.browser_action(json.dumps(command)))
        self.commands.append(command)
        return self.view

    def bid(self, art: str) -> None:
        cards = [card for card in self.view["match"]["hand"]
                 if card["art"] == art and card["can_bid"]]
        self.assertEqual(len(cards), 1, f"Expected one legal {art} bid")
        self.send("mini_bid", card_id=cards[0]["id"])

    def advance_opponents(self) -> None:
        for _ in range(20):
            if self.view["match"]["actor"] not in {"p2", "p3"}:
                return
            self.send("mini_advance")
        self.fail("Opponent steps did not yield control or finish the contest")

    @staticmethod
    def snapshot() -> tuple:
        return copy.deepcopy((bridge.browser_view(), bridge.session.state,
                              bridge.session.match.__dict__, bridge.session.trace))

    def assert_rejected_without_change(self, action: str, **payload: object) -> None:
        before = self.snapshot()
        command = {"action": action, "revision": self.view["revision"], **payload}
        with self.assertRaises(ValueError):
            bridge.browser_action(json.dumps(command))
        self.assertEqual(self.snapshot(), before)
        self.assertIs(bridge.session.match.state, bridge.session.state)

    def win_with_truth_pair(self) -> None:
        self.bid("truth_p1_4")
        self.advance_opponents()
        self.bid("truth_p1_6")
        self.advance_opponents()
        self.send("mini_pass")
        self.advance_opponents()
        self.assertEqual(self.view["match"]["phase"], "claim")
        self.assertEqual(self.view["match"]["winner"], "p1")

    def test_opening_requires_a_valid_owned_card_before_passing(self) -> None:
        self.assertFalse(self.view["match"]["can_pass"])
        invalid = [
            ("mini_pass", {}),
            ("mini_bid", {}),
            ("mini_bid", {"card_id": "missing-card"}),
            ("mini_bid", {"card_id": TRUTH_IDS["p2"][3]}),
            ("mini_bid", {"card_id": IDS["head"]}),
            ("mini_claim", {"manifest": False}),
        ]
        for action, payload in invalid:
            with self.subTest(action=action, payload=payload):
                self.assert_rejected_without_change(action, **payload)
        self.bid("truth_p1_4")
        self.assertEqual(self.view["match"]["actor"], "p2")

    def test_truth_bid_is_committed_once_and_stays_hidden_until_reveal(self) -> None:
        self.bid("truth_p1_4")
        bid_command = self.commands[-1]
        own = bridge.session.state.players["p1"]
        self.assertNotIn(TRUTH_IDS["p1"][4], [card.card_id for card in own.hand_cards])
        self.assertNotIn(4, own.truth_pool)
        self.assertEqual(own.used_truth, [4])
        self.assertEqual(own.truth_discard, [])
        self.assertEqual(self.view["match"]["own_bid_total"], 4)
        self.assert_rejected_without_change("mini_bid", card_id=TRUTH_IDS["p1"][6])
        self.assert_rejected_without_change(**bid_command)

        self.advance_opponents()
        self.assertEqual(len(bridge.session.match.contest.played_bids), 3)
        self.assertEqual(self.view["match"]["bids"], [])
        self.assertIsNone(self.view["match"]["score"])
        self.assertIsNone(self.view["match"]["winner"])
        self.assertFalse(any(bid.is_open for bid in bridge.session.match.contest.played_bids))
        # The same card also stays unavailable when it really is our turn again.
        self.assert_rejected_without_change("mini_bid", card_id=TRUTH_IDS["p1"][4])
        self.bid("truth_p1_6")
        self.assertEqual(self.view["match"]["own_bid_total"], 10)

    def test_pass_is_permanent_but_earlier_bid_counts_and_tie_uses_believers(self) -> None:
        # Before any prize reward, p2 has four believers including its bound monk;
        # p3 has eleven. Both will contribute seven truth points.
        p2, p3 = (bridge.session.state.players[pid] for pid in ("p2", "p3"))
        self.assertEqual(p2.meeples + sum(p2.assigned_role_meeples.values()), 4)
        self.assertEqual(p3.meeples + sum(p3.assigned_role_meeples.values()), 11)
        self.bid("truth_p1_4")
        self.advance_opponents()
        self.assertTrue(self.view["match"]["can_pass"])
        self.send("mini_pass")
        self.assertTrue(self.view["players"][0]["passed"])
        self.assert_rejected_without_change("mini_bid", card_id=TRUTH_IDS["p1"][6])
        self.advance_opponents()
        self.assertEqual(self.view["match"]["phase"], "round_end")
        self.assertEqual(self.view["match"]["score"], {"p1": 4, "p2": 7, "p3": 7})
        self.assertEqual(self.view["match"]["winner"], "p2")
        self.assertEqual(bridge.session.match.score.tie_breaker, "fewest_believers")
        self.assertEqual(bridge.session.state.players["p2"].stored_phenomena, [IDS["yak"]])
        self.assertEqual(bridge.session.state.players["p1"].stored_phenomena, [])
        self.assert_rejected_without_change("mini_claim", manifest=False)

    def test_highest_total_wins_even_after_passing_and_prize_is_awarded_once(self) -> None:
        self.win_with_truth_pair()
        self.assertTrue(self.view["players"][0]["passed"])
        self.assertEqual(self.view["match"]["score"], {"p1": 10, "p2": 7, "p3": 7})
        self.assertEqual(bridge.session.match.score.tie_breaker, "highest_bid_total")
        self.assertEqual([bid["values"] for bid in self.view["match"]["bids"]],
                         [[4], [3], [2], [6], [4], [5]])
        self.assertTrue(all(bid.is_open for bid in bridge.session.match.contest.played_bids))
        expected_discards = [TRUTH_IDS[pid][value] for pid, value in
                             (("p1", 4), ("p2", 3), ("p3", 2),
                              ("p1", 6), ("p2", 4), ("p3", 5))]
        self.assertEqual(Counter(card.card_id for card in bridge.session.state.truth_discard),
                         Counter(expected_discards))
        for pid, values in (("p1", (4, 6)), ("p2", (3, 4)), ("p3", (2, 5))):
            self.assertEqual(Counter(card.card_id for card in bridge.session.state.players[pid].truth_discard),
                             Counter(TRUTH_IDS[pid][value] for value in values))
        self.assertEqual(self.view["match"]["stored"], [])
        self.send("mini_claim", manifest=False)
        self.assertEqual(self.view["match"]["phase"], "round_end")
        self.assertEqual(self.view["match"]["stored"], ["yak"])
        self.assertEqual(self.view["players"][0]["believers"], 11)
        self.assertEqual(self.view["body_count"], 2)
        self.assertEqual(sum(event["type"] == "phenomenon_claimed"
                             for event in bridge.session.state.event_log), 1)
        self.assert_rejected_without_change("mini_claim", manifest=False)

    def test_heavenly_bid_uses_bid_value_without_playing_its_effect(self) -> None:
        opponents = copy.deepcopy({pid: bridge.session.state.players[pid] for pid in ("p2", "p3")})
        pool = list(bridge.session.state.players["p1"].truth_pool)
        self.bid("army")
        # No legs: Irmgard contributes three truth; bidding does not attack.
        self.assertEqual(self.view["match"]["own_bid_total"], 3)
        self.assertEqual(self.view["players"][0]["believers"], 6)
        self.assertEqual({pid: bridge.session.state.players[pid] for pid in opponents}, opponents)
        self.assertEqual(bridge.session.state.heavenly_discard_pile, [])
        self.advance_opponents()
        self.send("mini_pass")
        self.advance_opponents()
        self.assertEqual(self.view["match"]["score"], {"p1": 3, "p2": 7, "p3": 7})
        self.assertEqual([card.card_id for card in bridge.session.state.heavenly_discard_pile], [IDS["army"]])
        own = bridge.session.state.players["p1"]
        self.assertEqual(own.truth_pool, pool)
        self.assertEqual(own.used_truth, [])
        self.assertEqual(own.truth_discard, [])

    def test_replay_restores_hidden_bids_then_resolved_prize_without_duplicates(self) -> None:
        self.bid("truth_p1_4")
        self.send("mini_advance")  # p2 commits; p3 still has to act.
        mid_contest = self.snapshot()
        self.view = json.loads(bridge.browser_initialize(json.dumps({"commands": self.commands})))
        self.assertEqual(self.snapshot(), mid_contest)
        self.assertIs(bridge.session.match.state, bridge.session.state)
        self.advance_opponents()
        self.bid("truth_p1_6")
        self.advance_opponents()
        self.send("mini_pass")
        self.advance_opponents()
        self.assertEqual(self.view["match"]["winner"], "p1")
        self.send("mini_claim", manifest=False)
        resolved = self.snapshot()
        for _ in range(2):
            self.view = json.loads(bridge.browser_initialize(json.dumps({"commands": self.commands})))
            self.assertEqual(self.snapshot(), resolved)
            self.assertIs(bridge.session.match.state, bridge.session.state)
        self.send("mini_next_round")
        self.assertEqual(self.view["round"], 2)
        self.assertEqual(self.view["match"]["phase"], "turn")


if __name__ == "__main__":
    unittest.main()
