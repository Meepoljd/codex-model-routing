from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tomllib
from unittest import mock
import unittest

import model_router
from model_router import (
    RoutingError,
    discover_catalog,
    refresh,
    routing_lock,
    select_models,
    transactional_write,
)


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "installer.py"


def item(
    model: str,
    efforts: tuple[str, ...] = ("low", "medium", "high"),
    **extra: object,
) -> dict[str, object]:
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


def catalog(*models: dict[str, object]) -> list[object]:
    return list(models) or [
        item("gpt-6-luna"),
        item("gpt-6.1-sol"),
        item("gpt-6-astra"),
    ]


def install_temp(home: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(INSTALLER),
            "--codex-home",
            str(home),
            "--no-refresh",
            "--schedule",
            "disable",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stderr)


class SelectionTest(unittest.TestCase):
    def test_semantic_numeric_versions_are_selected(self):
        selected = select_models(
            catalog(
                item("gpt-6.9-luna"),
                item("gpt-6.10-luna"),
                item("gpt-6.9-sol"),
                item("gpt-6.10-sol"),
                item("gpt-6.9-astra"),
                item("gpt-6.10-astra"),
            )
        )
        self.assertEqual(selected["luna_worker"]["model"], "gpt-6.10-luna")
        self.assertEqual(selected["sol_worker"]["model"], "gpt-6.10-sol")
        self.assertEqual(selected["astra_worker"]["model"], "gpt-6.10-astra")

    def test_hidden_special_unknown_and_explicitly_tool_disabled_are_rejected(self):
        selected = select_models(
            catalog(
                item("gpt-9-luna", hidden=True),
                item("gpt-8-luna", modelSpecialty="auto-review"),
                item("gpt-7-luna", supportsTools=False),
                item("gpt-99-orbit"),
                item("gpt-6-luna"),
                item("gpt-6-sol"),
                item("gpt-6-astra"),
            )
        )
        self.assertEqual(selected["luna_worker"]["model"], "gpt-6-luna")

    def test_required_effort_is_enforced(self):
        with self.assertRaisesRegex(RoutingError, "sol model supporting high"):
            select_models(
                catalog(
                    item("gpt-6-luna"),
                    item("gpt-6-sol", ("low", "medium")),
                    item("gpt-6-astra"),
                )
            )

    def test_empty_and_malformed_catalogs_fail_closed(self):
        with self.assertRaises(RoutingError):
            select_models([])
        malformed = item("gpt-6-luna")
        malformed.pop("hidden")
        with self.assertRaisesRegex(RoutingError, "missing required fields"):
            select_models([malformed])


class RefreshTest(unittest.TestCase):
    def test_catalog_failure_preserves_last_good_files_and_state(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            install_temp(home)
            refresh(home, ROOT / "agents", catalog=catalog())
            before_state = (home / "model-routing/state.json").read_text()
            before_profiles = {
                path.name: path.read_text() for path in (home / "agents").glob("*.toml")
            }
            with self.assertRaises(RoutingError):
                refresh(home, ROOT / "agents", catalog=[])
            self.assertEqual((home / "model-routing/state.json").read_text(), before_state)
            self.assertEqual(
                {path.name: path.read_text() for path in (home / "agents").glob("*.toml")},
                before_profiles,
            )

    def test_rpc_failure_preserves_last_good_state(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            install_temp(home)
            before = (home / "model-routing/state.json").read_text()
            with mock.patch(
                "model_router.discover_catalog", side_effect=RoutingError("offline")
            ):
                with self.assertRaisesRegex(RoutingError, "offline"):
                    refresh(home, ROOT / "agents")
            self.assertEqual((home / "model-routing/state.json").read_text(), before)

    def test_fresh_last_good_state_honors_ttl_without_catalog_call(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            install_temp(home)
            expected = refresh(home, ROOT / "agents", catalog=catalog())
            with mock.patch("model_router.discover_catalog") as discover:
                actual = refresh(home, ROOT / "agents", if_stale=True)
            discover.assert_not_called()
            self.assertEqual(actual["lastSuccessAt"], expected["lastSuccessAt"])

    def test_user_modified_profile_stays_unmanaged_across_refreshes(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            install_temp(home)
            luna = home / "agents/luna_worker.toml"
            custom = luna.read_text().replace('model = "gpt-6-luna"', 'model = "custom-luna"')
            luna.write_text(custom)
            first = refresh(home, ROOT / "agents", catalog=catalog())
            self.assertFalse(first["managedProfiles"]["luna_worker"]["managed"])
            self.assertEqual(first["activeProfiles"]["luna_worker"]["model"], "custom-luna")
            refresh(
                home,
                ROOT / "agents",
                catalog=catalog(
                    item("gpt-7-luna"), item("gpt-7-sol"), item("gpt-7-astra")
                ),
            )
            self.assertEqual(luna.read_text(), custom)

    def test_preexisting_custom_profile_is_never_adopted(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            (home / "agents").mkdir(parents=True)
            custom = 'name = "sol_worker"\nmodel = "custom-sol"\nmodel_reasoning_effort = "high"\n'
            (home / "agents/sol_worker.toml").write_text(custom)
            install_temp(home)
            refresh(home, ROOT / "agents", catalog=catalog())
            refresh(
                home,
                ROOT / "agents",
                catalog=catalog(item("gpt-7-luna"), item("gpt-7-sol"), item("gpt-7-astra")),
            )
            self.assertEqual((home / "agents/sol_worker.toml").read_text(), custom)

    def test_user_root_change_ends_management_permanently(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            install_temp(home)
            config = home / "config.toml"
            edited = config.read_text().replace('model = "gpt-6-luna"', 'model = "gpt-6-astra"')
            config.write_text(edited)
            first = refresh(home, ROOT / "agents", catalog=catalog())
            self.assertFalse(first["managedRoot"]["managed"])
            self.assertNotIn("managed-root", config.read_text())
            refresh(
                home,
                ROOT / "agents",
                catalog=catalog(item("gpt-7-luna"), item("gpt-7-sol"), item("gpt-7-astra")),
            )
            self.assertEqual(tomllib.loads(config.read_text())["model"], "gpt-6-astra")

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
            result = {"data": [{"model":"gpt-6-luna","hidden":False,"modelSpecialty":None,"supportedReasoningEfforts":[{"reasoningEffort":"low","description":""},{"reasoningEffort":"medium","description":""}]}], "nextCursor":"page-2"}
        else:
            result = {"data": [{"model":"gpt-6-sol","hidden":False,"modelSpecialty":None,"supportedReasoningEfforts":[{"reasoningEffort":"high","description":""}]},{"model":"gpt-6-astra","hidden":False,"modelSpecialty":None,"supportedReasoningEfforts":[{"reasoningEffort":"high","description":""}]}], "nextCursor":None}
    print(json.dumps({"jsonrpc":"2.0","id":request["id"],"result":result}), flush=True)
''',
                encoding="utf-8",
            )
            result = discover_catalog([sys.executable, str(script), str(log)], timeout=2)
            self.assertEqual(len(result), 3)
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
