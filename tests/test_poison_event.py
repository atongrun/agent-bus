"""Poison-event protection tests for `agent-bus listen`.

Reproduces the crash-loop deterministically without a real server: the server
replays an un-ACKed event on every SSE (re)connect (see server/events.py Phase 1),
so a handler that always fails would be re-run forever. These tests drive the real
`listen` command via CliRunner against a fake httpx stream that replays the SAME
poison event id across simulated reconnects, and assert that `--max-event-attempts`
stops the handler after N attempts instead of looping.
"""

import json
import sys
import unittest
from unittest import mock

import httpx
from click.testing import CliRunner

from client.cli import cli


def _sse_lines_for(event: dict):
    """The SSE line sequence the server emits for one event replay."""
    return [
        f"id: {event['id']}",
        "event: message",
        f"data: {json.dumps(event)}",
        "",  # blank line terminates the event -> triggers process_event
    ]


class _FakeStreamResponse:
    """Stands in for httpx's streaming response context manager."""

    def __init__(self, lines):
        self.status_code = 200
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_lines(self):
        yield from self._lines


class _FakeClient:
    """Fake httpx.Client whose .stream() replays one event per connect, then
    raises ReadTimeout to make `listen` exit via its idle path.

    IMPORTANT: `listen`'s reconnect loop builds a NEW httpx.Client on every
    iteration, so the remaining-replays budget must be SHARED across instances
    (a one-element mutable list), not per-instance — otherwise the counter
    resets each reconnect and the listener loops forever. This shared budget is
    exactly what models the server replaying the same un-ACKed event on every
    reconnect (server/events.py Phase 1).
    """

    def __init__(self, event, budget, *args, **kwargs):
        self._event = event
        self._budget = budget  # shared [remaining] across reconnects

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def stream(self, method, url, **kwargs):
        if self._budget[0] <= 0:
            # No more replays: emulate the idle read-timeout that ends listen().
            raise httpx.ReadTimeout("idle")
        self._budget[0] -= 1
        return _FakeStreamResponse(_sse_lines_for(self._event))


POISON_EVENT = {
    "id": 42,
    "type": "test:poison-sim",
    "from_agent": "architect",
    "to_agent": "coder",
    "status": "delivered",
    "retry_count": 0,
    "payload": {"sim": "poison"},
}


def _run_listen(replays, max_attempts, handler_cmd):
    """Invoke the real `listen` command with a fake client that replays the
    poison event `replays` times. Returns the CliRunner result."""

    budget = [replays]  # shared across every reconnect's new client

    def client_factory(*args, **kwargs):
        return _FakeClient(POISON_EVENT, budget, *args, **kwargs)

    attempts = [0]

    def record_failure(*args, **kwargs):
        attempts[0] += 1
        status = "failed" if attempts[0] >= max_attempts else "pending"
        return {"status": status, "retry_count": attempts[0]}

    runner = CliRunner()
    with (
        mock.patch("client.cli.httpx.Client", side_effect=client_factory),
        mock.patch(
            # poison events never ACK; stub the network ACK so nothing hits a server.
            "client.cli._post_ack",
            return_value=False,
        ),
        mock.patch(
            # Also stub _post_fail so poison-branch calls don't hit the network.
            "client.cli._post_fail",
            side_effect=record_failure,
        ),
    ):
        return runner.invoke(
            cli,
            [
                "listen",
                "--agent",
                "coder",
                "--max-event-attempts",
                str(max_attempts),
                "--exit-after-idle",
                "1",
                "--handler-timeout",
                "5",
                "--on",
                "test:poison-sim",
                handler_cmd,
            ],
            obj={"url": "http://fake", "token": "x"},
        )


# A handler that always fails, and records each invocation to a temp file so we
# can count how many times it actually ran.
def _always_fail_handler(marker_path):
    # Appends one line per run, then exits non-zero.
    py = f"import sys;open({marker_path!r}, 'a').write('run\\n');sys.exit(7)"
    return f'{sys.executable} -c "{py}"'


def _always_fail_handler_argv(marker_path):
    py = f"import sys;open({marker_path!r}, 'a').write('run\\n');sys.exit(7)"
    return json.dumps([sys.executable, "-c", py])


class PoisonEventFailPersistenceTests(unittest.TestCase):
    """Tests for server-side fail persistence (ABUS-SERVER-FAIL-PERSIST-008)."""

    def test_each_independent_once_listener_records_its_failure(self):
        """Every process reports one attempt; the server owns the shared count."""
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock

        with tempfile.TemporaryDirectory() as tmp:
            marker = str(Path(tmp) / "runs.txt")
            fail_mock = MagicMock()
            fail_mock.side_effect = [
                {"status": "pending", "retry_count": 1},
                {"status": "pending", "retry_count": 2},
                {"status": "failed", "retry_count": 3},
            ]

            for observed_retry_count in range(3):
                budget = [1]
                event = {**POISON_EVENT, "retry_count": observed_retry_count}

                def client_factory(*args, **kwargs):
                    return _FakeClient(event, budget, *args, **kwargs)

                runner = CliRunner()
                with (
                    mock.patch("client.cli.httpx.Client", side_effect=client_factory),
                    mock.patch("client.cli._post_ack", return_value=False),
                    mock.patch("client.cli._post_fail", side_effect=fail_mock),
                ):
                    result = runner.invoke(
                        cli,
                        [
                            "listen",
                            "--agent",
                            "coder",
                            "--once",
                            "--max-event-attempts",
                            "3",
                            "--handler-timeout",
                            "5",
                            "--on",
                            "test:poison-sim",
                            _always_fail_handler(marker),
                        ],
                        obj={"url": "http://fake", "token": "x"},
                    )
                self.assertEqual(result.exit_code, 0, msg=result.output)

            self.assertEqual(fail_mock.call_count, 3)
            self.assertEqual(Path(marker).read_text().count("run"), 3)
            self.assertEqual(
                [
                    call.kwargs["expected_retry_count"]
                    for call in fail_mock.call_args_list
                ],
                [0, 1, 2],
            )

    def test_post_fail_called_when_handler_exhausts_attempts(self):
        """_post_fail must be called when a handler exhausts max_event_attempts."""
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock

        with tempfile.TemporaryDirectory() as tmp:
            marker = str(Path(tmp) / "runs.txt")
            fail_mock = MagicMock(
                side_effect=[
                    {"status": "pending", "retry_count": 1},
                    {"status": "pending", "retry_count": 2},
                    {"status": "failed", "retry_count": 3},
                ]
            )

            budget = [6]

            def client_factory(*args, **kwargs):
                return _FakeClient(POISON_EVENT, budget, *args, **kwargs)

            runner = CliRunner()
            with (
                mock.patch("client.cli.httpx.Client", side_effect=client_factory),
                mock.patch("client.cli._post_ack", return_value=False),
                mock.patch("client.cli._post_fail", side_effect=fail_mock),
            ):
                result = runner.invoke(
                    cli,
                    [
                        "listen",
                        "--agent",
                        "coder",
                        "--max-event-attempts",
                        "3",
                        "--exit-after-idle",
                        "1",
                        "--handler-timeout",
                        "5",
                        "--on",
                        "test:poison-sim",
                        _always_fail_handler(marker),
                    ],
                    obj={"url": "http://fake", "token": "x"},
                )

            self.assertEqual(result.exit_code, 0, msg=result.output)
            # Every failed handling attempt is persisted by the server.
            self.assertEqual(
                fail_mock.call_count,
                3,
                msg=f"_post_fail called {fail_mock.call_count} times. Output:\n{result.output}",
            )
            args, kwargs = fail_mock.call_args
            self.assertEqual(
                args[2], 42, msg=f"Wrong event_id. Output:\n{result.output}"
            )
            self.assertIn(
                "Handler failed",
                args[3],
                msg=f"Wrong error text. Output:\n{result.output}",
            )
            self.assertEqual(kwargs["expected_retry_count"], 0)
            self.assertEqual(kwargs["max_attempts"], 3)

    def test_structured_argv_handler_failure_records_fail_without_ack(self):
        """A non-zero --on-argv handler remains unacked and records failure."""
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock

        with tempfile.TemporaryDirectory() as tmp:
            marker = str(Path(tmp) / "runs.txt")
            fail_mock = MagicMock(return_value={"status": "pending", "retry_count": 1})
            budget = [1]

            def client_factory(*args, **kwargs):
                return _FakeClient(POISON_EVENT, budget, *args, **kwargs)

            runner = CliRunner()
            with (
                mock.patch("client.cli.httpx.Client", side_effect=client_factory),
                mock.patch("client.cli._post_ack", return_value=True) as ack_mock,
                mock.patch("client.cli._post_fail", side_effect=fail_mock),
            ):
                result = runner.invoke(
                    cli,
                    [
                        "listen",
                        "--agent",
                        "coder",
                        "--once",
                        "--max-event-attempts",
                        "3",
                        "--handler-timeout",
                        "5",
                        "--on-argv",
                        "test:poison-sim",
                        _always_fail_handler_argv(marker),
                    ],
                    obj={"url": "http://fake", "token": "x"},
                )

            self.assertEqual(result.exit_code, 0, msg=result.output)
            self.assertEqual(Path(marker).read_text().count("run"), 1)
            fail_mock.assert_called_once()
            ack_mock.assert_not_called()

    def test_post_fail_not_called_on_success(self):
        """_post_fail must NOT be called when the handler succeeds."""
        from unittest.mock import MagicMock

        fail_mock = MagicMock(return_value=True)

        budget = [5]

        def client_factory(*args, **kwargs):
            return _FakeClient(POISON_EVENT, budget, *args, **kwargs)

        ok_handler = f'{sys.executable} -c "raise SystemExit(0)"'
        runner = CliRunner()
        with (
            mock.patch("client.cli.httpx.Client", side_effect=client_factory),
            mock.patch("client.cli._post_ack", return_value=False),
            mock.patch("client.cli._post_fail", side_effect=fail_mock),
        ):
            result = runner.invoke(
                cli,
                [
                    "listen",
                    "--agent",
                    "coder",
                    "--max-event-attempts",
                    "3",
                    "--exit-after-idle",
                    "1",
                    "--handler-timeout",
                    "5",
                    "--on",
                    "test:poison-sim",
                    ok_handler,
                ],
                obj={"url": "http://fake", "token": "x"},
            )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        fail_mock.assert_not_called()


class PoisonEventTests(unittest.TestCase):
    def test_handler_stops_after_max_attempts(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            marker = str(Path(tmp) / "runs.txt")
            # Replay the poison event 6 times but make the server return terminal
            # failed on attempt 3. Buffered duplicates must not rerun the handler.
            result = _run_listen(
                replays=6, max_attempts=3, handler_cmd=_always_fail_handler(marker)
            )

            self.assertEqual(result.exit_code, 0, msg=result.output)

            runs = Path(marker).read_text().count("run") if Path(marker).exists() else 0
            self.assertEqual(
                runs,
                3,
                msg=f"handler ran {runs} times, expected exactly 3 (capped). Output:\n{result.output}",
            )
            self.assertIn("Event 42 is terminal failed after 3 attempts", result.output)

    def test_terminal_event_not_rerun_on_later_buffered_replays(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            marker = str(Path(tmp) / "runs.txt")
            result = _run_listen(
                replays=8, max_attempts=2, handler_cmd=_always_fail_handler(marker)
            )

            self.assertEqual(result.exit_code, 0, msg=result.output)
            runs = Path(marker).read_text().count("run") if Path(marker).exists() else 0
            # Cap is 2: handler runs twice, then local buffered duplicates are ignored.
            self.assertEqual(
                runs,
                2,
                msg=f"handler ran {runs} times, expected 2. Output:\n{result.output}",
            )
            self.assertIn("Event 42 is terminal failed after 2 attempts", result.output)

    def test_succeeding_handler_is_not_skipped(self):
        # A handler that always succeeds should ACK and never trip poison logic.
        # With _post_ack stubbed to False the event won't be marked completed,
        # so it replays; but since the handler SUCCEEDS, should_ack is True and
        # no failed attempt is recorded and no terminal message appears.
        ok_handler = f'{sys.executable} -c "raise SystemExit(0)"'
        result = _run_listen(replays=5, max_attempts=3, handler_cmd=ok_handler)

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertNotIn("terminal failed", result.output)


class ListenIdleReconnectTests(unittest.TestCase):
    def test_default_daemon_reconnects_and_replays_unacked_event_once(self):
        """A same-stream high-water mark cannot see old delivered rows; reconnect can."""
        from unittest.mock import MagicMock

        task_event = {
            **POISON_EVENT,
            "id": 501,
            "type": "task:new",
            "status": "delivered",
            "payload": {"task_id": "replay-after-idle"},
        }
        shutdown_event = {
            **POISON_EVENT,
            "id": 502,
            "type": "control:shutdown",
            "status": "pending",
            "payload": {"target": "coder"},
        }

        class TimeoutThenReplayClient:
            connects = 0

            def __init__(self, *args, **kwargs):
                self.status_code = 200
                self.timeout = kwargs.get("timeout")

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def stream(self, method, url, **kwargs):
                TimeoutThenReplayClient.connects += 1
                if TimeoutThenReplayClient.connects == 1:
                    return self
                return _FakeStreamResponse(
                    _sse_lines_for(task_event) + _sse_lines_for(shutdown_event)
                )

            def iter_lines(self):
                raise httpx.ReadTimeout("stale same-stream idle")

        ack_mock = MagicMock(return_value=True)
        handler_mock = MagicMock(return_value=True)

        runner = CliRunner()
        with (
            mock.patch("client.cli.httpx.Client", TimeoutThenReplayClient),
            mock.patch("client.cli._post_ack", ack_mock),
            mock.patch("client.cli._post_fail") as fail_mock,
            mock.patch("client.cli.run_handler", handler_mock),
            mock.patch("client.cli.time.sleep", return_value=None) as sleep_mock,
        ):
            result = runner.invoke(
                cli,
                [
                    "--url",
                    "http://fake",
                    "--token",
                    "x",
                    "listen",
                    "--agent",
                    "coder",
                    "--handler-timeout",
                    "5",
                    "--on",
                    "task:new",
                    "echo {payload.task_id}",
                ],
            )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertEqual(TimeoutThenReplayClient.connects, 2)
        self.assertIn("Stream idle/read timeout after 60s", result.output)
        sleep_mock.assert_called_once_with(1)
        fail_mock.assert_not_called()
        handler_mock.assert_called_once()
        self.assertEqual(ack_mock.call_count, 2)

    def test_explicit_exit_after_idle_still_exits_on_read_timeout(self):
        class AlwaysTimeoutClient:
            connects = 0

            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def stream(self, method, url, **kwargs):
                AlwaysTimeoutClient.connects += 1
                raise httpx.ReadTimeout("idle")

        runner = CliRunner()
        with (
            mock.patch("client.cli.httpx.Client", AlwaysTimeoutClient),
            mock.patch("client.cli.time.sleep", return_value=None) as sleep_mock,
        ):
            result = runner.invoke(
                cli,
                [
                    "--url",
                    "http://fake",
                    "--token",
                    "x",
                    "listen",
                    "--agent",
                    "coder",
                    "--exit-after-idle",
                    "7",
                ],
            )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertEqual(AlwaysTimeoutClient.connects, 1)
        self.assertIn("No events received for 7s; exiting.", result.output)
        self.assertNotIn("Reconnecting", result.output)
        sleep_mock.assert_not_called()


class UnmatchedPayloadRedactionTests(unittest.TestCase):
    def invoke_listener(self, *, handlers=True, ack_on_receive=False):
        payload_reads = []

        class ObservedPayload(dict):
            def get(self, key, default=None):
                payload_reads.append(key)
                return super().get(key, default)

        event = {
            **POISON_EVENT,
            "id": 77001,
            "type": "task:legacy",
            "payload": ObservedPayload(
                {
                    "task_id": "private-legacy-task",
                    "secret_marker": "must-not-reach-output",
                }
            ),
        }
        budget = [1]

        def client_factory(*args, **kwargs):
            return _FakeClient(event, budget, *args, **kwargs)

        argv = [
            "--url",
            "http://fake",
            "--token",
            "x",
            "listen",
            "--agent",
            "coder",
            "--once",
        ]
        if handlers:
            argv.extend(
                [
                    "--on",
                    "task:current",
                    f'{sys.executable} -c "raise SystemExit(0)"',
                ]
            )
        if ack_on_receive:
            argv.append("--ack-on-receive")

        runner = CliRunner()
        with (
            mock.patch("client.cli.httpx.Client", side_effect=client_factory),
            mock.patch("client.cli.json.loads", return_value=event),
            mock.patch("client.cli.json.dumps", wraps=json.dumps) as dumps_mock,
            mock.patch("client.cli._post_ack", return_value=True) as ack_mock,
            mock.patch("client.cli._post_fail") as fail_mock,
        ):
            result = runner.invoke(
                cli,
                argv,
                obj={"url": "http://fake", "token": "x"},
            )
        payload_dump_count = sum(
            call.args and call.args[0] is event["payload"]
            for call in dumps_mock.call_args_list
        )
        return result, ack_mock, fail_mock, payload_dump_count, payload_reads

    def test_unmatched_handler_redacts_payload_without_mutating_event(self):
        result, ack_mock, fail_mock, payload_dump_count, payload_reads = (
            self.invoke_listener()
        )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("task:legacy id=77001 task_id=-", result.output)
        self.assertIn("Payload: [redacted: no matching handler]", result.output)
        self.assertNotIn("private-legacy-task", result.output)
        self.assertNotIn("must-not-reach-output", result.output)
        self.assertIn("No handler configured; leaving event unacked", result.output)
        self.assertEqual(payload_reads, [])
        self.assertEqual(payload_dump_count, 0)
        ack_mock.assert_not_called()
        fail_mock.assert_not_called()

    def test_manual_listener_without_handlers_keeps_payload_visible(self):
        result, ack_mock, fail_mock, payload_dump_count, payload_reads = (
            self.invoke_listener(handlers=False)
        )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("private-legacy-task", result.output)
        self.assertIn("must-not-reach-output", result.output)
        self.assertEqual(payload_reads, ["task_id"])
        self.assertEqual(payload_dump_count, 1)
        ack_mock.assert_not_called()
        fail_mock.assert_not_called()

    def test_ack_on_receive_keeps_payload_visible_and_acks(self):
        result, ack_mock, fail_mock, payload_dump_count, payload_reads = (
            self.invoke_listener(ack_on_receive=True)
        )

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("private-legacy-task", result.output)
        self.assertIn("must-not-reach-output", result.output)
        self.assertEqual(payload_reads, ["task_id"])
        self.assertEqual(payload_dump_count, 1)
        ack_mock.assert_called_once()
        fail_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
