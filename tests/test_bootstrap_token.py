"""Tests for the bootstrap token exchange endpoint."""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from server.main import app


class BootstrapTokenTests(unittest.TestCase):
    """POST /bootstrap/token behavior."""

    def setUp(self):
        self.client = TestClient(app)

    def test_successful_token_exchange(self):
        """Correct secret + valid agent → 200 + token."""
        with patch.dict(
            os.environ,
            {
                "AGENT_BUS_BOOTSTRAP_SECRET": "correct-secret",
                "AGENT_BUS_AGENT_TOKENS": "architect=arch-token,coder=coder-token",
            },
            clear=True,
        ):
            resp = self.client.post(
                "/bootstrap/token",
                json={"agent": "coder"},
                headers={"X-Bootstrap-Secret": "correct-secret"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"agent": "coder", "token": "coder-token"})

    def test_wrong_secret_returns_401(self):
        """Incorrect X-Bootstrap-Secret → 401."""
        with patch.dict(
            os.environ,
            {
                "AGENT_BUS_BOOTSTRAP_SECRET": "correct-secret",
                "AGENT_BUS_AGENT_TOKENS": "coder=coder-token",
            },
            clear=True,
        ):
            resp = self.client.post(
                "/bootstrap/token",
                json={"agent": "coder"},
                headers={"X-Bootstrap-Secret": "wrong-secret"},
            )
        self.assertEqual(resp.status_code, 401)

    def test_missing_header_returns_401(self):
        """No X-Bootstrap-Secret header → 401."""
        with patch.dict(
            os.environ,
            {
                "AGENT_BUS_BOOTSTRAP_SECRET": "correct-secret",
                "AGENT_BUS_AGENT_TOKENS": "coder=coder-token",
            },
            clear=True,
        ):
            resp = self.client.post(
                "/bootstrap/token",
                json={"agent": "coder"},
                # No X-Bootstrap-Secret header
            )
        self.assertEqual(resp.status_code, 401)

    def test_unknown_agent_returns_404(self):
        """Valid secret but unknown agent name → 404."""
        with patch.dict(
            os.environ,
            {
                "AGENT_BUS_BOOTSTRAP_SECRET": "correct-secret",
                "AGENT_BUS_AGENT_TOKENS": "coder=coder-token",
            },
            clear=True,
        ):
            resp = self.client.post(
                "/bootstrap/token",
                json={"agent": "nonexistent"},
                headers={"X-Bootstrap-Secret": "correct-secret"},
            )
        self.assertEqual(resp.status_code, 404)

    def test_no_secret_configured_returns_404(self):
        """AGENT_BUS_BOOTSTRAP_SECRET unset → 404 (feature disabled)."""
        with patch.dict(
            os.environ,
            {
                "AGENT_BUS_AGENT_TOKENS": "coder=coder-token",
            },
            clear=True,
        ):
            resp = self.client.post(
                "/bootstrap/token",
                json={"agent": "coder"},
                headers={"X-Bootstrap-Secret": "any-secret"},
            )
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
