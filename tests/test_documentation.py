"""Regression checks for security-critical client setup documentation."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BootstrapDocumentationTests(unittest.TestCase):
    def test_readme_keeps_bootstrap_discoverable_without_the_full_recipe(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("bootstrap token endpoint", readme)
        self.assertIn("disabled by default", readme)
        self.assertRegex(readme, r"high-sensitivity\s+provisioning credential")
        self.assertIn("docs/guide/installation.md", readme)

        self.assertNotIn("-K ", readme)
        self.assertNotIn("temporary_file", readme)
        self.assertNotIn('mv -f "$temporary_file" "$credential_file"', readme)
        self.assertNotIn("icacls $root", readme)

    def test_installation_guide_covers_safe_bootstrap_patterns(self):
        guide = (ROOT / "docs/guide/installation.md").read_text(encoding="utf-8")

        self.assertIn("/bootstrap/token", guide)
        self.assertIn("Do not pass it with curl `-H` or `--header`", guide)
        self.assertIn("-K ", guide)
        self.assertRegex(guide, r"without writing either secret to the\s+terminal")
        self.assertRegex(guide, r"high-sensitivity\s+provisioning credential")
        self.assertNotRegex(
            guide,
            r"(?:-H|--header)\s+['\"]?X-Bootstrap-Secret:",
        )
        self.assertIn("mkdir -p ~/.config/agent-bus", guide)
        self.assertIn("chmod 700 ~/.config/agent-bus", guide)
        self.assertIn("temporary_file", guide)
        self.assertIn('> "$temporary_file"', guide)
        self.assertIn('mv -f "$temporary_file" "$credential_file"', guide)
        self.assertIn("icacls $root /inheritance:r", guide)
        self.assertIn('if ($LASTEXITCODE -ne 0) { throw "Failed to protect', guide)
        self.assertIn("Move-Item -Force $temporaryFile $credentialFile", guide)
        self.assertIn("-Encoding ascii", guide)
        self.assertNotIn("utf8NoBOM", guide)
        self.assertIn("sender.credentials.env", guide)
        self.assertIn("receiver.credentials.env", guide)


if __name__ == "__main__":
    unittest.main()
