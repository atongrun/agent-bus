"""Read-only operator cockpit regression tests."""

import base64
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from server.db import ack_event, insert_event, mark_delivered, record_failure
from server.main import app


class OperatorCockpitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "events.db")
        self.db_patch = patch("server.db.DB_PATH", self.db_path)
        self.env_patch = patch.dict(
            "os.environ",
            {
                "AGENT_BUS_AGENT_TOKENS": (
                    "architect=architect-token,coder=coder-token"
                ),
                "AGENT_BUS_OPERATOR_TOKEN": "operator-token",
            },
            clear=True,
        )
        self.db_patch.start()
        self.env_patch.start()
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()

        self.pending_id = self.create_event(
            "architect", "coder", "task:new", '{"task_id":"pending-task"}'
        )
        self.delivered_id = self.create_event(
            "architect", "coder", "task:accepted", '{"task_id":"delivered-task"}'
        )
        mark_delivered(self.delivered_id)
        self.acked_id = self.create_event(
            "coder", "architect", "task:completed", '{"task_id":"acked-task"}'
        )
        ack_event(self.acked_id)
        self.failed_id = self.create_event(
            "architect",
            "coder",
            "task:failed",
            '{"task_id":"failed-task","raw":"<script>never execute</script>"}',
        )
        record_failure(
            self.failed_id,
            "handler failed",
            max_attempts=1,
            expected_retry_count=0,
        )

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.env_patch.stop()
        self.db_patch.stop()
        self.tmp.cleanup()

    @staticmethod
    def operator_headers(token="operator-token"):
        credentials = base64.b64encode(f"operator:{token}".encode("utf-8")).decode(
            "ascii"
        )
        return {"Authorization": f"Basic {credentials}"}

    @staticmethod
    def agent_headers(agent):
        return {"Authorization": f"Bearer {agent}-token"}

    @staticmethod
    def create_event(from_agent, to_agent, event_type, payload_json):
        return insert_event(from_agent, to_agent, event_type, payload_json)["id"]

    def snapshot(self):
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT * FROM events ORDER BY id").fetchall()

    def test_operator_api_returns_every_status_and_raw_payload(self):
        response = self.client.get(
            "/operator/api/events", headers=self.operator_headers()
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(
            [event["id"] for event in body["items"]],
            [self.failed_id, self.acked_id, self.delivered_id, self.pending_id],
        )
        self.assertEqual(
            [event["status"] for event in body["items"]],
            ["failed", "acked", "delivered", "pending"],
        )
        self.assertEqual(
            body["counts"],
            {"pending": 1, "delivered": 1, "acked": 1, "failed": 1},
        )
        self.assertEqual(
            body["items"][0]["payload"]["raw"],
            "<script>never execute</script>",
        )

    def test_operator_reads_do_not_change_event_state(self):
        before = self.snapshot()

        page = self.client.get("/operator", headers=self.operator_headers())
        events = self.client.get(
            "/operator/api/events", headers=self.operator_headers()
        )

        self.assertEqual(page.status_code, 200, page.text)
        self.assertEqual(events.status_code, 200, events.text)
        self.assertEqual(self.snapshot(), before)

    def test_cursor_pagination_and_filters_are_stable(self):
        first = self.client.get(
            "/operator/api/events",
            params={"limit": 2},
            headers=self.operator_headers(),
        ).json()
        second = self.client.get(
            "/operator/api/events",
            params={"limit": 2, "before_id": first["next_before_id"]},
            headers=self.operator_headers(),
        ).json()
        failed = self.client.get(
            "/operator/api/events",
            params={"status": "failed"},
            headers=self.operator_headers(),
        ).json()
        searched = self.client.get(
            "/operator/api/events",
            params={"q": "acked-task"},
            headers=self.operator_headers(),
        ).json()

        self.assertEqual(
            [event["id"] for event in first["items"]],
            [self.failed_id, self.acked_id],
        )
        self.assertTrue(first["has_more"])
        self.assertEqual(first["next_before_id"], self.acked_id)
        self.assertEqual(
            [event["id"] for event in second["items"]],
            [self.delivered_id, self.pending_id],
        )
        self.assertFalse(second["has_more"])
        self.assertEqual([event["id"] for event in failed["items"]], [self.failed_id])
        self.assertEqual([event["id"] for event in searched["items"]], [self.acked_id])

    def test_operator_auth_is_separate_and_disabled_when_unconfigured(self):
        missing = self.client.get("/operator/api/events")
        wrong = self.client.get(
            "/operator/api/events", headers=self.operator_headers("wrong")
        )
        agent = self.client.get(
            "/operator/api/events", headers=self.agent_headers("architect")
        )
        query_token = self.client.get(
            "/operator/api/events", params={"token": "operator-token"}
        )

        with patch.dict(
            "os.environ",
            {"AGENT_BUS_AGENT_TOKENS": "architect=architect-token"},
            clear=True,
        ):
            disabled = self.client.get(
                "/operator/api/events", headers=self.operator_headers()
            )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(agent.status_code, 401)
        self.assertEqual(query_token.status_code, 401)
        self.assertEqual(disabled.status_code, 404)

    def test_operator_token_cannot_call_event_write_api(self):
        response = self.client.post(
            "/events",
            headers={"Authorization": "Bearer operator-token"},
            json={
                "from_agent": "architect",
                "to_agent": "coder",
                "type": "task:new",
                "payload": {},
            },
        )

        self.assertEqual(response.status_code, 401, response.text)

    def test_operator_token_wins_fail_closed_if_misconfigured_as_agent_token(self):
        with patch.dict(
            "os.environ",
            {
                "AGENT_BUS_AGENT_TOKENS": "architect=operator-token",
                "AGENT_BUS_OPERATOR_TOKEN": "operator-token",
            },
            clear=True,
        ):
            response = self.client.post(
                "/events",
                headers={"Authorization": "Bearer operator-token"},
                json={
                    "from_agent": "architect",
                    "to_agent": "coder",
                    "type": "task:new",
                    "payload": {},
                },
            )

        self.assertEqual(response.status_code, 401, response.text)

    def test_page_is_one_secured_html_shell_without_write_controls(self):
        response = self.client.get("/operator", headers=self.operator_headers())

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("Agent Bus", response.text)
        self.assertIn('nonce="', response.text)
        self.assertNotIn("operator-token", response.text)
        self.assertNotIn("/ack", response.text)
        self.assertNotIn("/requeue", response.text)
        self.assertNotIn('method: "POST"', response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        self.assertIn("default-src 'none'", response.headers["content-security-policy"])
        self.assertNotIn("'unsafe-inline'", response.headers["content-security-policy"])

    def test_page_preserves_expanded_payloads_across_polling_renders(self):
        response = self.client.get("/operator", headers=self.operator_headers())

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("expandedPayloadIds: new Set()", response.text)
        self.assertIn("expandedPayloadIds.has(eventId)", response.text)
        self.assertIn("expandedPayloadIds.add(eventId)", response.text)
        self.assertIn("expandedPayloadIds.delete(eventId)", response.text)
        self.assertIn(
            'details("View raw", JSON.stringify(event.payload, null, 2), event.id)',
            response.text,
        )
        self.assertIn(
            "Auto-refresh paused while a payload is open",
            response.text,
        )
        self.assertIn("state.expandedPayloadIds.size === 0", response.text)
        self.assertIn('elements.refreshLabel.textContent = "Refreshing…"', response.text)


if __name__ == "__main__":
    unittest.main()
