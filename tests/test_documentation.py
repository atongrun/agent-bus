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


class DockerDocumentationTests(unittest.TestCase):
    def test_readme_links_to_the_short_docker_path(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("| Docker Compose |", readme)
        self.assertIn("| Native systemd |", readme)
        self.assertIn("bash scripts/install-docker.sh", readme)
        self.assertIn("bash scripts/install.sh", readme)
        self.assertNotIn("cp .env.example .env", readme)
        self.assertNotIn("docker compose --env-file", readme)
        self.assertIn("installation and security guide", readme)
        self.assertNotIn("AGENT_BUS_AGENT_TOKENS=architect=change-me", readme)

    def test_installation_guide_covers_docker_lifecycle_and_boundaries(self):
        guide = (ROOT / "docs/guide/installation.md").read_text(encoding="utf-8")

        for required in (
            "### Docker Compose Server",
            "agent-bus-data",
            "Do not use `docker compose down -v`",
            "#### Docker Data Backup And Restore",
            "#### Docker Upgrade And Rollback",
            "#### Docker Deployment Acceptance",
            "AGENT_BUS_BIND_ADDRESS=<vps-tailscale-ip>",
            "Send a unique event",
            "Query `pending` again and confirm it is empty",
        ):
            self.assertIn(required, guide)

        self.assertIn("bash scripts/install-docker.sh", guide)
        self.assertIn("prints the new tokens once", guide)
        self.assertIn("#### Manual Docker Configuration", guide)
        self.assertIn("cp .env.example .env", guide)
        self.assertIn("docker compose up -d --build", guide)
        self.assertIn("If local policy requires credentials outside the checkout", guide)
        self.assertIn("--env-file", guide)
        self.assertIn("pass secrets as Docker build arguments", guide)
        self.assertIn("listener supervision", guide)


if __name__ == "__main__":
    unittest.main()
