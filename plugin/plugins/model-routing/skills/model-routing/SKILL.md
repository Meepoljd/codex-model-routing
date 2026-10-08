---
name: model-routing
description: Plan task boundaries and dependencies, choose the lowest-cost Codex model likely to succeed, and delegate through native workers with visible progress. Use when applying model routing or choosing how to split, assign, or escalate substantive work.
---

# Model Routing

This skill applies the routing workflow. A separate installed refresher maintains the worker profiles from the logged-in Codex `model/list` catalog without making inference calls. Preserve the user's scope and explicit model, delegation, and analysis-only instructions. Profile changes take effect in a new task and do not change a running session.

Before routing, use the current `simple_worker`, `routine_worker`, `complex_worker`, and `frontier_worker` profiles in the Codex agents directory as the source of model IDs. When exact status matters, run the installed `model_router.py ... status` command documented by this package and distinguish `catalogSelection` from `activeProfiles`. Do not copy a model ID from this skill. The refresher intersects native catalog entries with Codex Radar evidence across model families; current RadarBench accepts only complete model/effort points sharing one binding fingerprint and needs at least three complete candidates, so unmeasured new models do not block measured ones. It defaults to low, medium, and high effort only.

## Plan before assigning

Before the first worker spawn, give the user a short plan: intended outcome, whether splitting helps, work boundaries and dependencies, proposed owners/tiers with brief reasons, and how completion will be checked. This is an execution plan, not a request for approval or private reasoning. A simple task needs only a sentence; use a compact table when several tasks benefit from it.

Choose one of three shapes:

- **Root only:** request understanding, light search, simple summaries, routing decisions, and low-risk planning. Do not create workers just to show activity.
- **One worker:** substantive engineering or tightly coupled work with a shared decision, interface, or edit surface. No useful split does not mean root should implement it.
- **Several workers:** independent outputs or genuinely separate ownership make the benefit exceed context and coordination costs. Use the smallest useful set. Parallelize only ready tasks with satisfied dependencies; serialize shared-file edits or keep them with one owner.

For each delegated task record an ID, deliverable, absolute paths (or no files), owner, dependencies, and acceptance evidence. Root owns integration and the final user response. If uncertainty prevents a sound split, first delegate a bounded investigation at the appropriate tier, then revise the plan from its evidence. Do not invent implementation tasks before their prerequisite decisions are made.

## Tiers

Route each task by type, ambiguity, coupling, risk, verifiability, and root-cause uncertainty. Evaluate frontier, complex, routine, then simple; high-risk rules take priority. Do not use prompt length or file count as proxies. Judge coupled risks together rather than splitting a risky task into apparently routine pieces.

1. **Frontier (`frontier_worker`):** reserve this role for the hardest work, interacting uncertainty, evidence-backed repeated complex failures, or exceptional failure cost. Explicit `gpt6`, `gpt-6`, `GPT-6`, or `GPT-6 Astra` means an exact `gpt-6-astra` override, not this dynamic role. Tokens in quoted text, policy, documentation, status history, or rationale are not user model selections.
2. **Complex (`complex_worker`):** architecture; unclear root cause; high ambiguity, coupling, or risk; concurrency; distributed coordination; security-sensitive behavior; deep performance diagnosis; destructive migrations; or repeated routine failures.
3. **Routine (`routine_worker`):** ordinary features, refactors, test work, and moderate debugging when cause and impact are clear.
4. **Simple (`simple_worker`):** mechanical edits, formatting, and clearly scoped tiny fixes. Escalate to routine if focused verification fails or scope expands.
5. **Root:** the light coordination work described above. Existing root selections remain explicit pins and continue to follow routine. Delegate substantial implementation and route analysis by its actual difficulty.

## Handoff and native execution

Actually call the exposed native `spawn_agent` with the configured `agent_type`/role. Saying a worker is running is not execution. Inspect the current tool schema: use `fork_turns="none"` or minimal recent context when supported; use `fork_context=false` only on versions exposing that parameter. Never use a full-history fork for custom workers or pass unsupported arguments.

Every handoff must be self-contained:

```text
Task ID / objective / expected deliverable:
Absolute paths and write ownership (or no files / analysis only):
Inputs, dependencies, and decisions already settled:
Existing evidence, edits, and verification already performed:
Acceptance criteria and permitted focused verification:
Selected tier and escalation context:
Progress: report a meaningful finding, completed phase, blocker, or changed assumption
through the available parent-message tool; include task ID, status, evidence, and next step.
Final return: outcome, changed paths, evidence, verification actually run, unresolved issues.
You share the workspace: preserve others' edits and stay within your ownership.
Do not delegate or change tiers yourself; recommend escalation to root.
```

Retain returned agent IDs/task names so updates and results are attributable. A spawn failure or missing role is not a running worker. Report the limitation and use only a supported, authorized alternative without claiming the requested model ran.

## Visible progress and integration

Worker messages are a reporting contract, not automatic log streaming. Root keeps the main conversation useful:

- Show the plan and assignment before spawning. On successful spawn, report the actual task/worker reference; distinguish selected profile from runtime-confirmed model information.
- Ask workers to send concise milestone updates using the available parent-message tool. Forward meaningful findings, phase outputs, blockers, and evidence references in root commentary. Do not ask for private chain-of-thought or copy all raw tool output.
- Maintain task states such as pending, running, blocked, and completed from observed messages/results. A running state is not evidence of advancement; elapsed time alone is not failure.
- While independent root work exists, do it. When waiting, use the native wait tool and its documented semantics. A mailbox wakeup or timeout may not contain the result or mean completion; consume the delivered message/result before updating state. Avoid busy polling. Choose waits compatible with the host's user-update cadence, and report when there is no new evidence rather than invent progress.
- Use supported status/message/follow-up tools when a concrete blocker, changed instruction, or missing deliverable needs attention. Reuse the existing worker for related follow-up. Do not respawn or interrupt merely because it is quiet.
- Wait for required results, check each against its acceptance criteria, and integrate in dependency order. State verification actually performed, skipped checks, and unresolved limitations. Stop once the requested work and focused verification are complete.

The main conversation should expose the plan, task status, phase outputs, evidence, and final synthesis. Detailed thread inspection depends on the client. For capabilities and limits, see [worker visibility](references/worker-visibility.md). This skill cannot enable a hidden streaming API or guarantee that every worker event appears in the main conversation.

## Escalation and availability

Workers return recommendations; root revises the plan and decides escalation. Stop and recommend Sol when Luna work becomes architectural, the cause remains unclear, concurrency/distributed or security concerns arise, reasonable attempts repeatedly fail, or behavior impact is unclear.

Frontier handoffs must contain complex-worker attempts, evidence, failure reasons, and unresolved questions. When direct frontier routing is justified by exceptional criteria, state why. An explicit Astra request is an exact-model override, not a frontier handoff. Never fabricate attempts, repeat a failed approach without a new hypothesis, or enlarge scope because the model is stronger.

TOML profiles cannot make unavailable models available. Discovery failures keep the last-good profiles, and a user-modified or pre-existing custom profile stays unmanaged until the user explicitly replaces it. Follow the active runtime's supported mechanisms and disclose unavailable roles/models. Start a new Codex task after installing or refreshing this plugin. Project instructions and explicit user directions may override this policy.
