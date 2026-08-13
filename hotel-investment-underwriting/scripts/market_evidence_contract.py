"""Platform-neutral contract for page-collected hotel market evidence.

The underwriting engine remains deterministic and side-effect free.  This module
defines the narrow, versioned boundary between an authorised page-collection
runtime (Playwright, Ego Lite, Kimi WebBridge, crawl4ai, xcrawl or OpenCLI) and that
engine.  It deliberately accepts only source-attributed observations; it never
turns an unscoped listing price into an ADR input.
"""

from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse


CONTRACT_VERSION = "market-evidence-collection/v2"
SUPPORTED_ENGINES = {
    "ctrip-live-rates",
    "ego-browser",
    "playwright",
    "kimi-webbridge",
    "crawl4ai",
    "xcrawl",
    "opencli",
}
SUPPORTED_PROVIDER_PROFILES = {
    "360-map-v1",
    "ctrip-hotel-v1",
    "ctrip-live-rates-v1",
}
_BUNDLED_ENGINE_PROFILES = {
    "playwright": "360-map-v1",
    "ego-browser": "ctrip-hotel-v1",
    "ctrip-live-rates": "ctrip-live-rates-v1",
}
_CTRIP_AUTO_MAPPING_PROFILE = "ctrip-live-rates-v1"
_COVERAGE_STATUSES = {"complete", "partial", "not_collected", "failed"}
_RESULT_STATUSES = {"complete", "partial", "failed"}
_BOOKING_PLATFORMS = {"携程"}
MAX_BENCHMARK_CANDIDATES = 8
# This is a transport/validation safety limit for a *complete* 2km map pool,
# not the deep-research limit.  The latter remains eight selected benchmarks.
MAX_SPATIAL_CANDIDATES = 1_000


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


def _validate_candidate_inventory(
    value: Any, *, allow_automatic_ota_mapping: bool = False
) -> list[dict[str, Any]]:
    """Validate the cross-page identity bridge used by OTA profiles.

    The map profile owns the full 2km candidate population.  A booking profile
    may enrich only explicitly selected candidates, but it must receive the
    original map candidate object so its page data cannot become an unlocated
    or untraceable competitor.
    """

    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_SPATIAL_CANDIDATES:
        raise MarketEvidenceContractError(
            "collection_request.candidate_inventory must be an array of at most "
            f"{MAX_SPATIAL_CANDIDATES} items"
        )
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    selected_count = 0
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
        if selected:
            selected_count += 1
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
        if selected and ota is None and not allow_automatic_ota_mapping:
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
    if selected_count > MAX_BENCHMARK_CANDIDATES:
        raise MarketEvidenceContractError(
            "collection_request.candidate_inventory may select at most "
            f"{MAX_BENCHMARK_CANDIDATES} 2km price/visual benchmarks"
        )
    return normalized


def _candidate_ids_sha256(candidates: list[Mapping[str, Any]]) -> str:
    """Fingerprint the exact provider-place population passed between profiles."""

    identifiers = sorted(
        _require_text(
            candidate.get("provider_place_id"),
            "candidate.provider_place_id",
            maximum=200,
        )
        for candidate in candidates
    )
    if len(set(identifiers)) != len(identifiers):
        raise MarketEvidenceContractError("candidate.provider_place_id values must be unique")
    encoded = json.dumps(
        identifiers, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_spatial_pool(
    value: Any,
    *,
    candidates: list[Mapping[str, Any]],
    expected_center: Mapping[str, Any] | None,
    path: str,
    require_complete: bool,
) -> dict[str, Any]:
    """Validate the durable proof that an OTA profile received one full 2km pool."""

    raw = _require_mapping(value, path)
    _reject_unknown(
        raw,
        {
            "status",
            "source_engine",
            "source_profile",
            "center",
            "candidate_count",
            "candidate_ids_sha256",
        },
        path,
    )
    status = raw.get("status")
    if status not in {"complete", "partial"}:
        raise MarketEvidenceContractError(f"{path}.status must be complete or partial")
    if require_complete and status != "complete":
        raise MarketEvidenceContractError(f"{path}.status must be complete before OTA benchmark collection")
    source_engine = _require_text(raw.get("source_engine"), f"{path}.source_engine", maximum=100)
    if source_engine not in SUPPORTED_ENGINES:
        raise MarketEvidenceContractError(f"{path}.source_engine is unsupported")
    if raw.get("source_profile") != "360-map-v1":
        raise MarketEvidenceContractError(f"{path}.source_profile must equal '360-map-v1'")
    center = _validate_center(raw.get("center"), f"{path}.center")
    if expected_center is not None and center != dict(expected_center):
        raise MarketEvidenceContractError(f"{path}.center must match the request/receipt target center")
    candidate_count = _require_integer(
        raw.get("candidate_count"), f"{path}.candidate_count", 0, MAX_SPATIAL_CANDIDATES
    )
    if candidate_count != len(candidates):
        raise MarketEvidenceContractError(f"{path}.candidate_count must match candidate_inventory")
    digest = raw.get("candidate_ids_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise MarketEvidenceContractError(f"{path}.candidate_ids_sha256 must be lowercase SHA-256")
    if digest != _candidate_ids_sha256(candidates):
        raise MarketEvidenceContractError(f"{path}.candidate_ids_sha256 does not match candidate_inventory")
    return {
        "status": status,
        "source_engine": source_engine,
        "source_profile": "360-map-v1",
        "center": center,
        "candidate_count": candidate_count,
        "candidate_ids_sha256": digest,
    }


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
            "candidate_pool",
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
            search.get("max_candidates", MAX_SPATIAL_CANDIDATES),
            "collection_request.search.max_candidates",
            1,
            MAX_SPATIAL_CANDIDATES,
        ),
        "max_benchmark_candidates": _require_integer(
            search.get("max_benchmark_candidates", 8),
            "collection_request.search.max_benchmark_candidates",
            0,
            MAX_BENCHMARK_CANDIDATES,
        ),
        "max_images_per_candidate": _require_integer(
            search.get("max_images_per_candidate", 1),
            "collection_request.search.max_images_per_candidate",
            0,
            4,
        ),
    }
    if normalized_search["provider_profile"] not in SUPPORTED_PROVIDER_PROFILES:
        raise MarketEvidenceContractError(
            "collection_request.search.provider_profile is unsupported"
        )

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
    inventory = _validate_candidate_inventory(
        raw.get("candidate_inventory"),
        allow_automatic_ota_mapping=(
            normalized_search["provider_profile"] == _CTRIP_AUTO_MAPPING_PROFILE
        ),
    )
    normalized: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "target": normalized_target,
        "search": normalized_search,
        "pricing_context": normalized_context,
        "required_evidence": normalized_required,
        "candidate_inventory": inventory,
    }
    is_ota_profile = normalized_search["provider_profile"] in {
        "ctrip-hotel-v1",
        "ctrip-live-rates-v1",
    }
    raw_pool = raw.get("candidate_pool")
    if is_ota_profile:
        if not inventory:
            raise MarketEvidenceContractError(
                "OTA benchmark collection requires a complete 2km candidate_inventory"
            )
        normalized["candidate_pool"] = _validate_spatial_pool(
            raw_pool,
            candidates=[item["candidate"] for item in inventory],
            expected_center=normalized_target.get("center"),
            path="collection_request.candidate_pool",
            require_complete=True,
        )
    elif raw_pool is not None:
        raise MarketEvidenceContractError(
            "collection_request.candidate_pool is only valid for OTA benchmark profiles"
        )
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


_COLLECTION_ISSUE_CODES = {
    "AUTH_REQUIRED",
    "BROWSER_DISCONNECTED",
    "CAPTCHA_REQUIRED",
    "DOM_SCHEMA_DRIFT",
    "HOTEL_MAPPING_AMBIGUOUS",
    "NO_INVENTORY",
    "NETWORK_SCHEMA_DRIFT",
    "OPENCLI_UNAVAILABLE",
    "PRICE_MISMATCH",
    "QUERY_MISMATCH",
    "RATE_LOAD_TIMEOUT",
    "RPA_FAILED",
    "UIVISION_UNPAIRED",
}


def _validate_collection_issue(value: Any, path: str) -> dict[str, Any]:
    raw = _require_mapping(value, path)
    _reject_unknown(raw, {"code", "message", "retryable", "provider_place_id"}, path)
    code = raw.get("code")
    if code not in _COLLECTION_ISSUE_CODES:
        raise MarketEvidenceContractError(f"{path}.code is invalid")
    normalized: dict[str, Any] = {
        "code": code,
        "message": _require_text(raw.get("message"), f"{path}.message", maximum=500),
        "retryable": raw.get("retryable"),
    }
    if not isinstance(normalized["retryable"], bool):
        raise MarketEvidenceContractError(f"{path}.retryable must be boolean")
    if "provider_place_id" in raw:
        normalized["provider_place_id"] = _require_text(
            raw["provider_place_id"], f"{path}.provider_place_id", maximum=200
        )
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
            "collection_issues",
            "competitor_analysis",
            "competitor_report",
            "spatial_collection",
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
    expected_profile = _BUNDLED_ENGINE_PROFILES.get(engine)
    if expected_profile is not None and normalized_collector["source_profile"] != expected_profile:
        raise MarketEvidenceContractError(
            f"collection_result.collector.source_profile must equal {expected_profile!r} for {engine}"
        )
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
    issues = raw.get("collection_issues", [])
    if not isinstance(issues, list) or len(issues) > 500:
        raise MarketEvidenceContractError("collection_result.collection_issues is invalid")
    normalized_issues = [
        _validate_collection_issue(item, f"collection_result.collection_issues[{index}]")
        for index, item in enumerate(issues)
    ]
    analysis = _require_mapping(raw.get("competitor_analysis"), "collection_result.competitor_analysis")
    report = _require_mapping(raw.get("competitor_report"), "collection_result.competitor_report")
    if raw["status"] == "complete" and any(
        item["status"] != "complete" for item in normalized_coverage.values()
    ):
        raise MarketEvidenceContractError("complete collection requires complete coverage in every dimension")
    if raw["status"] == "complete" and analysis.get("collection_status") != "complete":
        raise MarketEvidenceContractError("complete collection requires competitor_analysis.collection_status=complete")
    analysis_status = analysis.get("collection_status")
    if analysis_status not in {"complete", "partial"}:
        raise MarketEvidenceContractError("collection_result.competitor_analysis.collection_status is invalid")
    analysis_candidates = analysis.get("candidates")
    if not isinstance(analysis_candidates, list) or any(
        not isinstance(item, Mapping) for item in analysis_candidates
    ):
        raise MarketEvidenceContractError("collection_result.competitor_analysis.candidates must be an object array")
    analysis_center = analysis.get("confirmed_location")
    normalized_analysis_center = (
        _validate_center(
            analysis_center, "collection_result.competitor_analysis.confirmed_location"
        )
        if analysis_center is not None
        else None
    )
    if normalized_target is not None and normalized_analysis_center != normalized_target:
        raise MarketEvidenceContractError(
            "collection_result competitor_analysis center must match target_resolution"
        )
    raw_spatial = raw.get("spatial_collection")
    if analysis_status == "complete":
        if normalized_target is None or normalized_analysis_center is None:
            raise MarketEvidenceContractError(
                "complete spatial collection requires matching target_resolution and confirmed_location"
            )
        if normalized_coverage["candidates"]["status"] != "complete":
            raise MarketEvidenceContractError(
                "complete spatial collection requires complete candidate coverage"
            )
        if raw_spatial is None:
            raise MarketEvidenceContractError(
                "complete competitor_analysis requires spatial_collection proof"
            )
    normalized_spatial = None
    if raw_spatial is not None:
        normalized_spatial = _validate_spatial_pool(
            raw_spatial,
            candidates=[dict(item) for item in analysis_candidates],
            expected_center=normalized_analysis_center or normalized_target,
            path="collection_result.spatial_collection",
            require_complete=analysis_status == "complete",
        )
        if normalized_spatial["status"] != analysis_status:
            raise MarketEvidenceContractError(
                "collection_result spatial_collection.status must match competitor_analysis.collection_status"
            )
        if normalized_coverage["candidates"]["observed_count"] != normalized_spatial["candidate_count"]:
            raise MarketEvidenceContractError(
                "collection_result candidate coverage count must match spatial_collection"
            )
    normalized: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "status": raw["status"],
        "collector": normalized_collector,
        "target_resolution": normalized_target,
        "coverage": normalized_coverage,
        "collection_gaps": [item.strip() for item in gaps],
        "collection_issues": normalized_issues,
        "competitor_analysis": dict(analysis),
        "competitor_report": dict(report),
    }
    if normalized_spatial is not None:
        normalized["spatial_collection"] = normalized_spatial
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
