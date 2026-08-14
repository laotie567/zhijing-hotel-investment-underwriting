#!/usr/bin/env python3
"""Parse one already-captured Ctrip room-panel HTML fragment offline.

This narrow CLI intentionally owns no browser, network request, credential,
cookie, page navigation or adaptive state by default.  Ui.Vision performs page
actions and OpenCLI supplies the fragment; this tool only turns that fragment
into candidates for the existing Network/DOM validator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping
from urllib.parse import urlparse


PARSER_VERSION = "ctrip-dom-parser/v1"
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = PACKAGE_ROOT / "collector" / "ctrip_element_registry.json"
MAX_FRAGMENT_BYTES = 1_000_000
_PRICE = re.compile(r"(?:￥|¥)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)")
_WORKSTATIONS = re.compile(r"([1-9][0-9]?)\s*(?:台|机|电脑)")


class CtripDomParserError(ValueError):
    """Raised when an offline DOM parsing request is not safe or complete."""


def _text(value: Any, maximum: int = 500) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:maximum]


def _load_registry() -> dict[str, Any]:
    value = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("roles"), dict):
        raise CtripDomParserError("bundled Ctrip element registry is invalid")
    if value.get("registry_version") != "ctrip-element-registry/v1":
        raise CtripDomParserError("bundled Ctrip element registry version is unsupported")
    return value


def _load_request(stream: Any) -> dict[str, Any]:
    try:
        value = json.load(stream)
    except json.JSONDecodeError as exc:
        raise CtripDomParserError("input must be one JSON object") from exc
    if not isinstance(value, dict):
        raise CtripDomParserError("input must be one JSON object")
    unknown = set(value) - {"source_url", "dom_fragment", "pricing_context"}
    if unknown:
        raise CtripDomParserError(f"input has unknown fields: {sorted(unknown)}")
    source_url = value.get("source_url")
    if not isinstance(source_url, str):
        raise CtripDomParserError("source_url must be an HTTPS Ctrip URL")
    parsed = urlparse(source_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or (parsed.hostname != "ctrip.com" and not parsed.hostname.endswith(".ctrip.com"))
    ):
        raise CtripDomParserError("source_url must be an HTTPS Ctrip URL")
    fragment = value.get("dom_fragment")
    if not isinstance(fragment, str) or not fragment.strip():
        raise CtripDomParserError("dom_fragment must be a non-empty HTML string")
    if len(fragment.encode("utf-8")) > MAX_FRAGMENT_BYTES:
        raise CtripDomParserError(f"dom_fragment must be at most {MAX_FRAGMENT_BYTES} bytes")
    context = value.get("pricing_context")
    if not isinstance(context, Mapping):
        raise CtripDomParserError("pricing_context must be an object")
    expected = {"check_in_date", "nights", "guests", "currency"}
    if set(context) != expected:
        raise CtripDomParserError("pricing_context must contain exactly check_in_date, nights, guests, currency")
    if (
        not isinstance(context["check_in_date"], str)
        or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", context["check_in_date"])
        or not isinstance(context["nights"], int)
        or not 1 <= context["nights"] <= 30
        or not isinstance(context["guests"], int)
        or not 1 <= context["guests"] <= 12
        or context["currency"] != "CNY"
    ):
        raise CtripDomParserError("pricing_context is invalid")
    return {"source_url": source_url, "dom_fragment": fragment, "pricing_context": dict(context)}


def _require_scrapling() -> Any:
    try:
        from scrapling import Selector
    except ImportError as exc:
        raise CtripDomParserError(
            "Scrapling parser dependency is unavailable; install collector/requirements-scrapling.txt with Python 3.10+"
        ) from exc
    return Selector


def _adaptive_url(source_url: str) -> str:
    """Use a stable host-scoped key, never the hotel/date-specific page URL."""

    return f"https://{urlparse(source_url).hostname}/ctrip-dom-parser/v1"


def _node_text(node: Any, selectors: list[str]) -> str:
    for selector in selectors:
        matches = node.css(selector)
        if matches:
            value = _text(matches[0].text)
            if value:
                return value
    return ""


def _node_attribute(node: Any, selectors: list[str], attribute: str) -> str:
    for selector in selectors:
        matches = node.css(selector)
        if matches:
            value = _text(matches[0].attrib.get(attribute, ""), 200)
            if value:
                return value
    return ""


def _role_selectors(registry: Mapping[str, Any], role: str) -> tuple[list[str], list[str]]:
    definition = registry["roles"].get(role)
    if not isinstance(definition, Mapping):
        raise CtripDomParserError(f"registry role {role} is unavailable")
    primary = definition.get("primary_selectors")
    fallback = definition.get("fallback_selectors")
    if not isinstance(primary, list) or not isinstance(fallback, list):
        raise CtripDomParserError(f"registry role {role} has invalid selectors")
    return [str(item) for item in primary], [str(item) for item in fallback]


def _single_room_container(
    page: Any,
    registry: Mapping[str, Any],
    *,
    save_adaptive: bool,
    enable_adaptive: bool,
) -> tuple[Any | None, str]:
    definition = registry["roles"]["room_container"]
    primary, fallback = _role_selectors(registry, "room_container")
    identifier = str(definition["adaptive_identifier"])
    for selector in primary:
        matches = page.css(selector, identifier=identifier, auto_save=save_adaptive)
        if matches:
            return matches[0], "primary"
    for selector in fallback:
        matches = page.css(selector, identifier=identifier, auto_save=save_adaptive)
        if matches:
            return matches[0], "fallback"
    if enable_adaptive and definition.get("adaptive_allowed"):
        for selector in primary:
            matches = page.css(selector, identifier=identifier, adaptive=True)
            if matches:
                return matches[0], "adaptive"
    return None, "missing"


def _cards(container: Any, registry: Mapping[str, Any]) -> list[Any]:
    primary, fallback = _role_selectors(registry, "room_card")
    for selector in [*primary, *fallback]:
        cards = container.css(selector)
        if cards:
            return list(cards)
    return []


def _availability(value: str) -> str:
    normalized = _text(value, 200)
    if normalized == "available" or re.search(r"可订|立即预订|有房", normalized):
        return "available"
    if normalized == "sold_out" or re.search(r"已订完|售罄|满房|不可订|暂无房", normalized):
        return "sold_out"
    return "unknown"


def _price(value: str) -> int | None:
    match = _PRICE.search(value)
    if not match:
        return None
    parsed = float(match.group(1).replace(",", ""))
    if parsed <= 0 or parsed >= 100_000 or not parsed.is_integer():
        return None
    return int(parsed)


def _workstations(value: str, attribute: str) -> int | None:
    if attribute.isdigit() and 1 <= int(attribute) <= 99:
        return int(attribute)
    match = _WORKSTATIONS.search(value)
    return int(match.group(1)) if match else None


def _tax_included(value: str) -> bool | None:
    """Keep an absent tax label unknown; absence is never "not included"."""

    normalized = _text(value, 300)
    if re.search(r"不含税|另付税|税费另计", normalized):
        return False
    if re.search(r"含税|税费已含", normalized):
        return True
    return None


def _room(card: Any, registry: Mapping[str, Any]) -> dict[str, Any] | None:
    def selectors(role: str) -> list[str]:
        primary, fallback = _role_selectors(registry, role)
        return [*primary, *fallback]

    room_id = _text(card.attrib.get("data-room-id") or card.attrib.get("data-room-ref"), 200)
    room_name = _node_text(card, selectors("room_name"))
    price_text = _node_text(card, selectors("price"))
    price_attribute = _node_attribute(card, selectors("price"), "data-price")
    display_price = _price(f"¥{price_attribute}") if price_attribute else _price(price_text)
    # A rendered DOM block has no trustworthy provider room ID on some Ctrip
    # layouts. The later Network/DOM matcher supplies the provider ID from the
    # network side; inventing one here would make the evidence less reliable.
    if not room_name or display_price is None:
        return None
    availability_text = _node_attribute(card, selectors("availability"), "data-availability") or _node_text(card, selectors("availability"))
    tax_text = _node_text(card, selectors("tax_scope"))
    cancellation = _node_text(card, selectors("cancellation"))
    workstation_text = _node_text(card, selectors("workstations"))
    workstation_attribute = _node_attribute(card, selectors("workstations"), "data-workstations")
    return {
        "room_id": room_id or None,
        "room_name": room_name,
        "rate_plan_name": _node_text(card, selectors("rate_plan")),
        "display_price": display_price,
        "availability": _availability(availability_text),
        "tax_included": _tax_included(tax_text),
        "cancellation_policy": cancellation or None,
        "workstations": _workstations(workstation_text, workstation_attribute),
        "selector_source": "primary",
        "adaptive_recovered": False,
        "requires_cross_validation": True,
    }


def _context_evidence(page: Any, context: Mapping[str, Any]) -> dict[str, Any]:
    check_in = _node_attribute(page, ["[data-check-in]"], "data-check-in")
    check_out = _node_attribute(page, ["[data-check-out]"], "data-check-out")
    guests = _node_attribute(page, ["[data-guests]"], "data-guests")
    expected_checkout_day = None
    try:
        from datetime import date, timedelta

        expected_checkout_day = (
            date.fromisoformat(str(context["check_in_date"]))
            + timedelta(days=int(context["nights"]))
        ).isoformat()
    except ValueError:
        pass
    verified = (
        check_in == context["check_in_date"]
        and check_out == expected_checkout_day
        and guests == str(context["guests"])
    )
    return {
        "check_in_date": check_in or None,
        "check_out_date": check_out or None,
        "guests": int(guests) if guests.isdigit() else None,
        "verified": verified,
    }


def parse(value: Mapping[str, Any], *, adaptive_store: str | None, save_adaptive: bool, enable_adaptive: bool) -> dict[str, Any]:
    request = _load_request_text(value)
    registry = _load_registry()
    if (save_adaptive or enable_adaptive) and not adaptive_store:
        raise CtripDomParserError("adaptive_store is required when adaptive parsing is requested")
    Selector = _require_scrapling()
    selector_kwargs: dict[str, Any] = {"url": _adaptive_url(request["source_url"])}
    if adaptive_store:
        selector_kwargs.update(
            {
                "adaptive": True,
                "storage_args": {
                    "storage_file": adaptive_store,
                    "url": _adaptive_url(request["source_url"]),
                },
            }
        )
    page = Selector(request["dom_fragment"], **selector_kwargs)
    container, source = _single_room_container(
        page,
        registry,
        save_adaptive=save_adaptive,
        enable_adaptive=enable_adaptive,
    )
    rooms = [_room(card, registry) for card in _cards(container, registry)] if container is not None else []
    normalized_rooms = [room for room in rooms if room is not None]
    return {
        "parser_version": PARSER_VERSION,
        "registry_version": registry["registry_version"],
        "status": "ok" if container is not None and normalized_rooms else "schema_drift",
        "room_container": {
            "semantic_id": registry["roles"]["room_container"]["semantic_id"],
            "selector_source": source,
            "adaptive_recovered": source == "adaptive",
        },
        "context_evidence": _context_evidence(page, request["pricing_context"]),
        "rooms": normalized_rooms,
        "evidence": {
            "source_url": request["source_url"],
            "dom_fragment_sha256": hashlib.sha256(
                request["dom_fragment"].encode("utf-8")
            ).hexdigest(),
        },
    }


def _load_request_text(value: Mapping[str, Any]) -> dict[str, Any]:
    """Use the same validation for programmatic calls without accepting a stream."""

    encoded = json.dumps(value, ensure_ascii=False)
    return _load_request_text_from_json(encoded)


def _load_request_text_from_json(encoded: str) -> dict[str, Any]:
    from io import StringIO

    return _load_request(StringIO(encoded))


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse one already-captured Ctrip room-panel HTML fragment")
    parser.add_argument("--input", required=True, help="JSON input path or - for stdin")
    parser.add_argument("--adaptive-store", help="Explicit host-managed SQLite path for Scrapling adaptive metadata")
    parser.add_argument("--save-adaptive", action="store_true", help="Save the known room-container selector metadata")
    parser.add_argument("--enable-adaptive", action="store_true", help="Use saved room-container metadata only after primary/fallback selectors fail")
    args = parser.parse_args()
    try:
        if args.input == "-":
            request = _load_request(sys.stdin)
        else:
            request = _load_request_text_from_json(Path(args.input).read_text(encoding="utf-8"))
        result = parse(
            request,
            adaptive_store=args.adaptive_store,
            save_adaptive=args.save_adaptive,
            enable_adaptive=args.enable_adaptive,
        )
    except (CtripDomParserError, OSError) as exc:
        print(f"ctrip_dom_parser: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
