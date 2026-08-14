"""Deterministic 2km pure-esports competitor analysis for underwriting."""

from __future__ import annotations

from datetime import date, datetime
import math
from statistics import median
from typing import Any, Mapping
from urllib.parse import urlparse


COMPETITOR_RADIUS_METERS = 2_000.0
MINIMUM_PRICING_SAMPLES = 3
_EARTH_RADIUS_METERS = 6_371_000.0
_SOURCE_FIELDS = ("source_platform", "source_url", "observed_at", "confidence")
_CONFIDENCE_LEVELS = {"low", "medium", "high"}
_ADR_ELIGIBLE_CONFIDENCE_LEVELS = {"medium", "high"}
_PRICING_CURRENCY = "CNY"
_OFFER_AVAILABILITY = {"available", "sold_out", "unknown"}
_MAX_ROOM_TYPE_EVIDENCE = 30


class CompetitorInputError(ValueError):
    """Raised when the public competitor-analysis request is not an object."""


def _valid_coordinate(value: Any, low: float, high: float) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and low <= float(value) <= high
    )


def _valid_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _valid_observed_at(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _valid_iso_date(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _positive_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _haversine_meters(
    center_longitude: float,
    center_latitude: float,
    longitude: float,
    latitude: float,
) -> float:
    """Return the unrounded great-circle distance between two GCJ-02 coordinates."""

    latitude_delta = math.radians(latitude - center_latitude)
    longitude_delta = math.radians(longitude - center_longitude)
    center_latitude_radians = math.radians(center_latitude)
    latitude_radians = math.radians(latitude)
    a = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(center_latitude_radians)
        * math.cos(latitude_radians)
        * math.sin(longitude_delta / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_METERS * math.asin(math.sqrt(a))


def _location_result(request: Mapping[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    raw = request.get("confirmed_location")
    if not isinstance(raw, Mapping):
        return None, ["confirmed_location"]

    missing: list[str] = []
    if raw.get("status") not in {"confirmed", "auto_confirmed_exact"}:
        missing.append("confirmed_location.status")
    if not isinstance(raw.get("provider"), str) or not raw["provider"].strip():
        missing.append("confirmed_location.provider")
    if not isinstance(raw.get("provider_place_id"), str) or not raw["provider_place_id"].strip():
        missing.append("confirmed_location.provider_place_id")
    if raw.get("coordinate_system") != "GCJ-02":
        missing.append("confirmed_location.coordinate_system")
    if not _valid_coordinate(raw.get("longitude"), -180, 180):
        missing.append("confirmed_location.longitude")
    if not _valid_coordinate(raw.get("latitude"), -90, 90):
        missing.append("confirmed_location.latitude")
    if missing:
        return None, missing
    return {
        "provider": raw["provider"].strip(),
        "provider_place_id": raw["provider_place_id"].strip(),
        "coordinate_system": "GCJ-02",
        "longitude": float(raw["longitude"]),
        "latitude": float(raw["latitude"]),
        "status": raw["status"],
    }, []


def _source_result(value: Any) -> tuple[dict[str, str], list[str]]:
    if not isinstance(value, Mapping):
        return {}, [f"source.{field}" for field in _SOURCE_FIELDS]
    source = {field: value.get(field) for field in _SOURCE_FIELDS}
    missing = [
        f"source.{field}"
        for field, field_value in source.items()
        if not isinstance(field_value, str) or not field_value.strip()
    ]
    if "source.source_url" not in missing and not _valid_url(source["source_url"]):
        missing.append("source.source_url")
    if "source.observed_at" not in missing and not _valid_observed_at(source["observed_at"]):
        missing.append("source.observed_at")
    if "source.confidence" not in missing and source["confidence"].lower() not in _CONFIDENCE_LEVELS:
        missing.append("source.confidence")
    return {field: str(field_value).strip() for field, field_value in source.items() if isinstance(field_value, str)}, missing


def _room_type_evidence_result(value: Any) -> tuple[list[dict[str, str]], bool]:
    """Keep only page-traceable room-type observations for presentation.

    A room-type name is useful to an operator even when the OTA cannot return a
    bookable price.  It is deliberately separate from ``room_offers`` so it
    can never be mistaken for an ADR-eligible offer.
    """

    if value is None:
        return [], True
    if not isinstance(value, list) or len(value) > _MAX_ROOM_TYPE_EVIDENCE:
        return [], False
    normalized: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {
            "room_type", "room_type_provider_id", "source_url", "observed_at"
        }:
            return [], False
        room_type = item.get("room_type")
        provider_id = item.get("room_type_provider_id")
        source_url = item.get("source_url")
        observed_at = item.get("observed_at")
        if (
            not isinstance(room_type, str)
            or not room_type.strip()
            or len(room_type.strip()) > 300
            or not isinstance(provider_id, str)
            or not provider_id.strip()
            or len(provider_id.strip()) > 240
            or not _valid_url(source_url)
            or not _valid_observed_at(observed_at)
            or provider_id.strip() in seen_ids
        ):
            return [], False
        seen_ids.add(provider_id.strip())
        normalized.append(
            {
                "room_type": room_type.strip(),
                "room_type_provider_id": provider_id.strip(),
                "source_url": source_url.strip(),
                "observed_at": observed_at.strip(),
            }
        )
    return normalized, True


def _pricing_context_result(
    request: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    raw = request.get("pricing_context")
    if not isinstance(raw, Mapping):
        return None, ["pricing_context"]

    missing: list[str] = []
    if not _valid_iso_date(raw.get("check_in_date")):
        missing.append("pricing_context.check_in_date")
    if not _positive_integer(raw.get("nights")):
        missing.append("pricing_context.nights")
    if not _positive_integer(raw.get("guests")):
        missing.append("pricing_context.guests")
    if raw.get("currency") != _PRICING_CURRENCY:
        missing.append("pricing_context.currency")
    if missing:
        return None, missing
    return {
        "check_in_date": raw["check_in_date"],
        "nights": raw["nights"],
        "guests": raw["guests"],
        "currency": _PRICING_CURRENCY,
    }, []


def _candidate_result(candidate: Any, center: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(candidate, Mapping):
        return {
            "provider_place_id": None,
            "name": None,
            "classification": "evidence_insufficient",
            "formal_competitor_allowed": False,
            "reason_codes": ["candidate_not_an_object"],
            "pending_fields": ["candidate"],
        }

    pending: list[str] = []
    place_id = candidate.get("provider_place_id")
    if not isinstance(place_id, str) or not place_id.strip():
        pending.append("provider_place_id")
        place_id = None
    else:
        place_id = place_id.strip()

    provider = candidate.get("provider")
    if not isinstance(provider, str) or not provider.strip():
        pending.append("provider")
        provider = None
    else:
        provider = provider.strip()
        if provider != center["provider"]:
            pending.append("provider_match")

    longitude = candidate.get("longitude")
    latitude = candidate.get("latitude")
    coordinate_system = candidate.get("coordinate_system")
    if coordinate_system != "GCJ-02":
        pending.append("coordinate_system")
    if not _valid_coordinate(longitude, -180, 180):
        pending.append("longitude")
    if not _valid_coordinate(latitude, -90, 90):
        pending.append("latitude")

    source, source_pending = _source_result(candidate.get("source"))
    pending.extend(source_pending)
    room_type_evidence, room_type_evidence_valid = _room_type_evidence_result(
        candidate.get("room_type_evidence")
    )
    if not room_type_evidence_valid:
        pending.append("room_type_evidence")
    property_kind = candidate.get("property_kind")
    esports_positioning = candidate.get("esports_positioning")
    operating_status = candidate.get("operating_status")
    if property_kind not in {"lodging", "non_lodging"}:
        pending.append("property_kind")
    elif property_kind == "lodging":
        if operating_status not in {"operating", "closed"}:
            pending.append("operating_status")
        elif operating_status == "operating" and esports_positioning not in {
            "primary",
            "incidental",
        }:
            pending.append("esports_positioning")

    result: dict[str, Any] = {
        "provider": provider,
        "provider_place_id": place_id,
        "name": candidate.get("name") if isinstance(candidate.get("name"), str) else None,
        "classification": "evidence_insufficient",
        "formal_competitor_allowed": False,
        "reason_codes": [],
        "pending_fields": pending,
        "source": source,
        "room_type_evidence": room_type_evidence,
        "room_offers": candidate.get("room_offers") if isinstance(candidate.get("room_offers"), list) else [],
        # P1/P2/P3 observations remain visible to a user even when the strict
        # ADR gate rejects them (for example tax scope or machine-count is not
        # proven). They never enter `_pricing_summary`, which consumes only
        # `room_offers` after `_valid_offer` succeeds.
        "pricing_observations": (
            candidate.get("pricing_observations")
            if isinstance(candidate.get("pricing_observations"), list)
            else []
        ),
        "benchmark_selected": candidate.get("benchmark_selected") is True,
        "booking_evidence": (
            candidate.get("booking_evidence")
            if isinstance(candidate.get("booking_evidence"), list)
            else []
        ),
    }
    benchmark_rank = candidate.get("benchmark_rank")
    if result["benchmark_selected"] and isinstance(benchmark_rank, int) and not isinstance(benchmark_rank, bool) and 1 <= benchmark_rank <= 8:
        result["benchmark_rank"] = benchmark_rank
    benchmark_reason = candidate.get("benchmark_selection_reason")
    if result["benchmark_selected"] and isinstance(benchmark_reason, str) and benchmark_reason.strip():
        result["benchmark_selection_reason"] = benchmark_reason.strip()[:500]
    if not {"coordinate_system", "longitude", "latitude"}.intersection(pending):
        distance = _haversine_meters(
            float(center["longitude"]),
            float(center["latitude"]),
            float(longitude),
            float(latitude),
        )
        result["distance_meters"] = round(distance, 3)
        if distance > COMPETITOR_RADIUS_METERS:
            result["classification"] = "excluded_out_of_range"
            result["reason_codes"] = ["outside_competitor_scope_2km"]
            if pending:
                result["reason_codes"].append("competitor_evidence_incomplete")
            return result

    if pending:
        result["reason_codes"] = ["competitor_evidence_incomplete"]
        return result
    if property_kind == "non_lodging":
        result["classification"] = "excluded_non_lodging"
        result["reason_codes"] = ["property_not_lodging"]
        return result
    if operating_status == "closed":
        result["classification"] = "excluded_not_operating"
        result["reason_codes"] = ["property_not_operating"]
        return result
    if esports_positioning == "incidental":
        result["classification"] = "incidental_esports_rooms"
        result["reason_codes"] = ["esports_not_primary_business"]
        return result

    result["classification"] = "pure_esports_hotel"
    result["formal_competitor_allowed"] = True
    return result


def _offer_workstations(value: Any) -> int | None:
    if not isinstance(value, Mapping):
        return None
    workstations = value.get("workstations")
    if not isinstance(workstations, int) or isinstance(workstations, bool) or workstations <= 0:
        return None
    return workstations


def _valid_offer(value: Any, context: Mapping[str, Any] | None) -> tuple[int, float] | None:
    """Return one ADR-eligible OTA offer, never an unscoped listing price."""

    if not isinstance(value, Mapping):
        return None
    workstations = _offer_workstations(value)
    price = value.get("nightly_price")
    if (
        workstations is None
        or not isinstance(price, (int, float))
        or isinstance(price, bool)
        or not math.isfinite(float(price))
        or float(price) <= 0
    ):
        return None
    if context is None:
        return None
    required_text = ("room_type", "room_type_provider_id", "cancellation_policy")
    if any(not isinstance(value.get(field), str) or not value[field].strip() for field in required_text):
        return None
    if value.get("availability") not in _OFFER_AVAILABILITY or value.get("availability") != "available":
        return None
    if value.get("currency") != _PRICING_CURRENCY or not isinstance(value.get("tax_included"), bool):
        return None
    if not _valid_url(value.get("source_url")) or not _valid_observed_at(value.get("observed_at")):
        return None
    raw_context = value.get("pricing_context")
    if not isinstance(raw_context, Mapping):
        return None
    if any(raw_context.get(field) != context.get(field) for field in ("check_in_date", "nights", "guests", "currency")):
        return None
    return workstations, float(price)


def _round_to_ten(value: float) -> float:
    return float(math.floor(value / 10 + 0.5) * 10)


def _pricing_summary(
    competitors: list[dict[str, Any]],
    collection_complete: bool,
    pricing_context: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    prices_by_workstations: dict[int, list[float]] = {}
    observed_workstations: set[int] = set()
    low_confidence_excluded: dict[int, int] = {}
    for competitor in competitors:
        property_prices: dict[int, list[float]] = {}
        for offer in competitor["room_offers"]:
            workstations = _offer_workstations(offer)
            if workstations is not None:
                observed_workstations.add(workstations)
            normalized = _valid_offer(offer, pricing_context)
            if normalized is None:
                continue
            workstations, price = normalized
            property_prices.setdefault(workstations, []).append(price)
        for workstations, prices in property_prices.items():
            # A property can publish multiple room offers. Collapse them to one
            # representative value so the minimum sample count means independent
            # competitor properties rather than duplicated offers.
            confidence = competitor["source"].get("confidence", "").lower()
            if confidence in _ADR_ELIGIBLE_CONFIDENCE_LEVELS:
                prices_by_workstations.setdefault(workstations, []).append(float(median(prices)))
            else:
                low_confidence_excluded[workstations] = (
                    low_confidence_excluded.get(workstations, 0) + 1
                )

    summaries: list[dict[str, Any]] = []
    for workstations in sorted(observed_workstations):
        prices = sorted(prices_by_workstations.get(workstations, []))
        status = "available"
        if not collection_complete:
            status = "collection_incomplete"
        elif pricing_context is None:
            status = "pricing_context_missing"
        elif len(prices) < MINIMUM_PRICING_SAMPLES:
            status = (
                "insufficient_confident_samples"
                if low_confidence_excluded.get(workstations, 0)
                else "insufficient_samples"
            )
        if status == "available":
            median_adr: float | None = float(median(prices))
            minimum_adr: float | None = float(prices[0])
            maximum_adr: float | None = float(prices[-1])
            recommended_adr: float | None = _round_to_ten(median_adr)
        else:
            # Candidate-level offers remain inspectable, but a partial,
            # incomparable, or insufficient sample must not expose a derived ADR.
            minimum_adr = None
            median_adr = None
            maximum_adr = None
            recommended_adr = None
        summaries.append(
            {
                "workstations": workstations,
                "status": status,
                "sample_count": len(prices),
                "minimum_adr": minimum_adr,
                "median_adr": median_adr,
                "maximum_adr": maximum_adr,
                "recommended_adr": recommended_adr,
                "low_confidence_excluded_property_count": low_confidence_excluded.get(
                    workstations, 0
                ),
            }
        )
    return summaries


def _mark_duplicate_place_ids(classified: list[dict[str, Any]]) -> None:
    by_place_id: dict[str, list[dict[str, Any]]] = {}
    for item in classified:
        place_id = item.get("provider_place_id")
        if isinstance(place_id, str) and place_id:
            by_place_id.setdefault(place_id, []).append(item)

    for duplicates in by_place_id.values():
        if len(duplicates) < 2:
            continue
        for item in duplicates:
            if "provider_place_id_unique" not in item["pending_fields"]:
                item["pending_fields"].append("provider_place_id_unique")
            if "duplicate_provider_place_id" not in item["reason_codes"]:
                item["reason_codes"].append("duplicate_provider_place_id")
            item["classification"] = "evidence_insufficient"
            item["formal_competitor_allowed"] = False


def _exclude_subject_property(
    classified: list[dict[str, Any]], center: Mapping[str, Any]
) -> None:
    center_place_id = center["provider_place_id"]
    for item in classified:
        if (
            item.get("provider") != center["provider"]
            or item.get("provider_place_id") != center_place_id
        ):
            continue
        item["classification"] = "excluded_subject_property"
        item["formal_competitor_allowed"] = False
        item["reason_codes"] = ["candidate_is_subject_property"]
        item["pending_fields"] = []
        item["room_offers"] = []


def _empty_result(status: str, missing_inputs: list[str]) -> dict[str, Any]:
    return {
        "status": status,
        "radius_meters": COMPETITOR_RADIUS_METERS,
        "distance_method": "haversine_straight_line",
        "candidate_count": 0,
        "formal_competitor_count": 0,
        "competitors": [],
        "excluded": [],
        "pricing_by_workstations": [],
        "pricing_context": None,
        "pricing_context_missing": [],
        "missing_inputs": missing_inputs,
    }


def analyze_competitors(request: Mapping[str, Any]) -> dict[str, Any]:
    """Classify a complete 2km candidate set and derive transparent ADR benchmarks.

    The caller owns external collection. This pure function accepts only a confirmed
    Amap center and candidate evidence, then applies the 2km and pure-esports rules.
    """

    if not isinstance(request, Mapping):
        raise CompetitorInputError("competitor analysis request must be an object")
    center, center_missing = _location_result(request)
    if center is None:
        return _empty_result("needs_location_confirmation", center_missing)

    candidates = request.get("candidates")
    if not isinstance(candidates, list):
        return _empty_result("evidence_insufficient", ["candidates"])
    collection_status = request.get("collection_status")
    collection_valid = collection_status in {"complete", "partial"}
    pricing_context, pricing_context_missing = _pricing_context_result(request)

    classified = [_candidate_result(candidate, center) for candidate in candidates]
    _exclude_subject_property(classified, center)
    _mark_duplicate_place_ids(classified)
    competitors = [
        item for item in classified if item["classification"] == "pure_esports_hotel"
    ]
    excluded = [item for item in classified if item["classification"] != "pure_esports_hotel"]
    missing_inputs: list[str] = []
    if not collection_valid:
        missing_inputs.append("collection_status")
    if collection_status == "partial":
        missing_inputs.append("collection_status=complete")
    for index, item in enumerate(classified, start=1):
        if not item["pending_fields"]:
            continue
        identifier = item.get("provider_place_id") or str(index)
        missing_inputs.extend(
            f"candidate[{identifier}].{field}"
            for field in item.get("pending_fields", [])
        )
    collection_complete = collection_status == "complete" and not any(
        item["pending_fields"] for item in classified
    )
    status = "complete" if collection_complete else "evidence_insufficient"
    pricing = _pricing_summary(
        competitors,
        collection_complete,
        pricing_context,
    )

    return {
        "status": status,
        "radius_meters": COMPETITOR_RADIUS_METERS,
        "distance_method": "haversine_straight_line",
        "center": center,
        "candidate_count": len(classified),
        "formal_competitor_count": len(competitors),
        "competitors": competitors,
        "excluded": excluded,
        "pricing_by_workstations": pricing,
        "pricing_context": pricing_context,
        "pricing_context_missing": pricing_context_missing,
        "missing_inputs": missing_inputs,
    }
