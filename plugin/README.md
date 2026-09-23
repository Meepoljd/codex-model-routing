# Model Routing for Codex

Installable Codex plugin that packages a task-aware model routing policy and Luna, Sol, and Astra worker profiles. The skill explains when to use each tier and how to delegate using Codex native agents.

## One-command install

From this directory:

```bash
./install.sh
```

The script registers this directory as a local Codex plugin marketplace, installs `model-routing`, and copies the three worker profiles into `~/.codex/agents/`. Existing profiles with the same names are backed up before replacement. It does not replace `~/.codex/AGENTS.md`; the installed skill is the portable policy source. Start a new Codex task after installation.

## Manual marketplace install

```bash
codex plugin marketplace add /absolute/path/to/model-routing-plugin
codex plugin add model-routing@model-routing
```

Use `$model-routing` to invoke the routing skill explicitly. Codex can also discover it when a request concerns model choice or delegation.

## Uninstall

```bash
./uninstall.sh
```

Uninstall removes the plugin and marketplace registration and restores worker files backed up by the installer. If a worker file did not exist before installation, it is removed. Backups are kept under `~/.codex/backups/model-routing-plugin-<timestamp>/`.

## Scope and compatibility

This plugin provides policy and worker profiles; it does not force the root model, alter active sessions, or create model availability. Worker model IDs must be supported by the user's Codex runtime. Install/upgrade and then start a new task for Codex to load the profiles and skill.
