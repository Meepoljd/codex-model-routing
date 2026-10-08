"""Policy checks that protect dynamic routing semantics without pinning model IDs."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ModelRoutingPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = (ROOT / "policy/model-routing-policy.md").read_text(encoding="utf-8")
        cls.skill = (
            ROOT / "plugin/plugins/model-routing/skills/model-routing/SKILL.md"
        ).read_text(encoding="utf-8")

    def test_policy_uses_dynamic_profiles_and_new_session_boundary(self):
        self.assertIn("active worker model IDs are dynamic", self.policy)
        self.assertIn("model-routing/state.json", self.policy)
        self.assertIn("Catalog refreshes take effect in new tasks", self.policy)
        self.assertNotIn("gpt-6.1-sol", self.policy)

    def test_three_role_boundaries_and_concurrency_escalation_are_present(self):
        for role in ("luna_worker", "sol_worker", "astra_worker"):
            self.assertIn(role, self.policy)
        self.assertIn("Deadlocks, lock-order correctness, cancellation safety", self.policy)
        self.assertIn("repeated evidence-backed Sol failures", self.policy)
        self.assertIn("multiple interacting architectural uncertainties", self.policy)

    def test_explicit_aliases_route_astra_but_mentions_do_not(self):
        for alias in ("`gpt6`", "`gpt-6`", "`GPT-6`", "`GPT-6 Astra`"):
            self.assertIn(alias, self.policy)
        self.assertIn("Merely mentioning those tokens", self.policy)
        self.assertIn("route to `astra_worker`", self.policy)

    def test_policy_documents_conservative_discovery_and_explicit_pin(self):
        self.assertIn("unknown-family", self.policy)
        self.assertIn("does not issue inference requests", self.policy)
        self.assertIn("last-good profiles unchanged", self.policy)
        self.assertIn("Existing root model settings are explicit pins", self.policy)

    def test_skill_uses_profiles_as_source_of_model_ids(self):
        self.assertIn("source of model IDs", self.skill)
        self.assertIn("catalogSelection", self.skill)
        self.assertIn("activeProfiles", self.skill)
        self.assertIn("unknown families", self.skill)


if __name__ == "__main__":
    unittest.main()
