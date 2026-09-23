#!/bin/bash
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
BACKUP_ROOT="$CODEX_HOME/backups/model-routing-plugin-$(date +%Y%m%dT%H%M%S)"

if ! command -v codex >/dev/null 2>&1; then
  echo "codex CLI was not found on PATH." >&2
  exit 1
fi

mkdir -p "$CODEX_HOME/agents" "$BACKUP_ROOT/agents"
for name in luna_worker sol_worker astra_worker; do
  target="$CODEX_HOME/agents/$name.toml"
  if [[ -e "$target" ]]; then
    cp -p "$target" "$BACKUP_ROOT/agents/$name.toml"
    : > "$BACKUP_ROOT/agents/$name.toml.existed"
  fi
done
printf '%s\n' "$PLUGIN_ROOT" > "$BACKUP_ROOT/marketplace-path"
printf '%s\n' "$CODEX_HOME" > "$BACKUP_ROOT/codex-home"

restore_on_error() {
  local status=$?
  if [[ $status -ne 0 ]]; then
    for name in luna_worker sol_worker astra_worker; do
      target="$CODEX_HOME/agents/$name.toml"
      if [[ -f "$BACKUP_ROOT/agents/$name.toml.existed" ]]; then
        cp -p "$BACKUP_ROOT/agents/$name.toml" "$target"
      else
        rm -f "$target"
      fi
    done
    echo "Install failed; prior worker profiles were restored. Backup: $BACKUP_ROOT" >&2
  fi
  exit "$status"
}
trap restore_on_error EXIT

for name in luna_worker sol_worker astra_worker; do
  install -m 0644 "$PLUGIN_ROOT/agents/$name.toml" "$CODEX_HOME/agents/$name.toml"
done

if ! codex plugin marketplace list 2>/dev/null | rg -q '^model-routing[[:space:]]'; then
  codex plugin marketplace add "$PLUGIN_ROOT"
fi
codex plugin add model-routing@model-routing

trap - EXIT
echo "Model Routing installed. Worker profiles are in $CODEX_HOME/agents/."
echo "Backup: $BACKUP_ROOT"
echo "Start a new Codex task to load the plugin skill and worker profiles."
