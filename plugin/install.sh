#!/usr/bin/env bash
set -euo pipefail

PLUGIN_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$PLUGIN_ROOT/.." && pwd)"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
export CODEX_HOME

if ! command -v codex >/dev/null 2>&1; then
  echo "codex CLI was not found on PATH." >&2
  exit 1
fi

marketplace_json="$(codex plugin marketplace list --json)"
marketplace_status="$(MARKETPLACE_JSON="$marketplace_json" python3 - "$PLUGIN_ROOT" <<'PY'
import json
import os
from pathlib import Path
import sys

desired = Path(sys.argv[1]).resolve()
payload = json.loads(os.environ["MARKETPLACE_JSON"])
matches = [entry for entry in payload.get("marketplaces", []) if entry.get("name") == "model-routing"]
if not matches:
    print("missing")
elif len(matches) != 1:
    print("ambiguous")
else:
    entry = matches[0]
    source = entry.get("root")
    if not source and isinstance(entry.get("marketplaceSource"), dict):
        source = entry["marketplaceSource"].get("source")
    try:
        same = source is not None and Path(source).resolve() == desired
    except OSError:
        same = False
    print("same" if same else "conflict:" + str(source))
PY
)"

case "$marketplace_status" in
  missing)
    ;;
  same)
    ;;
  *)
    echo "Marketplace 'model-routing' already points elsewhere ($marketplace_status)." >&2
    echo "Review it, then run: codex plugin marketplace remove model-routing" >&2
    echo "After removal, run: codex plugin marketplace add '$PLUGIN_ROOT'" >&2
    exit 2
    ;;
esac

python3 "$REPO_ROOT/installer.py" --codex-home "$CODEX_HOME"
if [[ "$marketplace_status" == "missing" ]]; then
  codex plugin marketplace add "$PLUGIN_ROOT"
fi
codex plugin add model-routing@model-routing

echo "Model Routing plugin installed. Start a new Codex task to load the refreshed policy and profiles."
