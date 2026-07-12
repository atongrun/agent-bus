"""Tests for repeatable workflow-listener initialization."""

import stat
import tempfile
import unittest
from pathlib import Path

from click.testing import CliRunner

from client.cli import cli
from client.listener_config import listener_environment_issues, render_listener_env


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


if __name__ == "__main__":
    unittest.main()
