import random
import unittest

from believe_engine.runner import choose_demo_move, run_match
from believe_engine.trace import trace_json


class RunnerTests(unittest.TestCase):
    def test_same_seed_produces_identical_trace(self):
        self.assertEqual(trace_json(run_match(seed=11)), trace_json(run_match(seed=11)))

    def test_seeds_can_change_trace_events(self):
        self.assertNotEqual(run_match(seed=1).final_state.events, run_match(seed=2).final_state.events)

    def test_randomness_is_isolated_from_global_generator(self):
        before = random.getstate()
        run_match(seed=9)
        self.assertEqual(random.getstate(), before)

    def test_supported_player_counts_finish_with_default_budget(self):
        for count in range(2, 9):
            with self.subTest(players=count):
                result = run_match(seed=3, player_count=count)
                self.assertEqual(result.status, "finished")
                self.assertLessEqual(result.turn_count, 200)
                self.assertTrue(all(player.resources >= 0 for player in result.final_state.players))

    def test_turn_limit_is_explicit(self):
        for budget in (0, 1, 2):
            with self.subTest(budget=budget):
                result = run_match(seed=7, max_turns=budget)
                self.assertEqual(result.status, "turn_limit")
                self.assertIsNone(result.winner_id)
                self.assertEqual(result.turn_count, budget)

    def test_invalid_runner_arguments(self):
        for args in ({"max_turns": -1}, {"max_turns": True}, {"max_turns": 1.5}, {"seed": "7"}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                run_match(**({"seed": 7} | args))

    def test_policy_rejects_finished_match(self):
        with self.assertRaises(ValueError):
            choose_demo_move(run_match(seed=7).final_state)
