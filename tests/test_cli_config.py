"""Regression tests for existing CLI and environment configuration behavior."""

import unittest
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from client.cli import cli, get_config


class CliConfigRegressionTests(unittest.TestCase):
    def test_get_config_uses_environment_and_strips_trailing_slash(self):
        env = {
            "AGENT_BUS_URL": "http://env-host:8800/",
            "AGENT_BUS_TOKEN": "env-token",
            "AGENT_BUS_AGENT": "env-agent",
        }

        with patch.dict("os.environ", env, clear=True):
            self.assertEqual(
                get_config(),
                ("http://env-host:8800", "env-token", "env-agent"),
            )

    def test_get_config_keeps_localhost_and_empty_identity_defaults(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(get_config(), ("http://localhost:8800", "", ""))

    def test_explicit_flags_override_environment(self):
        health = MagicMock(status_code=200)
        health.json.return_value = {"status": "ok"}
        pending = MagicMock(status_code=200)
        pending.json.return_value = []

        runner = CliRunner()
        with patch("client.cli.httpx.Client") as client_factory:
            client = client_factory.return_value.__enter__.return_value
            client.get.side_effect = [health, pending]
            result = runner.invoke(
                cli,
                [
                    "--url",
                    "http://flag-host:8800/",
                    "--token",
                    "flag-token",
                    "doctor",
                    "--agent",
                    "flag-agent",
                ],
                env={
                    "AGENT_BUS_URL": "http://env-host:8800",
                    "AGENT_BUS_TOKEN": "env-token",
                    "AGENT_BUS_AGENT": "env-agent",
                },
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn(
            "url=http://flag-host:8800 agent=flag-agent token=set", result.output
        )
        self.assertEqual(
            client.get.call_args_list[0].args[0], "http://flag-host:8800/health"
        )
        self.assertEqual(
            client.get.call_args_list[1].kwargs["params"], {"agent": "flag-agent"}
        )
        self.assertEqual(
            client.get.call_args_list[1].kwargs["headers"]["Authorization"],
            "Bearer flag-token",
        )


if __name__ == "__main__":
    unittest.main()
