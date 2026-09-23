# Worker visibility: capabilities and limits

Checked on 2026-09-23. Tool names and UI controls vary by Codex version and host; inspect the current tool schema before using examples.

## Main conversation

The portable design is worker milestone messages plus root commentary. Report task ID, observed status, result/evidence, and next step. For example:

```text
T1 / phase complete: traced the retry path to src/client.ts:84.
Evidence: the same request ID reaches both callbacks.
Next: inspect cancellation ownership; no edits yet.
```

This communicates an observable finding and action, not private chain-of-thought. Workers should report milestones and blockers without flooding the parent with every command. Root attributes and summarizes messages; it must not claim a tool command or check ran unless evidence supports it.

## Current collaboration surface

The environment used to review this plugin exposes these capabilities. They are evidence for this workflow, not APIs bundled or implemented by the plugin:

| Tool | Documented behavior | Consequence |
| --- | --- | --- |
| `spawn_agent` | Creates a child using a role and returns an agent/task reference | Record the reference; a written plan alone creates nothing |
| `send_message` | Queues a message to an existing agent; does not start a new turn | Workers can report milestones to root; delivery may wait for a message boundary or tool completion |
| `followup_task` | Sends work to an existing worker and starts a turn if idle | Use for related missing work rather than creating a duplicate |
| `wait_agent` | Wakes for a mailbox update, completion notification, user input, or timeout; returns a summary rather than message content | Read delivered messages and final results; a wakeup is not task success |
| `list_agents` | Lists agents and current status | Status inspection does not expose the complete tool transcript |
| `interrupt_agent` | Interrupts the current turn; agent remains available | Use to apply a necessary stop or redirection, not as a progress probe |

This review used worker-to-root `send_message` calls. It did not test all tools or every client UI. The exposed collaboration schema has no option to force all worker tool calls, results, or private reasoning into root commentary. No host-wide guarantee about delivery latency follows from milestone reporting.

## Inspecting more detail

Supported Codex clients expose worker threads; the CLI provides `/agent` to inspect and switch threads. Which controls and details appear depends on the client/version. See the official [Subagents documentation](https://learn.chatgpt.com/docs/agent-configuration/subagents).

A separate integration could use the **Agents API** event stream and saved history. Its documentation describes subagent creation and coordination events, warns that coordination items can omit message text, and says the stream is not a full transcript. This plugin does not implement that integration, and an API event stream must not be presented as a local Codex plugin feature. See [Agents API multi-agent observation](https://developers.openai.com/api/docs/guides/agents-api/multi-agent#observe-delegation).

More detailed UI or exported logs would require separately scoped host/API work. Thread messages, available tool records, and published summaries do not provide the model's full private reasoning.
