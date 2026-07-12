"""CLI helper behavior tests."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

from click.testing import CliRunner

from client.cli import _load_payload, render_command, run_handler, send


class CliHelperTests(unittest.TestCase):
    def test_render_command_supports_event_and_payload_fields(self):
        event = {
            "id": 12,
            "type": "task:new",
            "from_agent": "architect",
            "to_agent": "coder",
            "payload": {"task_id": "task-12", "prompt": "do it"},
        }

        rendered = render_command("opencode run {id} {payload.task_id} {payload.prompt}", event)

        # render_command returns an argv LIST (no shell). A value with a space
        # ("do it") is a single argv element, not two.
        self.assertEqual(rendered, ["opencode", "run", "12", "task-12", "do it"])

    def test_render_command_value_with_metacharacters_is_one_argv_element(self):
        # With shell=False there is no shell to inject into: a value containing shell
        # metacharacters is passed verbatim as a single argv element, never re-parsed.
        event = {
            "payload": {
                "prompt": "hello; echo hacked",
            },
        }

        rendered = render_command("opencode run --prompt {payload.prompt}", event)

        self.assertEqual(rendered, ["opencode", "run", "--prompt", "hello; echo hacked"])

    def test_render_command_honours_quoted_path_with_spaces(self):
        # A double-quoted token (e.g. a git-bash path with spaces) stays one argv
        # element — this is how awf_listen wraps the python exe + script path.
        event = {"payload": {"branch": "awf/x"}}

        rendered = render_command(
            '"C:\\Program Files\\Git\\python.exe" role --branch {payload.branch}', event
        )

        self.assertEqual(
            rendered,
            ["C:\\Program Files\\Git\\python.exe", "role", "--branch", "awf/x"],
        )

    def test_render_command_fails_on_missing_field(self):
        with self.assertRaises(KeyError):
            render_command("run {payload.missing}", {"payload": {}})

    def test_load_payload_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload_path = Path(tmp) / "payload.json"
            payload_path.write_text(json.dumps({"task_id": "t1"}), encoding="utf-8")

            self.assertEqual(_load_payload("{}", str(payload_path)), {"task_id": "t1"})

    def test_send_rejects_non_object_payload(self):
        runner = CliRunner()

        result = runner.invoke(send, ["--from", "architect", "--to", "coder", "--type", "task:new", "--payload", "[]"], obj={"url": "http://localhost", "token": "x"})

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Payload must be a JSON object", result.output)

    def test_handler_success_and_failure_follow_exit_code(self):
        # run_handler now takes an argv list and runs it with shell=False.
        self.assertTrue(
            run_handler([sys.executable, "-c", "raise SystemExit(0)"], timeout=5, workdir=None)
        )
        self.assertFalse(
            run_handler([sys.executable, "-c", "raise SystemExit(3)"], timeout=5, workdir=None)
        )


if __name__ == "__main__":
    unittest.main()
