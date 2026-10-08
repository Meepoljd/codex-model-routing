from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
import time
import unittest

from radar_source import (
    BINDING_URL,
    LEGACY_URL,
    SUMMARY_URL,
    RadarSource,
    RadarSourceError,
)


NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def candidate(model: str, *efforts: str):
    return SimpleNamespace(model=model, efforts=frozenset(efforts))


def binding(*pairs: tuple[str, str]):
    members = [
        {
            "task_id": f"task-{index}",
            "task_content_hash": f"{index + 1:064x}",
        }
        for index in range(2)
    ]
    return {
        "enabled": True,
        "interface_confirmed": True,
        "production_read_verified": True,
        "transport_origin": "https://api.codexradar.com",
        "endpoint_path": "/api/v1/radar-bench-score",
        "benchmark": "bench-2026",
        "catalog_version": "catalog-2026",
        "task_set_sha256": "a" * 64,
        "total_tasks": 2,
        "source_counts": {"software": 1, "science": 1},
        "model_efforts": [{"model": model, "effort": effort} for model, effort in pairs],
        "members": members,
        "public_api_observed_at": "2026-10-08T08:00:00+00:00",
    }


def summary(model: str, effort: str, *, score=80, coverage=2, status="complete", digest="a" * 64):
    return {
        "schema": "radar-bench-public-summary-v1",
        "benchmark": "bench-2026",
        "score_version": "radar-bench-v1",
        "catalog_version": "catalog-2026",
        "task_set_sha256": digest,
        "model": model,
        "effort": effort,
        "score": score if coverage else None,
        "coverage": coverage,
        "required_tasks": 2,
        "score_status": status,
        "source_counts": {"software": 1, "science": 1},
        "scoring_policy_version": "radar-bench-v1-last3-per-task-equal-weight-100",
    }


def legacy_point(
    model: str,
    effort: str,
    *,
    iq=90.0,
    passed=60,
    samples=100,
    latest="2026-10-07T00:00:00+00:00",
    price=1.25,
    price_samples=0,
    minutes=10.0,
    duration_samples=0,
):
    return {
        "model": model,
        "effort": effort,
        "harness": "codex",
        "iq": iq,
        "passed": passed,
        "valid_tasks": samples,
        "latest_graded_at": latest,
        "average_price_usd": price,
        "price_samples": price_samples,
        "average_minutes": minutes,
        "duration_samples": duration_samples,
    }


def legacy(*points, updated="2026-10-01T23:00:27+08:00"):
    return {
        "schema": 2,
        "mode": "equal_latest_3",
        "type": "distributed_intelligence_efficiency",
        "source_updated_at": updated,
        "fingerprint": "b" * 64,
        "points": list(points),
    }


class FakeFetch:
    def __init__(self, binding_payload, summaries, legacy_payload):
        self.binding_payload = binding_payload
        self.summaries = summaries
        self.legacy_payload = legacy_payload
        self.calls: list[str] = []

    def __call__(self, url: str):
        self.calls.append(url)
        if url == BINDING_URL:
            if isinstance(self.binding_payload, BaseException):
                raise self.binding_payload
            return self.binding_payload
        if url == LEGACY_URL:
            if isinstance(self.legacy_payload, BaseException):
                raise self.legacy_payload
            return self.legacy_payload
        if url.startswith(SUMMARY_URL):
            query = parse_qs(urlparse(url).query)
            return self.summaries[(query["model"][0], query["effort"][0])]
        raise AssertionError(url)


class RadarSourceTest(unittest.TestCase):
    def source(self, fetch, **kwargs):
        options = {"total_timeout": 2, "request_timeout": .2}
        options.update(kwargs)
        return RadarSource(now=lambda: NOW, fetch_json=fetch, **options)

    def test_complete_current_benchmark_is_used_as_one_fingerprint(self):
        pairs = (("new-family-a", "low"), ("new-family-b", "medium"), ("new-family-c", "high"))
        fetch = FakeFetch(
            binding(*pairs),
            {pair: summary(*pair, score=70 + index * 15) for index, pair in enumerate(pairs)},
            legacy(RadarSourceError("must not fetch legacy")),
        )
        result = self.source(fetch).load(
            [
                candidate("new-family-a", "low"),
                candidate("new-family-b", "medium"),
                candidate("new-family-c", "high"),
            ]
        )
        self.assertEqual(result.source_kind, "radar_bench")
        self.assertEqual(result.fingerprint, "a" * 64)
        self.assertEqual(result.source_time_kind, "metadata-observed-at")
        self.assertEqual([point.quality for point in result.points], [70.0, 85.0, 100.0])
        self.assertNotIn(LEGACY_URL, fetch.calls)

    def test_new_unmeasured_cell_does_not_block_three_complete_candidates(self):
        pairs = (("established", "low"), ("established", "medium"), ("established", "high"), ("brand-new", "low"))
        summaries = {
            pair: summary(*pair, score=70 + index * 10) for index, pair in enumerate(pairs[:3])
        }
        summaries[("brand-new", "low")] = summary(
            "brand-new", "low", score=0, coverage=1, status="provisional"
        )
        fetch = FakeFetch(binding(*pairs), summaries, RadarSourceError("legacy must not be used"))
        result = self.source(fetch).load(
            [candidate("established", "low", "medium", "high"), candidate("brand-new", "low")]
        )
        self.assertEqual(result.source_kind, "radar_bench")
        self.assertEqual(len(result.points), 3)
        self.assertEqual(result.thresholds["completeCandidates"], 3)
        self.assertEqual(result.exclusions[0]["model"], "brand-new")

    def test_any_partial_current_cell_falls_back_without_mixing(self):
        pairs = (("a", "low"), ("b", "high"))
        fetch = FakeFetch(
            binding(*pairs),
            {
                ("a", "low"): summary("a", "low", score=0, coverage=1, status="provisional"),
                ("b", "high"): summary("b", "high", score=100),
            },
            legacy(
                legacy_point("a", "low", iq=75, passed=50),
                legacy_point("b", "high", iq=105, passed=70),
            ),
        )
        result = self.source(fetch, max_workers=1).load([candidate("a", "low"), candidate("b", "high")])
        self.assertEqual(result.source_kind, "legacy_equal_latest_3")
        self.assertEqual(result.fingerprint, "b" * 64)
        self.assertTrue(result.fallback_reason)
        self.assertTrue(all(point.coverage is None for point in result.points))

    def test_wrong_current_hash_falls_back_to_legacy(self):
        pair = ("future", "medium")
        fetch = FakeFetch(
            binding(pair),
            {pair: summary(*pair, digest="c" * 64)},
            legacy(legacy_point(*pair)),
        )
        result = self.source(fetch).load([candidate(pair[0], pair[1])])
        self.assertEqual(result.source_kind, "legacy_equal_latest_3")
        self.assertIn("identity mismatch", result.fallback_reason)

    def test_legacy_filters_low_sample_stale_nan_and_non_catalog_points(self):
        fetch = FakeFetch(
            RadarSourceError("binding offline"),
            {},
            legacy(
                legacy_point("good", "low"),
                legacy_point("small", "low", iq=150, passed=2, samples=2),
                legacy_point("stale", "low", latest="2026-01-01T00:00:00+00:00"),
                legacy_point("nan", "low", iq=float("nan")),
                legacy_point("not-installed", "low"),
            ),
        )
        result = self.source(fetch).load(
            [candidate("good", "low"), candidate("small", "low"), candidate("stale", "low"), candidate("nan", "low")]
        )
        self.assertEqual([(point.model, point.effort) for point in result.points], [("good", "low")])
        reasons = {item["model"]: item["reason"] for item in result.exclusions}
        self.assertEqual(reasons["small"], "insufficient-samples")
        self.assertEqual(reasons["stale"], "stale-point")
        self.assertIn("nan", reasons)

    def test_legacy_cost_and_latency_require_real_sample_counts(self):
        pair = ("future", "low")
        unreliable = FakeFetch(
            RadarSourceError("offline"), {}, legacy(legacy_point(*pair, price_samples=0, duration_samples=0))
        )
        point = self.source(unreliable).load([candidate(*pair)]).points[0]
        self.assertIsNone(point.cost_usd)
        self.assertIsNone(point.latency_minutes)
        self.assertEqual(point.cost_reference_usd, 1.25)
        self.assertEqual(point.latency_reference_minutes, 10.0)

        reliable = FakeFetch(
            RadarSourceError("offline"), {}, legacy(legacy_point(*pair, price_samples=30, duration_samples=30))
        )
        point = self.source(reliable).load([candidate(*pair)]).points[0]
        self.assertEqual(point.cost_usd, 1.25)
        self.assertEqual(point.latency_minutes, 10.0)

    def test_stale_snapshot_and_total_outage_fail_closed(self):
        pair = ("future", "low")
        stale = FakeFetch(
            RadarSourceError("binding offline"),
            {},
            legacy(legacy_point(*pair), updated="2026-01-01T00:00:00+00:00"),
        )
        with self.assertRaisesRegex(RadarSourceError, "stale"):
            self.source(stale).load([candidate(*pair)])
        outage = FakeFetch(RadarSourceError("binding offline"), {}, RadarSourceError("legacy offline"))
        with self.assertRaisesRegex(RadarSourceError, "legacy offline"):
            self.source(outage).load([candidate(*pair)])

    def test_slow_current_read_cannot_consume_reserved_legacy_budget(self):
        pair = ("future", "low")

        def fetch(url):
            if url == BINDING_URL:
                time.sleep(.18)  # exceeds the 55% current share of a .3s budget
                return binding(pair)
            if url == LEGACY_URL:
                return legacy(legacy_point(*pair))
            raise AssertionError(url)

        result = self.source(fetch, total_timeout=.3).load([candidate(*pair)])
        self.assertEqual(result.source_kind, "legacy_equal_latest_3")
        self.assertIn("total timeout", result.fallback_reason)

    def test_only_fixed_https_endpoints_are_allowed(self):
        source = self.source(lambda url: {})
        with self.assertRaisesRegex(RadarSourceError, "unapproved"):
            source._validate_url("https://evil.example/data/radar-bench-binding.json")
        with self.assertRaisesRegex(RadarSourceError, "unapproved"):
            source._validate_url("http://codexradar.com/data/radar-bench-binding.json")

    def test_binding_rejects_duplicate_or_non_hex_content_hashes(self):
        broken = binding(("future", "low"))
        broken["members"][1]["task_content_hash"] = broken["members"][0]["task_content_hash"]
        fetch = FakeFetch(broken, {}, RadarSourceError("no fallback"))
        with self.assertRaisesRegex(RadarSourceError, "member identity"):
            self.source(fetch).load([candidate("future", "low")])


if __name__ == "__main__":
    unittest.main()
