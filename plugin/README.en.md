# Codex Model Routing Plugin

[中文](README.md)

Plan briefly before assigning work. Decide whether the root should handle it, one worker should own it, or several dependent tasks should be delegated. Select Luna, Sol, or Astra by risk and uncertainty. Root reports progress and integrates the evidence.

## Workflow

1. **Plan first:** state the outcome, acceptance criteria, known constraints, and whether a split helps. A simple task needs one sentence; planning adds no approval step.
2. **Define boundaries and dependencies:** list each deliverable, owned paths, prerequisite results, owner, and verification evidence. Investigate unsettled interfaces first. Give shared-file edits to one worker or serialize them.
3. **Choose tier and assign:** keep light search and summaries at root. Delegate substantive implementation to one worker when tightly coupled. Parallelize only independent work whose benefit exceeds coordination costs.
4. **Delegate for real:** call native `spawn_agent` with the selected role and minimum necessary context. Include evidence, edits, verification, ownership, and escalation context.
5. **Report and integrate:** workers report milestones and blockers. Root updates task status and evidence in the main conversation, waits for required results, integrates in dependency order, performs focused checks, and summarizes.

For an unknown root cause, ask Sol to investigate before assigning a bounded implementation to Luna. Do not start work that depends on findings that have not arrived.

## Routing tiers

Evaluate Astra → Sol → Luna, with risk taking priority.

| Tier | Work |
| --- | --- |
| Astra · `astra_worker` | Explicit GPT-6 Astra request; exceptionally difficult end-to-end work; interacting architectural uncertainties; or evidenced repeated Sol failures |
| Sol · `sol_worker` | Architecture, unclear causes, high coupling or risk, concurrency/distributed systems, security-sensitive design, deep performance diagnosis, destructive migrations |
| Luna · `luna_worker` | Routine engineering, features/refactors, API or data-model changes, test design, moderate debugging, bounded configuration fixes |
| Root · recommended Luna low | Understanding requests, light search, summaries, planning, and coordination; this plugin does not switch the root model |

Prompt length, file count, and model recency do not justify escalation. Generic GPT-6 or “use a stronger model” requests do not alone select Astra. Workers recommend escalation to Root and do not delegate further. Explain direct Astra routing and whether Sol was skipped.

## Execution visibility

The main conversation presents the plan, observed task states, phase outputs, evidence, and final synthesis. Workers send meaningful findings, completed phases, blockers, and changed assumptions through the available parent-message tool; Root summarizes them. A wait timeout means neither failure nor completion.

Supported clients expose worker threads; Codex CLI provides `/agent` for thread inspection. Exact controls depend on the client. See the official [Subagents documentation](https://learn.chatgpt.com/docs/agent-configuration/subagents).

The plugin does not mirror every worker tool event into the main conversation or expose full private reasoning. It implements no log collection service or dashboard. See [capabilities and limits](plugins/model-routing/skills/model-routing/references/worker-visibility.md), including how this differs from the separate Agents API event stream.

## Implementation and installation

- `plugins/model-routing/skills/model-routing/SKILL.md`: planning, decomposition, routing, handoffs, and root reporting. Invoke it with `$model-routing`.
- `agents/*_worker.toml`: model, reasoning effort, ownership, and progress-reporting instructions. Profiles cannot make unavailable models available.
- `install.sh` / `uninstall.sh`: marketplace registration, skill installation, and worker backup/copy/restore.

```bash
git clone git@github.com:Meepoljd/codex-model-routing.git
cd codex-model-routing/plugin
bash install.sh
```

Start a new Codex task after installation. The installer copies worker profiles to `~/.codex/agents/`, backing up existing files. It does not overwrite `~/.codex/AGENTS.md` or other Codex configuration.

Manual marketplace registration installs the skill but does not copy worker profiles:

```bash
codex plugin marketplace add /absolute/path/codex-model-routing/plugin
codex plugin add model-routing@model-routing
```

Run `bash uninstall.sh` from `plugin/` to uninstall. It restores workers from the latest matching backup, deletes files that were absent before installation, and leaves worker files in place if no matching backup exists. Backups are under `~/.codex/backups/model-routing-plugin-<timestamp>/`.

## Customize and verify

Edit `Plan before assigning` for decomposition, `Tiers` and the matching TOML files for routing, and `Visible progress and integration` plus worker instructions for reporting. Adding a worker also requires updating installer backup/copy and uninstaller restore logic. A new log UI/API requires separate implementation.

Check document links, TOML/JSON, and install paths. For runtime validation, use a temporary configuration and a new session to check root-only, coupled single-worker, independent multi-worker, dependency order, and actual progress delivery. State what was not tested. Do not package personal configuration, credentials, hooks, project paths, or session records.
