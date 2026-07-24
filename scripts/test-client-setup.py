"""Cross-platform acceptance test for the installed client setup command."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PORT = 18902
TOKEN = "client-setup-acceptance-token"


def installed_agent_bus() -> Path:
    configured = os.environ.get("AGENT_BUS_TEST_COMMAND")
    if configured:
        return Path(configured)

    discovered = shutil.which("agent-bus")
    if discovered:
        return Path(discovered)

    bin_dir = subprocess.run(
        ["uv", "tool", "dir", "--bin"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    executable = "agent-bus.exe" if os.name == "nt" else "agent-bus"
    return Path(bin_dir) / executable


def wait_for_server(
    server_url: str,
    server: subprocess.Popen,
    server_log: Path,
) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(30):
        if server.poll() is not None:
            output = server_log.read_text(encoding="utf-8", errors="replace")
            raise RuntimeError(
                f"temporary Agent Bus server exited with {server.returncode}:\n{output}"
            )
        try:
            with opener.open(f"{server_url}/health", timeout=2) as response:
                if json.load(response).get("status") == "ok":
                    return
        except Exception:
            time.sleep(1)
    output = server_log.read_text(encoding="utf-8", errors="replace")
    raise RuntimeError(f"temporary Agent Bus server did not become healthy:\n{output}")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agent-bus-client-setup-") as tmp:
        temporary = Path(tmp)
        config_home = temporary / "config"
        server_url = f"http://127.0.0.1:{PORT}"
        environment = os.environ.copy()
        environment.update(
            {
                "AGENT_BUS_AGENT_TOKENS": f"coder={TOKEN}",
                "AGENT_BUS_DB_PATH": os.fspath(temporary / "agent-bus.db"),
                "AGENT_BUS_CLIENT_TOKEN": TOKEN,
                "XDG_CONFIG_HOME": os.fspath(config_home),
                "APPDATA": os.fspath(config_home),
                "NO_PROXY": "127.0.0.1,localhost",
                "no_proxy": "127.0.0.1,localhost",
            }
        )

        server_log = temporary / "server.log"
        with server_log.open("w", encoding="utf-8") as log:
            server = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "server.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(PORT),
                ],
                cwd=ROOT,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                wait_for_server(server_url, server, server_log)
                executable = installed_agent_bus()
                subprocess.run(
                    [
                        os.fspath(executable),
                        "setup",
                        "--server",
                        server_url,
                        "--agent",
                        "coder",
                        "--name",
                        "coder",
                    ],
                    check=True,
                    cwd=ROOT,
                    env=environment,
                )

                agent_bus_root = config_home / "agent-bus"
                credential = agent_bus_root / "coder.credentials.env"
                context = agent_bus_root / "contexts" / "coder.json"
                if TOKEN not in credential.read_text(encoding="utf-8"):
                    raise RuntimeError("setup did not write the expected credential")
                if TOKEN in context.read_text(encoding="utf-8"):
                    raise RuntimeError("context must not contain the token value")

                environment.pop("AGENT_BUS_CLIENT_TOKEN")
                subprocess.run(
                    [os.fspath(executable), "doctor"],
                    check=True,
                    cwd=ROOT,
                    env=environment,
                )
                print("Cross-platform client setup acceptance passed.")
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=10)


if __name__ == "__main__":
    main()
