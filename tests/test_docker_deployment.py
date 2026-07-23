"""Static regression checks for the Docker server deployment contract."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"
COMPOSE = ROOT / "compose.yaml"
DOCKER_TEST = ROOT / "scripts/test-docker.sh"
ENV_EXAMPLE = ROOT / ".env.example"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class DockerDeploymentTests(unittest.TestCase):
    def test_dockerfile_uses_python_3_11_runtime_and_non_root_user(self):
        dockerfile = read(DOCKERFILE)

        self.assertIn("FROM python:3.11.15-slim-bookworm", dockerfile)
        self.assertIn("FROM ghcr.io/astral-sh/uv:0.11.30 AS uv", dockerfile)
        self.assertIn("COPY pyproject.toml uv.lock README.md ./", dockerfile)
        self.assertIn("uv sync --locked --no-dev --no-editable", dockerfile)
        self.assertNotIn("pip install", dockerfile)
        self.assertIn("USER agent-bus", dockerfile)
        self.assertRegex(dockerfile, r"useradd\b.*\bagent-bus")
        self.assertIn("--uid 10001", dockerfile)
        self.assertIn("EXPOSE 8800", dockerfile)
        self.assertIn('CMD ["sh", "-c"', dockerfile)
        self.assertIn("exec python -m server.main", dockerfile)

        self.assertNotIn("USER root", dockerfile)
        self.assertNotRegex(dockerfile, r"\b(sudo|supervisord|systemctl|tailscale)\b")

    def test_dockerfile_keeps_database_on_data_volume_and_healthchecks_core(self):
        dockerfile = read(DOCKERFILE)

        self.assertIn("AGENT_BUS_HOST=0.0.0.0", dockerfile)
        self.assertIn("AGENT_BUS_PORT=8800", dockerfile)
        self.assertIn("AGENT_BUS_DB_PATH=/data/agent-bus.db", dockerfile)
        self.assertIn('VOLUME ["/data"]', dockerfile)
        self.assertIn("HEALTHCHECK", dockerfile)
        self.assertIn("/health", dockerfile)
        self.assertIn("127.0.0.1", dockerfile)

    def test_dockerfile_does_not_bake_credentials_or_broad_context(self):
        dockerfile = read(DOCKERFILE)

        self.assertNotIn("dev-token", dockerfile)
        self.assertNotIn("change-me", dockerfile)
        self.assertNotRegex(dockerfile, r"(?m)^ARG\s+AGENT_BUS_.*TOKEN")
        self.assertNotRegex(dockerfile, r"(?m)^ENV\s+AGENT_BUS_AGENT_TOKENS")
        self.assertNotIn("COPY .", dockerfile)
        self.assertIn("AGENT_BUS_AGENT_TOKENS is required", dockerfile)

    def test_dockerignore_excludes_local_state_credentials_and_sqlite_files(self):
        ignored = {
            line.strip()
            for line in read(DOCKERIGNORE).splitlines()
            if line.strip() and not line.strip().startswith("#")
        }

        for pattern in {
            ".git",
            ".env",
            ".env.*",
            "*.docker.env",
            "data",
            "*.db",
            "*.db-wal",
            "*.db-shm",
            ".venv",
            ".omx",
        }:
            self.assertIn(pattern, ignored)

        gitignore = read(ROOT / ".gitignore")
        self.assertNotIn("!.env.example", ignored)
        self.assertIn(".env", gitignore)
        self.assertIn("*.docker.env", gitignore)

    def test_env_example_is_safe_to_copy_but_fails_closed_until_configured(self):
        example = read(ENV_EXAMPLE)

        self.assertIn("AGENT_BUS_AGENT_TOKENS=", example)
        self.assertNotIn("AGENT_BUS_AGENT_TOKENS=architect=", example)
        self.assertNotIn("change-me", example)
        self.assertNotIn("dev-token", example)
        self.assertNotRegex(example, r"(?m)^AGENT_BUS_AGENT_TOKENS=.+$")

    def test_compose_uses_single_agent_bus_service_with_persistent_named_volume(self):
        compose = read(COMPOSE)

        self.assertRegex(compose, r"(?m)^  agent-bus:$")
        self.assertIn("image: ${AGENT_BUS_IMAGE:-agent-bus:local}", compose)
        self.assertIn("AGENT_BUS_HOST: 0.0.0.0", compose)
        self.assertIn('AGENT_BUS_PORT: "8800"', compose)
        self.assertIn("AGENT_BUS_DB_PATH: /data/agent-bus.db", compose)
        self.assertIn("- agent-bus-data:/data", compose)
        self.assertRegex(
            compose,
            r"(?m)^  agent-bus-data:\n    name: \$\{AGENT_BUS_DATA_VOLUME:-agent-bus-data\}$",
        )
        self.assertIn("/health", compose)

        self.assertNotRegex(compose, r"\b(supervisord|systemd|tailscale|nginx|caddy|traefik)\b")

    def test_compose_hardens_runtime_without_extra_write_surfaces(self):
        compose = read(COMPOSE)

        self.assertIn("read_only: true", compose)
        self.assertRegex(compose, r"(?m)^    security_opt:\n      - no-new-privileges:true$")
        self.assertRegex(compose, r"(?m)^    cap_drop:\n      - ALL$")
        self.assertNotIn("tmpfs:", compose)
        self.assertNotIn("privileged: true", compose)

    def test_compose_requires_runtime_secret_injection_without_repo_secret_path(self):
        compose = read(COMPOSE)

        self.assertIn(
            "AGENT_BUS_AGENT_TOKENS: ${AGENT_BUS_AGENT_TOKENS:?",
            compose,
        )
        self.assertIn("AGENT_BUS_BOOTSTRAP_SECRET: ${AGENT_BUS_BOOTSTRAP_SECRET:-}", compose)
        self.assertNotIn("dev-token", compose)
        self.assertNotIn("change-me", compose)
        self.assertNotIn("env_file:", compose)
        self.assertNotIn("/etc/agent-bus/docker.env", compose)

    def test_compose_defaults_to_localhost_publish_for_private_network_safety(self):
        compose = read(COMPOSE)

        self.assertIn(
            '"${AGENT_BUS_BIND_ADDRESS:-127.0.0.1}:${AGENT_BUS_PUBLISHED_PORT:-8800}:8800"',
            compose,
        )
        self.assertNotIn("0.0.0.0:8800:8800", compose)

    def test_docker_acceptance_uses_isolated_validated_resource_names(self):
        script = read(DOCKER_TEST)

        self.assertIn('case "$TEST_ID" in', script)
        self.assertIn("AGENT_BUS_DOCKER_TEST_ID must contain only", script)
        self.assertIn('--project-name "agent-bus-test-${TEST_ID}"', script)
        self.assertIn('COMPOSE_ENV_FILES="$ENV_FILE"', script)
        self.assertIn('--project-directory "$ROOT_DIR"', script)
        self.assertIn('ENV_FILE="$TEST_TMP/.env"', script)
        self.assertNotIn('--env-file "$ENV_FILE"', script)
        self.assertIn('TEST_VOLUME="agent-bus-test-${TEST_ID}"', script)
        self.assertIn('TEST_IMAGE="agent-bus:test-${TEST_ID}"', script)


if __name__ == "__main__":
    unittest.main()
