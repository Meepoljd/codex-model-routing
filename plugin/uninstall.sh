#!/bin/bash
set -euo pipefail

CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
if ! command -v codex >/dev/null 2>&1; then
  echo "codex CLI was not found on PATH." >&2
  exit 1
fi

codex plugin remove model-routing@model-routing 2>/dev/null || true
codex plugin marketplace remove model-routing 2>/dev/null || true

backup_root=""
for candidate in "$CODEX_HOME"/backups/model-routing-plugin-*; do
  [[ -d "$candidate" ]] || continue
  [[ -f "$candidate/codex-home" ]] || continue
  if [[ "$(<"$candidate/codex-home")" == "$CODEX_HOME" ]]; then
    backup_root="$candidate"
  fi
done

if [[ -z "$backup_root" ]]; then
  echo "Plugin removed. No matching installer backup was found; worker files were left in place."
  exit 0
fi

for name in luna_worker sol_worker astra_worker; do
  target="$CODEX_HOME/agents/$name.toml"
  if [[ -f "$backup_root/agents/$name.toml.existed" ]]; then
    cp -p "$backup_root/agents/$name.toml" "$target"
  else
    rm -f "$target"
  fi
done

echo "Plugin removed and worker profiles restored from $backup_root."
