#!/usr/bin/env bash
set -euo pipefail

PLUGIN_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$PLUGIN_ROOT/.." && pwd)"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
export CODEX_HOME

if command -v codex >/dev/null 2>&1; then
  marketplace_json="$(codex plugin marketplace list --json)"
  marketplace_status="$(MARKETPLACE_JSON="$marketplace_json" python3 - "$PLUGIN_ROOT" <<'PY'
import json
import os
from pathlib import Path
import sys

desired = Path(sys.argv[1]).resolve()
payload = json.loads(os.environ["MARKETPLACE_JSON"])
matches = [entry for entry in payload.get("marketplaces", []) if entry.get("name") == "model-routing"]
if len(matches) != 1:
    print("missing-or-ambiguous")
else:
    entry = matches[0]
    source = entry.get("root")
    if not source and isinstance(entry.get("marketplaceSource"), dict):
        source = entry["marketplaceSource"].get("source")
    try:
        print("same" if source is not None and Path(source).resolve() == desired else "different")
    except OSError:
        print("different")
PY
)"
  if [[ "$marketplace_status" == "same" ]]; then
    codex plugin remove model-routing@model-routing 2>/dev/null || true
    codex plugin marketplace remove model-routing
  else
    echo "Marketplace 'model-routing' is absent, ambiguous, or points elsewhere; leaving plugin registry unchanged." >&2
  fi
fi

python3 "$REPO_ROOT/installer.py" --codex-home "$CODEX_HOME" --uninstall
echo "Model Routing plugin and managed runtime removed. Backups remain under $CODEX_HOME/backups/."
