#!/usr/bin/env python3
"""Read public CodexRadar evidence without credentials or inference calls."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import socket
import time
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


BINDING_URL = "https://codexradar.com/data/radar-bench-binding.json"
SUMMARY_URL = "https://codexradar.com/api/radar-bench-score"
LEGACY_URL = "https://codexradar.com/data/intelligence-efficiency.json"
AUTHORITY_ORIGIN = "https://api.codexradar.com"
AUTHORITY_PATH = "/api/v1/radar-bench-score"
USER_AGENT = "codex-model-routing/2 (+https://github.com/Meepoljd/codex-model-routing)"
SCORING_POLICY = "radar-bench-v1-last3-per-task-equal-weight-100"
MINIMUM_CURRENT_CANDIDATES = 3
SAFE_TOKEN_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:/-")


class RadarSourceError(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise RadarSourceError(f"{label} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RadarSourceError(f"{label} is not an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise RadarSourceError(f"{label} lacks a timezone")
    return parsed.astimezone(timezone.utc)


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RadarSourceError(f"{label} is not numeric")
    number = float(value)
    if not math.isfinite(number):
        raise RadarSourceError(f"{label} is not finite")
    return number


def _nonnegative_int(value: object, label: str) -> int:
    number = _finite_number(value, label)
    if number < 0 or not number.is_integer():
        raise RadarSourceError(f"{label} is not a non-negative integer")
    return int(number)


def _safe_token(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or value[0] not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        or any(character not in SAFE_TOKEN_CHARS for character in value)
    ):
        raise RadarSourceError(f"{label} is not a safe token")
    return value


@dataclass(frozen=True)
class EvidencePoint:
    model: str
    effort: str
    quality: float
    sample_count: int
    coverage: int | None = None
    required_tasks: int | None = None
    latest_at: str | None = None
    cost_usd: float | None = None
    cost_samples: int = 0
    cost_reference_usd: float | None = None
    latency_minutes: float | None = None
    latency_samples: int = 0
    latency_reference_minutes: float | None = None

    def as_state(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "effort": self.effort,
            "quality": self.quality,
            "sampleCount": self.sample_count,
            "coverage": self.coverage,
            "requiredTasks": self.required_tasks,
            "latestAt": self.latest_at,
            "costUsd": self.cost_usd,
            "costSamples": self.cost_samples,
            "costReferenceUsd": self.cost_reference_usd,
            "latencyMinutes": self.latency_minutes,
            "latencySamples": self.latency_samples,
            "latencyReferenceMinutes": self.latency_reference_minutes,
        }


@dataclass(frozen=True)
class EvidenceSnapshot:
    source_kind: str
    source_url: str
    fetched_at: str
    source_updated_at: str
    fingerprint: str
    quality_scale: float
    points: tuple[EvidencePoint, ...]
    benchmark: str | None = None
    source_time_kind: str = "source-updated-at"
    fallback_reason: str | None = None
    exclusions: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    thresholds: Mapping[str, Any] = field(default_factory=dict)

    @property
    def cost_mode(self) -> str:
        return (
            "verified-cost"
            if self.points and all(point.cost_usd is not None for point in self.points)
            else "quality-only"
        )

    def as_state(self) -> dict[str, Any]:
        return {
            "sourceKind": self.source_kind,
            "sourceUrl": self.source_url,
            "fetchedAt": self.fetched_at,
            "sourceUpdatedAt": self.source_updated_at,
            "sourceTimeKind": self.source_time_kind,
            "benchmark": self.benchmark,
            "fingerprint": self.fingerprint,
            "qualityScale": self.quality_scale,
            "costMode": self.cost_mode,
            "fallbackReason": self.fallback_reason,
            "thresholds": dict(self.thresholds),
            "points": [point.as_state() for point in self.points],
            "exclusions": [dict(exclusion) for exclusion in self.exclusions],
        }


def evidence_from_mapping(value: Mapping[str, Any]) -> EvidenceSnapshot:
    """Build an injectable, strictly finite test/offline evidence snapshot."""
    raw_points = value.get("points")
    if not isinstance(raw_points, list) or not raw_points:
        raise RadarSourceError("evidence points are missing")
    points: list[EvidencePoint] = []
    for index, raw in enumerate(raw_points):
        if not isinstance(raw, Mapping):
            raise RadarSourceError(f"evidence point {index} is not an object")
        model = _safe_token(raw.get("model"), f"evidence point {index} model")
        effort = _safe_token(raw.get("effort"), f"evidence point {index} effort")
        quality = _finite_number(raw.get("quality"), f"evidence point {index} quality")
        sample_count = _nonnegative_int(raw.get("sampleCount", raw.get("sample_count", 0)), "sample count")

        def optional_number(*keys: str) -> float | None:
            candidate = next((raw[key] for key in keys if key in raw), None)
            return None if candidate is None else _finite_number(candidate, keys[0])

        def optional_int(*keys: str) -> int | None:
            candidate = next((raw[key] for key in keys if key in raw), None)
            return None if candidate is None else _nonnegative_int(candidate, keys[0])

        points.append(
            EvidencePoint(
                model=model,
                effort=effort,
                quality=quality,
                sample_count=sample_count,
                coverage=optional_int("coverage"),
                required_tasks=optional_int("requiredTasks", "required_tasks"),
                latest_at=raw.get("latestAt") if isinstance(raw.get("latestAt"), str) else None,
                cost_usd=optional_number("costUsd", "cost_usd"),
                cost_samples=optional_int("costSamples", "cost_samples") or 0,
                cost_reference_usd=optional_number("costReferenceUsd", "cost_reference_usd"),
                latency_minutes=optional_number("latencyMinutes", "latency_minutes"),
                latency_samples=optional_int("latencySamples", "latency_samples") or 0,
                latency_reference_minutes=optional_number(
                    "latencyReferenceMinutes", "latency_reference_minutes"
                ),
            )
        )
    quality_scale = _finite_number(value.get("qualityScale", value.get("quality_scale", 100)), "quality scale")
    return EvidenceSnapshot(
        source_kind=str(value.get("sourceKind", value.get("source_kind", "injected"))),
        source_url=str(value.get("sourceUrl", value.get("source_url", "injected://fixture"))),
        fetched_at=str(value.get("fetchedAt", value.get("fetched_at", _utc_now().isoformat()))),
        source_updated_at=str(
            value.get("sourceUpdatedAt", value.get("source_updated_at", _utc_now().isoformat()))
        ),
        fingerprint=str(value.get("fingerprint", "injected")),
        quality_scale=quality_scale,
        points=tuple(points),
        benchmark=value.get("benchmark") if isinstance(value.get("benchmark"), str) else None,
        source_time_kind=str(value.get("sourceTimeKind", "fixture-time")),
        fallback_reason=(
            value.get("fallbackReason") if isinstance(value.get("fallbackReason"), str) else None
        ),
        exclusions=tuple(value.get("exclusions", ())),
        thresholds=dict(value.get("thresholds", {})),
    )


class RadarSource:
    """Fetch one internally consistent public CodexRadar evidence snapshot."""

    def __init__(
        self,
        *,
        now: Callable[[], datetime] = _utc_now,
        fetch_json: Callable[[str], Any] | None = None,
        request_timeout: float = 3.0,
        total_timeout: float = 15.0,
        retries: int = 1,
        max_workers: int = 4,
        legacy_max_age: timedelta = timedelta(days=14),
        point_max_age: timedelta = timedelta(days=30),
        minimum_samples: int = 30,
        metric_minimum_samples: int = 30,
    ):
        if request_timeout <= 0 or total_timeout <= 0 or retries < 0:
            raise ValueError("CodexRadar timeouts must be positive and retries non-negative")
        if minimum_samples <= 0 or metric_minimum_samples <= 0:
            raise ValueError("CodexRadar sample thresholds must be positive")
        self.now = now
        self.fetch_json = fetch_json
        self.request_timeout = request_timeout
        self.total_timeout = total_timeout
        self.retries = retries
        self.max_workers = max(1, min(max_workers, 8))
        self.legacy_max_age = legacy_max_age
        self.point_max_age = point_max_age
        self.minimum_samples = minimum_samples
        self.metric_minimum_samples = metric_minimum_samples

    def load(self, candidates: Sequence[object]) -> EvidenceSnapshot:
        candidate_pairs = self._candidate_pairs(candidates)
        if not candidate_pairs:
            raise RadarSourceError("native catalog has no safe visible model/effort pairs")
        started = time.monotonic()
        overall_deadline = started + self.total_timeout
        # Keep a real fallback budget even when the current benchmark is busy.
        current_budget = self.total_timeout * 0.55
        current_deadline = min(started + current_budget, overall_deadline)
        current_failure: str
        try:
            binding = self._binding(current_deadline)
            current = self._current(binding, candidate_pairs, current_deadline)
            return current
        except RadarSourceError as exc:
            current_failure = str(exc)
        try:
            return self._legacy(candidate_pairs, current_failure, overall_deadline)
        except RadarSourceError as legacy_exc:
            raise RadarSourceError(
                f"current RadarBench unavailable ({current_failure}); legacy fallback unavailable ({legacy_exc})"
            ) from legacy_exc

    @staticmethod
    def _candidate_pairs(candidates: Sequence[object]) -> set[tuple[str, str]]:
        pairs: set[tuple[str, str]] = set()
        for candidate in candidates:
            model = getattr(candidate, "model", None)
            efforts = getattr(candidate, "efforts", None)
            if not isinstance(model, str) or not isinstance(efforts, (set, frozenset)):
                raise RadarSourceError("native candidate has an invalid shape")
            for effort in efforts:
                if isinstance(effort, str):
                    pairs.add((model, effort))
        return pairs

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RadarSourceError("CodexRadar fetch exceeded its total timeout")
        return remaining

    def _get_json(self, url: str, max_bytes: int, deadline: float) -> Any:
        self._validate_url(url)
        if self.fetch_json is not None:
            self._remaining(deadline)
            result = self.fetch_json(url)
            self._remaining(deadline)
            return result
        last_error: BaseException | None = None
        for attempt in range(self.retries + 1):
            timeout = min(self.request_timeout, self._remaining(deadline))
            request = Request(
                url,
                headers={
                    "Accept": "application/json",
                    "Referer": "https://codexradar.com/",
                    "User-Agent": USER_AGENT,
                },
                method="GET",
            )
            try:
                opener = build_opener(_NoRedirect())
                with opener.open(request, timeout=timeout) as response:
                    length = response.headers.get("Content-Length")
                    if length and int(length) > max_bytes:
                        raise RadarSourceError(f"CodexRadar response exceeds {max_bytes} bytes")
                    chunks: list[bytes] = []
                    size = 0
                    while True:
                        remaining = self._remaining(deadline)
                        # urllib's timeout is per socket operation. Tighten it as the
                        # overall deadline approaches and re-check after every chunk.
                        try:
                            response.fp.raw._sock.settimeout(min(self.request_timeout, remaining))
                        except (AttributeError, OSError):
                            pass
                        chunk = response.read(min(65_536, max_bytes + 1 - size))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        size += len(chunk)
                        if size > max_bytes:
                            raise RadarSourceError(f"CodexRadar response exceeds {max_bytes} bytes")
                    payload = b"".join(chunks)
                result = json.loads(payload)
                self._remaining(deadline)
                return result
            except HTTPError as exc:
                last_error = exc
                if exc.code not in {429, 502, 503, 504} or attempt >= self.retries:
                    break
                retry_after = exc.headers.get("Retry-After")
                try:
                    delay = min(max(float(retry_after or 0.2), 0.0), 1.0)
                except ValueError:
                    delay = 0.2
            except (URLError, socket.timeout, TimeoutError, json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                delay = 0.2
            if delay:
                time.sleep(min(delay, self._remaining(deadline)))
        raise RadarSourceError(f"public GET failed for {url}: {last_error}")

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlparse(url)
        allowed = {
            ("codexradar.com", "/data/radar-bench-binding.json"),
            ("codexradar.com", "/api/radar-bench-score"),
            ("codexradar.com", "/data/intelligence-efficiency.json"),
            ("api.codexradar.com", AUTHORITY_PATH),
        }
        if parsed.scheme != "https" or parsed.username or parsed.password or (parsed.hostname, parsed.path) not in allowed:
            raise RadarSourceError(f"refusing unapproved CodexRadar URL: {url}")

    def _binding(self, deadline: float) -> Mapping[str, Any]:
        raw = self._get_json(BINDING_URL, 1_000_000, deadline)
        if not isinstance(raw, Mapping):
            raise RadarSourceError("RadarBench binding is not an object")
        for flag in ("enabled", "interface_confirmed", "production_read_verified"):
            if raw.get(flag) is not True:
                raise RadarSourceError(f"RadarBench binding {flag} is not true")
        if raw.get("transport_origin") != AUTHORITY_ORIGIN or raw.get("endpoint_path") != AUTHORITY_PATH:
            raise RadarSourceError("RadarBench binding names an unapproved authority")
        total_tasks = _nonnegative_int(raw.get("total_tasks"), "binding total_tasks")
        if total_tasks <= 0:
            raise RadarSourceError("RadarBench binding has no tasks")
        source_counts = raw.get("source_counts")
        if not isinstance(source_counts, Mapping) or sum(
            _nonnegative_int(value, "binding source count") for value in source_counts.values()
        ) != total_tasks:
            raise RadarSourceError("RadarBench source counts do not match total_tasks")
        benchmark = _safe_token(raw.get("benchmark"), "binding benchmark")
        catalog_version = _safe_token(raw.get("catalog_version"), "binding catalog_version")
        digest = raw.get("task_set_sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise RadarSourceError("RadarBench task-set digest is invalid")
        efforts = raw.get("model_efforts")
        if not isinstance(efforts, list) or not efforts:
            raise RadarSourceError("RadarBench binding has no model efforts")
        seen: set[tuple[str, str]] = set()
        for index, item in enumerate(efforts):
            if not isinstance(item, Mapping):
                raise RadarSourceError(f"binding model_efforts item {index} is invalid")
            pair = (
                _safe_token(item.get("model"), "binding model"),
                _safe_token(item.get("effort"), "binding effort"),
            )
            if pair in seen:
                raise RadarSourceError("RadarBench binding repeats a model/effort pair")
            seen.add(pair)
        members = raw.get("members")
        if not isinstance(members, list) or len(members) != total_tasks:
            raise RadarSourceError("RadarBench binding member count is inconsistent")
        member_ids: set[str] = set()
        content_hashes: set[str] = set()
        for member in members:
            if not isinstance(member, Mapping):
                raise RadarSourceError("RadarBench binding member is invalid")
            task_id = _safe_token(member.get("task_id"), "binding task_id")
            content_hash = member.get("task_content_hash")
            if (
                task_id in member_ids
                or not isinstance(content_hash, str)
                or len(content_hash) != 64
                or any(character not in "0123456789abcdef" for character in content_hash)
                or content_hash in content_hashes
            ):
                raise RadarSourceError("RadarBench binding member identity is invalid")
            member_ids.add(task_id)
            content_hashes.add(content_hash)
        # Preserve the validated fields without trusting arbitrary transport metadata later.
        return {
            "benchmark": benchmark,
            "catalog_version": catalog_version,
            "task_set_sha256": digest,
            "total_tasks": total_tasks,
            "source_counts": dict(source_counts),
            "model_efforts": seen,
            "public_api_observed_at": raw.get("public_api_observed_at"),
        }

    def _current(
        self,
        binding: Mapping[str, Any],
        candidate_pairs: set[tuple[str, str]],
        deadline: float,
    ) -> EvidenceSnapshot:
        comparable = sorted(candidate_pairs & set(binding["model_efforts"]))
        if not comparable:
            raise RadarSourceError("RadarBench binding has no native-catalog model/effort pairs")

        def fetch(pair: tuple[str, str]) -> tuple[tuple[str, str], Any]:
            query = urlencode({"model": pair[0], "effort": pair[1], "view": "summary"})
            return pair, self._get_json(f"{SUMMARY_URL}?{query}", 128_000, deadline)

        points: list[EvidencePoint] = []
        exclusions: list[dict[str, Any]] = []
        processed = 0
        executor = ThreadPoolExecutor(max_workers=min(self.max_workers, len(comparable)))
        futures = {executor.submit(fetch, pair): pair for pair in comparable}
        try:
            for future in as_completed(futures, timeout=self._remaining(deadline)):
                pair = futures[future]
                processed += 1
                try:
                    actual_pair, payload = future.result()
                    point, reason = self._summary_point(payload, actual_pair, binding)
                    if point is None:
                        exclusions.append({"model": pair[0], "effort": pair[1], "reason": reason})
                    else:
                        points.append(point)
                except Exception as exc:
                    exclusions.append(
                        {"model": pair[0], "effort": pair[1], "reason": f"summary-invalid-or-unavailable: {exc}"}
                    )
                remaining = len(comparable) - processed
                if len(points) + remaining < MINIMUM_CURRENT_CANDIDATES:
                    break
        except TimeoutError:
            exclusions.extend(
                {"model": pair[0], "effort": pair[1], "reason": "summary-budget-exhausted"}
                for future, pair in futures.items()
                if not future.done()
            )
        finally:
            for future in futures:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
        if len(points) < MINIMUM_CURRENT_CANDIDATES:
            reasons = "; ".join(str(item["reason"]) for item in exclusions[:3])
            raise RadarSourceError(
                f"RadarBench has only {len(points)} complete comparable candidates; "
                f"requires {MINIMUM_CURRENT_CANDIDATES}" + (f" ({reasons})" if reasons else "")
            )
        points.sort(key=lambda point: (point.model, point.effort))
        observed = binding.get("public_api_observed_at")
        observed_time = _parse_time(observed, "binding public_api_observed_at")
        return EvidenceSnapshot(
            source_kind="radar_bench",
            source_url=SUMMARY_URL,
            fetched_at=self.now().astimezone(timezone.utc).isoformat(),
            source_updated_at=observed_time.isoformat(),
            source_time_kind="metadata-observed-at",
            benchmark=str(binding["benchmark"]),
            fingerprint=str(binding["task_set_sha256"]),
            quality_scale=100.0,
            points=tuple(points),
            exclusions=tuple(exclusions),
            thresholds={
                "requiredCoverage": int(binding["total_tasks"]),
                "minimumCompleteCandidates": MINIMUM_CURRENT_CANDIDATES,
                "completeCandidates": len(points),
                "comparableCells": len(comparable),
            },
        )

    @staticmethod
    def _summary_point(
        raw: object,
        pair: tuple[str, str],
        binding: Mapping[str, Any],
    ) -> tuple[EvidencePoint | None, str | None]:
        if not isinstance(raw, Mapping):
            raise RadarSourceError("RadarBench summary is not an object")
        expected_fields = {
            "schema",
            "benchmark",
            "score_version",
            "catalog_version",
            "task_set_sha256",
            "model",
            "effort",
            "score",
            "coverage",
            "required_tasks",
            "score_status",
            "source_counts",
            "scoring_policy_version",
        }
        if set(raw) != expected_fields:
            raise RadarSourceError(f"RadarBench summary fields changed for {pair[0]}@{pair[1]}")
        expected = {
            "schema": "radar-bench-public-summary-v1",
            "benchmark": binding["benchmark"],
            "score_version": "radar-bench-v1",
            "catalog_version": binding["catalog_version"],
            "task_set_sha256": binding["task_set_sha256"],
            "model": pair[0],
            "effort": pair[1],
            "scoring_policy_version": SCORING_POLICY,
        }
        if any(raw.get(key) != value for key, value in expected.items()):
            raise RadarSourceError(f"RadarBench summary identity mismatch for {pair[0]}@{pair[1]}")
        coverage = _nonnegative_int(raw.get("coverage"), "summary coverage")
        required = _nonnegative_int(raw.get("required_tasks"), "summary required_tasks")
        if required != binding["total_tasks"] or coverage > required:
            raise RadarSourceError("RadarBench summary coverage is inconsistent")
        if raw.get("source_counts") != binding["source_counts"]:
            raise RadarSourceError("RadarBench summary source counts changed")
        status = raw.get("score_status")
        if status not in {"missing_current_result", "provisional", "complete"}:
            raise RadarSourceError("RadarBench summary has an unknown status")
        if status != "complete" or coverage != required:
            return None, f"{status}-coverage-{coverage}-of-{required}"
        score = _finite_number(raw.get("score"), "summary score")
        if not 0 <= score <= 100:
            raise RadarSourceError("RadarBench score is outside 0..100")
        return (
            EvidencePoint(
                model=pair[0],
                effort=pair[1],
                quality=score,
                sample_count=coverage,
                coverage=coverage,
                required_tasks=required,
            ),
            None,
        )

    def _legacy(
        self,
        candidate_pairs: set[tuple[str, str]],
        fallback_reason: str,
        deadline: float,
    ) -> EvidenceSnapshot:
        raw = self._get_json(LEGACY_URL, 16_000_000, deadline)
        if not isinstance(raw, Mapping):
            raise RadarSourceError("legacy snapshot is not an object")
        if raw.get("schema") != 2 or raw.get("mode") != "equal_latest_3":
            raise RadarSourceError("legacy snapshot schema/mode is unsupported")
        if raw.get("type") != "distributed_intelligence_efficiency":
            raise RadarSourceError("legacy snapshot type is unsupported")
        now = self.now().astimezone(timezone.utc)
        updated = _parse_time(raw.get("source_updated_at"), "legacy source_updated_at")
        if updated > now + timedelta(minutes=5) or now - updated > self.legacy_max_age:
            raise RadarSourceError("legacy snapshot is stale or future-dated")
        fingerprint = raw.get("fingerprint")
        if not isinstance(fingerprint, str) or len(fingerprint) != 64:
            raise RadarSourceError("legacy snapshot fingerprint is invalid")
        points_raw = raw.get("points")
        if not isinstance(points_raw, list):
            raise RadarSourceError("legacy snapshot points are missing")
        points: list[EvidencePoint] = []
        exclusions: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for index, item in enumerate(points_raw):
            if not isinstance(item, Mapping):
                continue
            try:
                model = _safe_token(item.get("model"), f"legacy point {index} model")
                effort = _safe_token(item.get("effort"), f"legacy point {index} effort")
            except RadarSourceError:
                continue
            pair = (model, effort)
            if pair not in candidate_pairs:
                continue
            if pair in seen:
                raise RadarSourceError(f"legacy snapshot repeats {model}@{effort}")
            seen.add(pair)
            reason: str | None = None
            try:
                if item.get("harness") != "codex":
                    reason = "non-codex-harness"
                    raise ValueError
                quality = _finite_number(item.get("iq"), "legacy IQ")
                samples = _nonnegative_int(item.get("valid_tasks"), "legacy valid_tasks")
                passed = _finite_number(item.get("passed"), "legacy passed")
                if not 0 <= quality <= 150 or not 0 <= passed <= samples:
                    reason = "invalid-quality-range"
                    raise ValueError
                if abs(quality - (passed / samples * 150 if samples else 0)) > 0.02:
                    reason = "quality-formula-mismatch"
                    raise ValueError
                if samples < self.minimum_samples:
                    reason = "insufficient-samples"
                    raise ValueError
                latest = _parse_time(item.get("latest_graded_at"), "legacy latest_graded_at")
                if latest > now + timedelta(minutes=5) or now - latest > self.point_max_age:
                    reason = "stale-point"
                    raise ValueError
            except (RadarSourceError, ValueError) as exc:
                exclusions.append({"model": model, "effort": effort, "reason": reason or str(exc)})
                continue

            price_reference = self._optional_metric(item.get("average_price_usd"), minimum=0)
            price_samples = self._optional_count(item.get("price_samples"))
            reliable_price = (
                price_reference
                if price_reference is not None and price_samples >= self.metric_minimum_samples
                else None
            )
            latency_reference = self._optional_metric(item.get("average_minutes"), minimum=0)
            latency_samples = self._optional_count(item.get("duration_samples"))
            reliable_latency = (
                latency_reference
                if latency_reference is not None and latency_samples >= self.metric_minimum_samples
                else None
            )
            points.append(
                EvidencePoint(
                    model=model,
                    effort=effort,
                    quality=quality,
                    sample_count=samples,
                    latest_at=latest.isoformat(),
                    cost_usd=reliable_price,
                    cost_samples=price_samples,
                    cost_reference_usd=price_reference,
                    latency_minutes=reliable_latency,
                    latency_samples=latency_samples,
                    latency_reference_minutes=latency_reference,
                )
            )
        if not points:
            raise RadarSourceError("legacy snapshot has no fresh sufficiently sampled native candidates")
        points.sort(key=lambda point: (point.model, point.effort))
        return EvidenceSnapshot(
            source_kind="legacy_equal_latest_3",
            source_url=LEGACY_URL,
            fetched_at=now.isoformat(),
            source_updated_at=updated.isoformat(),
            source_time_kind="source-updated-at",
            benchmark=None,
            fingerprint=fingerprint,
            quality_scale=150.0,
            points=tuple(points),
            fallback_reason=fallback_reason,
            exclusions=tuple(exclusions),
            thresholds={
                "sourceMaxAgeSeconds": int(self.legacy_max_age.total_seconds()),
                "pointMaxAgeSeconds": int(self.point_max_age.total_seconds()),
                "minimumSamples": self.minimum_samples,
                "metricMinimumSamples": self.metric_minimum_samples,
            },
        )

    @staticmethod
    def _optional_metric(value: object, *, minimum: float) -> float | None:
        try:
            number = _finite_number(value, "optional metric")
        except RadarSourceError:
            return None
        return number if number >= minimum else None

    @staticmethod
    def _optional_count(value: object) -> int:
        try:
            return _nonnegative_int(value, "optional metric sample count")
        except RadarSourceError:
            return 0


def snapshot_digest(snapshot: EvidenceSnapshot) -> str:
    encoded = json.dumps(snapshot.as_state(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
