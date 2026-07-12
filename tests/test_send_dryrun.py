"""Tests for the `send --dry-run` flag.

Verifies that --dry-run validates the payload, prints the event JSON, and
makes zero HTTP calls.  Non-dry-run send behaviour is unchanged (existing
tests cover that path).
"""

import json
import unittest
from unittest.mock import patch

from click.testing import CliRunner

from client.cli import send


class SendDryRunTest(unittest.TestCase):
    """send --dry-run prints the event and exits 0 without HTTP."""

    def setUp(self):
        self.runner = CliRunner()
        self.ctx = {"url": "http://localhost:8800", "token": "test-token"}

    def test_dry_run_prints_event_and_exits_zero(self):
        """--dry-run prints the complete event JSON and exits 0.

        httpx.Client must never be constructed during dry-run.
        """
        with patch("client.cli.httpx.Client") as MockClient:
            result = self.runner.invoke(
                send, [
                    "--from", "architect",
                    "--to", "coder",
                    "--type", "task:new",
                    "--payload", '{"k": 1}',
                    "--dry-run",
                ],
                obj=self.ctx,
            )

        self.assertEqual(result.exit_code, 0)
        expected = {
            "from_agent": "architect",
            "to_agent": "coder",
            "type": "task:new",
            "payload": {"k": 1},
        }
        self.assertEqual(json.loads(result.output), expected)
        MockClient.assert_not_called()

    def test_dry_run_with_invalid_json_exits_nonzero(self):
        """--dry-run with invalid JSON exits non-zero (existing validation
        from _load_payload runs before the dry-return)."""
        result = self.runner.invoke(
            send, [
                "--from", "architect",
                "--to", "coder",
                "--type", "task:new",
                "--payload", "not-json",
                "--dry-run",
            ],
            obj=self.ctx,
        )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Payload must be valid JSON", result.output)


if __name__ == "__main__":
    unittest.main()
