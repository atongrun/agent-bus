"""Durable server-side failure lifecycle regression tests."""

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from server.main import app
from server.db import check_new_events, mark_delivered


class FailureLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_patch = patch(
            "server.db.DB_PATH", str(Path(self.tmp.name) / "events.db")
        )
        self.env_patch = patch.dict(
            "os.environ",
            {
                "AGENT_BUS_AGENT_TOKENS": (
                    "architect=architect-token,coder=coder-token,reviewer=reviewer-token"
                )
            },
            clear=True,
        )
        self.db_patch.start()
        self.env_patch.start()
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.env_patch.stop()
        self.db_patch.stop()
        self.tmp.cleanup()

    @staticmethod
    def headers(agent):
        return {"Authorization": f"Bearer {agent}-token"}

    def create_event(self):
        response = self.client.post(
            "/events",
            headers=self.headers("architect"),
            json={
                "from_agent": "architect",
                "to_agent": "coder",
                "type": "task:new",
                "payload": {"task_id": "durable-failure"},
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def record_failure(self, event_id, attempt):
        return self.client.post(
            f"/events/{event_id}/fail",
            headers=self.headers("coder"),
            json={
                "error": f"handler failure {attempt}",
                "max_attempts": 3,
                "expected_retry_count": attempt - 1,
            },
        )

    def test_three_separate_fail_calls_persist_attempts_and_terminal_state(self):
        event_id = self.create_event()

        first = self.record_failure(event_id, 1)
        second = self.record_failure(event_id, 2)
        third = self.record_failure(event_id, 3)

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(
            (first.json()["status"], first.json()["retry_count"]), ("pending", 1)
        )
        self.assertEqual(
            (second.json()["status"], second.json()["retry_count"]), ("pending", 2)
        )
        self.assertEqual(
            (third.json()["status"], third.json()["retry_count"]), ("failed", 3)
        )
        self.assertEqual(third.json()["last_error"], "handler failure 3")

        pending = self.client.get(
            "/events/pending", params={"agent": "coder"}, headers=self.headers("coder")
        )
        failed = self.client.get(
            "/events/failed", params={"agent": "coder"}, headers=self.headers("coder")
        )
        self.assertEqual(pending.json(), [])
        self.assertEqual([event["id"] for event in failed.json()], [event_id])
        self.assertEqual(check_new_events("coder", 0), [])

        # A repeated terminal report is idempotent and cannot inflate evidence.
        repeated = self.record_failure(event_id, 4)
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json()["retry_count"], 3)
        self.assertEqual(repeated.json()["last_error"], "handler failure 3")

    def test_failed_inspection_and_requeue_are_recipient_scoped(self):
        event_id = self.create_event()
        for attempt in range(1, 4):
            self.record_failure(event_id, attempt)

        for agent in ("architect", "reviewer"):
            inspect = self.client.get(
                "/events/failed", params={"agent": "coder"}, headers=self.headers(agent)
            )
            requeue = self.client.post(
                f"/events/{event_id}/requeue", headers=self.headers(agent)
            )
            fail = self.client.post(
                f"/events/{event_id}/fail",
                headers=self.headers(agent),
                json={
                    "error": "forbidden",
                    "max_attempts": 3,
                    "expected_retry_count": 3,
                },
            )
            self.assertEqual(inspect.status_code, 403, inspect.text)
            self.assertEqual(requeue.status_code, 403, requeue.text)
            self.assertEqual(fail.status_code, 403, fail.text)

        requeued = self.client.post(
            f"/events/{event_id}/requeue", headers=self.headers("coder")
        )
        self.assertEqual(requeued.status_code, 200, requeued.text)
        self.assertEqual(requeued.json()["status"], "pending")
        self.assertEqual(requeued.json()["retry_count"], 3)

        # Requeue is idempotent while the event remains pending.
        repeated = self.client.post(
            f"/events/{event_id}/requeue", headers=self.headers("coder")
        )
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json()["status"], "pending")

        acked = self.client.post(
            f"/events/{event_id}/ack", headers=self.headers("coder")
        )
        reacked = self.client.post(
            f"/events/{event_id}/ack", headers=self.headers("coder")
        )
        self.assertEqual(acked.status_code, 200, acked.text)
        self.assertEqual(reacked.status_code, 200, reacked.text)
        self.assertEqual(reacked.json()["status"], "acked")

        fail_after_ack = self.record_failure(event_id, 5)
        requeue_after_ack = self.client.post(
            f"/events/{event_id}/requeue", headers=self.headers("coder")
        )
        self.assertEqual(fail_after_ack.status_code, 409, fail_after_ack.text)
        self.assertEqual(requeue_after_ack.status_code, 409, requeue_after_ack.text)

    def test_stale_attempt_cannot_overwrite_failure_or_ack_it(self):
        event_id = self.create_event()
        first = self.record_failure(event_id, 1)
        self.assertTrue(first.json()["attempt_recorded"])

        duplicate = self.client.post(
            f"/events/{event_id}/fail",
            headers=self.headers("coder"),
            json={
                "error": "duplicate request",
                "max_attempts": 3,
                "expected_retry_count": 0,
            },
        )
        self.assertEqual(duplicate.status_code, 200, duplicate.text)
        self.assertFalse(duplicate.json()["attempt_recorded"])
        self.assertEqual(duplicate.json()["retry_count"], 1)
        self.assertEqual(duplicate.json()["last_error"], "handler failure 1")

        stale_ack = self.client.post(
            f"/events/{event_id}/ack",
            params={"expected_retry_count": 0},
            headers=self.headers("coder"),
        )
        self.assertEqual(stale_ack.status_code, 409, stale_ack.text)

    def test_delivered_event_cannot_be_requeued(self):
        event_id = self.create_event()
        delivered = mark_delivered(event_id)
        self.assertEqual(delivered["status"], "delivered")

        response = self.client.post(
            f"/events/{event_id}/requeue", headers=self.headers("coder")
        )
        self.assertEqual(response.status_code, 409, response.text)

    def test_legacy_fail_payload_preserves_terminal_transition(self):
        event_id = self.create_event()

        first = self.client.post(
            f"/events/{event_id}/fail",
            headers=self.headers("coder"),
            json={"error": "legacy listener exhausted local attempts"},
        )
        repeated = self.client.post(
            f"/events/{event_id}/fail",
            headers=self.headers("coder"),
            json={"error": "duplicate legacy report"},
        )

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["status"], "failed")
        self.assertEqual(first.json()["retry_count"], 1)
        self.assertEqual(
            first.json()["last_error"], "legacy listener exhausted local attempts"
        )
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertFalse(repeated.json()["attempt_recorded"])
        self.assertEqual(repeated.json()["retry_count"], 1)
        self.assertEqual(
            repeated.json()["last_error"],
            "legacy listener exhausted local attempts",
        )

    def test_duplicate_concurrent_failure_reports_increment_once(self):
        event_id = self.create_event()

        def report(attempt):
            with TestClient(app) as client:
                return client.post(
                    f"/events/{event_id}/fail",
                    headers=self.headers("coder"),
                    json={
                        "error": f"concurrent {attempt}",
                        "max_attempts": 3,
                        "expected_retry_count": 0,
                    },
                )

        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(report, range(8)))

        self.assertTrue(all(response.status_code == 200 for response in responses))
        failed = self.client.get(
            "/events/failed", params={"agent": "coder"}, headers=self.headers("coder")
        ).json()
        pending = self.client.get(
            "/events/pending", params={"agent": "coder"}, headers=self.headers("coder")
        ).json()
        self.assertEqual(failed, [])
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["retry_count"], 1)


if __name__ == "__main__":
    unittest.main()
