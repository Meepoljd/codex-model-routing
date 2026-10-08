"""Policy checks for Radar-backed generic routing semantics."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ModelRoutingPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = (ROOT / "policy/model-routing-policy.md").read_text(encoding="utf-8")
        cls.skill = (ROOT / "plugin/plugins/model-routing/skills/model-routing/SKILL.md").read_text(encoding="utf-8")

    def test_policy_has_generic_roles_and_session_boundary(self):
        for role in ("routine_worker", "complex_worker", "frontier_worker"):
            self.assertIn(role, self.policy)
        self.assertIn("new Codex task", self.policy)
        self.assertIn("activeProfiles", self.policy)

    def test_policy_documents_radar_thresholds_and_limits(self):
        for text in ("codexradar.com", "70%", "90%", "quality-only", "xhigh, max, or ultra"):
            self.assertIn(text, self.policy)
        self.assertIn("30 samples", self.policy)
        self.assertIn("14 days", self.policy)
        self.assertIn("30 days", self.policy)

    def test_explicit_aliases_select_astra_not_dynamic_frontier(self):
        for alias in ("`gpt6`", "`gpt-6`", "`GPT-6`", "`GPT-6 Astra`"):
            self.assertIn(alias, self.policy)
        self.assertIn("`gpt-6-astra` specifically", self.policy)
        self.assertIn("never mean whichever model currently powers `frontier_worker`", self.policy)

    def test_policy_covers_last_good_and_root_pin(self):
        self.assertIn("last-good", self.policy)
        self.assertIn("explicit model/default-agent override", self.policy)
        self.assertIn("plugin heuristic, not an official capability certification", self.policy)

    def test_skill_uses_generic_profiles_and_radar_evidence(self):
        self.assertIn("source of model IDs", self.skill)
        self.assertIn("catalogSelection", self.skill)
        self.assertIn("activeProfiles", self.skill)
        self.assertIn("Codex Radar evidence", self.skill)
        self.assertIn("frontier_worker", self.skill)


if __name__ == "__main__":
    unittest.main()
