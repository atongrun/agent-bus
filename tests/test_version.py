"""Release version consistency checks."""

import tomllib
import unittest
from pathlib import Path

from server.main import app


ROOT = Path(__file__).resolve().parents[1]


class VersionConsistencyTests(unittest.TestCase):
    def test_package_and_api_versions_match_v0_2_0(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(project["project"]["version"], "0.2.0")
        self.assertEqual(app.version, "0.2.0")

    def test_lockfile_carries_project_version(self):
        lockfile = (ROOT / "uv.lock").read_text(encoding="utf-8")

        self.assertIn('name = "agent-bus"\nversion = "0.2.0"', lockfile)


if __name__ == "__main__":
    unittest.main()
