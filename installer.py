#!/usr/bin/env python3
"""Install the portable Codex model-routing policy without replacing local settings."""

from __future__ import annotations

import argparse
import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys
import tempfile
import tomllib


ROOT = Path(__file__).resolve().parent
POLICY_FILE = ROOT / "policy" / "model-routing-policy.md"
WORKERS = ("spark_worker.toml", "terra_worker.toml", "sol_worker.toml", "astra_worker.toml")
START = "<!-- codex-model-routing:begin -->"
END = "<!-- codex-model-routing:end -->"
DEFAULT_CONFIG = 'model = "gpt-5.6-luna"\nmodel_reasoning_effort = "low"\n\n[agents]\nenabled = true\n'


class InstallError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=Path, default=Path.home() / ".codex")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report changes without writing files.")
    return parser.parse_args()


def validate_package() -> None:
    if not POLICY_FILE.is_file():
        raise InstallError(f"Missing packaged policy: {POLICY_FILE}")
    for worker in WORKERS:
        source = ROOT / "agents" / worker
        if not source.is_file():
            raise InstallError(f"Missing packaged worker: {source}")
        tomllib.loads(source.read_text(encoding="utf-8"))


def table_spans(text: str) -> list[tuple[int, str, bool]]:
    """Find TOML table headers outside multiline basic/literal strings.

    tomllib validates syntax first. This small scanner is intentionally limited to
    locating table boundaries, so comments and unrelated source text are retained.
    """
    spans: list[tuple[int, str, bool]] = []
    delimiter: str | None = None
    offset = 0
    for line in text.splitlines(keepends=True):
        i = 0
        quote = delimiter
        while i < len(line):
            if quote:
                if line.startswith(quote, i):
                    quote = None
                    i += 3
                else:
                    i += 1
                continue
            if line.startswith('"""', i) or line.startswith("'''", i):
                quote = line[i : i + 3]
                i += 3
                continue
            if line[i] == "#":
                break
            i += 1
        if delimiter is None and quote is None:
            stripped = line.lstrip()
            if stripped.startswith("["):
                array = stripped.startswith("[[")
                close_token = "]]" if array else "]"
                close = stripped.find(close_token, 2 if array else 1)
                if close > 1:
                    name = stripped[2:close].strip() if array else stripped[1:close].strip()
                    trailer = stripped[close + len(close_token) :].strip()
                    if trailer == "" or trailer.startswith("#"):
                        spans.append((offset, name, array))
        delimiter = quote
        offset += len(line)
    return spans


def replace_key_in_region(region: str, key: str, value: str) -> tuple[str, bool]:
    """Replace an exact bare key assignment while preserving line comments."""
    lines = region.splitlines(keepends=True)
    delimiter: str | None = None
    for index, line in enumerate(lines):
        if delimiter is not None:
            close = line.find(delimiter)
            if close >= 0:
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
        comment_index = rest.find("#")
        comment = "" if comment_index < 0 else " " + rest[comment_index:].rstrip("\r\n")
        newline = "\n" if line.endswith("\n") else ""
        lines[index] = f"{prefix}{key} = {value}{comment}{newline}"
        return "".join(lines), True
    return region, False


def merge_config(existing: str | None) -> str:
    if existing is None:
        return DEFAULT_CONFIG
    try:
        original_data = tomllib.loads(existing)
    except tomllib.TOMLDecodeError as exc:
        raise InstallError(f"Existing config.toml is invalid; no files changed: {exc}") from exc

    spans = table_spans(existing)
    first_table = spans[0][0] if spans else len(existing)
    root, tail = existing[:first_table], existing[first_table:]
    for key, value in (("model", '"gpt-5.6-luna"'), ("model_reasoning_effort", '"low"')):
        root, found = replace_key_in_region(root, key, value)
        if not found:
            if root and not root.endswith("\n"):
                root += "\n"
            root += f"{key} = {value}\n"

    agents = next(((pos, name) for pos, name, array in spans if name == "agents" and not array), None)
    if agents is None:
        if tail and not tail.endswith("\n"):
            tail += "\n"
        tail += "\n[agents]\nenabled = true\n"
    else:
        start = agents[0] - first_table
        following = [pos - first_table for pos, _, _ in spans if pos > agents[0]]
        end = following[0] if following else len(tail)
        region, found = replace_key_in_region(tail[start:end], "enabled", "true")
        if not found:
            if region and not region.endswith("\n"):
                region += "\n"
            region += "enabled = true\n"
        tail = tail[:start] + region + tail[end:]
    result = root + tail
    try:
        result_data = tomllib.loads(result)
    except tomllib.TOMLDecodeError as exc:
        raise InstallError(f"Refusing generated invalid config.toml: {exc}") from exc
    expected = copy.deepcopy(original_data)
    expected["model"] = "gpt-5.6-luna"
    expected["model_reasoning_effort"] = "low"
    agents_data = expected.get("agents")
    if agents_data is None:
        expected["agents"] = {"enabled": True}
    elif not isinstance(agents_data, dict):
        raise InstallError("Existing agents value is not a TOML table; no files changed.")
    else:
        agents_data["enabled"] = True
    if result_data != expected:
        raise InstallError("Unsupported TOML layout would change unrelated semantics; no files changed.")
    return result


def merge_agents(existing: str | None) -> str:
    policy = POLICY_FILE.read_text(encoding="utf-8").strip()
    managed = f"{START}\n{policy}\n{END}\n"
    if existing is None or not existing.strip():
        return managed
    if START in existing or END in existing:
        if existing.count(START) != 1 or existing.count(END) != 1:
            raise InstallError("AGENTS.md has ambiguous existing managed routing markers; no files changed.")
        start = existing.index(START)
        end = existing.index(END, start) + len(END)
        return existing[:start] + managed.rstrip("\n") + existing[end:]
    lines = existing.splitlines(keepends=True)
    header = next((i for i, line in enumerate(lines) if line.rstrip("\r\n") == "## Model Routing Policy"), None)
    if header is not None:
        end = next(
            (i for i in range(header + 1, len(lines)) if lines[i].startswith("# ") or lines[i].startswith("## ")),
            len(lines),
        )
        return "".join(lines[:header]) + managed + "".join(lines[end:])
    suffix = "" if existing.endswith("\n") else "\n"
    return existing + suffix + "\n" + managed


def checked_file(path: Path) -> None:
    if path.is_symlink():
        raise InstallError(f"Refusing symbolic-link target: {path}")
    if path.exists() and not path.is_file():
        raise InstallError(f"Expected a file but found another path type: {path}")


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def make_backup(home: Path, changes: dict[Path, str]) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = home / f"codex-model-routing-backup-{stamp}"
    number = 1
    while backup.exists():
        backup = home / f"codex-model-routing-backup-{stamp}-{number}"
        number += 1
    backup.mkdir(parents=True)
    manifest: dict[str, str | None] = {}
    for path in changes:
        relative = str(path.relative_to(home))
        if path.exists():
            destination = backup / path.relative_to(home)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            manifest[relative] = relative
        else:
            manifest[relative] = None
    (backup / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return backup


def install(home: Path, dry_run: bool) -> tuple[list[Path], Path | None]:
    validate_package()
    if home.exists() and (home.is_symlink() or not home.is_dir()):
        raise InstallError(f"Codex home must be a real directory: {home}")
    config = home / "config.toml"
    agents_doc = home / "AGENTS.md"
    agents_dir = home / "agents"
    if agents_dir.is_symlink():
        raise InstallError(f"Refusing symbolic-link directory: {agents_dir}")
    if agents_dir.exists() and not agents_dir.is_dir():
        raise InstallError(f"Expected an agents directory but found another path type: {agents_dir}")
    targets = [config, agents_doc, *(home / "agents" / worker for worker in WORKERS)]
    for target in targets:
        checked_file(target)
    config_text = config.read_text(encoding="utf-8") if config.exists() else None
    agents_text = agents_doc.read_text(encoding="utf-8") if agents_doc.exists() else None
    desired: dict[Path, str] = {config: merge_config(config_text), agents_doc: merge_agents(agents_text)}
    desired.update({home / "agents" / worker: (ROOT / "agents" / worker).read_text(encoding="utf-8") for worker in WORKERS})
    changes = {path: content for path, content in desired.items() if not path.exists() or path.read_text(encoding="utf-8") != content}
    if dry_run or not changes:
        return list(changes), None
    home.mkdir(parents=True, exist_ok=True)
    backup = make_backup(home, changes)
    try:
        for path, content in changes.items():
            atomic_write(path, content)
    except BaseException:
        # Backups remain available for manual recovery if an external filesystem error occurs.
        raise
    return list(changes), backup


def main() -> int:
    args = parse_args()
    try:
        changes, backup = install(args.codex_home.expanduser().absolute(), args.dry_run)
    except InstallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.dry_run:
        print("Dry run: " + (", ".join(str(path) for path in changes) if changes else "no changes"))
    elif changes:
        print("Installed: " + ", ".join(str(path) for path in changes))
        print(f"Backup: {backup}")
    else:
        print("Already installed; no changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
