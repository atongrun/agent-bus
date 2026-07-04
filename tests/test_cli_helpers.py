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

        self.assertEqual(rendered, "opencode run 12 task-12 'do it'")

    def test_render_command_quotes_shell_metacharacters(self):
        event = {
            "payload": {
                "prompt": "hello; echo hacked",
            },
        }

        rendered = render_command("opencode run --prompt {payload.prompt}", event)

        self.assertEqual(rendered, "opencode run --prompt 'hello; echo hacked'")

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
        self.assertTrue(run_handler(f"{sys.executable} -c \"raise SystemExit(0)\"", timeout=5, workdir=None))
        self.assertFalse(run_handler(f"{sys.executable} -c \"raise SystemExit(3)\"", timeout=5, workdir=None))


if __name__ == "__main__":
    unittest.main()
