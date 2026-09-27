import unittest

from believe_engine.metrics import summarize_results
from believe_engine.runner import run_match


class MetricsTests(unittest.TestCase):
    def test_empty_summary(self):
        self.assertEqual(summarize_results([]), {
            "games": 0, "finished_games": 0, "turn_limited_games": 0,
            "winner_counts": {}, "average_turns": 0.0,
        })

    def test_unfinished_runs_are_not_counted_as_winners(self):
        finished = run_match(seed=7)
        limited = run_match(seed=7, max_turns=0)
        result = summarize_results(iter((finished, limited)))
        self.assertEqual(result, {
            "games": 2, "finished_games": 1, "turn_limited_games": 1,
            "winner_counts": {finished.winner_id: 1},
            "average_turns": finished.turn_count / 2,
        })
