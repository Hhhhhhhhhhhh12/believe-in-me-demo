import json
import unittest

from believe_engine.runner import run_match
from believe_engine.trace import trace_json, trace_payload


class TraceTests(unittest.TestCase):
    def test_trace_fields_and_json_contract(self):
        result = run_match(seed=5)
        payload = trace_payload(result)
        self.assertEqual(set(payload), {
            "schema_version", "seed", "status", "turn_count", "winner_id", "events", "players",
        })
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(json.loads(trace_json(result)), payload)
        self.assertTrue({"round", "turn_index", "player_id", "type"} <= payload["events"][0].keys())

    def test_export_cannot_mutate_engine_or_another_export(self):
        result = run_match(seed=5)
        before = trace_json(result)
        exported = trace_payload(result)
        exported["events"][0]["type"] = "changed"
        exported["players"][0]["resources"] = -999
        exported["events"].clear()
        self.assertEqual(trace_json(result), before)

    def test_finished_trace_has_one_terminal_event(self):
        result = run_match(seed=7)
        events = trace_payload(result)["events"]
        self.assertEqual(len(events), result.turn_count + 1)
        self.assertEqual(sum(event["type"] == "match_finished" for event in events), 1)
        self.assertEqual(events[-1]["winner_id"], result.winner_id)

    def test_zero_turn_trace_is_valid_json(self):
        payload = json.loads(trace_json(run_match(seed=7, max_turns=0)))
        self.assertEqual(payload["status"], "turn_limit")
        self.assertEqual(payload["events"], [])
        self.assertIsNone(payload["winner_id"])
