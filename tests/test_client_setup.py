"""Behavior and security checks for the cross-platform client setup command."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from click.testing import CliRunner
from dotenv import dotenv_values

from client.cli import cli
from client.context_config import ContextError, write_credential_file


ROOT = Path(__file__).resolve().parents[1]


class ClientCredentialTests(unittest.TestCase):
    def test_private_dotenv_round_trip_preserves_token_without_shell_evaluation(self):
        with tempfile.TemporaryDirectory() as tmp:
            credential = Path(tmp) / "coder.credentials.env"
            token = 'value with # "quotes" and \\slashes'

            write_credential_file(credential, token)

            self.assertEqual(
                dotenv_values(credential)["AGENT_BUS_CLIENT_TOKEN"],
                token,
            )
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(credential.stat().st_mode), 0o600)

    def test_credential_rejects_empty_multiline_and_symlink_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for token in ("", "line1\nline2", "nul\x00token"):
                with self.subTest(token=repr(token)):
                    with self.assertRaises(ContextError):
                        write_credential_file(root / "credential.env", token)

            if os.name != "nt":
                target = root / "target"
                target.write_text("do not replace", encoding="utf-8")
                link = root / "linked.env"
                link.symlink_to(target)
                with self.assertRaisesRegex(ContextError, "symlinked"):
                    write_credential_file(link, "safe-token")
                self.assertEqual(target.read_text(encoding="utf-8"), "do not replace")


class ClientSetupCommandTests(unittest.TestCase):
    def test_setup_writes_token_free_context_selects_it_and_verifies(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            health = Mock(status_code=200)
            health.json.return_value = {"status": "ok"}
            pending = Mock(status_code=200)
            pending.json.return_value = []

            with patch("client.cli.httpx.Client") as client_factory:
                client = client_factory.return_value.__enter__.return_value
                client.get.side_effect = [health, pending]
                result = runner.invoke(
                    cli,
                    [
                        "setup",
                        "--server",
                        "http://mesh-host:8800",
                        "--agent",
                        "architect",
                    ],
                    input="secret-token\n",
                    env={"XDG_CONFIG_HOME": tmp},
                )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertNotIn("secret-token", result.output)
            self.assertIn("All checks passed.", result.output)

            root = Path(tmp) / "agent-bus"
            credential = root / "architect.credentials.env"
            context = root / "contexts" / "architect.json"
            self.assertEqual(
                dotenv_values(credential)["AGENT_BUS_CLIENT_TOKEN"],
                "secret-token",
            )
            context_data = json.loads(context.read_text(encoding="utf-8"))
            self.assertEqual(context_data["server"], "http://mesh-host:8800")
            self.assertEqual(context_data["agent"], "architect")
            self.assertEqual(
                context_data["credential"],
                {
                    "type": "env-file",
                    "path": os.fspath(credential),
                    "key": "AGENT_BUS_CLIENT_TOKEN",
                },
            )
            self.assertNotIn("secret-token", context.read_text(encoding="utf-8"))
            self.assertEqual(
                (root / "current-context").read_text(encoding="utf-8"),
                "architect\n",
            )

    def test_setup_can_be_noninteractive_and_reuses_existing_credential(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "XDG_CONFIG_HOME": tmp,
                "AGENT_BUS_SERVER": "http://mesh-host:8800",
                "AGENT_BUS_AGENT": "coder",
                "AGENT_BUS_CLIENT_TOKEN": "first-token",
            }
            first = runner.invoke(cli, ["setup", "--no-verify"], env=env)
            self.assertEqual(first.exit_code, 0, first.output)

            env.pop("AGENT_BUS_CLIENT_TOKEN")
            second = runner.invoke(cli, ["setup", "--no-verify"], env=env)
            self.assertEqual(second.exit_code, 0, second.output)
            self.assertIn("Reusing protected credential", second.output)
            credential = Path(tmp) / "agent-bus" / "coder.credentials.env"
            self.assertEqual(
                dotenv_values(credential)["AGENT_BUS_CLIENT_TOKEN"],
                "first-token",
            )

    def test_setup_validates_context_name_before_writing_a_credential(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            result = runner.invoke(
                cli,
                [
                    "setup",
                    "--server",
                    "http://mesh-host:8800",
                    "--agent",
                    "coder",
                    "--name",
                    "../outside",
                    "--no-verify",
                ],
                env={
                    "XDG_CONFIG_HOME": tmp,
                    "AGENT_BUS_CLIENT_TOKEN": "must-not-be-written",
                },
            )

            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("context name must start", result.output)
            self.assertFalse((Path(tmp) / "outside.credentials.env").exists())

    def test_setup_rejects_symlinked_existing_credential(self):
        if os.name == "nt":
            self.skipTest("symlink creation is not reliably available on Windows CI")
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "agent-bus"
            root.mkdir()
            target = Path(tmp) / "target.env"
            target.write_text("AGENT_BUS_CLIENT_TOKEN=external\n", encoding="utf-8")
            (root / "coder.credentials.env").symlink_to(target)

            result = runner.invoke(
                cli,
                [
                    "setup",
                    "--server",
                    "http://mesh-host:8800",
                    "--agent",
                    "coder",
                    "--no-verify",
                ],
                env={"XDG_CONFIG_HOME": tmp},
            )

            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("symlinked credential", result.output)
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "AGENT_BUS_CLIENT_TOKEN=external\n",
            )

    def test_setup_verifies_the_new_context_not_legacy_environment(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            health = Mock(status_code=200)
            health.json.return_value = {"status": "ok"}
            pending = Mock(status_code=200)
            pending.json.return_value = []
            env = {
                "XDG_CONFIG_HOME": tmp,
                "AGENT_BUS_CLIENT_TOKEN": "new-token",
                "AGENT_BUS_URL": "http://stale-host:8800",
                "AGENT_BUS_TOKEN": "stale-token",
                "AGENT_BUS_AGENT": "stale-agent",
            }

            with patch("client.cli.httpx.Client") as client_factory:
                client = client_factory.return_value.__enter__.return_value
                client.get.side_effect = [health, pending]
                result = runner.invoke(
                    cli,
                    [
                        "setup",
                        "--server",
                        "http://new-host:8800",
                        "--agent",
                        "coder",
                    ],
                    env=env,
                )

            self.assertEqual(result.exit_code, 0, result.output)
            calls = client.get.call_args_list
            self.assertEqual(calls[0].args[0], "http://new-host:8800/health")
            self.assertEqual(calls[1].args[0], "http://new-host:8800/events/pending")
            self.assertEqual(
                calls[1].kwargs["headers"]["Authorization"],
                "Bearer new-token",
            )


class ClientSetupAcceptanceContractTests(unittest.TestCase):
    def test_windows_ci_runs_the_same_installed_command_as_other_platforms(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        acceptance = (ROOT / "scripts" / "test-client-setup.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("uv tool install", workflow)
        self.assertIn("python scripts/test-client-setup.py", workflow)
        self.assertIn('"setup"', acceptance)
        self.assertIn('"doctor"', acceptance)
        self.assertNotIn("powershell", workflow.lower())


if __name__ == "__main__":
    unittest.main()
