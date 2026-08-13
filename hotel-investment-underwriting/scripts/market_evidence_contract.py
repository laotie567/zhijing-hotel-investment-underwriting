"""Platform-neutral contract for page-collected hotel market evidence.

The underwriting engine remains deterministic and side-effect free.  This module
defines the narrow, versioned boundary between an authorised page-collection
runtime (Playwright, Ego Lite, Kimi WebBridge, crawl4ai, xcrawl or OpenCLI) and that
engine.  It deliberately accepts only source-attributed observations; it never
turns an unscoped listing price into an ADR input.
"""

from __future__ import annotations

from datetime import date, datetime
import json
import math
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse


CONTRACT_VERSION = "market-evidence-collection/v1"
SUPPORTED_ENGINES = {
    "ego-browser",
    "playwright",
    "kimi-webbridge",
    "crawl4ai",
    "xcrawl",
    "opencli",
}
_COVERAGE_STATUSES = {"complete", "partial", "not_collected", "failed"}
_RESULT_STATUSES = {"complete", "partial", "failed"}
_BOOKING_PLATFORMS = {"携程"}


class MarketEvidenceContractError(ValueError):
    """Raised when collection input or its signed-off evidence is invalid."""


def _require_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MarketEvidenceContractError(f"{path} must be an object")
    return value


def _require_text(value: Any, path: str, *, maximum: int = 2_000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MarketEvidenceContractError(f"{path} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise MarketEvidenceContractError(f"{path} must be at most {maximum} characters")
    return normalized


def _require_integer(value: Any, path: str, low: int, high: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise MarketEvidenceContractError(f"{path} must be an integer between {low} and {high}")
    return value


def _require_number(value: Any, path: str, low: float, high: float) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or not low <= float(value) <= high
    ):
        raise MarketEvidenceContractError(f"{path} must be a finite number between {low} and {high}")
    return float(value)


def _require_url(value: Any, path: str) -> str:
    result = _require_text(value, path, maximum=4_000)
    parsed = urlparse(result)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise MarketEvidenceContractError(f"{path} must be an http(s) URL")
    return result


def _require_datetime(value: Any, path: str) -> str:
    result = _require_text(value, path, maximum=80)
    try:
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MarketEvidenceContractError(f"{path} must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None:
        raise MarketEvidenceContractError(f"{path} must include a timezone")
    return result


def _require_date(value: Any, path: str) -> str:
    result = _require_text(value, path, maximum=10)
    try:
        if date.fromisoformat(result).isoformat() != result:
            raise ValueError
    except ValueError as exc:
        raise MarketEvidenceContractError(f"{path} must be YYYY-MM-DD") from exc
    return result


def _reject_unknown(value: Mapping[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise MarketEvidenceContractError(f"{path} has unknown fields: {unknown}")


def _validate_center(value: Any, path: str) -> dict[str, Any]:
    raw = _require_mapping(value, path)
    _reject_unknown(
        raw,
        {
            "provider",
            "provider_place_id",
            "coordinate_system",
            "longitude",
            "latitude",
            "status",
        },
        path,
    )
    provider = _require_text(raw.get("provider"), f"{path}.provider", maximum=100)
    place_id = _require_text(raw.get("provider_place_id"), f"{path}.provider_place_id", maximum=200)
    if raw.get("coordinate_system") != "GCJ-02":
        raise MarketEvidenceContractError(f"{path}.coordinate_system must equal 'GCJ-02'")
    status = raw.get("status")
    if status not in {"confirmed", "auto_confirmed_exact"}:
        raise MarketEvidenceContractError(
            f"{path}.status must be confirmed or auto_confirmed_exact"
        )
    return {
        "provider": provider,
        "provider_place_id": place_id,
        "coordinate_system": "GCJ-02",
        "longitude": _require_number(raw.get("longitude"), f"{path}.longitude", -180, 180),
        "latitude": _require_number(raw.get("latitude"), f"{path}.latitude", -90, 90),
        "status": status,
    }


def _validate_candidate_inventory(value: Any) -> list[dict[str, Any]]:
    """Validate the cross-page identity bridge used by OTA profiles.

    The map profile owns the full 2km candidate population.  A booking profile
    may enrich only explicitly selected candidates, but it must receive the
    original map candidate object so its page data cannot become an unlocated
    or untraceable competitor.
    """

    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 200:
        raise MarketEvidenceContractError("collection_request.candidate_inventory must be an array of at most 200 items")
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        path = f"collection_request.candidate_inventory[{index}]"
        raw = _require_mapping(item, path)
        _reject_unknown(raw, {"candidate", "benchmark_selected", "ota_property"}, path)
        candidate = _require_mapping(raw.get("candidate"), f"{path}.candidate")
        place_id = _require_text(
            candidate.get("provider_place_id"), f"{path}.candidate.provider_place_id", maximum=200
        )
        if place_id in seen_ids:
            raise MarketEvidenceContractError(
                f"collection_request.candidate_inventory has duplicate provider_place_id: {place_id}"
            )
        seen_ids.add(place_id)
        selected = raw.get("benchmark_selected", False)
        if not isinstance(selected, bool):
            raise MarketEvidenceContractError(f"{path}.benchmark_selected must be boolean")
        ota_raw = raw.get("ota_property")
        ota: dict[str, str] | None = None
        if ota_raw is not None:
            ota_mapping = _require_mapping(ota_raw, f"{path}.ota_property")
            _reject_unknown(
                ota_mapping,
                {"platform", "property_id", "property_url", "match_method", "matched_at"},
                f"{path}.ota_property",
            )
            platform = _require_text(ota_mapping.get("platform"), f"{path}.ota_property.platform", maximum=80)
            if platform not in _BOOKING_PLATFORMS:
                raise MarketEvidenceContractError(f"{path}.ota_property.platform is unsupported")
            ota = {
                "platform": platform,
                "property_id": _require_text(
                    ota_mapping.get("property_id"), f"{path}.ota_property.property_id", maximum=200
                ),
                "property_url": _require_url(
                    ota_mapping.get("property_url"), f"{path}.ota_property.property_url"
                ),
                "match_method": _require_text(
                    ota_mapping.get("match_method"), f"{path}.ota_property.match_method", maximum=100
                ),
                "matched_at": _require_datetime(
                    ota_mapping.get("matched_at"), f"{path}.ota_property.matched_at"
                ),
            }
        if selected and ota is None:
            raise MarketEvidenceContractError(
                f"{path}.ota_property is required for a selected price/visual benchmark"
            )
        normalized.append(
            {
                "candidate": dict(candidate),
                "benchmark_selected": selected,
                **({"ota_property": ota} if ota is not None else {}),
            }
        )
    return normalized


def validate_collection_request(value: Any) -> dict[str, Any]:
    """Validate a host request before it reaches an external page collector."""

    raw = _require_mapping(value, "collection_request")
    _reject_unknown(
        raw,
        {
            "contract_version",
            "request_id",
            "target",
            "search",
            "pricing_context",
            "required_evidence",
            "candidate_inventory",
        },
        "collection_request",
    )
    if raw.get("contract_version") != CONTRACT_VERSION:
        raise MarketEvidenceContractError(
            f"collection_request.contract_version must equal {CONTRACT_VERSION!r}"
        )
    target = _require_mapping(raw.get("target"), "collection_request.target")
    _reject_unknown(
        target,
        {"name", "address", "city_id", "center"},
        "collection_request.target",
    )
    normalized_target: dict[str, Any] = {
        "name": _require_text(target.get("name"), "collection_request.target.name", maximum=200),
        "address": _require_text(target.get("address"), "collection_request.target.address", maximum=500),
        "city_id": _require_text(target.get("city_id"), "collection_request.target.city_id", maximum=40),
    }
    if "center" in target:
        normalized_target["center"] = _validate_center(
            target["center"], "collection_request.target.center"
        )

    search = _require_mapping(raw.get("search"), "collection_request.search")
    _reject_unknown(
        search,
        {
            "provider_profile",
            "query",
            "radius_meters",
            "max_candidates",
            "max_benchmark_candidates",
            "max_images_per_candidate",
        },
        "collection_request.search",
    )
    normalized_search = {
        "provider_profile": _require_text(
            search.get("provider_profile"), "collection_request.search.provider_profile", maximum=100
        ),
        "query": _require_text(search.get("query"), "collection_request.search.query", maximum=100),
        "radius_meters": _require_integer(
            search.get("radius_meters"), "collection_request.search.radius_meters", 1, 2_000
        ),
        "max_candidates": _require_integer(
            search.get("max_candidates", 200), "collection_request.search.max_candidates", 1, 200
        ),
        "max_benchmark_candidates": _require_integer(
            search.get("max_benchmark_candidates", 8),
            "collection_request.search.max_benchmark_candidates",
            0,
            30,
        ),
        "max_images_per_candidate": _require_integer(
            search.get("max_images_per_candidate", 1),
            "collection_request.search.max_images_per_candidate",
            0,
            4,
        ),
    }

    context = _require_mapping(raw.get("pricing_context"), "collection_request.pricing_context")
    _reject_unknown(
        context,
        {"check_in_date", "nights", "guests", "currency"},
        "collection_request.pricing_context",
    )
    normalized_context = {
        "check_in_date": _require_date(
            context.get("check_in_date"), "collection_request.pricing_context.check_in_date"
        ),
        "nights": _require_integer(
            context.get("nights"), "collection_request.pricing_context.nights", 1, 30
        ),
        "guests": _require_integer(
            context.get("guests"), "collection_request.pricing_context.guests", 1, 12
        ),
        "currency": "CNY",
    }
    if context.get("currency") != "CNY":
        raise MarketEvidenceContractError(
            "collection_request.pricing_context.currency must equal 'CNY'"
        )

    required = raw.get("required_evidence", {})
    required = _require_mapping(required, "collection_request.required_evidence")
    _reject_unknown(
        required,
        {"room_types", "images", "pricing", "benchmark_set"},
        "collection_request.required_evidence",
    )
    normalized_required = {
        field: bool(required.get(field, True))
        for field in ("room_types", "images", "pricing", "benchmark_set")
    }
    if any(not isinstance(required.get(field, True), bool) for field in normalized_required):
        raise MarketEvidenceContractError("collection_request.required_evidence values must be boolean")
    normalized: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "target": normalized_target,
        "search": normalized_search,
        "pricing_context": normalized_context,
        "required_evidence": normalized_required,
        "candidate_inventory": _validate_candidate_inventory(raw.get("candidate_inventory")),
    }
    if "request_id" in raw:
        normalized["request_id"] = _require_text(raw["request_id"], "collection_request.request_id", maximum=200)
    return normalized


def _validate_coverage(value: Any, path: str) -> dict[str, Any]:
    raw = _require_mapping(value, path)
    _reject_unknown(raw, {"status", "observed_count", "notes"}, path)
    status = raw.get("status")
    if status not in _COVERAGE_STATUSES:
        raise MarketEvidenceContractError(f"{path}.status is invalid")
    normalized = {
        "status": status,
        "observed_count": _require_integer(raw.get("observed_count", 0), f"{path}.observed_count", 0, 100_000),
    }
    if "notes" in raw:
        normalized["notes"] = _require_text(raw["notes"], f"{path}.notes", maximum=2_000)
    return normalized


def validate_collection_result(value: Any) -> dict[str, Any]:
    """Validate an adapter response before an agent merges it into Skill input."""

    raw = _require_mapping(value, "collection_result")
    _reject_unknown(
        raw,
        {
            "contract_version",
            "request_id",
            "status",
            "collector",
            "target_resolution",
            "coverage",
            "collection_gaps",
            "competitor_analysis",
            "competitor_report",
        },
        "collection_result",
    )
    if raw.get("contract_version") != CONTRACT_VERSION:
        raise MarketEvidenceContractError(
            f"collection_result.contract_version must equal {CONTRACT_VERSION!r}"
        )
    if raw.get("status") not in _RESULT_STATUSES:
        raise MarketEvidenceContractError("collection_result.status is invalid")
    collector = _require_mapping(raw.get("collector"), "collection_result.collector")
    _reject_unknown(
        collector,
        {"engine", "engine_version", "source_profile", "started_at", "finished_at", "page_sources"},
        "collection_result.collector",
    )
    engine = _require_text(collector.get("engine"), "collection_result.collector.engine", maximum=100)
    if engine not in SUPPORTED_ENGINES:
        raise MarketEvidenceContractError(f"unsupported page collector engine: {engine}")
    normalized_collector = {
        "engine": engine,
        "engine_version": _require_text(
            collector.get("engine_version"), "collection_result.collector.engine_version", maximum=100
        ),
        "source_profile": _require_text(
            collector.get("source_profile"), "collection_result.collector.source_profile", maximum=100
        ),
        "started_at": _require_datetime(
            collector.get("started_at"), "collection_result.collector.started_at"
        ),
        "finished_at": _require_datetime(
            collector.get("finished_at"), "collection_result.collector.finished_at"
        ),
    }
    page_sources = collector.get("page_sources", [])
    if not isinstance(page_sources, list) or len(page_sources) > 500:
        raise MarketEvidenceContractError("collection_result.collector.page_sources is invalid")
    normalized_collector["page_sources"] = [
        {
            "url": _require_url(_require_mapping(item, "page_source").get("url"), "page_source.url"),
            "status": _require_integer(_require_mapping(item, "page_source").get("status"), "page_source.status", 100, 599),
        }
        for item in page_sources
    ]
    if not normalized_collector["page_sources"] and raw["status"] != "failed":
        raise MarketEvidenceContractError("a non-failed collection requires a page-source receipt")

    target_resolution = raw.get("target_resolution")
    normalized_target = (
        _validate_center(target_resolution, "collection_result.target_resolution")
        if target_resolution is not None
        else None
    )
    coverage = _require_mapping(raw.get("coverage"), "collection_result.coverage")
    _reject_unknown(
        coverage,
        {"candidates", "benchmark_set", "room_types", "images", "pricing"},
        "collection_result.coverage",
    )
    normalized_coverage = {
        name: _validate_coverage(coverage.get(name), f"collection_result.coverage.{name}")
        for name in ("candidates", "benchmark_set", "room_types", "images", "pricing")
    }
    gaps = raw.get("collection_gaps", [])
    if not isinstance(gaps, list) or any(not isinstance(item, str) or not item.strip() for item in gaps):
        raise MarketEvidenceContractError("collection_result.collection_gaps must be a string array")
    analysis = _require_mapping(raw.get("competitor_analysis"), "collection_result.competitor_analysis")
    report = _require_mapping(raw.get("competitor_report"), "collection_result.competitor_report")
    if raw["status"] == "complete" and any(
        item["status"] != "complete" for item in normalized_coverage.values()
    ):
        raise MarketEvidenceContractError("complete collection requires complete coverage in every dimension")
    if raw["status"] == "complete" and analysis.get("collection_status") != "complete":
        raise MarketEvidenceContractError("complete collection requires competitor_analysis.collection_status=complete")
    normalized: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "status": raw["status"],
        "collector": normalized_collector,
        "target_resolution": normalized_target,
        "coverage": normalized_coverage,
        "collection_gaps": [item.strip() for item in gaps],
        "competitor_analysis": dict(analysis),
        "competitor_report": dict(report),
    }
    if "request_id" in raw:
        normalized["request_id"] = _require_text(raw["request_id"], "collection_result.request_id", maximum=200)
    return normalized


def skill_request_patch(value: Any) -> dict[str, Any]:
    """Return receipt plus the two evidence fields an agent merges into Skill input."""

    result = validate_collection_result(value)
    return {
        "market_evidence": result,
        "competitor_analysis": result["competitor_analysis"],
        "competitor_report": result["competitor_report"],
    }


def load_json_object(path: str) -> dict[str, Any]:
    """Load one UTF-8 object for the CLI without accepting JSON arrays/scalars."""

    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MarketEvidenceContractError(f"{path} must contain one JSON object")
    return value
