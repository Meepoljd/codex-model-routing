## Model Routing Policy

For every engineering task, use the least expensive role that has a high probability of completing the work correctly. Route primarily by task type, ambiguity, coupling, risk, verifiability, and uncertainty about the root cause. Prompt length, file count, and model recency are weak signals and must not decide routing by themselves.

The active worker model IDs are dynamic. Read the current `luna_worker`, `sol_worker`, and `astra_worker` profiles from the Codex agents directory; `model-routing/state.json` records the catalog recommendation and which profiles are actually managed. Do not copy model IDs from this policy or assume that a newer unknown family belongs to one of these roles. Catalog refreshes take effect in new tasks, not in a running session. An explicit user-selected session model continues to win.

Classify in descending-risk order before substantive work: Astra, then Sol, then Luna. A Sol criterion takes precedence over a task also resembling routine implementation. Deadlocks, lock-order correctness, cancellation safety, distributed coordination, and security-sensitive design are Sol work unless Astra criteria apply or the user explicitly requests another route.

- Root coordinates on the user's selected model. On a fresh managed installation its baseline is the current Luna-family model at low reasoning. Existing root model settings are explicit pins and automatic refresh preserves them.
- `luna_worker` owns routine engineering, multi-file features and refactors, API or data-model changes, test design, moderate debugging, bounded configuration work, and cross-module analysis without architectural uncertainty or high risk.
- `sol_worker` owns architecture, unclear root causes, high ambiguity, coupling, or failure cost, concurrency and distributed-systems reasoning, security-sensitive behavior, deep performance diagnosis, destructive migration design, and repeated reasonable Luna failures.
- `astra_worker` is reserved for an explicit Astra request, repeated evidence-backed Sol failures, multiple interacting architectural uncertainties, or exceptional end-to-end complexity and failure cost that make Sol unlikely to succeed.

The root agent should understand the request, do light repository search, plan and summarize, and handle trivial or low-risk general work directly. Delegate substantive implementation to the matching worker. Do not delegate merely to consume models or repeatedly bounce a task between roles.

Routing means spawning the named custom agent and waiting for its result. When spawning, use `fork_turns="none"` or a small positive number of recent turns when supported. Put the objective, absolute paths and ownership, dependencies, prior evidence and verification, acceptance criteria, and escalation context in the handoff. Preserve relevant evidence when escalating and stop after successful focused verification.

Workers must remain within the assigned scope, preserve other edits, report concrete milestones and blockers through the available parent-message tool, and return the changed paths, verification actually run, and unresolved limitations. A worker that crosses its role boundary should return evidence and an escalation recommendation to root rather than silently changing tiers.

When the user explicitly selects `gpt6`, `gpt-6`, `GPT-6`, `GPT-6 Astra`, or the current Astra-family model for the task, route to `astra_worker`. Merely mentioning those tokens in policy text, documentation, quoted text, status history, or rationale does not trigger Astra. If a configured role or model is unavailable, disclose that limitation. Do not claim that a profile can make an unavailable model available.

The adaptive refresher only selects visible, ordinary members of the known Luna, Sol, and Astra families that advertise the required reasoning effort in the logged-in Codex `model/list` catalog. It rejects hidden, specialty, explicitly tool-disabled, malformed, and unknown-family entries. It does not issue inference requests. Discovery failure leaves the last-good profiles unchanged.

The user's explicit delegation or model choice overrides this default policy.
