#!/usr/bin/env python3
"""Install, refresh, or uninstall adaptive Codex model routing."""

from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - systemd user services are Linux-only.
    fcntl = None

from model_router import (
    MANAGED_ROOT_MARKER,
    ROLES,
    RoutingError,
    STATE_VERSION,
    read_state,
    refresh,
    routing_lock,
    profile_selection,
    sha256_text,
    transactional_write,
    utc_now,
)


ROOT = Path(__file__).resolve().parent
POLICY_FILE = ROOT / "policy" / "model-routing-policy.md"
ENGINE_FILE = ROOT / "model_router.py"
RADAR_SOURCE_FILE = ROOT / "radar_source.py"
WORKERS = tuple(f"{role}.toml" for role in ROLES)
START = "<!-- codex-model-routing:begin -->"
END = "<!-- codex-model-routing:end -->"
DEFAULT_SELECTIONS = {
    "routine_worker": {"model": "gpt-6-luna", "effort": "medium"},
    "complex_worker": {"model": "gpt-6.1-sol", "effort": "high"},
    "frontier_worker": {"model": "gpt-6-astra", "effort": "high"},
    "root": {"model": "gpt-6-luna", "effort": "low"},
}
DEFAULT_CONFIG = (
    f"{MANAGED_ROOT_MARKER}\n"
    'model = "gpt-6-luna"\n'
    'model_reasoning_effort = "low"\n\n'
    "[agents]\n"
    "enabled = true\n"
)

# Exact repository-managed files from pre-adaptive releases. Same-named custom
# profiles are never migrated or overwritten unless their bytes match a hash.
KNOWN_MANAGED_PROFILE_HASHES = {
    "luna_worker": {"d4f1f3422aa2d93356bf66e24b67a151c2ae04d9815ee37ff04f114e909897c7"},
    "sol_worker": {
        "d2e8281f573a9694588723cd0acccdd4e85fb772cb17d1ef84e5c991e5a11ca7",
        "43074c9c89489874b451e1908a8036ab89db6d41d85502dbe3e822395e81d0f3",
    },
    "astra_worker": {
        "0f8675ce1bb54cdab6bf5221fef25b4e40ad7e220483f782f8e02d9832cc74fe",
        "8f07469e812fb5953d1cca1eee655f1a65f8ab0400b6f703e7356eaf7bbad0c7",
    },
}
LEGACY_REMOVALS = {
    "luna_worker.toml": None,
    "sol_worker.toml": None,
    "astra_worker.toml": None,
    "spark_worker.toml": "7df5f18540776579ec50e5e251ed1d7883c7ab7f22b95416d27c3e2628446e8d",
    "terra_worker.toml": "cdf695ff6dd349ebe198e036678115562c42224e15720eb2b6b4ed9ed011ce11",
}


class InstallError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--no-refresh",
        action="store_true",
        help="Install packaged last-good defaults without querying model/list.",
    )
    parser.add_argument("--schedule", choices=("auto", "enable", "disable"), default="auto")
    parser.add_argument("--uninstall", action="store_true")
    return parser.parse_args()


def validate_package() -> None:
    for path in (POLICY_FILE, ENGINE_FILE, RADAR_SOURCE_FILE):
        if not path.is_file():
            raise InstallError(f"Missing packaged file: {path}")
    for worker in WORKERS:
        source = ROOT / "agents" / worker
        if not source.is_file():
            raise InstallError(f"Missing packaged worker: {source}")
        data = tomllib.loads(source.read_text(encoding="utf-8"))
        if data.get("name") != worker.removesuffix(".toml"):
            raise InstallError(f"Worker name does not match file: {source}")


def table_spans(text: str) -> list[tuple[int, str, bool]]:
    spans: list[tuple[int, str, bool]] = []
    delimiter: str | None = None
    offset = 0
    for line in text.splitlines(keepends=True):
        index = 0
        quote = delimiter
        while index < len(line):
            if quote:
                if line.startswith(quote, index):
                    quote = None
                    index += 3
                else:
                    index += 1
                continue
            if line.startswith('"""', index) or line.startswith("'''", index):
                quote = line[index : index + 3]
                index += 3
                continue
            if line[index] == "#":
                break
            index += 1
        if delimiter is None and quote is None:
            stripped = line.lstrip()
            if stripped.startswith("["):
                array = stripped.startswith("[[")
                close_token = "]]" if array else "]"
                close = stripped.find(close_token, 2 if array else 1)
                if close > 1:
                    name = stripped[2:close].strip() if array else stripped[1:close].strip()
                    trailer = stripped[close + len(close_token) :].strip()
                    if not trailer or trailer.startswith("#"):
                        spans.append((offset, name, array))
        delimiter = quote
        offset += len(line)
    return spans


def replace_key_in_region(region: str, key: str, value: str) -> tuple[str, bool]:
    lines = region.splitlines(keepends=True)
    delimiter: str | None = None
    for index, line in enumerate(lines):
        if delimiter is not None:
            if delimiter in line:
                delimiter = None
            continue
        stripped = line.lstrip()
        if stripped.startswith("#") or not stripped.startswith(key):
            if '"""' in line:
                delimiter = '"""'
            elif "'''" in line:
                delimiter = "'''"
            continue
        rest = stripped[len(key) :]
        if not rest.lstrip().startswith("="):
            continue
        prefix = line[: len(line) - len(stripped)]
        comment_at = rest.find("#")
        comment = "" if comment_at < 0 else " " + rest[comment_at:].rstrip("\r\n")
        newline = "\n" if line.endswith("\n") else ""
        lines[index] = f"{prefix}{key} = {value}{comment}{newline}"
        return "".join(lines), True
    return region, False


def merge_config(existing: str | None) -> tuple[str, dict[str, Any]]:
    if existing is None:
        return DEFAULT_CONFIG, {"managed": True, **DEFAULT_SELECTIONS["root"]}
    try:
        original = tomllib.loads(existing)
    except tomllib.TOMLDecodeError as exc:
        raise InstallError(f"Existing config.toml is invalid; no files changed: {exc}") from exc
    spans = table_spans(existing)
    first_table = spans[0][0] if spans else len(existing)
    root, tail = existing[:first_table], existing[first_table:]
    agents = next(
        ((position, name) for position, name, array in spans if name == "agents" and not array),
        None,
    )
    if agents is None:
        if tail and not tail.endswith("\n"):
            tail += "\n"
        tail += "\n[agents]\nenabled = true\n"
    else:
        start = agents[0] - first_table
        following = [position - first_table for position, _, _ in spans if position > agents[0]]
        end = following[0] if following else len(tail)
        region, found = replace_key_in_region(tail[start:end], "enabled", "true")
        if not found:
            if region and not region.endswith("\n"):
                region += "\n"
            region += "enabled = true\n"
        tail = tail[:start] + region + tail[end:]
    result = root + tail
    rendered = tomllib.loads(result)
    expected = copy.deepcopy(original)
    agents_data = expected.get("agents")
    if agents_data is None:
        expected["agents"] = {"enabled": True}
    elif not isinstance(agents_data, dict):
        raise InstallError("Existing agents value is not a TOML table; no files changed.")
    else:
        agents_data["enabled"] = True
    if rendered != expected:
        raise InstallError("Unsupported TOML layout would change unrelated semantics; no files changed.")
    return result, {"managed": False, "reason": "pre-existing-config"}


def merge_agents(existing: str | None) -> str:
    policy = POLICY_FILE.read_text(encoding="utf-8").strip()
    managed = f"{START}\n{policy}\n{END}\n"
    if existing is None or not existing.strip():
        return managed
    if START in existing or END in existing:
        if existing.count(START) != 1 or existing.count(END) != 1:
            raise InstallError("AGENTS.md has ambiguous routing markers; no files changed.")
        start = existing.index(START)
        end = existing.index(END, start) + len(END)
        return existing[:start] + managed.rstrip("\n") + existing[end:]
    lines = existing.splitlines(keepends=True)
    heading = next(
        (index for index, line in enumerate(lines) if line.rstrip("\r\n") == "## Model Routing Policy"),
        None,
    )
    if heading is not None:
        end = next(
            (
                index
                for index in range(heading + 1, len(lines))
                if lines[index].startswith("# ") or lines[index].startswith("## ")
            ),
            len(lines),
        )
        return "".join(lines[:heading]) + managed + "".join(lines[end:])
    suffix = "" if existing.endswith("\n") else "\n"
    return existing + suffix + "\n" + managed


def checked_file(path: Path) -> None:
    if path.is_symlink():
        raise InstallError(f"Refusing symbolic-link target: {path}")
    if path.exists() and not path.is_file():
        raise InstallError(f"Expected a file but found another path type: {path}")


def _initial_state(
    home: Path,
    root_state: dict[str, Any],
    *,
    config_created: bool,
    agents_created: bool,
) -> dict[str, Any]:
    existing = read_state(home)
    if existing is not None:
        # State v1 named fixed model families.  Preserve its last-good choices
        # while translating them to the generic role contract used by v2.
        selection = existing.get("catalogSelection")
        if isinstance(selection, dict):
            aliases = {
                "luna_worker": "routine_worker",
                "sol_worker": "complex_worker",
                "astra_worker": "frontier_worker",
            }
            migrated = {
                aliases.get(role, role): value for role, value in selection.items()
            }
            for role, default in DEFAULT_SELECTIONS.items():
                migrated.setdefault(role, default)
            existing["catalogSelection"] = migrated
        existing["version"] = STATE_VERSION
        return existing
    return {
        "version": STATE_VERSION,
        "installedAt": utc_now().isoformat(),
        "lastSuccessAt": None,
        "catalogSelection": DEFAULT_SELECTIONS,
        "activeProfiles": {
            role: {"managed": True, **selection}
            for role, selection in DEFAULT_SELECTIONS.items()
            if role != "root"
        },
        "managedProfiles": {},
        "managedRoot": root_state,
        "configCreated": config_created,
        "agentsCreated": agents_created,
    }


def _profile_is_managed(path: Path, role: str, state: dict[str, Any]) -> bool:
    if not path.exists():
        return True
    digest = sha256_text(path.read_text(encoding="utf-8"))
    record = state.get("managedProfiles", {}).get(role)
    if isinstance(record, dict) and record.get("managed") is True and record.get("sha256") == digest:
        return True
    return digest in KNOWN_MANAGED_PROFILE_HASHES.get(role, set())


def _legacy_profile_is_managed(path: Path, role: str, state: dict[str, Any]) -> bool:
    """Only remove an old role when state or an exact known release proves ownership."""
    digest = sha256_text(path.read_text(encoding="utf-8"))
    record = state.get("managedProfiles", {}).get(role)
    if isinstance(record, dict) and record.get("managed") is True and record.get("sha256") == digest:
        return True
    return digest in KNOWN_MANAGED_PROFILE_HASHES.get(role, set()) or digest == LEGACY_REMOVALS.get(path.name)


def _systemd_units(home: Path, codex_executable: str | None) -> dict[Path, str]:
    runtime = home / "model-routing"
    script = str(runtime / "model_router.py").replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"')
    codex_home = str(home).replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"')
    codex_dir = str(Path(codex_executable).parent) if codex_executable else ""
    service_path = os.pathsep.join(part for part in (codex_dir, "/usr/local/bin", "/usr/bin", "/bin") if part)
    service_path = service_path.replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"')
    service = f'''[Unit]
Description=Refresh adaptive Codex model routing

[Service]
Type=oneshot
Environment="PATH={service_path}"
ExecStart=/usr/bin/env python3 "{script}" --codex-home "{codex_home}" refresh --if-stale
'''
    timer = '''[Unit]
Description=Refresh adaptive Codex model routing periodically

[Timer]
OnBootSec=5m
OnUnitActiveSec=6h
RandomizedDelaySec=15m
Persistent=true

[Install]
WantedBy=timers.target
'''
    return {
        runtime / "systemd" / "codex-model-routing.service": service,
        runtime / "systemd" / "codex-model-routing.timer": timer,
    }


def _systemd_available() -> bool:
    return sys.platform.startswith("linux") and shutil.which("systemctl") is not None


@contextmanager
def _systemd_timer_lock():
    """Serialize mutations of the user-global model-routing unit names."""
    path = Path.home() / ".codex-model-routing-systemd.lock"
    handle = path.open("a+")
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _unit_fragment_path(unit: str) -> Path | None:
    result = subprocess.run(
        ["systemctl", "--user", "show", unit, "--property=FragmentPath", "--value"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        return None
    return Path(value).expanduser().absolute()


def timer_owned_by(home: Path) -> bool:
    """Return true only when both global unit names belong to this Codex home."""
    if not _systemd_available():
        return False
    unit_dir = home.expanduser().absolute() / "model-routing" / "systemd"
    expected = {
        "codex-model-routing.timer": unit_dir / "codex-model-routing.timer",
        "codex-model-routing.service": unit_dir / "codex-model-routing.service",
    }
    for unit, expected_path in expected.items():
        actual = _unit_fragment_path(unit)
        if actual is None:
            return False
        try:
            if actual.resolve(strict=False) != expected_path.resolve(strict=False):
                return False
        except OSError:
            return False
    return True


def enable_timer(home: Path, *, required: bool) -> str | None:
    if not _systemd_available():
        if required:
            raise InstallError("systemd user services are unavailable; use model-router refresh manually")
        return "systemd unavailable; use the portable refresh command"
    units = home / "model-routing" / "systemd"
    commands = (
        [
            "systemctl",
            "--user",
            "link",
            "--force",
            str(units / "codex-model-routing.service"),
            str(units / "codex-model-routing.timer"),
        ],
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "codex-model-routing.timer"],
    )
    try:
        with _systemd_timer_lock():
            for command in commands:
                subprocess.run(
                    command,
                    check=True,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
    except subprocess.CalledProcessError as exc:
        if required:
            raise InstallError(f"could not enable systemd timer: {exc.stderr.strip()}") from exc
        return f"could not enable systemd timer: {exc.stderr.strip()}"
    return None


def disable_timer(home: Path) -> bool:
    """Disable the shared unit names only when this home owns both fragments."""
    with _systemd_timer_lock():
        if not timer_owned_by(home):
            return False
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", "codex-model-routing.timer"],
            check=False,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["systemctl", "--user", "disable", "codex-model-routing.service"],
            check=False,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return True


def _install_files(
    home: Path,
    *,
    dry_run: bool,
    no_refresh: bool,
    schedule: str,
) -> tuple[list[Path], Path | None, list[str]]:
    validate_package()
    home = home.expanduser().absolute()
    if home.exists() and (home.is_symlink() or not home.is_dir()):
        raise InstallError(f"Codex home must be a real directory: {home}")
    if not dry_run:
        home.mkdir(parents=True, exist_ok=True)
    config = home / "config.toml"
    agents_doc = home / "AGENTS.md"
    agents_dir = home / "agents"
    if agents_dir.is_symlink() or (agents_dir.exists() and not agents_dir.is_dir()):
        raise InstallError(f"Agents path must be a real directory: {agents_dir}")
    for directory, label in (
        (home / "model-routing", "model-routing runtime"),
        (home / "backups", "backup directory"),
    ):
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            raise InstallError(f"{label} must be a real directory: {directory}")
    targets = (
        config,
        agents_doc,
        *(agents_dir / worker for worker in WORKERS),
        *(agents_dir / name for name in LEGACY_REMOVALS),
    )
    for target in targets:
        checked_file(target)
    config_text = config.read_text(encoding="utf-8") if config.exists() else None
    agents_text = agents_doc.read_text(encoding="utf-8") if agents_doc.exists() else None
    merged_config, root_state = merge_config(config_text)
    state = _initial_state(
        home,
        root_state,
        config_created=config_text is None,
        agents_created=agents_text is None,
    )
    desired: dict[Path, str | None] = {
        config: merged_config,
        agents_doc: merge_agents(agents_text),
        home / "model-routing" / "model_router.py": ENGINE_FILE.read_text(encoding="utf-8"),
        home / "model-routing" / "radar_source.py": RADAR_SOURCE_FILE.read_text(encoding="utf-8"),
        **_systemd_units(home, shutil.which("codex")),
    }
    warnings: list[str] = []
    managed_profiles: dict[str, Any] = {}
    selections = (
        state.get("catalogSelection")
        if isinstance(state.get("catalogSelection"), dict)
        else DEFAULT_SELECTIONS
    )
    active_profiles: dict[str, Any] = {}
    for worker in WORKERS:
        role = worker.removesuffix(".toml")
        source = ROOT / "agents" / worker
        template = source.read_text(encoding="utf-8")
        desired[home / "model-routing" / "templates" / worker] = template
        target = agents_dir / worker
        if _profile_is_managed(target, role, state):
            selection = selections.get(role, DEFAULT_SELECTIONS[role])
            rendered = re.sub(
                r'(?m)^model\s*=\s*"[^"]+"\s*$',
                f'model = "{selection["model"]}"',
                template,
                count=1,
            )
            rendered = re.sub(
                r'(?m)^model_reasoning_effort\s*=\s*"[^"]+"\s*$',
                f'model_reasoning_effort = "{selection["effort"]}"',
                rendered,
                count=1,
            )
            desired[target] = rendered
            managed_profiles[role] = {"managed": True, "sha256": sha256_text(rendered)}
            active_profiles[role] = {"managed": True, **selection}
        else:
            warnings.append(f"preserved custom profile {target}")
            managed_profiles[role] = {
                "managed": False,
                "reason": "pre-existing-custom-profile",
            }
            active_profiles[role] = profile_selection(target)
    for name in LEGACY_REMOVALS:
        target = agents_dir / name
        role = target.stem
        if target.exists() and _legacy_profile_is_managed(target, role, state):
            desired[target] = None
        elif target.exists():
            warnings.append(f"preserved custom legacy-named profile {target}")
    state["managedProfiles"] = managed_profiles
    state["activeProfiles"] = active_profiles
    if not isinstance(state.get("managedRoot"), dict):
        state["managedRoot"] = root_state
    state_path = home / "model-routing" / "state.json"
    desired[state_path] = json.dumps(state, indent=2, sort_keys=True) + "\n"
    changes = [
        path
        for path, content in desired.items()
        if (content is None and path.exists())
        or (
            content is not None
            and (not path.exists() or path.read_text(encoding="utf-8") != content)
        )
    ]
    if dry_run:
        return changes, None, warnings
    backup = transactional_write(home, desired)
    return changes, backup, warnings


def install(
    home: Path,
    *,
    dry_run: bool,
    no_refresh: bool,
    schedule: str,
) -> tuple[list[Path], Path | None, list[str]]:
    home = home.expanduser().absolute()
    if dry_run:
        return _install_files(home, dry_run=True, no_refresh=True, schedule=schedule)
    home.mkdir(parents=True, exist_ok=True)
    with routing_lock(home):
        changes, backup, warnings = _install_files(
            home, dry_run=False, no_refresh=True, schedule=schedule
        )
    if not no_refresh:
        try:
            refresh(home, home / "model-routing" / "templates")
        except (RoutingError, OSError, tomllib.TOMLDecodeError) as exc:
            warnings.append(
                f"catalog refresh deferred; packaged last-good routing remains active: {exc}"
            )
    expected_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser().absolute()
    should_enable = schedule == "enable" or (schedule == "auto" and home == expected_home)
    if should_enable or schedule == "disable":
        with routing_lock(home):
            runtime_exists = (home / "model-routing" / "state.json").is_file()
            if should_enable and runtime_exists:
                warning = enable_timer(home, required=schedule == "enable")
                if warning:
                    warnings.append(warning)
            elif schedule == "disable":
                disable_timer(home)
    return changes, backup, warnings


def _remove_managed_agents_block(text: str) -> str:
    if text.count(START) == 1 and text.count(END) == 1:
        start = text.index(START)
        end = text.index(END, start) + len(END)
        before, after = text[:start].rstrip(), text[end:].lstrip("\n")
        return ((before + "\n\n") if before and after else before) + after
    return text


def _uninstall_files(home: Path, *, dry_run: bool) -> tuple[list[Path], Path | None]:
    home = home.expanduser().absolute()
    state = read_state(home)
    if state is None:
        return [], None
    desired: dict[Path, str | None] = {}
    agents_doc = home / "AGENTS.md"
    if agents_doc.exists():
        agents_text = agents_doc.read_text(encoding="utf-8")
        without_policy = _remove_managed_agents_block(agents_text)
        desired[agents_doc] = (
            None if state.get("agentsCreated") is True and not without_policy.strip() else without_policy
        )
    managed = state.get("managedProfiles", {})
    for role in ROLES:
        target = home / "agents" / f"{role}.toml"
        record = managed.get(role) if isinstance(managed, dict) else None
        if target.exists() and isinstance(record, dict) and record.get("managed") is True:
            if sha256_text(target.read_text(encoding="utf-8")) == record.get("sha256"):
                desired[target] = None
    config = home / "config.toml"
    root = state.get("managedRoot")
    if config.exists() and isinstance(root, dict) and root.get("managed") is True:
        text = config.read_text(encoding="utf-8")
        parsed = tomllib.loads(text)
        if (
            parsed.get("model") == root.get("model")
            and parsed.get("model_reasoning_effort") == root.get("effort")
        ):
            clean = text.replace(MANAGED_ROOT_MARKER + "\n", "", 1)
            expected = {
                "model": root.get("model"),
                "model_reasoning_effort": root.get("effort"),
                "agents": {"enabled": True},
            }
            desired[config] = (
                None
                if state.get("configCreated") is True and tomllib.loads(clean) == expected
                else clean
            )
    runtime = home / "model-routing"
    if runtime.exists():
        for path in sorted(runtime.rglob("*"), reverse=True):
            if path.is_file():
                desired[path] = None
    changes = [
        path
        for path, value in desired.items()
        if path.exists() and (value is None or path.read_text(encoding="utf-8") != value)
    ]
    if dry_run:
        return changes, None
    backup = transactional_write(home, desired)
    for directory in (runtime / "templates", runtime / "systemd", runtime):
        try:
            directory.rmdir()
        except OSError:
            pass
    return changes, backup


def uninstall(home: Path, *, dry_run: bool) -> tuple[list[Path], Path | None]:
    home = home.expanduser().absolute()
    if dry_run:
        return _uninstall_files(home, dry_run=True)
    with routing_lock(home):
        disable_timer(home)
        return _uninstall_files(home, dry_run=False)


def main() -> int:
    args = parse_args()
    try:
        if args.uninstall:
            changes, backup = uninstall(args.codex_home, dry_run=args.dry_run)
            warnings: list[str] = []
        else:
            changes, backup, warnings = install(
                args.codex_home,
                dry_run=args.dry_run,
                no_refresh=args.no_refresh or args.dry_run,
                schedule=args.schedule,
            )
    except (InstallError, RoutingError, OSError, tomllib.TOMLDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    verb = "Would change" if args.dry_run else ("Uninstalled" if args.uninstall else "Installed")
    print(f"{verb}: " + (", ".join(str(path) for path in changes) if changes else "no changes"))
    if backup:
        print(f"Backup: {backup}")
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if not args.uninstall and not args.dry_run:
        home = args.codex_home.expanduser().absolute()
        print(
            "Refresh manually: "
            f"python3 {home / 'model-routing/model_router.py'} --codex-home {home} refresh"
        )
        print("Start a new Codex task to load refreshed profiles and policy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
