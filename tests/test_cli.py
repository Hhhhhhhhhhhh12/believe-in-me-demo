from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import unittest
from unittest.mock import patch

from believe_engine.__main__ import main


class CliTests(unittest.TestCase):
    def test_json_output_is_machine_readable(self):
        output = StringIO()
        with patch("sys.argv", ["believe-demo", "--seed", "7", "--json"]), redirect_stdout(output):
            self.assertEqual(main(), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "finished")

    def test_invalid_arguments_report_usage_without_traceback(self):
        for args in (["--players", "1"], ["--max-turns", "-1"], ["--seed", "abc"]):
            output = StringIO()
            with self.subTest(args=args), patch("sys.argv", ["believe-demo", *args]), redirect_stderr(output):
                with self.assertRaises(SystemExit) as raised:
                    main()
            self.assertEqual(raised.exception.code, 2)
            self.assertIn("error:", output.getvalue())
            self.assertNotIn("Traceback", output.getvalue())
