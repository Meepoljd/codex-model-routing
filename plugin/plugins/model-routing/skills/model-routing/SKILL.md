---
name: model-routing
description: Choose the lowest-cost Codex model likely to complete the task correctly, then use native worker delegation when needed. Use for task planning, implementation, diagnosis, reviews, and any request to select or escalate a model.
---

# Model Routing

Route by task type, ambiguity, coupling, risk, verifiability, and root-cause uncertainty. Do not route by prompt length or file count alone. Evaluate tiers in this order: Astra, Sol, Luna. High-risk rules take priority over routine low-cost rules.

## Tiers

1. **Astra (`gpt-6-astra`, `astra_worker`)**: explicit request for GPT-6 Astra; hardest end-to-end engineering; multiple interacting architectural uncertainties; evidenced repeated Sol failures; exceptional cross-system complexity and failure cost that makes Sol likely insufficient; or extremely complex synthesis or implementation. A generic GPT-6 request is routed by task class to Sol or Luna. A mention in quoted text, a document, or policy is not a request. Ordinary architecture, security, and concurrency work stays at Sol. Prompt length, file count, and model recency are not escalation reasons.
2. **Sol (`gpt-6-sol`, `sol_worker`)**: architecture; unclear root cause; high ambiguity, coupling, or risk; concurrency, deadlocks, lock ordering, cancellation safety, distributed coordination; security-sensitive design or security-critical behavior; deep performance root-cause analysis; destructive migration design; or repeated Luna failures.
3. **Luna (`gpt-6-luna`, `luna_worker`)**: routine engineering; multi-file features/refactors; API or data-model changes; test design; moderate debugging; bounded configuration fixes; and cross-module analysis without architectural uncertainty or high risk.
4. **Root on Luna (`gpt-6-luna`, low)**: request understanding, light search, simple summaries, routing decisions, and low-risk planning. Substantial coding work should be delegated to a worker.

## Delegation rules

- Actually call native `spawn_agent` using the configured role (`luna_worker`, `sol_worker`, or `astra_worker`) and wait for the result with the native collaboration wait tool. Mentioning delegation is not enough.
- Use a no-history fork (`fork_turns="none"`) or the smallest useful recent context. Never use a full-history fork for a custom worker.
- The worker handoff must include absolute paths or explicitly say there are no files, scope and ownership, existing evidence, work and verification already done, expected result, and escalation context.
- Workers return evidence, edits, verification, unresolved questions, and escalation reasons. The root decides whether to escalate. Do not bounce the same work between agents.
- Do not delegate analysis-only tasks that belong to root. Preserve explicit user model and analysis-only instructions.
- Escalate to Astra only for its listed criteria. Include Sol attempts, evidence, failure reasons, and unresolved questions. If direct Astra routing applies, say no Sol attempt occurred and why. Never fabricate attempts or repeat a failed approach without a new hypothesis.
- Stop and recommend Sol if a Luna task becomes architectural, root cause remains unclear, concurrency/distributed or security-sensitive concerns appear, reasonable attempts repeatedly fail, or behavior impact is unclear.
- Do not mark a goal complete until the requested result and required work are actually finished.

## Model availability

The worker TOML profiles are defaults, not guarantees: Codex or the active runtime may not expose every model. If a configured model is unavailable, report that limitation and follow the runtime's supported routing mechanism without claiming the configured worker ran.

## Session lifecycle

Policy and TOML edits do not hot-switch the current session. Start a new Codex task after installing or changing this plugin. Project-specific instructions and explicit user directions may override this policy.
