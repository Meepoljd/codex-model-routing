from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import time
import tomllib
from unittest import mock
import unittest

import model_router
from model_router import (
    DEFAULT_ALLOWED_EFFORTS,
    ROLES,
    RoutingError,
    discover_catalog,
    normalize_catalog,
    read_state,
    refresh,
    routing_lock,
    select_models,
    transactional_write,
)
from radar_source import RadarSourceError


def item(model: str, efforts: tuple[str, ...] = ("low", "medium", "high"), **extra: object) -> dict[str, object]:
    result: dict[str, object] = {
        "id": model,
        "model": model,
        "hidden": False,
        "modelSpecialty": None,
        "supportedReasoningEfforts": [
            {"reasoningEffort": effort, "description": effort} for effort in efforts
        ],
    }
    result.update(extra)
    return result


def evidence(*points: tuple[str, str, float], costs: dict[tuple[str, str], tuple[float, int]] | None = None):
    result = []
    for model, effort, quality in points:
        cost, samples = (costs or {}).get((model, effort), (None, 0))
        result.append(
            {
                "model": model,
                "effort": effort,
                "quality": quality,
                "sampleCount": 100,
                "costUsd": cost,
                "costSamples": samples,
            }
        )
    return {
        "sourceKind": "injected-test",
        "sourceUrl": "injected://fixture",
        "sourceUpdatedAt": "2026-10-08T00:00:00+00:00",
        "fetchedAt": "2026-10-08T00:00:00+00:00",
        "fingerprint": "fixture",
        "qualityScale": 100,
        "points": result,
    }


def make_install(home: Path, *, version: int = 1) -> Path:
    (home / "model-routing").mkdir(parents=True)
    (home / "agents").mkdir()
    state = {
        "version": version,
        "managedProfiles": {role: {"managed": True} for role in ROLES},
        "managedRoot": {"managed": False},
    }
    (home / "model-routing/state.json").write_text(json.dumps(state), encoding="utf-8")
    templates = home / "templates"
    templates.mkdir()
    for role in ROLES:
        (templates / f"{role}.toml").write_text(
            f'name = "{role}"\nmodel = "placeholder"\nmodel_reasoning_effort = "low"\n',
            encoding="utf-8",
        )
    return templates


class SelectionTest(unittest.TestCase):
    def test_unknown_model_names_are_ranked_without_family_or_version_rules(self):
        selected = select_models(
            [
                item("acme-nebula", ("high",)),
                item("model_2027/orbit", ("medium",)),
                item("future:quark", ("low",)),
            ],
            evidence=evidence(
                ("acme-nebula", "high", 100),
                ("model_2027/orbit", "medium", 91),
                ("future:quark", "low", 70),
            ),
        )
        self.assertEqual(selected["routine_worker"], {"model": "future:quark", "effort": "low"})
        self.assertEqual(selected["simple_worker"], {"model": "future:quark", "effort": "low"})
        self.assertEqual(selected["complex_worker"], {"model": "model_2027/orbit", "effort": "medium"})
        self.assertEqual(selected["frontier_worker"], {"model": "acme-nebula", "effort": "high"})
        self.assertEqual(selected["root"], selected["routine_worker"])

    def test_roles_can_share_one_model_at_different_efforts(self):
        selected = select_models(
            [item("brand-new-model")],
            evidence=evidence(
                ("brand-new-model", "low", 70),
                ("brand-new-model", "medium", 92),
                ("brand-new-model", "high", 100),
            ),
        )
        self.assertEqual([selected[role]["model"] for role in ROLES], ["brand-new-model"] * 4)
        self.assertEqual([selected[role]["effort"] for role in ROLES], ["low", "low", "medium", "high"])

    def test_simple_uses_lowest_quality_meeting_40_percent_floor(self):
        selected = select_models(
            [item("simple", ("low",)), item("routine", ("medium",)), item("frontier", ("high",))],
            evidence=evidence(
                ("simple", "low", 40),
                ("routine", "medium", 70),
                ("frontier", "high", 100),
            ),
        )
        self.assertEqual(selected["simple_worker"], {"model": "simple", "effort": "low"})
        self.assertEqual(selected["routine_worker"], {"model": "routine", "effort": "medium"})
        self.assertEqual(selected["root"], selected["routine_worker"])

    def test_default_policy_never_automatically_selects_xhigh_max_or_ultra(self):
        selected = select_models(
            [item("future-one", ("low", "high", "xhigh", "max", "ultra"))],
            evidence=evidence(
                ("future-one", "low", 70),
                ("future-one", "high", 90),
                ("future-one", "ultra", 150),
            ),
        )
        self.assertNotIn("ultra", {choice["effort"] for choice in selected.values()})
        self.assertEqual(DEFAULT_ALLOWED_EFFORTS, {"low", "medium", "high"})

    def test_hidden_special_and_explicitly_tool_disabled_models_are_rejected(self):
        candidates = normalize_catalog(
            [
                item("hidden-model", hidden=True),
                item("special-model", modelSpecialty="auto-review"),
                item("flagged-special", special=True),
                item("no-tools", supportsTools=False),
                item("capability-no-tools", capabilities={"tools": False}),
                item("eligible-model"),
            ]
        )
        self.assertEqual([candidate.model for candidate in candidates], ["eligible-model"])

    def test_missing_tool_capability_field_is_not_treated_as_false(self):
        self.assertEqual(normalize_catalog([item("model-with-unspecified-tools")])[0].model, "model-with-unspecified-tools")

    def test_unsafe_tokens_and_malformed_catalogs_fail_closed(self):
        with self.assertRaisesRegex(RoutingError, "invalid model token"):
            normalize_catalog([item('bad"\nmodel')])
        malformed = item("valid-model")
        malformed.pop("hidden")
        with self.assertRaisesRegex(RoutingError, "missing required fields"):
            normalize_catalog([malformed])

    def test_removed_model_and_unsupported_effort_cannot_be_selected(self):
        selected = select_models(
            [item("remaining")],
            evidence=evidence(
                ("removed", "high", 100),
                ("remaining", "ultra", 120),
                ("remaining", "low", 80),
            ),
        )
        self.assertTrue(all(choice == {"model": "remaining", "effort": "low"} for choice in selected.values()))

    def test_verified_cost_can_choose_within_quality_floor(self):
        selected = select_models(
            [item("quality-leader", ("high",)), item("cheap-qualified", ("medium",))],
            evidence=evidence(
                ("quality-leader", "high", 100),
                ("cheap-qualified", "medium", 92),
                costs={("quality-leader", "high"): (8.0, 100), ("cheap-qualified", "medium"): (1.0, 100)},
            ),
        )
        self.assertEqual(selected["complex_worker"]["model"], "cheap-qualified")
        self.assertEqual(selected["frontier_worker"]["model"], "quality-leader")


class RefreshTest(unittest.TestCase):
    def test_v1_state_refreshes_to_v2_with_evidence_and_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            templates = make_install(home, version=1)
            result = refresh(
                home,
                templates,
                catalog=[item("one", ("low",)), item("two", ("medium",)), item("three", ("high",))],
                evidence=evidence(("one", "low", 70), ("two", "medium", 91), ("three", "high", 100)),
            )
            self.assertEqual(result["version"], 2)
            self.assertEqual(result["refreshStatus"]["status"], "current")
            self.assertEqual(result["evidence"]["thresholds"]["allowedEfforts"], ["low", "medium", "high"])
            self.assertEqual(tomllib.loads((home / "agents/routine_worker.toml").read_text())["model"], "one")
            self.assertEqual(read_state(home)["catalogSelection"]["frontier_worker"]["model"], "three")

    def test_source_outage_records_degraded_and_preserves_last_good_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            templates = make_install(home)
            catalog = [item("one", ("low",)), item("two", ("high",))]
            first = refresh(home, templates, catalog=catalog, evidence=evidence(("one", "low", 70), ("two", "high", 100)))
            profiles_before = {path.name: path.read_text() for path in (home / "agents").glob("*.toml")}

            class Offline:
                def load(self, candidates):
                    raise RadarSourceError("offline")

            with self.assertRaisesRegex(RoutingError, "offline"):
                refresh(home, templates, catalog=catalog, radar=Offline())
            after = read_state(home)
            self.assertEqual(after["catalogSelection"], first["catalogSelection"])
            self.assertEqual(after["evidence"], first["evidence"])
            self.assertEqual(after["lastSuccessAt"], first["lastSuccessAt"])
            self.assertEqual(after["refreshStatus"]["status"], "degraded")
            self.assertEqual({path.name: path.read_text() for path in (home / "agents").glob("*.toml")}, profiles_before)

    def test_fresh_state_honors_ttl_without_catalog_call(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            templates = make_install(home)
            expected = refresh(home, templates, catalog=[item("one", ("low",))], evidence=evidence(("one", "low", 100)))
            with mock.patch("model_router.discover_catalog") as discover:
                actual = refresh(home, templates, if_stale=True)
            discover.assert_not_called()
            self.assertEqual(actual["lastSuccessAt"], expected["lastSuccessAt"])

    def test_user_modified_profile_stays_unmanaged_across_refreshes(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            templates = make_install(home)
            refresh(home, templates, catalog=[item("one", ("low",))], evidence=evidence(("one", "low", 100)))
            target = home / "agents/routine_worker.toml"
            custom = target.read_text().replace('model = "one"', 'model = "my-custom-model"')
            target.write_text(custom)
            first = refresh(home, templates, catalog=[item("two", ("low",))], evidence=evidence(("two", "low", 100)))
            self.assertFalse(first["managedProfiles"]["routine_worker"]["managed"])
            refresh(home, templates, catalog=[item("three", ("low",))], evidence=evidence(("three", "low", 100)))
            self.assertEqual(target.read_text(), custom)

    def test_explicit_root_pin_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            templates = make_install(home)
            config = home / "config.toml"
            config.write_text('model = "explicit-user-model"\nmodel_reasoning_effort = "low"\n')
            refresh(home, templates, catalog=[item("dynamic", ("low",))], evidence=evidence(("dynamic", "low", 100)))
            self.assertEqual(tomllib.loads(config.read_text())["model"], "explicit-user-model")

    def test_transaction_rolls_back_partial_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            first, second = home / "a", home / "b"
            first.write_text("old-a")
            second.write_text("old-b")
            real_atomic = model_router.atomic_write

            def fail_second(path: Path, content: str) -> None:
                if path == second and content == "new-b":
                    raise OSError("injected")
                real_atomic(path, content)

            with mock.patch("model_router.atomic_write", side_effect=fail_second):
                with self.assertRaisesRegex(OSError, "injected"):
                    transactional_write(home, {first: "new-a", second: "new-b"})
            self.assertEqual(first.read_text(), "old-a")
            self.assertEqual(second.read_text(), "old-b")

    def test_concurrent_lock_attempt_times_out(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with routing_lock(home):
                with self.assertRaisesRegex(RoutingError, "holds the lock"):
                    with routing_lock(home, timeout=0.05):
                        pass


class RpcTest(unittest.TestCase):
    def test_pagination_uses_cursor_and_collects_all_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "fake_server.py"
            log = root / "requests.jsonl"
            script.write_text(
                '''import json, sys
log = sys.argv[1]
for line in sys.stdin:
    request = json.loads(line)
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(request) + "\\n")
    if "id" not in request:
        continue
    if request["method"] == "initialize":
        result = {"ok": True}
    else:
        cursor = request["params"].get("cursor")
        if cursor is None:
            result = {"data": [{"model":"unknown-alpha","hidden":False,"modelSpecialty":None,"supportedReasoningEfforts":[{"reasoningEffort":"low","description":""}]}], "nextCursor":"page-2"}
        else:
            result = {"data": [{"model":"unknown-beta","hidden":False,"modelSpecialty":None,"supportedReasoningEfforts":[{"reasoningEffort":"high","description":""}]}], "nextCursor":None}
    print(json.dumps({"jsonrpc":"2.0","id":request["id"],"result":result}), flush=True)
''',
                encoding="utf-8",
            )
            result = discover_catalog([sys.executable, str(script), str(log)], timeout=2)
            self.assertEqual(len(result), 2)
            requests = [json.loads(line) for line in log.read_text().splitlines()]
            pages = [request for request in requests if request.get("method") == "model/list"]
            self.assertTrue(pages[0]["params"]["includeHidden"])
            self.assertNotIn("cursor", pages[0]["params"])
            self.assertEqual(pages[1]["params"]["cursor"], "page-2")

    def test_initialize_timeout_cleans_up_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "hanging_server.py"
            pid_file = root / "pid"
            script.write_text(
                '''import os, sys, time
open(sys.argv[1], "w").write(str(os.getpid()))
sys.stdin.readline()
time.sleep(60)
''',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RoutingError, "timed out"):
                discover_catalog([sys.executable, str(script), str(pid_file)], timeout=0.1)
            pid = int(pid_file.read_text())
            for _ in range(20):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.02)
            else:
                self.fail("timed-out app-server process was not reaped")


if __name__ == "__main__":
    unittest.main()
