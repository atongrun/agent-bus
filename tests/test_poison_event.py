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
    "payload": {"sim": "poison"},
}


def _run_listen(replays, max_attempts, handler_cmd):
    """Invoke the real `listen` command with a fake client that replays the
    poison event `replays` times. Returns the CliRunner result."""

    budget = [replays]  # shared across every reconnect's new client

    def client_factory(*args, **kwargs):
        return _FakeClient(POISON_EVENT, budget, *args, **kwargs)

    runner = CliRunner()
    with mock.patch("client.cli.httpx.Client", side_effect=client_factory), mock.patch(
        # poison events never ACK; stub the network ACK so nothing hits a server.
        "client.cli._post_ack",
        return_value=False,
    ), mock.patch(
        # Also stub _post_fail so poison-branch calls don't hit the network.
        "client.cli._post_fail",
        return_value=True,
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
    py = (
        "import sys;"
        f"open({marker_path!r}, 'a').write('run\\n');"
        "sys.exit(7)"
    )
    return f'{sys.executable} -c "{py}"'


class PoisonEventFailPersistenceTests(unittest.TestCase):
    """Tests for server-side fail persistence (ABUS-SERVER-FAIL-PERSIST-008)."""

    def test_post_fail_called_when_handler_exhausts_attempts(self):
        """_post_fail must be called when a handler exhausts max_event_attempts."""
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock

        with tempfile.TemporaryDirectory() as tmp:
            marker = str(Path(tmp) / "runs.txt")
            fail_mock = MagicMock(return_value=True)

            budget = [6]

            def client_factory(*args, **kwargs):
                return _FakeClient(POISON_EVENT, budget, *args, **kwargs)

            runner = CliRunner()
            with mock.patch("client.cli.httpx.Client", side_effect=client_factory), \
                 mock.patch("client.cli._post_ack", return_value=False), \
                 mock.patch("client.cli._post_fail", side_effect=fail_mock):
                result = runner.invoke(
                    cli,
                    [
                        "listen",
                        "--agent", "coder",
                        "--max-event-attempts", "3",
                        "--exit-after-idle", "1",
                        "--handler-timeout", "5",
                        "--on", "test:poison-sim",
                        _always_fail_handler(marker),
                    ],
                    obj={"url": "http://fake", "token": "x"},
                )

            self.assertEqual(result.exit_code, 0, msg=result.output)
            # _post_fail should have been called exactly once (after 3rd failure)
            self.assertEqual(fail_mock.call_count, 1,
                             msg=f"_post_fail called {fail_mock.call_count} times. Output:\n{result.output}")
            args, _ = fail_mock.call_args
            self.assertEqual(args[2], 42, msg=f"Wrong event_id. Output:\n{result.output}")
            self.assertIn("Handler failed after 3 consecutive attempts", args[3],
                          msg=f"Wrong error text. Output:\n{result.output}")

    def test_post_fail_not_called_on_success(self):
        """_post_fail must NOT be called when the handler succeeds."""
        from unittest.mock import MagicMock

        fail_mock = MagicMock(return_value=True)

        budget = [5]

        def client_factory(*args, **kwargs):
            return _FakeClient(POISON_EVENT, budget, *args, **kwargs)

        ok_handler = f'{sys.executable} -c "raise SystemExit(0)"'
        runner = CliRunner()
        with mock.patch("client.cli.httpx.Client", side_effect=client_factory), \
             mock.patch("client.cli._post_ack", return_value=False), \
             mock.patch("client.cli._post_fail", side_effect=fail_mock):
            result = runner.invoke(
                cli,
                [
                    "listen",
                    "--agent", "coder",
                    "--max-event-attempts", "3",
                    "--exit-after-idle", "1",
                    "--handler-timeout", "5",
                    "--on", "test:poison-sim",
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
            # Replay the poison event 6 times but cap attempts at 3: the handler
            # must run at most 3 times, then the event is skipped.
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
            self.assertIn("Skipping poison event 42", result.output)

    def test_skipped_event_not_rerun_on_later_replays(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            marker = str(Path(tmp) / "runs.txt")
            result = _run_listen(
                replays=8, max_attempts=2, handler_cmd=_always_fail_handler(marker)
            )

            self.assertEqual(result.exit_code, 0, msg=result.output)
            runs = Path(marker).read_text().count("run") if Path(marker).exists() else 0
            # Cap is 2: handler runs twice, then skipped for all remaining replays.
            self.assertEqual(runs, 2, msg=f"handler ran {runs} times, expected 2. Output:\n{result.output}")
            # The "previously skipped" line proves later replays short-circuit.
            self.assertIn("previously skipped", result.output)

    def test_succeeding_handler_is_not_skipped(self):
        # A handler that always succeeds should ACK and never trip poison logic.
        # With _post_ack stubbed to False the event won't be marked completed,
        # so it replays; but since the handler SUCCEEDS, should_ack is True and
        # failure_counts is never incremented -> no skip message ever appears.
        ok_handler = f'{sys.executable} -c "raise SystemExit(0)"'
        result = _run_listen(replays=5, max_attempts=3, handler_cmd=ok_handler)

        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertNotIn("Skipping poison event", result.output)


if __name__ == "__main__":
    unittest.main()
