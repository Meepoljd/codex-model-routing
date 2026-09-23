---
name: model-routing
description: Plan task boundaries and dependencies, choose the lowest-cost Codex model likely to succeed, and delegate through native workers with visible progress. Use when applying model routing or choosing how to split, assign, or escalate substantive work.
---

# Model Routing

This is a prompt-driven workflow, not a runtime router. Preserve the user's scope and explicit model, delegation, and analysis-only instructions. Policy or TOML edits do not change the model of a running session.

## Plan before assigning

Before the first worker spawn, give the user a short plan: intended outcome, whether splitting helps, work boundaries and dependencies, proposed owners/tiers with brief reasons, and how completion will be checked. This is an execution plan, not a request for approval or private reasoning. A simple task needs only a sentence; use a compact table when several tasks benefit from it.

Choose one of three shapes:

- **Root only:** request understanding, light search, simple summaries, routing decisions, and low-risk planning. Do not create workers just to show activity.
- **One worker:** substantive engineering or tightly coupled work with a shared decision, interface, or edit surface. No useful split does not mean root should implement it.
- **Several workers:** independent outputs or genuinely separate ownership make the benefit exceed context and coordination costs. Use the smallest useful set. Parallelize only ready tasks with satisfied dependencies; serialize shared-file edits or keep them with one owner.

For each delegated task record an ID, deliverable, absolute paths (or no files), owner, dependencies, and acceptance evidence. Root owns integration and the final user response. If uncertainty prevents a sound split, first delegate a bounded investigation at the appropriate tier, then revise the plan from its evidence. Do not invent implementation tasks before their prerequisite decisions are made.

## Tiers

Route each task by type, ambiguity, coupling, risk, verifiability, and root-cause uncertainty. Evaluate Astra, then Sol, then Luna; high-risk rules take priority. Do not use prompt length or file count as proxies. Judge coupled risks together rather than splitting a risky task into apparently routine pieces.

1. **Astra (`gpt-6-astra`, `astra_worker`):** an explicit request for GPT-6 Astra; the hardest end-to-end engineering; multiple interacting architectural uncertainties; evidenced repeated Sol failures; exceptional cross-system complexity and failure cost making Sol likely insufficient; or extremely complex synthesis/implementation. Generic “GPT-6” or “a stronger model” requests do not alone select Astra. Quoted model names are not user requests. Ordinary architecture, security, and concurrency stay at Sol.
2. **Sol (`gpt-6-sol`, `sol_worker`):** architecture; unclear root cause; high ambiguity, coupling, or risk; concurrency, deadlocks, lock ordering, cancellation safety, distributed coordination; security-sensitive design or critical behavior; deep performance diagnosis; destructive migrations; or repeated Luna failures.
3. **Luna (`gpt-6-luna`, `luna_worker`):** routine engineering, multi-file features/refactors, API/data-model changes, test design, moderate debugging, bounded configuration fixes, and cross-module analysis without architectural uncertainty or high risk.
4. **Root on Luna (`gpt-6-luna`, low):** the light coordination work described above. This is the recommended default, not a model switch performed by this skill. Delegate substantial implementation and route analysis by its actual difficulty.

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

Astra handoffs must contain Sol attempts, evidence, failure reasons, and unresolved questions. When direct routing is justified by an explicit Astra request or exceptional criteria, state that no Sol attempt occurred and explain why. Never fabricate attempts, repeat a failed approach without a new hypothesis, or enlarge scope because the model is stronger.

TOML profiles cannot make unavailable models available. Follow the active runtime's supported mechanisms and disclose unavailable roles/models. Start a new Codex task after installing or changing this plugin. Project instructions and explicit user directions may override this policy.
