from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "installer.py"


def run(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(INSTALLER),
            "--codex-home",
            str(home),
            "--no-refresh",
            "--schedule",
            "disable",
            *args,
        ],
        text=True,
        capture_output=True,
        check=False,
    )


class InstallerIntegrationTest(unittest.TestCase):
    def test_fresh_install_is_self_contained_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            first = run(home)
            self.assertEqual(first.returncode, 0, first.stderr)
            config = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
            self.assertEqual(config["model"], "gpt-6-luna")
            self.assertEqual(config["model_reasoning_effort"], "low")
            self.assertTrue(config["agents"]["enabled"])
            self.assertTrue((home / "model-routing" / "model_router.py").is_file())
            self.assertTrue((home / "model-routing" / "templates" / "sol_worker.toml").is_file())
            service = (home / "model-routing/systemd/codex-model-routing.service").read_text()
            self.assertIn(str(home / "model-routing/model_router.py"), service)
            self.assertNotIn(str(ROOT), service)
            state_before = (home / "model-routing/state.json").read_text(encoding="utf-8")

            second = run(home)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("Installed: no changes", second.stdout)
            self.assertEqual((home / "model-routing/state.json").read_text(encoding="utf-8"), state_before)

    def test_packaged_workers_are_three_dynamic_roles_and_plugin_copy_matches(self):
        expected = {
            "luna_worker.toml": ("gpt-6-luna", "medium"),
            "sol_worker.toml": ("gpt-6.1-sol", "high"),
            "astra_worker.toml": ("gpt-6-astra", "high"),
        }
        self.assertEqual({path.name for path in (ROOT / "agents").glob("*.toml")}, set(expected))
        for filename, values in expected.items():
            root_text = (ROOT / "agents" / filename).read_text(encoding="utf-8")
            self.assertEqual(root_text, (ROOT / "plugin/agents" / filename).read_text(encoding="utf-8"))
            worker = tomllib.loads(root_text)
            self.assertEqual((worker["model"], worker["model_reasoning_effort"]), values)

    def test_existing_root_pin_and_unrelated_config_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            home.mkdir()
            original = '''# keep
model = "gpt-6-astra" # explicit
model_reasoning_effort = "low"
note = """[agents] is text
and remains text"""

[plugins.example]
enabled = false
'''
            (home / "config.toml").write_text(original, encoding="utf-8")
            result = run(home)
            self.assertEqual(result.returncode, 0, result.stderr)
            merged = (home / "config.toml").read_text(encoding="utf-8")
            self.assertIn('model = "gpt-6-astra" # explicit', merged)
            self.assertIn('model_reasoning_effort = "low"', merged)
            self.assertIn('[plugins.example]\nenabled = false', merged)
            state = json.loads((home / "model-routing/state.json").read_text())
            self.assertFalse(state["managedRoot"]["managed"])

    def test_custom_profiles_and_agents_content_survive_install_and_uninstall(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            (home / "agents").mkdir(parents=True)
            custom = 'name = "luna_worker"\nmodel = "my-model"\nmodel_reasoning_effort = "high"\n'
            (home / "agents/luna_worker.toml").write_text(custom, encoding="utf-8")
            (home / "AGENTS.md").write_text(
                "# Mine\n\nkeep before\n\n## Model Routing Policy\nold\n\n## Other\nkeep after\n",
                encoding="utf-8",
            )
            installed = run(home)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            self.assertEqual((home / "agents/luna_worker.toml").read_text(), custom)
            document = (home / "AGENTS.md").read_text()
            self.assertIn("keep before", document)
            self.assertIn("## Other\nkeep after", document)
            self.assertEqual(document.count("<!-- codex-model-routing:begin -->"), 1)

            removed = run(home, "--uninstall")
            self.assertEqual(removed.returncode, 0, removed.stderr)
            self.assertEqual((home / "agents/luna_worker.toml").read_text(), custom)
            self.assertNotIn("codex-model-routing:begin", (home / "AGENTS.md").read_text())

    def test_malformed_config_is_non_destructive(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            home.mkdir()
            malformed = 'model = "missing end\n'
            (home / "config.toml").write_text(malformed, encoding="utf-8")
            (home / "AGENTS.md").write_text("# Existing\n", encoding="utf-8")
            result = run(home)
            self.assertEqual(result.returncode, 2)
            self.assertEqual((home / "config.toml").read_text(), malformed)
            self.assertEqual((home / "AGENTS.md").read_text(), "# Existing\n")
            self.assertFalse((home / "agents").exists())

    def test_dry_run_has_no_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            result = run(home, "--dry-run")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(home.exists())

    def test_symlinked_runtime_is_rejected_without_touching_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / ".codex"
            outside = root / "outside"
            home.mkdir()
            outside.mkdir()
            (home / "model-routing").symlink_to(outside, target_is_directory=True)
            result = run(home)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(list(outside.iterdir()), [])

    def test_custom_legacy_named_profile_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            (home / "agents").mkdir(parents=True)
            custom = 'name = "spark_worker"\nmodel = "custom"\n'
            (home / "agents/spark_worker.toml").write_text(custom, encoding="utf-8")
            result = run(home)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((home / "agents/spark_worker.toml").read_text(), custom)
            self.assertIn("preserved custom legacy-named profile", result.stderr)

    def test_exact_repository_legacy_profiles_are_backed_up_and_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            (home / "agents").mkdir(parents=True)
            for role in ("spark", "terra"):
                fixture = ROOT / f"tests/fixtures/legacy_{role}_worker.toml"
                (home / f"agents/{role}_worker.toml").write_text(fixture.read_text())
            result = run(home)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((home / "agents/spark_worker.toml").exists())
            self.assertFalse((home / "agents/terra_worker.toml").exists())
            backups = list((home / "backups").glob("model-routing-refresh-*"))
            self.assertTrue(backups)
            self.assertTrue(any((backup / "agents/spark_worker.toml").is_file() for backup in backups))

    def test_uninstall_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            self.assertEqual(run(home).returncode, 0)
            first = run(home, "--uninstall")
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertFalse((home / "config.toml").exists())
            self.assertFalse((home / "AGENTS.md").exists())
            self.assertFalse((home / "model-routing").exists())
            second = run(home, "--uninstall")
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("no changes", second.stdout)


if __name__ == "__main__":
    unittest.main()
