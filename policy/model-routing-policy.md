## Model Routing Policy

For every engineering task, use the least expensive model that has a high probability of completing the work correctly. Route primarily by task type, ambiguity, coupling, risk, verifiability, and uncertainty about the root cause. Prompt length and file count are weak signals and must not decide routing by themselves.

When routing, treat the aliases `gpt6`, `gpt-6`, `GPT-6`, and `GPT-6 Astra` as shorthand for model token `gpt-6-astra` and map those explicit requests to `astra_worker` with `model="gpt-6-astra"`. Mentioning GPT-6 in policy text, documentation, status history, or rationale does not itself trigger `astra_worker`.

Classify in descending-risk order before doing substantive work: first check the Astra escalation criteria, then Sol, then Terra, then Spark, and finally Luna. A Sol criterion takes precedence over the fact that a task is also multi-file or resembles ordinary debugging. Deadlocks, lock-order correctness, cancellation safety, distributed coordination, and security-sensitive design are Sol work unless the Astra escalation criteria apply or the user explicitly requests another route.

Configured policy:

- `root` (`Luna`) uses `gpt-5.6-luna` with `low` reasoning effort.
- `spark_worker` uses `gpt-5.3-codex-spark` with `low` reasoning effort.
- `terra_worker` uses `gpt-5.6-terra` with `medium` reasoning effort.
- `sol_worker` uses `gpt-5.6-sol` with `high` reasoning effort.
- `astra_worker` uses `gpt-6-astra` with `high` reasoning effort.

These are fixed worker defaults; there is no automatic xhigh/max/ultra escalation and no runtime override mechanism from documentation changes.
Changing docs does not alter an active session.
An explicit user-selected model continues to win over policy and should still be respected.

The root agent should normally run on Luna and acts as coordinator. Respect an explicitly selected session model; do not claim to change the running model through these instructions. It should understand the request, do lightweight repository exploration and search, gather enough context to classify the task, perform simple analysis and planning, summarize findings, and handle low-risk general or non-coding work directly. Do not delegate trivial work. For substantial implementation, delegate to the matching worker instead of doing the implementation in the root thread merely because it appears possible.

Delegate to `spark_worker` when implementation is bounded, deterministic, low-risk, loosely coupled, and easy to verify. Good fits include targeted edits, mechanical refactors or renames, lint and type fixes, known-cause bug fixes, straightforward tests, configuration changes, well-specified scripts, and code that follows an established pattern. A change may touch many files and still fit Spark when it is mechanical and verifiable.

Delegate to `terra_worker` for ordinary engineering work that needs broader context or multi-file reasoning: feature implementation, meaningful refactoring, API or data-model changes, test design, multi-step implementation, and non-trivial debugging. This applies to analysis-only requests too: when producing an engineering plan requires tracing interactions across multiple modules, the root must delegate that analysis to Terra rather than treating it as lightweight Luna planning. Escalate Spark work to Terra when verification fails unexpectedly, scope expands materially, substantial ambiguity appears, or several coupled modules must be understood.

Delegate to `sol_worker` only when the task itself clearly involves architectural decisions, an unclear root cause, high ambiguity or coupling, high failure cost, security-sensitive behavior, concurrency or distributed-systems reasoning, deep performance diagnosis, destructive migration design, or repeated failures at lower tiers. These are Sol tasks even when the user asks only for diagnosis, review, or a design recommendation and no code changes. The root must delegate clearly qualifying work instead of performing the hard reasoning itself. Escalate Terra work to Sol when repeated reasonable attempts fail or architectural uncertainty becomes the main problem.

Delegate to `astra_worker` (GPT-6 Astra, `gpt-6-astra`) for the hardest end-to-end engineering work: repeated evidence-backed Sol attempts have failed, multiple interacting architectural uncertainties remain, or unusually high failure cost and cross-system complexity make Sol unlikely to succeed. Explicit user selection of Astra also takes precedence. Ordinary security and concurrency work remains Sol work; neither prompt length nor the presence of a newer model justifies Astra. Preserve prior evidence and failed attempts when escalating. If `astra_worker` is not available in the current session, spawn a default agent with `model="gpt-6-astra"`, `reasoning_effort="high"`, and `fork_turns="none"`, supplying the same bounded scope and context. If the model is unavailable, report that limitation rather than silently claiming Astra routing.

Model identifiers and capabilities were checked against https://developers.openai.com/api/docs/models/gpt-6-astra on 2026-09-07. This routing hierarchy is a local cost/complexity policy, not an official price guarantee; use observed verification outcomes to reassess it.

Apply these operating rules:

- Routing means spawning the named custom agent and waiting for its result; describing a delegation without spawning does not count.
- When spawning a named custom agent, use `fork_turns="none"` or a small positive number of recent turns. A full-history fork inherits the parent agent type and cannot select a custom worker. Put all necessary repository paths, task scope, evidence, and prior verification into the spawn message.
- Do not delegate merely to consume models, and do not repeatedly bounce the same task between agents.
- Preserve relevant context during escalation. Tell the stronger worker what was inspected or changed, what was tried, the exact verification result, and why the lower tier stopped.
- Treat successful focused verification as a strong signal to stop escalating.
- If a worker reports that its boundary was crossed, reassess once and either handle a small coordination step in Luna or escalate to the next appropriate tier.
- The user's explicit request about whether to delegate or which worker to use overrides this default routing policy.
- Use the weakest model likely to succeed, not merely the weakest model available.
