# Codex Radar Adaptive Routing Plugin

[中文](README.md)

The plugin installs `routine_worker`, `complex_worker`, and `frontier_worker` profiles. It combines the native logged-in `model/list` catalog with [Codex Radar](https://codexradar.com/) evidence across model families. Routine selects the lowest score at least 70% of the best quality score, complex the lowest at least 90%, and frontier the best score. Current RadarBench accepts only complete model/effort points sharing one binding fingerprint and requires at least three complete candidates; an unmeasured new model does not block other complete points. It falls back only when necessary to the legacy schema-2 equal/latest snapshot, with 30 samples, 14-day source freshness, and 30-day point freshness. This is a heuristic, not an official capability certification.

Default selection permits low, medium, and high effort only. It never automatically promotes to xhigh, max, or ultra. Reliable cost ranking also requires 30 usable cost samples; when samples are zero, the policy is quality-only and makes no cheapest-model claim. Explicit `gpt6`, `gpt-6`, `GPT-6`, and `GPT-6 Astra` request `gpt-6-astra` directly; they do not select the dynamic frontier profile.

```bash
bash install.sh
python3 ~/.codex/model-routing/model_router.py --codex-home ~/.codex status
python3 ~/.codex/model-routing/model_router.py --codex-home ~/.codex refresh
```

Status records selection, active profiles, evidence/freshness, and current or degraded refresh status. Failure keeps the last-good profiles. The installed runtime includes its Radar dependency and needs no checkout. Existing root settings are pins; custom old profiles are preserved, while proven managed legacy roles are backed up and migrated away. Start a new Codex task after refresh.
