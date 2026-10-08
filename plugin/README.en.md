# Adaptive Codex Model Routing Plugin

[中文](README.md)

The plugin plans and assigns work by risk and uncertainty, then delegates through native Codex `spawn_agent` roles: Luna, Sol, or Astra. A separate refresher maintains worker model IDs from the logged-in account's native `model/list` catalog. It neither reads authentication files nor sends inference requests.

## Routing and adaptive selection

Evaluate Astra → Sol → Luna, with higher-risk criteria taking priority:

| Role | Work |
| --- | --- |
| `astra_worker` | Explicit GPT-6/Astra selection; evidenced repeated Sol failures; interacting architectural uncertainty; exceptional cross-system complexity and failure cost beyond Sol |
| `sol_worker` | Architecture, unclear causes, high coupling or risk, concurrency/distributed systems, security-sensitive behavior, deep performance diagnosis, destructive migrations |
| `luna_worker` | Routine engineering, multi-file features/refactors, API/data-model changes, test design, moderate debugging, bounded configuration changes |
| Root | Request understanding, light search, summaries, planning, coordination, and integration |

Prompt length, file count, and model recency do not justify escalation. `gpt6`, `gpt-6`, `GPT-6`, or `GPT-6 Astra` routes to Astra when the user explicitly selects it for the task. Those tokens in documentation, quotations, status history, or policy text do not trigger Astra.

The refresher recognizes only ordinary visible models whose names strictly belong to the Luna, Sol, or Astra families. It compares numeric versions, requires the role's reasoning effort, and rejects hidden, specialty, malformed, unknown-family, and explicitly tool-disabled entries. Future versions within the known families update automatically; a new unknown family is never guessed into a role.

Packaged last-good defaults are Luna `gpt-6-luna`/medium, Sol `gpt-6.1-sol`/high, and Astra `gpt-6-astra`/high. The installed `~/.codex/agents/*_worker.toml` files are authoritative; do not copy model IDs from documentation.

## Workflow and visibility

Root first states the goal, split decision, dependencies, owned paths, and verification. One suitable worker owns tightly coupled work. Parallel workers are used only for independent work whose benefit exceeds coordination cost. Handoffs include prior evidence, edits, verification, boundaries, and escalation context.

Workers report meaningful findings, completed phases, blockers, and changed assumptions. Root presents the plan, observed state, evidence, and integrated result. Supported clients expose worker threads; the CLI provides `/agent`. The plugin does not mirror every tool event or expose private reasoning. See the [visibility reference](plugins/model-routing/skills/model-routing/references/worker-visibility.md).

## Installation

```bash
git clone git@github.com:Meepoljd/codex-model-routing.git
cd codex-model-routing/plugin
bash install.sh
```

The installer merges a marked global routing block while preserving other AGENTS.md content. Existing root model/effort settings are explicit pins. A fresh config starts with a managed Luna/low root; a later user edit ends root management. Same-named custom worker profiles are preserved. Only missing files, the tool's last write, or exact repository legacy bytes are managed. Legacy Spark/Terra files are backed up and removed only on an exact byte match.

On Linux the installer attempts to enable a six-hour systemd user timer. The installed runtime under `~/.codex/model-routing/` is self-contained and does not depend on the checkout or plugin cache. Other platforms use the portable manual command. Start a new task after install or refresh; running sessions do not hot reload profiles.

## Status, refresh, and troubleshooting

```bash
python3 ~/.codex/model-routing/model_router.py --codex-home ~/.codex status
python3 ~/.codex/model-routing/model_router.py --codex-home ~/.codex refresh
```

`catalogSelection` reports catalog recommendations; `activeProfiles` reports effective profiles. Custom files show `managed: false`. Pagination, timeout, empty or malformed catalogs, and a missing role all fail without changing the last-good state.

```bash
systemctl --user status codex-model-routing.timer
systemctl --user start codex-model-routing.service
journalctl --user -u codex-model-routing.service --since today
```

If a marketplace with the same name points elsewhere, installation stops with inspection and repair commands instead of removing or silently replacing it. After changing plugin contents, use the official cachebuster update flow, reinstall, and validate in a new task.

## Uninstall and development

```bash
bash uninstall.sh
```

Uninstall removes the plugin, disables the timer, and removes profiles and policy content still managed by this tool. User-modified and pre-existing custom profiles remain. Pre-write backups remain under `~/.codex/backups/model-routing-refresh-*`.

Run repository tests with:

```bash
python3 -m unittest discover -s tests -v
```

After skill changes, run the skill `quick_validate.py`; before delivery, run `validate_plugin.py`. Do not package personal config, credentials, hooks, project paths, or session data.
