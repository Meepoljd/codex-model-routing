#!/usr/bin/env python3
"""Discover available Codex models and refresh managed worker profiles safely."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from typing import Any, Iterator, Mapping, Sequence

try:  # pragma: no cover - exercised on Unix CI; fallback keeps the script portable.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None


STATE_VERSION = 1
DEFAULT_TTL = timedelta(hours=6)
ROLES: dict[str, dict[str, str]] = {
    "luna_worker": {"family": "luna", "effort": "medium"},
    "sol_worker": {"family": "sol", "effort": "high"},
    "astra_worker": {"family": "astra", "effort": "high"},
}
ROOT_ROLE = {"family": "luna", "effort": "low"}
MODEL_PATTERN = re.compile(r"^gpt-(?P<version>[0-9]+(?:\.[0-9]+)*)-(?P<family>luna|sol|astra)$")
MANAGED_ROOT_MARKER = "# codex-model-routing:managed-root"


class RoutingError(RuntimeError):
    pass


@dataclass(frozen=True)
class Candidate:
    model: str
    family: str
    version: tuple[int, ...]
    efforts: frozenset[str]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _capability_explicitly_false(item: Mapping[str, Any]) -> bool:
    for key in ("supportsTools", "supportsToolCalls", "toolCalls"):
        if item.get(key) is False:
            return True
    capabilities = item.get("capabilities")
    return isinstance(capabilities, Mapping) and any(
        capabilities.get(key) is False for key in ("tools", "toolCalls")
    )


def normalize_catalog(items: Sequence[object]) -> list[Candidate]:
    """Validate model/list records and retain conservative routing candidates."""
    candidates: list[Candidate] = []
    seen: set[str] = set()
    for index, raw in enumerate(items):
        if not isinstance(raw, Mapping):
            raise RoutingError(f"model/list item {index} is not an object")
        required = ("model", "hidden", "supportedReasoningEfforts")
        if any(key not in raw for key in required):
            raise RoutingError(f"model/list item {index} is missing required fields")
        model = raw["model"]
        if not isinstance(model, str) or not model:
            raise RoutingError(f"model/list item {index} has an invalid model token")
        if model in seen:
            raise RoutingError(f"model/list returned duplicate model token {model!r}")
        seen.add(model)
        if not isinstance(raw["hidden"], bool):
            raise RoutingError(f"model/list item {model!r} has a non-boolean hidden field")
        raw_efforts = raw["supportedReasoningEfforts"]
        if not isinstance(raw_efforts, list):
            raise RoutingError(f"model/list item {model!r} has invalid reasoning efforts")
        efforts: set[str] = set()
        for effort in raw_efforts:
            if not isinstance(effort, Mapping) or not isinstance(effort.get("reasoningEffort"), str):
                raise RoutingError(f"model/list item {model!r} has an invalid reasoning effort")
            efforts.add(effort["reasoningEffort"])

        match = MODEL_PATTERN.fullmatch(model)
        if (
            not match
            or raw["hidden"]
            or raw.get("modelSpecialty") is not None
            or _capability_explicitly_false(raw)
        ):
            continue
        candidates.append(
            Candidate(
                model=model,
                family=match.group("family"),
                version=tuple(int(part) for part in match.group("version").split(".")),
                efforts=frozenset(efforts),
            )
        )
    return candidates


def select_models(items: Sequence[object]) -> dict[str, dict[str, str]]:
    candidates = normalize_catalog(items)
    selected: dict[str, dict[str, str]] = {}
    for role, requirement in ROLES.items():
        eligible = [
            item
            for item in candidates
            if item.family == requirement["family"] and requirement["effort"] in item.efforts
        ]
        if not eligible:
            raise RoutingError(
                f"catalog has no visible {requirement['family']} model supporting "
                f"{requirement['effort']} reasoning"
            )
        choice = max(eligible, key=lambda item: item.version)
        selected[role] = {"model": choice.model, "effort": requirement["effort"]}
    root_eligible = [
        item
        for item in candidates
        if item.family == ROOT_ROLE["family"] and ROOT_ROLE["effort"] in item.efforts
    ]
    if not root_eligible:
        raise RoutingError("catalog has no visible luna model supporting low reasoning")
    root = max(root_eligible, key=lambda item: item.version)
    selected["root"] = {"model": root.model, "effort": ROOT_ROLE["effort"]}
    return selected


class JsonRpcClient:
    def __init__(
        self,
        command: Sequence[str],
        timeout: float = 15.0,
        env: Mapping[str, str] | None = None,
    ):
        self.command = list(command)
        self.timeout = timeout
        self.env = None if env is None else dict(env)
        self.process: subprocess.Popen[str] | None = None
        self.lines: queue.Queue[str | BaseException | None] = queue.Queue()
        self.next_id = 1

    def __enter__(self) -> "JsonRpcClient":
        try:
            self.process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
                env=self.env,
            )
        except OSError as exc:
            raise RoutingError(f"could not start Codex app-server: {exc}") from exc
        threading.Thread(target=self._reader, daemon=True).start()
        try:
            self.request(
                "initialize",
                {"clientInfo": {"name": "codex-model-routing", "version": "1.0"}},
            )
            self.notify("initialized", {})
        except BaseException:
            self._close()
            raise
        return self

    def __exit__(self, *_: object) -> None:
        self._close()

    def _close(self) -> None:
        if self.process is None:
            return
        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if self.process.stdout:
            self.process.stdout.close()
        self.process = None

    def _reader(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        try:
            for line in self.process.stdout:
                self.lines.put(line)
        except BaseException as exc:  # pragma: no cover - unusual pipe failure
            self.lines.put(exc)
        finally:
            self.lines.put(None)

    def _send(self, message: Mapping[str, Any]) -> None:
        assert self.process is not None and self.process.stdin is not None
        try:
            self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise RoutingError(f"Codex app-server pipe failed: {exc}") from exc

    def notify(self, method: str, params: Mapping[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: Mapping[str, Any]) -> Any:
        request_id = self.next_id
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RoutingError(f"Codex app-server timed out during {method}")
            try:
                line = self.lines.get(timeout=remaining)
            except queue.Empty as exc:
                raise RoutingError(f"Codex app-server timed out during {method}") from exc
            if line is None:
                code = None if self.process is None else self.process.poll()
                raise RoutingError(f"Codex app-server closed during {method} (exit {code})")
            if isinstance(line, BaseException):
                raise RoutingError(f"Codex app-server output failed: {line}") from line
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RoutingError("Codex app-server returned invalid JSON") from exc
            if not isinstance(message, Mapping):
                raise RoutingError("Codex app-server returned a non-object JSON-RPC message")
            if message.get("id") != request_id:
                continue  # notifications and unrelated server messages are harmless here
            if "error" in message:
                raise RoutingError(f"Codex app-server rejected {method}: {message['error']}")
            if "result" not in message:
                raise RoutingError(f"Codex app-server omitted the result for {method}")
            return message["result"]


def discover_catalog(
    command: Sequence[str] = ("codex", "app-server", "--stdio"),
    *,
    timeout: float = 15.0,
    page_limit: int = 100,
    max_pages: int = 20,
    env: Mapping[str, str] | None = None,
) -> list[object]:
    data: list[object] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    with JsonRpcClient(command, timeout=timeout, env=env) as client:
        for _ in range(max_pages):
            params: dict[str, Any] = {"includeHidden": True, "limit": page_limit}
            if cursor is not None:
                params["cursor"] = cursor
            result = client.request("model/list", params)
            if not isinstance(result, Mapping) or not isinstance(result.get("data"), list):
                raise RoutingError("model/list returned an invalid response shape")
            data.extend(result["data"])
            next_cursor = result.get("nextCursor")
            if next_cursor is None:
                break
            if not isinstance(next_cursor, str) or not next_cursor:
                raise RoutingError("model/list returned an invalid pagination cursor")
            if next_cursor in seen_cursors:
                raise RoutingError("model/list repeated a pagination cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        else:
            raise RoutingError(f"model/list exceeded {max_pages} pages")
    if not data:
        raise RoutingError("model/list returned an empty catalog")
    return data


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def ensure_real_directory(path: Path, label: str) -> None:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise RoutingError(f"{label} must be a real directory: {path}")


@contextmanager
def routing_lock(home: Path, timeout: float = 5.0) -> Iterator[None]:
    ensure_real_directory(home, "Codex home")
    lock_path = home / ".model-routing.lock"
    home.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+")
    try:
        if fcntl is None:  # Best-effort fallback for platforms without fcntl.
            yield
            return
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RoutingError("another model-routing update holds the lock")
                time.sleep(0.05)
        yield
    finally:
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


def read_state(home: Path) -> dict[str, Any] | None:
    path = home / "model-routing" / "state.json"
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RoutingError(f"routing state is invalid: {exc}") from exc
    if not isinstance(value, dict) or value.get("version") != STATE_VERSION:
        raise RoutingError("routing state has an unsupported format")
    return value


def render_profile(template: str, model: str, effort: str) -> str:
    parsed = tomllib.loads(template)
    if parsed.get("name") not in ROLES:
        raise RoutingError("worker template has an unknown role")
    rendered, model_count = re.subn(
        r'(?m)^model\s*=\s*"[^"]+"\s*$', f'model = "{model}"', template, count=1
    )
    rendered, effort_count = re.subn(
        r'(?m)^model_reasoning_effort\s*=\s*"[^"]+"\s*$',
        f'model_reasoning_effort = "{effort}"',
        rendered,
        count=1,
    )
    if model_count != 1 or effort_count != 1:
        raise RoutingError("worker template lacks a single model/effort assignment")
    tomllib.loads(rendered)
    return rendered


def profile_selection(path: Path) -> dict[str, Any]:
    """Return the effective model/effort of a profile for honest status output."""
    try:
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {"managed": False, "model": None, "effort": None}
    model = parsed.get("model")
    effort = parsed.get("model_reasoning_effort")
    return {
        "managed": False,
        "model": model if isinstance(model, str) else None,
        "effort": effort if isinstance(effort, str) else None,
    }


def _replace_managed_root(config: str, previous: Mapping[str, Any], selected: Mapping[str, str]) -> tuple[str, bool]:
    marker = MANAGED_ROOT_MARKER + "\n"
    if marker not in config:
        return config, False
    old_model = previous.get("model")
    old_effort = previous.get("effort")
    parsed = tomllib.loads(config)
    if parsed.get("model") != old_model or parsed.get("model_reasoning_effort") != old_effort:
        return config.replace(marker, "", 1), False
    first_table = config.find("\n[")
    boundary = len(config) if first_table < 0 else first_table + 1
    root, tail = config[:boundary], config[boundary:]
    root, count_model = re.subn(
        r'(?m)^model\s*=\s*"[^"]+"', f'model = "{selected["model"]}"', root, count=1
    )
    root, count_effort = re.subn(
        r'(?m)^model_reasoning_effort\s*=\s*"[^"]+"',
        f'model_reasoning_effort = "{selected["effort"]}"',
        root,
        count=1,
    )
    if count_model != 1 or count_effort != 1:
        return config.replace(marker, "", 1), False
    result = root + tail
    tomllib.loads(result)
    return result, True


def _backup_changes(home: Path, changes: Mapping[Path, str | None]) -> Path:
    stamp = utc_now().strftime("%Y%m%dT%H%M%S.%fZ")
    backup_root = home / "backups"
    ensure_real_directory(backup_root, "backup directory")
    backup = backup_root / f"model-routing-refresh-{stamp}"
    backup.mkdir(parents=True)
    manifest: dict[str, str | None] = {}
    for path in changes:
        relative = str(path.relative_to(home))
        if path.exists():
            destination = backup / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            manifest[relative] = relative
        else:
            manifest[relative] = None
    atomic_write(backup / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return backup


def transactional_write(home: Path, desired: Mapping[Path, str | None]) -> Path | None:
    changes = {
        path: content
        for path, content in desired.items()
        if (content is None and path.exists())
        or (content is not None and (not path.exists() or path.read_text(encoding="utf-8") != content))
    }
    if not changes:
        return None
    backup = _backup_changes(home, changes)
    original = {path: path.read_text(encoding="utf-8") if path.exists() else None for path in changes}
    written: list[Path] = []
    try:
        for path, content in changes.items():
            if content is None:
                path.unlink()
            else:
                atomic_write(path, content)
            written.append(path)
    except BaseException:
        for path in reversed(written):
            before = original[path]
            if before is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, before)
        raise
    return backup


def refresh(
    home: Path,
    templates: Path,
    *,
    catalog: Sequence[object] | None = None,
    timeout: float = 15.0,
    if_stale: bool = False,
    ttl: timedelta = DEFAULT_TTL,
) -> dict[str, Any]:
    home = home.expanduser().absolute()
    with routing_lock(home):
        state = read_state(home)
        if state is None:
            raise RoutingError("model routing is not installed")
        if if_stale and isinstance(state.get("lastSuccessAt"), str):
            try:
                last = datetime.fromisoformat(state["lastSuccessAt"])
            except ValueError:
                last = datetime.min.replace(tzinfo=timezone.utc)
            if utc_now() - last < ttl:
                return state

        if catalog is None:
            app_env = os.environ.copy()
            app_env["CODEX_HOME"] = str(home)
            catalog_items = discover_catalog(timeout=timeout, env=app_env)
        else:
            catalog_items = list(catalog)
        selected = select_models(catalog_items)
        managed = state.setdefault("managedProfiles", {})
        desired: dict[Path, str] = {}
        new_hashes: dict[str, str] = {}
        active_profiles: dict[str, dict[str, Any]] = {}
        for role in ROLES:
            template_path = templates / f"{role}.toml"
            if not template_path.is_file():
                raise RoutingError(f"missing worker template: {template_path}")
            target = home / "agents" / f"{role}.toml"
            record = managed.get(role)
            if isinstance(record, dict) and record.get("managed") is False:
                active_profiles[role] = profile_selection(target)
                continue
            previous_hash = record.get("sha256") if isinstance(record, dict) else None
            if target.exists() and previous_hash and sha256_text(target.read_text(encoding="utf-8")) != previous_hash:
                managed[role] = {"managed": False, "reason": "user-modified"}
                active_profiles[role] = profile_selection(target)
                continue
            content = render_profile(
                template_path.read_text(encoding="utf-8"),
                selected[role]["model"],
                selected[role]["effort"],
            )
            desired[target] = content
            new_hashes[role] = sha256_text(content)
            active_profiles[role] = {"managed": True, **selected[role]}

        root_state = state.get("managedRoot")
        if isinstance(root_state, dict) and root_state.get("managed") is True:
            config_path = home / "config.toml"
            if config_path.exists():
                updated, still_managed = _replace_managed_root(
                    config_path.read_text(encoding="utf-8"), root_state, selected["root"]
                )
                desired[config_path] = updated
                root_state = {
                    "managed": still_managed,
                    **(selected["root"] if still_managed else {}),
                }

        now = utc_now().isoformat()
        new_state = dict(state)
        new_state.update(
            {
                "version": STATE_VERSION,
                "lastSuccessAt": now,
                "catalogSelection": selected,
                "activeProfiles": active_profiles,
                "catalogSha256": sha256_text(json.dumps(catalog_items, sort_keys=True, separators=(",", ":"))),
                "managedRoot": root_state,
            }
        )
        new_managed = dict(managed)
        for role, digest in new_hashes.items():
            new_managed[role] = {"managed": True, "sha256": digest}
        new_state["managedProfiles"] = new_managed
        state_path = home / "model-routing" / "state.json"
        desired[state_path] = json.dumps(new_state, indent=2, sort_keys=True) + "\n"
        transactional_write(home, desired)
        return new_state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")))
    subparsers = parser.add_subparsers(dest="command", required=True)
    refresh_parser = subparsers.add_parser("refresh", help="Refresh managed profiles from model/list.")
    refresh_parser.add_argument("--if-stale", action="store_true")
    refresh_parser.add_argument("--timeout", type=float, default=15.0)
    subparsers.add_parser("status", help="Print the last-good routing state.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    home = args.codex_home.expanduser().absolute()
    try:
        if args.command == "status":
            state = read_state(home)
            if state is None:
                raise RoutingError("model routing is not installed")
            print(json.dumps(state, indent=2, sort_keys=True))
            return 0
        script_dir = Path(__file__).resolve().parent
        templates = script_dir / "templates" if (script_dir / "templates").is_dir() else script_dir / "agents"
        state = refresh(home, templates, timeout=args.timeout, if_stale=args.if_stale)
        print("Model routing is current: " + ", ".join(
            f"{role}={selection['model']}@{selection['effort']}"
            for role, selection in state.get("activeProfiles", {}).items()
            if selection.get("model") and selection.get("effort")
        ))
        return 0
    except (RoutingError, OSError, tomllib.TOMLDecodeError) as exc:
        print(f"error: {exc}; existing routing remains unchanged", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
