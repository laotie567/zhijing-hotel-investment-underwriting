"""Render a portable HTML competitor-research deliverable from one Skill result."""

from __future__ import annotations

import base64
from datetime import datetime
import hashlib
from html import escape
import re
from typing import Any, Mapping
from urllib.parse import urlparse


_IMAGE_DATA_URI = re.compile(
    r"^data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/]+={0,2})$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_IMAGES_PER_CANDIDATE = 4
_MAX_IMAGE_DATA_URI_LENGTH = 2_800_000
_MAX_TOTAL_IMAGE_DATA_URI_LENGTH = 8_000_000
_MAX_CANDIDATE_MEDIA = 30


class CompetitorReportError(ValueError):
    """Raised when display-only competitor evidence is unsafe or malformed."""


def _valid_http_url(value: Any) -> bool:
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


def _valid_image_bytes(media_type: str, payload: str) -> bool:
    try:
        image = base64.b64decode(payload, validate=True)
    except ValueError:
        return False
    if media_type == "jpeg":
        return image.startswith(b"\xff\xd8\xff")
    if media_type == "png":
        return image.startswith(b"\x89PNG\r\n\x1a\n")
    return len(image) >= 12 and image.startswith(b"RIFF") and image[8:12] == b"WEBP"


def _optional_text(value: Any, path: str, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise CompetitorReportError(f"{path} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise CompetitorReportError(f"{path} must be at most {maximum} characters")
    return normalized


def _required_text(value: Any, path: str, maximum: int) -> str:
    result = _optional_text(value, path, maximum)
    if result is None:
        raise CompetitorReportError(f"{path} must be a non-empty string")
    return result


def _normalize_image(value: Any, path: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise CompetitorReportError(f"{path} must be an object")
    unknown = set(value) - {
        "caption",
        "data_uri",
        "source_url",
        "observed_at",
        "mime_type",
        "sha256",
        "room_type_provider_id",
    }
    if unknown:
        raise CompetitorReportError(f"{path} has unknown fields: {sorted(unknown)}")
    caption = _optional_text(value.get("caption"), f"{path}.caption", 240)
    data_uri = value.get("data_uri")
    if not isinstance(data_uri, str) or len(data_uri) > _MAX_IMAGE_DATA_URI_LENGTH:
        raise CompetitorReportError(f"{path}.data_uri must be a bounded image data URI")
    match = _IMAGE_DATA_URI.fullmatch(data_uri)
    if match is None or not _valid_image_bytes(match.group(1), match.group(2)):
        raise CompetitorReportError(f"{path}.data_uri must contain a valid JPEG, PNG or WebP image")
    source_url = value.get("source_url")
    if not _valid_http_url(source_url):
        raise CompetitorReportError(f"{path}.source_url must be an http(s) URL")
    normalized = {
        "caption": caption or "竞品公开图片",
        "data_uri": data_uri,
        "source_url": str(source_url).strip(),
    }
    observed_at = value.get("observed_at")
    if observed_at is not None:
        if not _valid_observed_at(observed_at):
            raise CompetitorReportError(f"{path}.observed_at must be an ISO-8601 datetime with timezone")
        normalized["observed_at"] = str(observed_at).strip()
    mime_type = value.get("mime_type")
    if mime_type is not None:
        if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise CompetitorReportError(f"{path}.mime_type is invalid")
        if not data_uri.startswith(f"data:{mime_type};"):
            raise CompetitorReportError(f"{path}.mime_type must match data_uri")
        normalized["mime_type"] = mime_type
    sha256 = value.get("sha256")
    if sha256 is not None:
        if not isinstance(sha256, str) or _SHA256.fullmatch(sha256) is None:
            raise CompetitorReportError(f"{path}.sha256 must be lowercase SHA-256")
        if hashlib.sha256(base64.b64decode(match.group(2), validate=True)).hexdigest() != sha256:
            raise CompetitorReportError(f"{path}.sha256 does not match data_uri")
        normalized["sha256"] = sha256
    room_type_provider_id = value.get("room_type_provider_id")
    if room_type_provider_id is not None:
        normalized["room_type_provider_id"] = _required_text(
            room_type_provider_id, f"{path}.room_type_provider_id", 240
        )
    return normalized


def validate_report_evidence(value: Any) -> dict[str, Any]:
    """Normalize optional, presentation-only research evidence for the report."""

    if value is None:
        return {"title": None, "candidate_media": []}
    if not isinstance(value, Mapping):
        raise CompetitorReportError("competitor_report must be an object")
    unknown = set(value) - {"title", "candidate_media"}
    if unknown:
        raise CompetitorReportError(
            f"competitor_report has unknown fields: {sorted(unknown)}"
        )
    title = _optional_text(value.get("title"), "competitor_report.title", 160)
    raw_candidates = value.get("candidate_media", [])
    if not isinstance(raw_candidates, list):
        raise CompetitorReportError("competitor_report.candidate_media must be an array")
    if len(raw_candidates) > _MAX_CANDIDATE_MEDIA:
        raise CompetitorReportError(
            "competitor_report.candidate_media exceeds the portable report limit"
        )

    candidate_media: list[dict[str, Any]] = []
    seen_place_ids: set[str] = set()
    total_data_uri_length = 0
    for index, raw_candidate in enumerate(raw_candidates):
        path = f"competitor_report.candidate_media[{index}]"
        if not isinstance(raw_candidate, Mapping):
            raise CompetitorReportError(f"{path} must be an object")
        unknown = set(raw_candidate) - {
            "provider_place_id",
            "renovation_observation",
            "observation_source_url",
            "images",
        }
        if unknown:
            raise CompetitorReportError(f"{path} has unknown fields: {sorted(unknown)}")
        place_id = _optional_text(raw_candidate.get("provider_place_id"), path, 200)
        if place_id is None:
            raise CompetitorReportError(f"{path}.provider_place_id is required")
        if place_id in seen_place_ids:
            raise CompetitorReportError(
                f"competitor_report candidate media must be unique: {place_id}"
            )
        seen_place_ids.add(place_id)
        observation = _optional_text(
            raw_candidate.get("renovation_observation"),
            f"{path}.renovation_observation",
            2_000,
        )
        observation_source_url = raw_candidate.get("observation_source_url")
        if observation is not None and not _valid_http_url(observation_source_url):
            raise CompetitorReportError(
                f"{path}.observation_source_url must be an http(s) URL when an observation is supplied"
            )
        if observation is None and observation_source_url is not None:
            raise CompetitorReportError(
                f"{path}.observation_source_url requires renovation_observation"
            )
        raw_images = raw_candidate.get("images", [])
        if not isinstance(raw_images, list):
            raise CompetitorReportError(f"{path}.images must be an array")
        if len(raw_images) > _MAX_IMAGES_PER_CANDIDATE:
            raise CompetitorReportError(
                f"{path}.images exceeds {_MAX_IMAGES_PER_CANDIDATE} images"
            )
        images = [
            _normalize_image(image, f"{path}.images[{image_index}]")
            for image_index, image in enumerate(raw_images)
        ]
        total_data_uri_length += sum(len(image["data_uri"]) for image in images)
        if total_data_uri_length > _MAX_TOTAL_IMAGE_DATA_URI_LENGTH:
            raise CompetitorReportError(
                "competitor_report embedded images exceed the portable report size limit"
            )
        candidate_media.append(
            {
                "provider_place_id": place_id,
                "renovation_observation": observation,
                "observation_source_url": (
                    str(observation_source_url).strip()
                    if observation_source_url is not None
                    else None
                ),
                "images": images,
            }
        )
    return {"title": title, "candidate_media": candidate_media}


def _text(value: Any) -> str:
    return escape("" if value is None else str(value), quote=True)


def _number(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.0f}"
    return "—"


def _money(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value / 10_000:,.2f} 万元"
    return "—"


def _percent(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.1%}"
    return "—"


def _payback_months(value: Any, rounded_up: Any) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "不回本"
    if isinstance(rounded_up, int) and not isinstance(rounded_up, bool):
        return f"{rounded_up} 个月（测算值 {value:.1f}）"
    return f"{value:.1f} 个月"


def _url(value: Any, label: str = "查看来源") -> str:
    if not _valid_http_url(value):
        return "—"
    return (
        f'<a href="{_text(value)}" rel="noopener noreferrer" target="_blank">'
        f"{_text(label)}</a>"
    )


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return '<p class="empty">暂无可展示数据。</p>'
    header_html = "".join(f"<th scope=\"col\">{_text(header)}</th>" for header in headers)
    body_html = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return (
        '<div class="table-wrap"><table><thead><tr>'
        f"{header_html}</tr></thead><tbody>{body_html}</tbody></table></div>"
    )


def _candidate_media_by_place_id(evidence: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        item["provider_place_id"]: item
        for item in evidence.get("candidate_media", [])
        if isinstance(item, Mapping)
    }


def _validate_candidate_bindings(
    evidence: Mapping[str, Any], competitors: Mapping[str, Any]
) -> None:
    candidate_place_ids = {
        candidate["provider_place_id"].strip()
        for candidate in competitors.get("competitors", [])
        if isinstance(candidate, Mapping)
        and isinstance(candidate.get("provider_place_id"), str)
        and candidate["provider_place_id"].strip()
    }
    unknown_place_ids = sorted(
        item["provider_place_id"]
        for item in evidence.get("candidate_media", [])
        if item["provider_place_id"] not in candidate_place_ids
    )
    if unknown_place_ids:
        raise CompetitorReportError(
            "competitor_report references candidates absent from the formal competitor set: "
            f"{unknown_place_ids}"
        )


def _offer_rows(candidate: Mapping[str, Any]) -> list[list[str]]:
    """Render-only room-offer rows shared by evidence and visual comparisons."""

    offer_rows = []
    for offer in candidate.get("room_offers", []):
        if not isinstance(offer, Mapping):
            continue
        offer_rows.append(
            [
                _text(offer.get("room_type") or "未命名房型"),
                _number(offer.get("workstations")),
                _number(offer.get("nightly_price")),
            ]
        )
    return offer_rows


def _observation_rows(candidate: Mapping[str, Any]) -> list[list[str]]:
    """Show page-observed prices without promoting them into the ADR model."""

    rows = []
    for observation in candidate.get("pricing_observations", []):
        if not isinstance(observation, Mapping):
            continue
        verified = "Network+DOM 已核验" if observation.get("price_match") else "待核验/存在差异"
        qualification_gaps = observation.get("qualification_gaps")
        gaps = "、".join(str(item) for item in qualification_gaps) if isinstance(qualification_gaps, list) else ""
        adr_scope = "可计入 ADR" if observation.get("adr_eligible") is True else (f"仅供展示：{gaps or '口径未齐'}")
        rows.append(
            [
                _text(observation.get("room_type") or "未命名房型"),
                _text(observation.get("price_type") or "页面价格"),
                _number(observation.get("display_price")),
                _text(observation.get("availability") or "unknown"),
                verified,
                adr_scope,
            ]
        )
    return rows


def _candidate_card(candidate: Mapping[str, Any]) -> str:
    name = _text(candidate.get("name") or candidate.get("provider_place_id") or "未命名候选")
    source = candidate.get("source") if isinstance(candidate.get("source"), Mapping) else {}
    source_details = " · ".join(
        part
        for part in (
            _text(source.get("source_platform")) if source.get("source_platform") else "",
            _text(source.get("confidence")) if source.get("confidence") else "",
            _text(source.get("observed_at")) if source.get("observed_at") else "",
        )
        if part
    ) or "来源信息待补齐"
    detail_rows = [
        ["地图实体", _text(candidate.get("provider_place_id") or "—")],
        ["直线距离", f"{_number(candidate.get('distance_meters'))} 米"],
        ["来源", source_details],
        ["来源链接", _url(source.get("source_url"))],
    ]
    return (
        f'<article class="candidate"><h3>{name}</h3>'
        f"{_table(['字段', '值'], detail_rows)}"
        '<h4>已采集房型与报价</h4>'
        f"{_table(['房型', '机位', '同条件房价（元）'], _offer_rows(candidate))}"
        '<h4>携程页面价格观察</h4>'
        f"{_table(['房型', '价格级别', '页面价格（元）', '可订状态', '双证据', 'ADR 资格'], _observation_rows(candidate))}"
        "</article>"
    )


def _visual_benchmark_card(candidate: Mapping[str, Any], media: Mapping[str, Any]) -> str:
    """Render one formal competitor's visual evidence without affecting underwriting."""

    name = _text(candidate.get("name") or candidate.get("provider_place_id") or "未命名候选")
    source = candidate.get("source") if isinstance(candidate.get("source"), Mapping) else {}
    source_details = " · ".join(
        part
        for part in (
            _text(source.get("source_platform")) if source.get("source_platform") else "",
            _text(source.get("confidence")) if source.get("confidence") else "",
            _text(source.get("observed_at")) if source.get("observed_at") else "",
        )
        if part
    ) or "来源信息待补齐"
    observation = media.get("renovation_observation")
    observation_html = (
        '<div class="observation"><strong>装修观察（来源记录）</strong><p>'
        f"{_text(observation)} {_url(media.get('observation_source_url'))}</p></div>"
        if observation
        else ""
    )
    images = media.get("images", [])
    image_html = "".join(
        "<figure>"
        f'<img src="{_text(image["data_uri"])}" alt="{_text(image["caption"])}">'
        f"<figcaption>{_text(image['caption'])} · {_url(image['source_url'])}"
        f"{(' · ' + _text(image['observed_at'])) if image.get('observed_at') else ''}"
        f"{(' · SHA-256 ' + _text(image['sha256'])[:12] + '…') if image.get('sha256') else ''}"
        "</figcaption>"
        "</figure>"
        for image in images
    )
    gallery_html = f'<div class="gallery">{image_html}</div>' if image_html else ""
    return (
        f'<article class="visual-card"><h3>{name}</h3>'
        '<p class="visual-meta">'
        f"直线距离 {_number(candidate.get('distance_meters'))} 米 · {source_details}"
        "</p>"
        f"{observation_html}"
        '<h4>房型与同条件报价</h4>'
        f"{_table(['房型', '机位', '同条件房价（元）'], _offer_rows(candidate))}"
        f"{gallery_html}</article>"
    )


def _financial_summary_section(financial_result: Mapping[str, Any]) -> str:
    """Render finance outputs already computed by the core Skill.

    The report is presentation-only: it reads the deterministic finance result
    and never writes project inputs or mixes it into the competitor conclusion.
    """

    base_case = financial_result.get("base_case")
    if not isinstance(base_case, Mapping):
        return '<p class="empty">暂无可展示的财务测算结果。</p>'
    annual = base_case.get("annual")
    first_year = annual[0] if isinstance(annual, list) and annual and isinstance(annual[0], Mapping) else {}
    rows: list[list[str]] = []
    views = (
        ("智竞未来", base_case.get("jwl"), "jwl_net_cashflow"),
        ("业主（完全成本）", base_case.get("owner_fully_loaded"), "owner_fully_loaded_net_cashflow"),
    )
    for label, metrics, first_year_cashflow_key in views:
        if not isinstance(metrics, Mapping):
            continue
        rows.append(
            [
                label,
                _money(metrics.get("initial_capex")),
                _money(first_year.get(first_year_cashflow_key)),
                _payback_months(
                    metrics.get("static_payback_months"),
                    metrics.get("static_payback_months_rounded_up"),
                ),
                _payback_months(
                    metrics.get("discounted_payback_months"),
                    metrics.get("discounted_payback_months_rounded_up"),
                ),
                _percent(metrics.get("irr")),
                _money(metrics.get("npv")),
            ]
        )
    if not rows:
        return '<p class="empty">暂无可展示的财务测算结果。</p>'
    return (
        _table(
            ["视角", "一次性初投", "首年经营净现金", "静态回本", "动态回本（折现）", "IRR", "NPV"],
            rows,
        )
        + '<p class="muted">静态回本沿用历史投资表“回款周期/月”口径：一次性初投 ÷ 首年平均月经营净现金；不含后续设备重置和末期残值。动态回本保留完整年度现金流、重置、残值与折现口径，按 12 个月/年表达。</p>'
    )


def render_competitor_report(
    result: Mapping[str, Any], request: Mapping[str, Any]
) -> str:
    """Return a no-JavaScript, self-contained mobile-friendly HTML document."""

    if not isinstance(result, Mapping) or not isinstance(request, Mapping):
        raise CompetitorReportError("report rendering requires Skill result and request objects")
    evidence = validate_report_evidence(request.get("competitor_report"))
    competitors = result.get("competitor_analysis")
    if not isinstance(competitors, Mapping):
        raise CompetitorReportError("Skill result does not contain competitor_analysis")
    _validate_candidate_bindings(evidence, competitors)
    financial_result = result.get("financial_result")
    project_name = (
        financial_result.get("project_name")
        if isinstance(financial_result, Mapping)
        else None
    )
    project_name = project_name if isinstance(project_name, str) and project_name else "酒店项目"
    title = evidence.get("title") or f"{project_name}｜2km竞品调研报告"
    workflow = result.get("workflow") if isinstance(result.get("workflow"), Mapping) else {}
    is_complete = result.get("conclusion_scope") == "ready_for_review"
    status_title = (
        "2km正式竞品集合已完成"
        if is_complete
        else "预评估：正式竞品结论未完成"
    )
    status_detail = (
        "本报告可用于审阅已采集证据；任何建议 ADR 仍须以结构化结果为准。"
        if is_complete
        else "本报告展示已采集证据与缺失项，不构成完整的 2km 竞品或 ADR 结论。"
    )
    missing_inputs = competitors.get("missing_inputs", [])
    missing_html = "".join(
        f"<li>{_text(item)}</li>" for item in missing_inputs if isinstance(item, str)
    ) or "<li>无</li>"
    center = competitors.get("center") if isinstance(competitors.get("center"), Mapping) else {}
    center_rows = [
        ["竞品分析状态", _text(competitors.get("status") or "—")],
        ["2km中心地图 provider", _text(center.get("provider") or "待确认")],
        ["中心地图实体 ID", _text(center.get("provider_place_id") or "待确认")],
        ["分析半径", f"{_number(competitors.get('radius_meters'))} 米"],
        ["距离方法", _text(competitors.get("distance_method") or "—")],
    ]
    pricing_rows = []
    for pricing in competitors.get("pricing_by_workstations", []):
        if not isinstance(pricing, Mapping):
            continue
        pricing_rows.append(
            [
                _number(pricing.get("workstations")),
                _text(pricing.get("status") or "—"),
                _number(pricing.get("sample_count")),
                _number(pricing.get("minimum_adr")),
                _number(pricing.get("median_adr")),
                _number(pricing.get("maximum_adr")),
                _number(pricing.get("recommended_adr")),
            ]
        )
    pricing_context = (
        competitors.get("pricing_context")
        if isinstance(competitors.get("pricing_context"), Mapping)
        else None
    )
    pricing_context_rows = (
        [
            ["入住日期", _text(pricing_context.get("check_in_date") or "—")],
            ["晚数", _number(pricing_context.get("nights"))],
            ["入住人数", _number(pricing_context.get("guests"))],
            ["币种", _text(pricing_context.get("currency") or "—")],
        ]
        if pricing_context is not None
        else [["报价口径", "未形成统一报价口径；不生成建议 ADR。"]]
    )
    media_by_place_id = _candidate_media_by_place_id(evidence)
    formal_cards = "".join(
        _candidate_card(candidate)
        for candidate in competitors.get("competitors", [])
        if isinstance(candidate, Mapping)
    ) or '<p class="empty">暂无正式竞品。</p>'
    visual_cards = "".join(
        _visual_benchmark_card(candidate, media)
        for candidate in competitors.get("competitors", [])
        if isinstance(candidate, Mapping)
        for media in [media_by_place_id.get(str(candidate.get("provider_place_id")))]
        if isinstance(media, Mapping)
        and (media.get("renovation_observation") or media.get("images"))
    )
    visual_content = (
        f'<div class="visual-grid">{visual_cards}</div>'
        if visual_cards
        else (
            '<p class="empty">暂无可追溯的竞品房图或装修观察；请由宿主按正式竞品 '
            'provider_place_id 补齐来源记录和选定图片。</p>'
        )
    )
    excluded_rows = []
    for candidate in competitors.get("excluded", []):
        if not isinstance(candidate, Mapping):
            continue
        excluded_rows.append(
            [
                _text(candidate.get("name") or candidate.get("provider_place_id") or "未命名"),
                _text(candidate.get("classification") or "—"),
                _text("、".join(candidate.get("reason_codes", []))),
                _text("、".join(candidate.get("pending_fields", []))),
            ]
        )
    conditions_html = "".join(
        f"<li>{_text(condition)}</li>"
        for condition in workflow.get("conditions", [])
        if isinstance(condition, str)
    ) or "<li>无</li>"
    financial_summary = (
        _financial_summary_section(financial_result)
        if isinstance(financial_result, Mapping)
        else '<p class="empty">暂无可展示的财务测算结果。</p>'
    )
    css = """
      :root { color-scheme: light; --ink:#172033; --muted:#586174; --line:#dfe5ef;
        --brand:#2957d4; --soft:#f4f7ff; --warn:#8d5500; --warn-bg:#fff7e8; }
      * { box-sizing:border-box; } body { margin:0; background:#f5f7fb; color:var(--ink);
        font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",
        "Microsoft YaHei",sans-serif; }
      main { max-width:1100px; margin:0 auto; padding:24px 16px 48px; }
      header, section, article { background:#fff; border:1px solid var(--line); border-radius:14px;
        box-shadow:0 2px 8px rgba(23,32,51,.04); }
      header { padding:28px; background:linear-gradient(135deg,#fff 0%,var(--soft) 100%); }
      section { margin-top:16px; padding:22px; } article { margin-top:14px; padding:18px; }
      h1,h2,h3,h4 { line-height:1.25; } h1 { margin:0 0 8px; font-size:clamp(24px,5vw,38px); }
      h2 { font-size:20px; margin:0 0 14px; } h3 { font-size:18px; margin:0 0 12px; }
      h4 { margin:18px 0 8px; font-size:15px; } p { margin:8px 0; }
      p,li,th,td,h1,h2,h3,h4 { overflow-wrap:anywhere; } .meta,.muted { color:var(--muted); }
      .status { margin-top:16px; padding:12px 14px; border-radius:10px; background:var(--warn-bg);
        color:var(--warn); } .status.complete { background:#edf8f1; color:#17673b; }
      .table-wrap { overflow-x:auto; border:1px solid var(--line); border-radius:10px; }
      table { width:100%; min-width:560px; border-collapse:collapse; } th,td { padding:10px 12px;
        text-align:left; vertical-align:top; border-bottom:1px solid var(--line); } th { background:#f8faff;
        color:#39445b; font-weight:650; } tr:last-child td { border-bottom:0; }
      a { color:var(--brand); word-break:break-all; } .candidate,.visual-card { border-left:4px solid var(--brand); }
      .gallery { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:12px;
        margin-top:14px; } figure { margin:0; border:1px solid var(--line); border-radius:10px;
        overflow:hidden; background:#fff; } img { display:block; width:100%; height:160px; object-fit:cover;
        background:#edf1f7; } figcaption { padding:8px 10px; color:var(--muted); font-size:13px; }
      .observation { margin-top:14px; padding:12px; border-radius:10px; background:var(--soft); }
      .visual-guidance { margin:0 0 16px; padding:12px 14px; border-radius:10px; background:var(--soft); }
      .visual-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:14px; }
      .visual-card { margin:0; } .visual-meta { color:var(--muted); font-size:13px; }
      .visual-card .gallery img { height:210px; }
      .empty { color:var(--muted); font-style:italic; } ul { margin:8px 0 0; padding-left:20px; }
      footer { color:var(--muted); font-size:12px; padding:16px 4px 0; }
      @media (max-width:620px) { main { padding:12px 10px 28px; } header,section { padding:18px; }
        .table-wrap { width:100%; max-width:100%; min-width:0; }
        table { min-width:0; table-layout:fixed; } th,td { padding:8px 10px; overflow-wrap:anywhere; } }
      @media print { body { background:#fff; } main { max-width:none; padding:0; } header,section,article {
        box-shadow:none; break-inside:avoid; } a { color:inherit; text-decoration:none; } }
    """
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">
  <title>{_text(title)}</title>
  <style>{css}</style>
</head>
<body>
  <main>
    <header>
      <p class="meta">独立 HTML 交付物 · 2km 竞品调研</p>
      <h1>{_text(title)}</h1>
      <p class="meta">Skill 版本：{_text(result.get('skill_version') or '—')} · 输入指纹：{_text(result.get('input_sha256') or '—')}</p>
      <div class="status{' complete' if is_complete else ''}">
        <strong>{_text(status_title)}</strong><br>{_text(status_detail)}
      </div>
    </header>
    <section>
      <h2>1. 分析边界与完成状态</h2>
      {_table(['字段', '值'], center_rows)}
      <h3>待补齐项</h3><ul>{missing_html}</ul>
      <h3>工作流条件</h3><ul>{conditions_html}</ul>
    </section>
    <section>
      <h2>2. 正式竞品与房型证据</h2>
      <p class="muted">正式竞品：{_number(competitors.get('formal_competitor_count'))} 家；候选：{_number(competitors.get('candidate_count'))} 家。</p>
      {formal_cards}
    </section>
    <section>
      <h2>3. 视觉竞品对标</h2>
      <p class="visual-guidance"><strong>使用方式：</strong>仅用于人工调价研判。请结合房图中的装修维护、机位桌面、卫生与灯光等可见状态，以及同条件房型报价综合判断；图片不自动变更 ADR 或财务输入。</p>
      {visual_content}
    </section>
    <section>
      <h2>4. 机位 ADR 参考</h2>
      <p class="muted">只有状态为 available 的机位才可形成建议 ADR；其余聚合值按数据契约保持为空。</p>
      <h3>报价口径</h3>
      {_table(['字段', '值'], pricing_context_rows)}
      {_table(['机位', '状态', '样本', '最低 ADR', '中位 ADR', '最高 ADR', '建议 ADR'], pricing_rows)}
    </section>
    <section>
      <h2>5. 排除与待补证候选</h2>
      {_table(['候选', '分类', '原因', '待补字段'], excluded_rows)}
    </section>
    <section>
      <h2>6. 投资回报与回本周期</h2>
      {financial_summary}
    </section>
    <section>
      <h2>7. 与投资测算的衔接</h2>
      <p>结论范围：<strong>{_text(result.get('conclusion_scope') or '—')}</strong>；竞品建议 ADR 到财务输入：<strong>{_text(workflow.get('competitor_pricing_to_financial_input') or '—')}</strong>。</p>
      <p class="muted">本报告不自动改写财务收入假设；图片和装修观察均为宿主提供的来源记录，不替代现场踏勘。</p>
    </section>
    <footer>该文件不加载外部脚本、样式或图片。内嵌图片可离线打开；来源链接仅用于追溯。</footer>
  </main>
</body>
</html>
"""
