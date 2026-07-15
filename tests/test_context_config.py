"""Tests for native Agent Bus client contexts."""

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from client.cli import cli
from client.context_config import (
    ContextError,
    ContextStore,
    default_context_root,
    resolve_runtime_config,
    validate_context_name,
)


class ContextPathTests(unittest.TestCase):
    def test_posix_root_prefers_xdg_then_home_config(self):
        home = Path("/home/tester")
        self.assertEqual(
            default_context_root(
                env={"XDG_CONFIG_HOME": "/custom/config"},
                platform="posix",
                home=home,
            ),
            (Path("/custom/config/agent-bus"), None),
        )
        self.assertEqual(
            default_context_root(env={}, platform="posix", home=home),
            (home / ".config" / "agent-bus", None),
        )

    def test_windows_root_uses_appdata_with_clear_safe_fallback(self):
        home = Path("C:/Users/tester")
        self.assertEqual(
            default_context_root(
                env={"APPDATA": "C:/Users/tester/AppData/Roaming"},
                platform="nt",
                home=home,
            ),
            (Path("C:/Users/tester/AppData/Roaming/agent-bus"), None),
        )
        root, notice = default_context_root(env={}, platform="nt", home=home)
        self.assertEqual(root, home / "AppData" / "Roaming" / "agent-bus")
        self.assertIn("APPDATA is not set", notice)
        self.assertIn(os.fspath(root), notice)

    def test_context_names_reject_path_traversal_and_unsafe_characters(self):
        for name in ("../coder", "a/b", "a\\b", ".", "..", " coder", "coder token"):
            with self.subTest(name=name):
                with self.assertRaises(ContextError):
                    validate_context_name(name)
        self.assertEqual(validate_context_name("coder.eu-1"), "coder.eu-1")


class ContextStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "agent-bus"
        self.store = ContextStore(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_use_list_show_delete_round_trip(self):
        self.store.add(
            "coder",
            server="http://mesh-host:8800/",
            agent="coder",
            token_env="AWF_CODER_TOKEN",
        )
        self.store.use("coder")

        self.assertEqual(self.store.list_names(), ["coder"])
        self.assertEqual(self.store.current_name(), "coder")
        if os.name != "nt":
            self.assertEqual(
                stat.S_IMODE(self.store.current_path.stat().st_mode), 0o600
            )
        self.assertEqual(
            self.store.get("coder"),
            {
                "version": 1,
                "server": "http://mesh-host:8800",
                "agent": "coder",
                "credential": {"type": "env", "name": "AWF_CODER_TOKEN"},
            },
        )
        with self.assertRaisesRegex(ContextError, "currently selected"):
            self.store.delete("coder")
        self.store.delete("coder", force=True)
        self.assertEqual(self.store.list_names(), [])
        self.assertIsNone(self.store.current_name())

    def test_env_file_reference_records_only_path_and_key(self):
        secret = "never-store-this-token"
        self.store.add(
            "coder",
            server="https://mesh-host.example:8800",
            agent="coder",
            token_env="AWF_CODER_TOKEN",
            env_file="~/.config/awf/dispatch.env",
        )

        context_path = self.root / "contexts" / "coder.json"
        raw = context_path.read_text(encoding="utf-8")
        self.assertNotIn(secret, raw)
        self.assertEqual(
            json.loads(raw)["credential"],
            {
                "type": "env-file",
                "path": "~/.config/awf/dispatch.env",
                "key": "AWF_CODER_TOKEN",
            },
        )
        self.assertFalse(list(context_path.parent.glob("*.tmp")))
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(context_path.stat().st_mode), 0o600)

    def test_add_refuses_overwrite_without_force(self):
        self.store.add(
            "coder",
            server="http://first:8800",
            agent="coder",
            token_env="TOKEN",
        )
        with self.assertRaisesRegex(ContextError, "already exists"):
            self.store.add(
                "coder",
                server="http://second:8800",
                agent="coder",
                token_env="TOKEN",
            )
        self.assertEqual(self.store.get("coder")["server"], "http://first:8800")

    def test_env_file_must_be_stable_and_terminal_safe(self):
        with self.assertRaisesRegex(ContextError, "absolute"):
            self.store.add(
                "relative",
                server="http://mesh-host:8800",
                agent="coder",
                token_env="TOKEN",
                env_file=".env",
            )
        with self.assertRaisesRegex(ContextError, "control characters"):
            self.store.add(
                "unsafe-path",
                server="http://mesh-host:8800",
                agent="coder",
                token_env="TOKEN",
                env_file="~/credentials\x1b[31m.env",
            )
        with self.assertRaisesRegex(ContextError, "control characters"):
            self.store.add(
                "unsafe-server",
                server="http://mesh-host:8800/\x1b[31m",
                agent="coder",
                token_env="TOKEN",
            )

    def test_loader_rejects_fields_outside_context_boundary(self):
        path = self.root / "contexts" / "coder.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "server": "http://mesh-host:8800",
                    "agent": "coder",
                    "credential": {"type": "env", "name": "TOKEN"},
                    "repo_dir": "/workspace/project",
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ContextError, "unsupported fields"):
            self.store.get("coder")

    def test_loader_wraps_malformed_credential_types_as_context_errors(self):
        path = self.root / "contexts" / "coder.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "server": "http://mesh-host:8800",
                    "agent": "coder",
                    "credential": {"type": "env", "name": ["TOKEN"]},
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ContextError, "variable name is invalid"):
            self.store.get("coder")


class ContextResolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "agent-bus"
        self.store = ContextStore(self.root)
        self.env_file = Path(self.tmp.name) / "dispatch.env"
        self.env_file.write_text(
            "export AWF_CODER_TOKEN=context-secret\n", encoding="utf-8"
        )
        self.store.add(
            "coder",
            server="http://context-host:8800",
            agent="context-agent",
            token_env="AWF_CODER_TOKEN",
            env_file=os.fspath(self.env_file),
        )
        self.store.use("coder")

    def tearDown(self):
        self.tmp.cleanup()

    def test_precedence_is_flags_then_environment_then_context_then_defaults(self):
        from_flags = resolve_runtime_config(
            cli_url="http://flag-host:8800/",
            cli_token="flag-secret",
            cli_agent="flag-agent",
            env={
                "AGENT_BUS_URL": "http://env-host:8800",
                "AGENT_BUS_TOKEN": "env-secret",
                "AGENT_BUS_AGENT": "env-agent",
            },
            root=self.root,
        )
        self.assertEqual(
            (from_flags.url, from_flags.token, from_flags.agent),
            ("http://flag-host:8800", "flag-secret", "flag-agent"),
        )

        from_env = resolve_runtime_config(
            env={
                "AGENT_BUS_URL": "http://env-host:8800/",
                "AGENT_BUS_TOKEN": "env-secret",
                "AGENT_BUS_AGENT": "env-agent",
            },
            root=self.root,
        )
        self.assertEqual(
            (from_env.url, from_env.token, from_env.agent),
            ("http://env-host:8800", "env-secret", "env-agent"),
        )

        from_context = resolve_runtime_config(env={}, root=self.root)
        self.assertEqual(
            (from_context.url, from_context.token, from_context.agent),
            ("http://context-host:8800", "context-secret", "context-agent"),
        )

        defaults = resolve_runtime_config(
            env={}, root=Path(self.tmp.name) / "empty-agent-bus"
        )
        self.assertEqual(
            (defaults.url, defaults.token, defaults.agent),
            ("http://localhost:8800", "", ""),
        )

    def test_environment_token_does_not_require_context_credential_file(self):
        self.env_file.unlink()
        resolved = resolve_runtime_config(
            env={"AGENT_BUS_TOKEN": "headless-secret"}, root=self.root
        )
        self.assertEqual(resolved.token, "headless-secret")

    def test_complete_environment_ignores_a_stale_selected_context(self):
        (self.root / "contexts" / "coder.json").unlink()
        resolved = resolve_runtime_config(
            env={
                "AGENT_BUS_URL": "http://headless-host:8800",
                "AGENT_BUS_TOKEN": "headless-secret",
                "AGENT_BUS_AGENT": "headless-agent",
            },
            root=self.root,
        )
        self.assertEqual(
            (resolved.url, resolved.token, resolved.agent),
            ("http://headless-host:8800", "headless-secret", "headless-agent"),
        )

    def test_explicit_context_is_validated_even_with_complete_environment(self):
        (self.root / "contexts" / "coder.json").unlink()
        with self.assertRaisesRegex(ContextError, "does not exist"):
            resolve_runtime_config(
                context_name="coder",
                env={
                    "AGENT_BUS_URL": "http://headless-host:8800",
                    "AGENT_BUS_TOKEN": "headless-secret",
                    "AGENT_BUS_AGENT": "headless-agent",
                },
                root=self.root,
            )


class ContextCliTests(unittest.TestCase):
    def test_context_commands_are_discoverable_and_never_print_token_value(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "XDG_CONFIG_HOME": tmp,
                "AWF_CODER_TOKEN": "never-print-this-token",
            }
            added = runner.invoke(
                cli,
                [
                    "context",
                    "add",
                    "coder",
                    "--server",
                    "http://mesh-host:8800",
                    "--agent",
                    "coder",
                    "--token-env",
                    "AWF_CODER_TOKEN",
                    "--select",
                ],
                env=env,
            )
            listed = runner.invoke(cli, ["context", "list"], env=env)
            shown = runner.invoke(cli, ["context", "show"], env=env)
            help_result = runner.invoke(cli, ["context", "--help"], env=env)

        for result in (added, listed, shown, help_result):
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertNotIn("never-print-this-token", result.output)
        self.assertIn("* coder", listed.output)
        self.assertIn('"type": "env"', shown.output)
        for command in ("add", "list", "show", "use", "delete"):
            self.assertIn(command, help_result.output)

    def test_selected_context_supplies_sender_identity_without_exports(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {"XDG_CONFIG_HOME": tmp, "CODER_TOKEN": "secret"}
            add_result = runner.invoke(
                cli,
                [
                    "context",
                    "add",
                    "coder",
                    "--server",
                    "http://mesh-host:8800",
                    "--agent",
                    "coder",
                    "--token-env",
                    "CODER_TOKEN",
                    "--select",
                ],
                env=env,
            )
            result = runner.invoke(
                cli,
                [
                    "send",
                    "--to",
                    "receiver",
                    "--type",
                    "task:new",
                    "--dry-run",
                ],
                env=env,
            )

        self.assertEqual(add_result.exit_code, 0, add_result.output)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(json.loads(result.output)["from_agent"], "coder")

    def test_help_dry_run_and_legacy_init_do_not_require_context_credential(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {"XDG_CONFIG_HOME": tmp}
            store = ContextStore(root / "agent-bus")
            store.add(
                "coder",
                server="http://mesh-host:8800",
                agent="coder",
                token_env="MISSING_TOKEN",
            )
            store.use("coder")

            help_result = runner.invoke(cli, ["send", "--help"], env=env)
            doctor_result = runner.invoke(cli, ["doctor"], env=env)
            dry_run = runner.invoke(
                cli,
                [
                    "send",
                    "--to",
                    "receiver",
                    "--type",
                    "task:new",
                    "--dry-run",
                ],
                env=env,
            )

            awf_env = root / "dispatch.env"
            repo = root / "repo"
            scripts = root / "scripts"
            output = root / "listener.env"
            awf_env.touch()
            repo.mkdir()
            scripts.mkdir()
            init_result = runner.invoke(
                cli,
                [
                    "init",
                    "--agent",
                    "coder",
                    "--server-url",
                    "http://mesh-host:8800",
                    "--token-env",
                    "MISSING_TOKEN",
                    "--awf-env",
                    os.fspath(awf_env),
                    "--repo-dir",
                    os.fspath(repo),
                    "--script-dir",
                    os.fspath(scripts),
                    "--config",
                    os.fspath(output),
                ],
                env=env,
            )

        for result in (help_result, dry_run, init_result):
            self.assertEqual(result.exit_code, 0, result.output)
        self.assertNotEqual(doctor_result.exit_code, 0)
        self.assertIn("MISSING_TOKEN", doctor_result.output)
        self.assertNotIn("token=set", doctor_result.output)
        self.assertEqual(json.loads(dry_run.output)["from_agent"], "coder")
        self.assertIn("listener.env remains supported", init_result.output)

    def test_command_flags_and_help_ignore_a_stale_selected_context(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            env = {"XDG_CONFIG_HOME": tmp}
            store = ContextStore(Path(tmp) / "agent-bus")
            store.add(
                "stale",
                server="http://stale-host:8800",
                agent="stale-agent",
                token_env="STALE_TOKEN",
            )
            store.use("stale")
            (store.contexts_dir / "stale.json").unlink()

            help_result = runner.invoke(cli, ["pending", "--help"], env=env)
            with patch("client.cli.httpx.Client") as client_factory:
                response = (
                    client_factory.return_value.__enter__.return_value.get.return_value
                )
                response.status_code = 200
                response.json.return_value = []
                command_result = runner.invoke(
                    cli,
                    [
                        "--url",
                        "http://flag-host:8800",
                        "--token",
                        "flag-token",
                        "pending",
                        "--agent",
                        "flag-agent",
                        "--count",
                    ],
                    env=env,
                )

        self.assertEqual(help_result.exit_code, 0, help_result.output)
        self.assertEqual(command_result.exit_code, 0, command_result.output)
        self.assertEqual(command_result.output.strip(), "0")


if __name__ == "__main__":
    unittest.main()
