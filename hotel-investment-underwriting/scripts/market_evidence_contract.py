"""Platform-neutral contract for page-collected hotel market evidence.

The underwriting engine remains deterministic and side-effect free.  This module
defines the narrow, versioned boundary between an authorised page-collection
runtime (Playwright, Ego Lite, Kimi WebBridge, crawl4ai, xcrawl or OpenCLI) and that
engine.  It deliberately accepts only source-attributed observations; it never
turns an unscoped listing price into an ADR input.
"""

from __future__ import annotations

import copy
from datetime import date, datetime
import hashlib
import hmac
import json
import math
import os
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
_RECEIPT_ATTESTATION_ENVIRONMENT = "MARKET_EVIDENCE_RECEIPT_HMAC_KEY"
_RECEIPT_ATTESTATION_ALGORITHM = "hmac-sha256"


class MarketEvidenceContractError(ValueError):
    """Raised when collection input or its signed-off evidence is invalid."""


def _canonical_json(value: Any) -> bytes:
    """Return a stable byte representation for a host-issued receipt signature."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _receipt_attestation_key() -> bytes:
    """Read the host-owned signing key without ever returning it in an error."""

    configured = os.environ.get(_RECEIPT_ATTESTATION_ENVIRONMENT, "")
    key = configured.encode("utf-8")
    if len(key) < 32:
        raise MarketEvidenceContractError(
            "market evidence attestation is unavailable: host must provide "
            f"{_RECEIPT_ATTESTATION_ENVIRONMENT} with at least 32 bytes"
        )
    return key


def _unsigned_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(item)
        for key, item in value.items()
        if key != "attestation"
    }


def _receipt_signature(value: Mapping[str, Any], key: bytes) -> str:
    return hmac.new(key, _canonical_json(_unsigned_receipt(value)), hashlib.sha256).hexdigest()


def _receipt_key_id(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:16]


def _validate_attestation(value: Any, path: str) -> dict[str, str]:
    raw = _require_mapping(value, path)
    _reject_unknown(raw, {"algorithm", "key_id", "signature"}, path)
    if raw.get("algorithm") != _RECEIPT_ATTESTATION_ALGORITHM:
        raise MarketEvidenceContractError(
            f"{path}.algorithm must equal {_RECEIPT_ATTESTATION_ALGORITHM!r}"
        )
    key_id = _require_text(raw.get("key_id"), f"{path}.key_id", maximum=64)
    signature = raw.get("signature")
    if not isinstance(signature, str) or len(signature) != 64 or any(
        character not in "0123456789abcdef" for character in signature
    ):
        raise MarketEvidenceContractError(f"{path}.signature must be a lowercase SHA-256 HMAC")
    return {
        "algorithm": _RECEIPT_ATTESTATION_ALGORITHM,
        "key_id": key_id,
        "signature": signature,
    }


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


def _candidate_snapshot_sha256(candidates: list[Mapping[str, Any]]) -> str:
    """Fingerprint the immutable map facts handed to every downstream profile.

    A provider ID alone cannot prevent a caller from changing coordinates,
    classification or source attribution while retaining the same candidate
    count.  Enrichment fields (OTA mapping, room evidence and price evidence)
    are intentionally excluded because those are added downstream.
    """

    immutable_fields = (
        "provider",
        "provider_place_id",
        "coordinate_system",
        "longitude",
        "latitude",
        "property_kind",
        "esports_positioning",
        "operating_status",
        "source",
    )
    snapshot = []
    for candidate in candidates:
        item = {field: candidate.get(field) for field in immutable_fields}
        source = candidate.get("source")
        # Do not hash a caller-controlled mapping order. These are the exact
        # immutable source fields accepted by the candidate normalizer and are
        # emitted in the same order by the JavaScript map collector.
        item["source"] = {
            field: source.get(field) if isinstance(source, Mapping) else None
            for field in ("source_platform", "source_url", "observed_at", "confidence")
        }
        snapshot.append(item)
    snapshot.sort(key=lambda item: str(item.get("provider_place_id", "")))
    # Field order above is part of this cross-runtime protocol: JavaScript's
    # map collector emits the same ordered object list before handing it to
    # Python. Do not alphabetically re-sort nested source keys here.
    encoded = json.dumps(
        snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False
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
            "candidate_snapshot_sha256",
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
    snapshot_digest = raw.get("candidate_snapshot_sha256")
    if not isinstance(snapshot_digest, str) or len(snapshot_digest) != 64 or any(
        character not in "0123456789abcdef" for character in snapshot_digest
    ):
        raise MarketEvidenceContractError(
            f"{path}.candidate_snapshot_sha256 must be lowercase SHA-256"
        )
    if snapshot_digest != _candidate_snapshot_sha256(candidates):
        raise MarketEvidenceContractError(
            f"{path}.candidate_snapshot_sha256 does not match immutable candidate facts"
        )
    return {
        "status": status,
        "source_engine": source_engine,
        "source_profile": "360-map-v1",
        "center": center,
        "candidate_count": candidate_count,
        "candidate_ids_sha256": digest,
        "candidate_snapshot_sha256": snapshot_digest,
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


def _matches_verified_p2_observation(
    offer: Mapping[str, Any], observation: Any
) -> bool:
    """Ensure an ADR offer is a lossless projection of one verified P2 observation."""

    if not isinstance(observation, Mapping):
        return False
    if observation.get("price_type") != "P2":
        return False
    if not all(observation.get(field) is True for field in ("network_verified", "dom_verified", "price_match", "adr_eligible")):
        return False
    if observation.get("qualification_gaps") not in ([], None):
        return False
    fields = (
        ("room_type", "room_type"),
        ("room_type_provider_id", "room_type_provider_id"),
        ("nightly_price", "display_price"),
        ("availability", "availability"),
        ("currency", "currency"),
        ("tax_included", "tax_included"),
        ("cancellation_policy", "cancellation_policy"),
        ("pricing_context", "pricing_context"),
        ("source_url", "source_url"),
        ("observed_at", "observed_at"),
    )
    return all(offer.get(offer_field) == observation.get(observation_field) for offer_field, observation_field in fields)


def _validate_profile_pricing_semantics(
    profile: str, candidates: list[Mapping[str, Any]]
) -> None:
    """Keep P1 display observations structurally unable to become an ADR sample."""

    for candidate_index, candidate in enumerate(candidates):
        offers = candidate.get("room_offers", [])
        if not isinstance(offers, list):
            raise MarketEvidenceContractError(
                f"collection_result.competitor_analysis.candidates[{candidate_index}].room_offers must be an array"
            )
        if profile in {"360-map-v1", "ctrip-hotel-v1"}:
            if offers:
                evidence_kind = "P1" if profile == "ctrip-hotel-v1" else "map"
                raise MarketEvidenceContractError(
                    f"{evidence_kind} profile {profile} must not emit room_offers for ADR"
                )
            continue
        if profile != "ctrip-live-rates-v1":
            continue
        observations = candidate.get("pricing_observations", [])
        if not isinstance(observations, list):
            raise MarketEvidenceContractError(
                f"collection_result.competitor_analysis.candidates[{candidate_index}].pricing_observations must be an array"
            )
        for offer_index, offer in enumerate(offers):
            if not isinstance(offer, Mapping) or not any(
                _matches_verified_p2_observation(offer, observation)
                for observation in observations
            ):
                raise MarketEvidenceContractError(
                    "P2 room_offers must exactly match one verified Network/DOM "
                    f"pricing_observation (candidate {candidate_index}, offer {offer_index})"
                )


def _validate_benchmark_coverage_truth(
    coverage: Mapping[str, Mapping[str, Any]],
    candidates: list[Mapping[str, Any]],
    report: Mapping[str, Any],
    issues: list[Mapping[str, Any]],
) -> None:
    """Bind each benchmark coverage counter to source-attributed candidate facts."""

    selected = {
        str(candidate.get("provider_place_id"))
        for candidate in candidates
        if candidate.get("benchmark_selected") is True
        and isinstance(candidate.get("provider_place_id"), str)
    }
    observed_benchmarks = coverage["benchmark_set"]["observed_count"]
    if observed_benchmarks != len(selected):
        raise MarketEvidenceContractError(
            "collection_result.coverage.benchmark_set.observed_count must match benchmark_selected candidates"
        )

    room_type_ids = {
        str(candidate.get("provider_place_id"))
        for candidate in candidates
        if str(candidate.get("provider_place_id")) in selected
        and isinstance(candidate.get("room_type_evidence"), list)
        and candidate["room_type_evidence"]
    }
    media = report.get("candidate_media", [])
    image_ids = {
        str(item.get("provider_place_id"))
        for item in media
        if isinstance(item, Mapping)
        and str(item.get("provider_place_id")) in selected
        and isinstance(item.get("images"), list)
        and item["images"]
    }
    no_inventory_ids = {
        str(item.get("provider_place_id"))
        for item in issues
        if item.get("code") == "NO_INVENTORY" and isinstance(item.get("provider_place_id"), str)
    }
    pricing_ids = {
        str(candidate.get("provider_place_id"))
        for candidate in candidates
        if str(candidate.get("provider_place_id")) in selected
        and isinstance(candidate.get("pricing_observations"), list)
        and candidate["pricing_observations"]
    } | (no_inventory_ids & selected)

    facts = {
        "room_types": room_type_ids,
        "images": image_ids,
        "pricing": pricing_ids,
    }
    for dimension, observed_ids in facts.items():
        item = coverage[dimension]
        if item["observed_count"] != len(observed_ids):
            raise MarketEvidenceContractError(
                f"collection_result.coverage.{dimension}.observed_count must match candidate evidence"
            )
        if item["status"] == "complete" and observed_ids != selected:
            raise MarketEvidenceContractError(
                f"complete collection_result.coverage.{dimension} requires every selected benchmark"
            )


def validate_collection_result(
    value: Any, *, require_attestation: bool = False
) -> dict[str, Any]:
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
            "attestation",
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
    normalized_collector["page_sources"] = []
    for index, item in enumerate(page_sources):
        path = f"collection_result.collector.page_sources[{index}]"
        source = _require_mapping(item, path)
        _reject_unknown(source, {"url", "status", "status_observed"}, path)
        # Browser control APIs can prove the page URL without exposing a real
        # HTTP response.  Make that uncertainty explicit instead of recording
        # a fabricated 200.  Legacy signed receipts that omit the flag are
        # interpreted as a real status only when they carry a valid integer.
        observed = source.get("status_observed")
        if observed is None:
            observed = source.get("status") is not None
        if not isinstance(observed, bool):
            raise MarketEvidenceContractError(f"{path}.status_observed must be boolean")
        status = source.get("status")
        if observed:
            normalized_status: int | None = _require_integer(
                status, f"{path}.status", 100, 599
            )
        else:
            if status is not None:
                raise MarketEvidenceContractError(
                    f"{path}.status must be null when status_observed=false"
                )
            normalized_status = None
        normalized_collector["page_sources"].append(
            {
                "url": _require_url(source.get("url"), f"{path}.url"),
                "status": normalized_status,
                "status_observed": observed,
            }
        )
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
    _validate_profile_pricing_semantics(
        normalized_collector["source_profile"], analysis_candidates
    )
    _validate_benchmark_coverage_truth(
        normalized_coverage,
        analysis_candidates,
        report,
        normalized_issues,
    )
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
    if "attestation" in raw:
        normalized["attestation"] = _validate_attestation(
            raw["attestation"], "collection_result.attestation"
        )
    if require_attestation:
        attestation = normalized.get("attestation")
        if not isinstance(attestation, Mapping):
            raise MarketEvidenceContractError(
                "market evidence attestation is required; pass a receipt emitted by collect_market_evidence.py"
            )
        key = _receipt_attestation_key()
        if attestation.get("key_id") != _receipt_key_id(key):
            raise MarketEvidenceContractError("market evidence attestation key_id does not match this host")
        if not hmac.compare_digest(
            str(attestation.get("signature", "")), _receipt_signature(normalized, key)
        ):
            raise MarketEvidenceContractError("market evidence attestation signature is invalid")
    return normalized


def skill_request_patch(value: Any) -> dict[str, Any]:
    """Return receipt plus the two evidence fields an agent merges into Skill input."""

    result = validate_collection_result(value, require_attestation=True)
    return {
        "market_evidence": result,
        "competitor_analysis": result["competitor_analysis"],
        "competitor_report": result["competitor_report"],
    }


def attest_collection_result(value: Any) -> dict[str, Any]:
    """Attach a host HMAC after an adapter receipt has passed structural validation.

    The HMAC key is injected by the deployment host and never enters a result,
    report, manifest, source tree, or production archive.  A later `run.py`
    invocation must use the same host-scoped key to consume the receipt.
    """

    normalized = validate_collection_result(value, require_attestation=False)
    unsigned = _unsigned_receipt(normalized)
    key = _receipt_attestation_key()
    unsigned["attestation"] = {
        "algorithm": _RECEIPT_ATTESTATION_ALGORITHM,
        "key_id": _receipt_key_id(key),
        "signature": _receipt_signature(unsigned, key),
    }
    return unsigned


def load_json_object(path: str) -> dict[str, Any]:
    """Load one UTF-8 object for the CLI without accepting JSON arrays/scalars."""

    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MarketEvidenceContractError(f"{path} must contain one JSON object")
    return value
