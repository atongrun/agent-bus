"""Native, token-free client context storage and runtime resolution."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from dotenv import dotenv_values

from client.listener_config import _make_private


_CONTEXT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_AGENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_ENV_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_CONTEXT_FIELDS = {"version", "server", "agent", "credential"}


class ContextError(ValueError):
    """A safe, user-facing context configuration error."""


@dataclass(frozen=True)
class RuntimeConfig:
    """Resolved runtime configuration after applying all precedence layers."""

    url: str
    token: str
    agent: str
    context_name: str | None


def default_context_root(
    *,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
    home: Path | None = None,
) -> tuple[Path, str | None]:
    """Return the platform-native context root and an optional fallback notice."""
    current = os.environ if env is None else env
    platform = os.name if platform is None else platform
    home = Path.home() if home is None else home

    if platform == "nt":
        appdata = current.get("APPDATA")
        if appdata:
            return Path(appdata) / "agent-bus", None
        fallback = home / "AppData" / "Roaming" / "agent-bus"
        return (
            fallback,
            f"APPDATA is not set; using safe fallback config directory: {fallback}",
        )

    xdg = current.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else home / ".config"
    return base / "agent-bus", None


def validate_context_name(name: str) -> str:
    """Validate a context name before it is used as a file name."""
    if name in {".", ".."} or not _CONTEXT_NAME_RE.fullmatch(name):
        raise ContextError(
            "context name must start with a letter or digit and contain only "
            "letters, digits, '.', '_' or '-' (maximum 64 characters)"
        )
    return name


def _validate_agent(agent: str) -> str:
    if not isinstance(agent, str) or not _AGENT_RE.fullmatch(agent):
        raise ContextError(
            "agent must start with a letter and contain only letters, digits, _ or -"
        )
    return agent


def _validate_env_name(name: str) -> str:
    if not isinstance(name, str) or not _ENV_VAR_RE.fullmatch(name):
        raise ContextError("credential environment variable name is invalid")
    return name


def _reject_control_characters(value: str, label: str) -> str:
    if _CONTROL_CHAR_RE.search(value):
        raise ContextError(f"{label} must not contain control characters")
    return value


def _validate_server(server: str) -> str:
    if not isinstance(server, str):
        raise ContextError("context server must be a string")
    value = _reject_control_characters(server, "server URL").rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ContextError("server must be an http(s) URL with a hostname")
    if parsed.username or parsed.password:
        raise ContextError("server URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ContextError("server URL must not contain a query or fragment")
    return value


def _credential_reference(token_env: str, env_file: str | None) -> dict[str, str]:
    key = _validate_env_name(token_env)
    if env_file is None:
        return {"type": "env", "name": key}
    if not isinstance(env_file, str) or not env_file.strip():
        raise ContextError("credential env-file path must not be empty")
    path = _reject_control_characters(env_file, "credential env-file path")
    if not Path(path).expanduser().is_absolute():
        raise ContextError(
            "credential env-file path must be absolute or start with '~'"
        )
    return {"type": "env-file", "path": path, "key": key}


def _validate_context(data: object) -> dict:
    if not isinstance(data, dict):
        raise ContextError("context JSON must contain an object")
    extra = set(data) - _CONTEXT_FIELDS
    missing = _CONTEXT_FIELDS - set(data)
    if extra:
        raise ContextError(
            f"context contains unsupported fields: {', '.join(sorted(extra))}"
        )
    if missing:
        raise ContextError(
            f"context is missing required fields: {', '.join(sorted(missing))}"
        )
    if type(data["version"]) is not int or data["version"] != 1:
        raise ContextError("unsupported context version")

    credential = data["credential"]
    if not isinstance(credential, dict):
        raise ContextError("context credential must be an object")
    credential_type = credential.get("type")
    if credential_type == "env":
        if set(credential) != {"type", "name"}:
            raise ContextError("env credential must contain only type and name")
        validated_credential = {
            "type": "env",
            "name": _validate_env_name(credential.get("name", "")),
        }
    elif credential_type == "env-file":
        if set(credential) != {"type", "path", "key"}:
            raise ContextError(
                "env-file credential must contain only type, path and key"
            )
        path = credential.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ContextError("credential env-file path must not be empty")
        path = _reject_control_characters(path, "credential env-file path")
        if not Path(path).expanduser().is_absolute():
            raise ContextError(
                "credential env-file path must be absolute or start with '~'"
            )
        validated_credential = {
            "type": "env-file",
            "path": path,
            "key": _validate_env_name(credential.get("key", "")),
        }
    else:
        raise ContextError("credential type must be 'env' or 'env-file'")

    server = data["server"]
    agent = data["agent"]
    return {
        "version": 1,
        "server": _validate_server(server),
        "agent": _validate_agent(agent),
        "credential": validated_credential,
    }


def _atomic_write_private(path: Path, content: str) -> None:
    """Atomically replace a private context file without a predictable temp name."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.parent.chmod(0o700)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        _make_private(temporary_path)
        temporary_path.replace(path)
        _make_private(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def write_credential_file(path: Path, token: str) -> None:
    """Write one client token to a private dotenv file.

    JSON string quoting is compatible with python-dotenv and preserves values
    containing spaces, ``#``, quotes, or backslashes without shell evaluation.
    """
    if not isinstance(token, str) or not token:
        raise ContextError("token must not be empty")
    if "\x00" in token or "\r" in token or "\n" in token:
        raise ContextError("token must not contain NUL or line breaks")

    path = path.expanduser()
    if path.is_symlink():
        raise ContextError(f"refusing to replace symlinked credential file: {path}")
    _atomic_write_private(
        path,
        f"AGENT_BUS_CLIENT_TOKEN={json.dumps(token, ensure_ascii=True)}\n",
    )


def protect_credential_file(path: Path) -> None:
    """Fail closed on unsafe credential targets and restore private permissions."""
    path = path.expanduser()
    if path.is_symlink():
        raise ContextError(f"refusing to use symlinked credential file: {path}")
    if not path.is_file():
        raise ContextError(f"credential path is not a regular file: {path}")
    _make_private(path)


def validate_context_configuration(
    name: str,
    *,
    server: str,
    agent: str,
    token_env: str,
    env_file: str | None = None,
) -> dict:
    """Validate a context and its filename before any filesystem writes."""
    validate_context_name(name)
    return _validate_context(
        {
            "version": 1,
            "server": server,
            "agent": agent,
            "credential": _credential_reference(token_env, env_file),
        }
    )


class ContextStore:
    """Read and write named contexts beneath one platform config root."""

    def __init__(self, root: Path):
        self.root = root.expanduser()
        self.contexts_dir = self.root / "contexts"
        self.current_path = self.root / "current-context"

    def _path(self, name: str) -> Path:
        return self.contexts_dir / f"{validate_context_name(name)}.json"

    def add(
        self,
        name: str,
        *,
        server: str,
        agent: str,
        token_env: str,
        env_file: str | None = None,
        force: bool = False,
    ) -> dict:
        path = self._path(name)
        if path.exists() and not force:
            raise ContextError(
                f"context '{name}' already exists; use --force to replace it"
            )
        context = validate_context_configuration(
            name,
            server=server,
            agent=agent,
            token_env=token_env,
            env_file=env_file,
        )
        _atomic_write_private(path, json.dumps(context, indent=2) + "\n")
        return context

    def list_names(self) -> list[str]:
        if not self.contexts_dir.is_dir():
            return []
        names = []
        for path in self.contexts_dir.glob("*.json"):
            try:
                names.append(validate_context_name(path.stem))
            except ContextError:
                continue
        return sorted(names)

    def current_name(self) -> str | None:
        if not self.current_path.exists():
            return None
        try:
            name = self.current_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ContextError(f"could not read current context: {exc}") from exc
        if not name:
            raise ContextError("current-context is empty")
        return validate_context_name(name)

    def get(self, name: str | None = None) -> dict:
        selected = self.current_name() if name is None else validate_context_name(name)
        if selected is None:
            raise ContextError("no context is selected")
        path = self._path(selected)
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ContextError(f"context '{selected}' does not exist") from exc
        except OSError as exc:
            raise ContextError(f"could not read context '{selected}': {exc}") from exc
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ContextError(f"context '{selected}' is not valid JSON") from exc
        return _validate_context(loaded)

    def use(self, name: str) -> None:
        selected = validate_context_name(name)
        self.get(selected)
        _atomic_write_private(self.current_path, f"{selected}\n")

    def delete(self, name: str, *, force: bool = False) -> None:
        selected = validate_context_name(name)
        path = self._path(selected)
        if not path.exists():
            raise ContextError(f"context '{selected}' does not exist")
        current = self.current_name()
        if current == selected and not force:
            raise ContextError(
                f"context '{selected}' is currently selected; use --force to delete it"
            )
        if current == selected:
            self.current_path.unlink(missing_ok=True)
        path.unlink()


def _resolve_context_token(context: dict, env: Mapping[str, str]) -> str:
    credential = context["credential"]
    if credential["type"] == "env":
        name = credential["name"]
        token = env.get(name, "")
        if not token:
            raise ContextError(f"credential environment variable {name} is not set")
        return token

    path = Path(credential["path"]).expanduser()
    key = credential["key"]
    try:
        values = dotenv_values(path)
    except OSError as exc:
        raise ContextError(f"could not read credential env-file: {path}") from exc
    token = values.get(key)
    if not token:
        raise ContextError(f"credential key {key} is not set in env-file: {path}")
    return token


def resolve_runtime_config(
    *,
    cli_url: str | None = None,
    cli_token: str | None = None,
    cli_agent: str | None = None,
    context_name: str | None = None,
    env: Mapping[str, str] | None = None,
    root: Path | None = None,
    resolve_credential: bool = True,
    resolve_agent: bool = True,
) -> RuntimeConfig:
    """Resolve flags > environment > selected context > defaults."""
    current = os.environ if env is None else env
    if root is None:
        root, _ = default_context_root(env=current)
    store = ContextStore(root)
    env_url = current.get("AGENT_BUS_URL") or None
    env_token = current.get("AGENT_BUS_TOKEN") or None
    env_agent = current.get("AGENT_BUS_AGENT") or None
    url = cli_url if cli_url is not None else env_url
    token = cli_token if cli_token is not None else env_token
    agent = cli_agent if cli_agent is not None else env_agent

    selected = None
    context = None
    needs_context = (
        url is None
        or (agent is None and resolve_agent)
        or (token is None and resolve_credential)
        or context_name is not None
    )
    if needs_context:
        selected = (
            validate_context_name(context_name)
            if context_name is not None
            else store.current_name()
        )
        context = store.get(selected) if selected else None

    if url is None:
        url = context["server"] if context else "http://localhost:8800"
    if token is None:
        token = (
            _resolve_context_token(context, current)
            if context and resolve_credential
            else ""
        )
    if agent is None and resolve_agent:
        agent = context["agent"] if context else ""
    return RuntimeConfig(
        url=url.rstrip("/"),
        token=token,
        agent=agent or "",
        context_name=selected,
    )
