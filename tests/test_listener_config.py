"""Tests for repeatable workflow-listener initialization."""

import stat
import tempfile
import unittest
from pathlib import Path
from pathlib import PureWindowsPath
from unittest.mock import patch

from click.testing import CliRunner

from client.cli import cli
from client.listener_config import (
    listener_environment_issues,
    render_listener_env,
    source_path,
    warm_network_path,
)


class ListenerConfigTests(unittest.TestCase):
    def test_render_bridges_role_token_without_copying_secret(self):
        rendered = render_listener_env(
            agent="coder",
            url="http://mesh-host:8800",
            awf_env=Path("/config/awf/dispatch.env"),
            repo_dir=Path("D:/workspace/repo"),
            script_dir=Path("D:/workspace/workflow/scripts"),
        )

        self.assertIn("${AWF_CODER_TOKEN:?AWF_CODER_TOKEN is required}", rendered)
        self.assertIn("export AWF_REPO_DIR='D:/workspace/repo'", rendered)
        self.assertIn("export AGENT_BUS_NETWORK_HOST='mesh-host'", rendered)
        self.assertIn("OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS=true", rendered)

    def test_windows_awf_env_is_rendered_for_git_bash_source(self):
        self.assertEqual(
            source_path(PureWindowsPath("D:/workspace/config/dispatch.env")),
            "/d/workspace/config/dispatch.env",
        )

    def test_explicit_token_env_supports_existing_role_alias(self):
        rendered = render_listener_env(
            agent="architect",
            token_env="AWF_ARCH_TOKEN",
            url="http://mesh-host:8800",
            awf_env=Path("/config/awf/dispatch.env"),
            repo_dir=Path("/workspace/repo"),
            script_dir=Path("/workspace/scripts"),
        )

        self.assertIn("${AWF_ARCH_TOKEN:?AWF_ARCH_TOKEN is required}", rendered)
        self.assertNotIn("AWF_ARCHITECT_TOKEN", rendered)

    def test_rejects_unsafe_token_env_name(self):
        with self.assertRaisesRegex(ValueError, "variable name is invalid"):
            render_listener_env(
                agent="architect",
                token_env="AWF_ARCH_TOKEN$(bad)",
                url="http://mesh-host:8800",
                awf_env=Path("/config/awf/dispatch.env"),
                repo_dir=Path("/workspace/repo"),
                script_dir=Path("/workspace/scripts"),
            )

    def test_rejects_shell_metacharacters_in_hostname(self):
        with self.assertRaisesRegex(ValueError, "unsupported characters"):
            render_listener_env(
                agent="coder",
                url="http://mesh$(touch-x):8800",
                awf_env=Path("/config/dispatch.env"),
                repo_dir=Path("/workspace/repo"),
                script_dir=Path("/workspace/scripts"),
            )

    def test_init_writes_private_file_and_never_prints_token(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            awf_env = root / "dispatch.env"
            repo = root / "repo"
            scripts = root / "scripts"
            output = root / "config" / "listener.env"
            awf_env.write_text("export AWF_CODER_TOKEN=top-secret\n", encoding="utf-8")
            repo.mkdir()
            scripts.mkdir()

            result = runner.invoke(
                cli,
                [
                    "init",
                    "--agent",
                    "coder",
                    "--server-url",
                    "http://mesh-host:8800",
                    "--awf-env",
                    str(awf_env),
                    "--repo-dir",
                    str(repo),
                    "--script-dir",
                    str(scripts),
                    "--config",
                    str(output),
                ],
            )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertNotIn("top-secret", result.output)
            self.assertNotIn("top-secret", output.read_text(encoding="utf-8"))
            self.assertIn("Load it with: source '", result.output)
            self.assertIn("listener.env'", result.output)
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)

    def test_init_refuses_to_overwrite_without_force(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = root / "dispatch.env"
            env_file.touch()
            repo = root / "repo"
            scripts = root / "scripts"
            repo.mkdir()
            scripts.mkdir()
            output = root / "listener.env"
            output.write_text("keep", encoding="utf-8")
            args = [
                "init",
                "--agent",
                "coder",
                "--server-url",
                "http://host:8800",
                "--awf-env",
                str(env_file),
                "--repo-dir",
                str(repo),
                "--script-dir",
                str(scripts),
                "--config",
                str(output),
            ]

            result = runner.invoke(cli, args)

            self.assertNotEqual(result.exit_code, 0)
            self.assertEqual(output.read_text(encoding="utf-8"), "keep")

    def test_listener_diagnostics_are_static_and_actionable(self):
        with tempfile.TemporaryDirectory() as tmp:
            complete = {
                "AGENT_BUS_TOKEN": "secret",
                "AGENT_BUS_AGENT": "coder",
                "AWF_REPO_DIR": tmp,
                "AWF_SCRIPT_DIR": tmp,
                "OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS": "true",
                "AGENT_BUS_NETWORK_HOST": "mesh-host",
                "AGENT_BUS_WARMUP_COMMAND": "true",
                "NO_PROXY": "localhost,mesh-host",
            }
            self.assertEqual(listener_environment_issues(complete), [])

            broken = dict(complete)
            broken.pop("AGENT_BUS_TOKEN")
            broken["NO_PROXY"] = "localhost"
            self.assertEqual(
                listener_environment_issues(broken),
                [
                    "AGENT_BUS_TOKEN is not set",
                    "AGENT_BUS_NETWORK_HOST is missing from NO_PROXY",
                ],
            )

    def test_missing_warmup_configuration_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "AGENT_BUS_TOKEN": "secret",
                "AGENT_BUS_AGENT": "coder",
                "AWF_REPO_DIR": tmp,
                "AWF_SCRIPT_DIR": tmp,
                "OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS": "true",
            }
            issues = listener_environment_issues(env)
            self.assertIn("AGENT_BUS_NETWORK_HOST is not set", issues)
            self.assertIn("AGENT_BUS_WARMUP_COMMAND is not set", issues)

    @patch("client.listener_config.subprocess.run")
    def test_network_warmup_uses_argv_without_shell(self, run):
        run.return_value.returncode = 0

        issue = warm_network_path(
            {
                "AGENT_BUS_WARMUP_COMMAND": "tailscale",
                "AGENT_BUS_NETWORK_HOST": "mesh-host",
            }
        )

        self.assertIsNone(issue)
        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [
                ["tailscale", "status"],
                [
                    "tailscale",
                    "ping",
                    "--until-direct=false",
                    "--c=1",
                    "mesh-host",
                ],
            ],
        )


if __name__ == "__main__":
    unittest.main()
