"""Tests for the `pending` CLI command, including --count."""

import json
import unittest
from unittest.mock import patch

from click.testing import CliRunner

from client.cli import cli


class PendingCountTest(unittest.TestCase):
    """pending --count prints the integer count and exits 0."""

    def setUp(self):
        self.runner = CliRunner()
        # Minimal context every command needs.
        self.ctx = {"url": "http://localhost:8800", "token": "test-token"}

    def test_count_prints_integer(self):
        """--count prints just the integer number of events."""
        mock_events = [
            {"id": 1, "type": "task:new", "status": "pending"},
            {"id": 2, "type": "task:result", "status": "pending"},
            {"id": 3, "type": "task:ack", "status": "pending"},
        ]

        with patch("client.cli.httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            resp = instance.get.return_value
            resp.status_code = 200
            resp.json.return_value = mock_events

            result = self.runner.invoke(
                cli, ["pending", "--agent", "coder", "--count"], obj=self.ctx,
            )

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output.strip(), "3")

    def test_no_count_prints_json(self):
        """Without --count, output is the indented JSON array."""
        mock_events = [
            {"id": 1, "type": "task:new", "status": "pending"},
        ]

        with patch("client.cli.httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            resp = instance.get.return_value
            resp.status_code = 200
            resp.json.return_value = mock_events

            result = self.runner.invoke(
                cli, ["pending", "--agent", "coder"], obj=self.ctx,
            )

        self.assertEqual(result.exit_code, 0)
        expected = json.dumps(mock_events, indent=2, ensure_ascii=False) + "\n"
        self.assertEqual(result.output, expected)

    def test_count_empty_returns_zero(self):
        """--count on an empty queue prints 0."""
        with patch("client.cli.httpx.Client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            resp = instance.get.return_value
            resp.status_code = 200
            resp.json.return_value = []

            result = self.runner.invoke(
                cli, ["pending", "--agent", "coder", "--count"], obj=self.ctx,
            )

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output.strip(), "0")


if __name__ == "__main__":
    unittest.main()
