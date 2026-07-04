"""Authentication behavior tests."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.security import HTTPAuthorizationCredentials

from server.auth import AuthContext, get_agent_tokens, verify_token


class AuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_token_maps_to_agent(self):
        request = SimpleNamespace(query_params={})
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="coder-token")

        with patch.dict(os.environ, {"AGENT_BUS_AGENT_TOKENS": "architect=arch-token,coder=coder-token"}, clear=True):
            auth = await verify_token(request, credentials)

        self.assertEqual(auth, AuthContext(agent="coder", legacy=False))

    async def test_legacy_token_still_works_without_agent_tokens(self):
        request = SimpleNamespace(query_params={})
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="legacy-token")

        with patch.dict(os.environ, {"AGENT_BUS_TOKEN": "legacy-token"}, clear=True):
            auth = await verify_token(request, credentials)

        self.assertEqual(auth, AuthContext(agent=None, legacy=True))

    async def test_query_token_is_accepted_for_fallback_clients(self):
        request = SimpleNamespace(query_params={"token": "arch-token"})

        with patch.dict(os.environ, {"AGENT_BUS_AGENT_TOKENS": "architect=arch-token"}, clear=True):
            auth = await verify_token(request, None)

        self.assertEqual(auth, AuthContext(agent="architect", legacy=False))

    def test_agent_token_parser_rejects_malformed_entries(self):
        with patch.dict(os.environ, {"AGENT_BUS_AGENT_TOKENS": "architect"}, clear=True):
            with self.assertRaises(Exception):
                get_agent_tokens()


if __name__ == "__main__":
    unittest.main()
