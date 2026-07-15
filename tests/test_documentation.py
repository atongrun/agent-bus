"""Regression checks for security-critical client setup documentation."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BootstrapDocumentationTests(unittest.TestCase):
    def test_client_guides_cover_safe_bootstrap_patterns(self):
        documents = {}
        for relative in ("README.md", "docs/guide/installation.md"):
            with self.subTest(path=relative):
                content = (ROOT / relative).read_text(encoding="utf-8")
                documents[relative] = content
                self.assertIn("/bootstrap/token", content)
                self.assertIn("-K ", content)
                self.assertIn("high-sensitivity provisioning credential", content)
                self.assertNotRegex(
                    content,
                    r"(?:-H|--header)\s+['\"]?X-Bootstrap-Secret:",
                )
                self.assertIn("temporary_file", content)
                self.assertIn('> "$temporary_file"', content)
                self.assertIn('mv -f "$temporary_file" "$credential_file"', content)

        readme = documents["README.md"]
        guide = documents["docs/guide/installation.md"]
        self.assertIn("mkdir -p ~/.config/agent-bus", readme)
        self.assertIn("chmod 700 ~/.config/agent-bus", readme)
        self.assertIn("coder.credentials.env", readme)
        self.assertIn("icacls $root /inheritance:r", guide)
        self.assertIn('if ($LASTEXITCODE -ne 0) { throw "Failed to protect', guide)
        self.assertIn("Move-Item -Force $temporaryFile $credentialFile", guide)
        self.assertIn("-Encoding ascii", guide)
        self.assertNotIn("utf8NoBOM", guide)
        self.assertIn("sender.credentials.env", guide)
        self.assertIn("receiver.credentials.env", guide)


if __name__ == "__main__":
    unittest.main()
