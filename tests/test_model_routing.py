"""Regression checks for the portable routing policy and packaged worker defaults."""

from pathlib import Path
import tomllib
import unittest

from installer import DEFAULT_CONFIG


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "policy" / "model-routing-policy.md"
AGENTS_DIR = ROOT / "agents"


class ModelRoutingPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = POLICY_PATH.read_text(encoding="utf-8")

    def test_aliases_resolve_to_astra_without_automatic_escalation(self):
        for alias in ("gpt6", "gpt-6", "GPT-6", "GPT-6 Astra", "gpt-6-astra"):
            self.assertIn(alias, self.policy)
        self.assertIn('map those explicit requests to `astra_worker` with `model="gpt-6-astra"`', self.policy)
        self.assertIn("does not itself trigger `astra_worker`", self.policy)

    def test_explicit_selected_model_is_respected(self):
        self.assertIn("Respect an explicitly selected session model", self.policy)
        self.assertIn("An explicit user-selected model continues to win over policy", self.policy)

    def test_routing_boundaries_and_constraints_are_preserved(self):
        self.assertIn("first check the Astra escalation criteria, then Sol, then Terra, then Spark, and finally Luna", self.policy)
        self.assertIn("A Sol criterion takes precedence", self.policy)
        self.assertIn("Deadlocks, lock-order correctness, cancellation safety", self.policy)
        self.assertIn("Ordinary security and concurrency work remains Sol", self.policy)
        self.assertIn("no automatic xhigh/max/ultra escalation", self.policy)
        self.assertIn("Changing docs does not alter an active session.", self.policy)
        self.assertIn("An explicit user-selected model continues to win over policy", self.policy)

    def test_astra_fallback_and_weakest_sufficient_model_are_documented(self):
        self.assertIn('model="gpt-6-astra"', self.policy)
        self.assertIn('reasoning_effort="high"', self.policy)
        self.assertIn('fork_turns="none"', self.policy)
        self.assertIn("Use the weakest model likely to succeed, not merely the weakest model available", self.policy)

    def test_astra_escalation_preserves_sol_boundary(self):
        self.assertIn("repeated evidence-backed Sol attempts have failed", self.policy)
        self.assertIn("multiple interacting architectural uncertainties", self.policy)
        self.assertIn("Ordinary security and concurrency work remains Sol", self.policy)

    def test_packaged_workers_match_policy_defaults(self):
        expected = {
            "spark_worker.toml": ("spark_worker", "gpt-5.3-codex-spark", "low"),
            "terra_worker.toml": ("terra_worker", "gpt-5.6-terra", "medium"),
            "sol_worker.toml": ("sol_worker", "gpt-5.6-sol", "high"),
            "astra_worker.toml": ("astra_worker", "gpt-6-astra", "high"),
        }
        for filename, values in expected.items():
            worker = tomllib.loads((AGENTS_DIR / filename).read_text(encoding="utf-8"))
            self.assertEqual(
                (worker["name"], worker["model"], worker["model_reasoning_effort"]), values
            )

    def test_sanitized_defaults_are_luna_and_agents_enabled_only(self):
        config = tomllib.loads(DEFAULT_CONFIG)
        self.assertEqual(config, {
            "model": "gpt-5.6-luna",
            "model_reasoning_effort": "low",
            "agents": {"enabled": True},
        })
        rendered = DEFAULT_CONFIG.lower()
        for forbidden in ("projects", "plugin", "marketplace", "hook", "trust", "session"):
            self.assertNotIn(forbidden, rendered)

    def test_policy_lists_every_documented_default(self):
        for line in (
            "- `root` (`Luna`) uses `gpt-5.6-luna` with `low` reasoning effort.",
            "- `spark_worker` uses `gpt-5.3-codex-spark` with `low` reasoning effort.",
            "- `terra_worker` uses `gpt-5.6-terra` with `medium` reasoning effort.",
            "- `sol_worker` uses `gpt-5.6-sol` with `high` reasoning effort.",
            "- `astra_worker` uses `gpt-6-astra` with `high` reasoning effort.",
        ):
            self.assertIn(line, self.policy)


if __name__ == "__main__":
    unittest.main()
