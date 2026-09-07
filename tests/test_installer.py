from __future__ import annotations

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
        [sys.executable, str(INSTALLER), "--codex-home", str(home), *args],
        text=True,
        capture_output=True,
        check=False,
    )


class InstallerIntegrationTest(unittest.TestCase):
    def test_fresh_install_writes_only_portable_files(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            result = run(home)
            self.assertEqual(result.returncode, 0, result.stderr)
            config = (home / "config.toml").read_text(encoding="utf-8")
            self.assertIn('model = "gpt-5.6-luna"', config)
            self.assertIn('[agents]\nenabled = true', config)
            self.assertTrue((home / "AGENTS.md").is_file())
            self.assertTrue((home / "agents" / "astra_worker.toml").is_file())
            self.assertFalse((home / "projects").exists())

    def test_packaged_workers_have_documented_models_and_efforts(self):
        expected = {
            "spark_worker.toml": ("gpt-5.3-codex-spark", "low"),
            "terra_worker.toml": ("gpt-5.6-terra", "medium"),
            "sol_worker.toml": ("gpt-5.6-sol", "high"),
            "astra_worker.toml": ("gpt-6-astra", "high"),
        }
        for filename, (model, effort) in expected.items():
            worker = tomllib.loads((ROOT / "agents" / filename).read_text(encoding="utf-8"))
            self.assertEqual(worker["model"], model)
            self.assertEqual(worker["model_reasoning_effort"], effort)

    def test_merges_config_without_losing_unrelated_sections_comments_or_multiline_value(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            home.mkdir()
            original = '''# retain this comment
model = "custom" # local preference
model_reasoning_effort = "high"
note = """[agents] is text, not a table
and survives intact"""

[plugins.example]
enabled = false # retain too
'''
            (home / "config.toml").write_text(original, encoding="utf-8")
            result = run(home)
            self.assertEqual(result.returncode, 0, result.stderr)
            merged = (home / "config.toml").read_text(encoding="utf-8")
            self.assertIn("# retain this comment", merged)
            self.assertIn('model = "gpt-5.6-luna" # local preference', merged)
            self.assertIn('model_reasoning_effort = "low"', merged)
            self.assertIn('note = """[agents] is text, not a table', merged)
            self.assertIn('[plugins.example]\nenabled = false # retain too', merged)
            self.assertIn('[agents]\nenabled = true', merged)

    def test_replaces_existing_policy_section_and_rerun_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            home.mkdir()
            (home / "AGENTS.md").write_text(
                "# My Instructions\n\nKeep this.\n\n## Model Routing Policy\nold rules\n\n## Other\nAlso keep.\n",
                encoding="utf-8",
            )
            first = run(home)
            self.assertEqual(first.returncode, 0, first.stderr)
            document = (home / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("Keep this.", document)
            self.assertIn("## Other\nAlso keep.", document)
            self.assertEqual(document.count("<!-- codex-model-routing:begin -->"), 1)
            second = run(home)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("Already installed; no changes.", second.stdout)
            self.assertEqual((home / "AGENTS.md").read_text(encoding="utf-8"), document)

    def test_multiline_text_and_array_table_are_not_treated_as_root_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            home.mkdir()
            (home / "config.toml").write_text(
                '''note = """model = "not a setting"
model_reasoning_effort = "also text"""
[[workers]]
model = "custom-array-value"
''',
                encoding="utf-8",
            )
            result = run(home)
            self.assertEqual(result.returncode, 0, result.stderr)
            merged = (home / "config.toml").read_text(encoding="utf-8")
            self.assertIn('model = "not a setting"', merged)
            self.assertIn('model = "custom-array-value"', merged)
            self.assertIn('model = "gpt-5.6-luna"', merged)

    def test_replacing_policy_preserves_following_top_level_heading(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            home.mkdir()
            (home / "AGENTS.md").write_text(
                "## Model Routing Policy\nold\n\n# Project Instructions\nkeep\n", encoding="utf-8"
            )
            result = run(home)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("# Project Instructions\nkeep", (home / "AGENTS.md").read_text(encoding="utf-8"))

    def test_dry_run_does_not_create_files_or_backups(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            result = run(home, "--dry-run")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(home.exists())

    def test_malformed_toml_leaves_every_target_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".codex"
            home.mkdir()
            malformed = 'model = "missing end\n'
            (home / "config.toml").write_text(malformed, encoding="utf-8")
            (home / "AGENTS.md").write_text("# Existing\n", encoding="utf-8")
            result = run(home)
            self.assertEqual(result.returncode, 2)
            self.assertIn("invalid", result.stderr)
            self.assertEqual((home / "config.toml").read_text(encoding="utf-8"), malformed)
            self.assertEqual((home / "AGENTS.md").read_text(encoding="utf-8"), "# Existing\n")
            self.assertFalse((home / "agents").exists())
            self.assertEqual(list(home.glob("codex-model-routing-backup-*")), [])


if __name__ == "__main__":
    unittest.main()
