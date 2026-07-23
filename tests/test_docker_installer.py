"""Behavior checks for the one-command Docker server installer."""

import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-docker.sh"


class DockerInstallerTests(unittest.TestCase):
    def test_installer_generates_protected_tokens_and_reuses_them(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            temporary = Path(temporary_dir)
            fake_bin = temporary / "bin"
            fake_bin.mkdir()
            fake_docker = fake_bin / "docker"
            fake_docker.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "inspect" ]; then
    echo healthy
    exit 0
fi
if [ "${1:-}" != "compose" ]; then
    exit 64
fi
case " $* " in
    *" version "*) exit 0 ;;
    *" ps -q agent-bus "*) echo fake-agent-bus-container; exit 0 ;;
    *) exit 0 ;;
esac
""",
                encoding="utf-8",
            )
            fake_docker.chmod(0o700)

            environment_file = temporary / "server.env"
            environment = os.environ.copy()
            environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
            environment["AGENT_BUS_DOCKER_ENV_FILE"] = str(environment_file)

            first = subprocess.run(
                ["bash", str(INSTALLER)],
                cwd=ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn("Architect token:", first.stdout)
            self.assertIn("Coder token:", first.stdout)
            self.assertEqual(stat.S_IMODE(environment_file.stat().st_mode), 0o600)

            contents = environment_file.read_text(encoding="utf-8")
            match = re.search(
                r"^AGENT_BUS_AGENT_TOKENS=architect=([0-9a-f]{64}),coder=([0-9a-f]{64})$",
                contents,
                re.MULTILINE,
            )
            self.assertIsNotNone(match)
            self.assertNotEqual(match.group(1), match.group(2))

            second = subprocess.run(
                ["bash", str(INSTALLER)],
                cwd=ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertNotIn("Architect token:", second.stdout)
            self.assertNotIn("Coder token:", second.stdout)
            self.assertEqual(
                environment_file.read_text(encoding="utf-8"),
                contents,
            )

    def test_installer_keeps_secrets_out_of_shell_execution(self):
        installer = INSTALLER.read_text(encoding="utf-8")

        self.assertIn("od -An -N32 -tx1 /dev/urandom", installer)
        self.assertIn('chmod 600 "$ENV_FILE"', installer)
        self.assertIn("compose config --quiet", installer)
        self.assertIn("compose up -d --build", installer)
        self.assertIn("wait_for_health", installer)
        self.assertNotIn('source "$ENV_FILE"', installer)
        self.assertNotRegex(installer, r"\beval\b")


if __name__ == "__main__":
    unittest.main()
