"""Single stateless entrypoint for competitor-aware investment underwriting."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import bitable_delivery
import calculate
import competitor_analysis
import competitor_report
import input_contract


_PACKAGE_VERSION_PATH = Path(__file__).resolve().parent.parent / "VERSION"
SKILL_VERSION = f"hotel-investment-underwriting/{_PACKAGE_VERSION_PATH.read_text(encoding='utf-8').strip()}"
_REQUEST_FIELDS = {"project_input", "competitor_analysis", "competitor_report"}


class SkillRunError(ValueError):
    """Raised when a request cannot enter the single-Skill workflow."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _workflow(competitors: Mapping[str, Any]) -> dict[str, Any]:
    pricing = competitors.get("pricing_by_workstations", [])
    pricing_statuses = {item.get("status") for item in pricing}
    unavailable_prices = [
        item
        for item in pricing
        if item.get("status") != "available"
    ]
    if competitors.get("status") != "complete":
        missing = competitors.get("missing_inputs", [])
        suffix = "、".join(str(item) for item in missing) if missing else "已授权候选集"
        return {
            "status": "pre_evaluation_only",
            "competitor_pricing_to_financial_input": "not_applied",
            "conditions": [f"2km竞品分析未完成：请补齐{suffix}"],
        }
    conditions: list[str] = []
    if not pricing:
        conditions.append("2km纯电竞竞品已完成，但没有可用房型报价；请人工确认目标ADR")
    elif "pricing_context_missing" in pricing_statuses:
        conditions.append(
            "2km竞品报价缺少统一报价条件（入住日期、晚数、人数、币种），"
            "未生成对应机位的建议ADR"
        )
    elif "insufficient_confident_samples" in pricing_statuses:
        conditions.append(
            "2km竞品报价的中/高置信度样本不足，低置信度来源未计入建议ADR"
        )
    elif unavailable_prices:
        conditions.append("部分2km竞品报价样本不足，未生成对应机位的建议ADR")
    return {
        "status": "ready_for_review",
        "competitor_pricing_to_financial_input": "not_applied",
        "conditions": conditions,
    }


def _competitor_summary(competitors: Mapping[str, Any]) -> list[str]:
    if competitors.get("status") != "complete":
        missing = competitors.get("missing_inputs", [])
        suffix = "、".join(str(item) for item in missing) if missing else "竞品证据"
        return [f"【2km竞品】未完成：补齐{suffix}后再形成正式竞品结论。"]

    lines = [
        "【2km竞品】"
        f"已完成：纯电竞正式竞品 {competitors.get('formal_competitor_count', 0)} 家，"
        f"候选 {competitors.get('candidate_count', 0)} 家。"
    ]
    unavailable_reasons = {
        "pricing_context_missing": "缺少统一报价条件",
        "insufficient_confident_samples": "中/高置信度样本不足",
        "insufficient_samples": "独立物业样本不足",
        "collection_incomplete": "候选集未完整收集",
    }
    for pricing in competitors.get("pricing_by_workstations", []):
        seats = pricing["workstations"]
        if pricing["status"] == "available":
            lines.append(
                f"{seats}机房建议ADR {pricing['recommended_adr']:.0f}元"
                f"（{pricing['sample_count']}家独立物业，中位数{pricing['median_adr']:.0f}元）。"
            )
        else:
            status = str(pricing["status"])
            reason = unavailable_reasons.get(status, "报价证据不足")
            low_confidence_count = pricing.get(
                "low_confidence_excluded_property_count", 0
            )
            low_confidence_note = (
                f"，另有{low_confidence_count}家低置信度来源未计入"
                if low_confidence_count
                else ""
            )
            lines.append(
                f"{seats}机房报价暂不建议定价（{status}：{reason}，"
                f"样本{pricing['sample_count']}家独立物业{low_confidence_note}）。"
            )
    return lines


def run(request: Mapping[str, Any], defaults: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Run the required 2km analysis and existing financial engine once.

    Competitor-derived ADR is intentionally not merged into `project_input`.
    A reviewer must explicitly choose the financial revenue assumption, so the
    Skill never silently changes an investment conclusion from external evidence.
    """

    if not isinstance(request, Mapping):
        raise SkillRunError("skill request must be an object")
    unknown = set(request) - _REQUEST_FIELDS
    if unknown:
        raise SkillRunError(f"unknown skill request fields: {sorted(unknown)}")
    project_input = request.get("project_input")
    if not isinstance(project_input, Mapping):
        raise SkillRunError("project_input must be an object")
    if defaults is not None and not isinstance(defaults, Mapping):
        raise SkillRunError("defaults must be an object")
    try:
        input_contract.validate_project_fragment(project_input, label="project_input")
        if defaults is not None:
            input_contract.validate_project_fragment(defaults, label="defaults")
        input_contract.validate_project_input(
            calculate.deep_merge(
                dict(defaults) if defaults is not None else {},
                dict(project_input),
            )
        )
    except input_contract.InputContractError as exc:
        raise SkillRunError(str(exc)) from exc

    competitor_input = request.get("competitor_analysis", {})
    competitors = competitor_analysis.analyze_competitors(competitor_input)
    financial_result = calculate.run(
        dict(project_input),
        dict(defaults) if defaults is not None else None,
    )
    workflow = _workflow(competitors)
    financial_result["conclusion_scope"] = workflow["status"]
    summary = _competitor_summary(competitors)
    if workflow["status"] == "pre_evaluation_only":
        summary.append("【财务预评估】以下财务结论不构成完整的2km竞品结论。")
    summary.append(financial_result["feishu_summary"])
    return {
        "status": "ok",
        "skill_version": SKILL_VERSION,
        "input_sha256": _sha256(request),
        "defaults_sha256": _sha256(defaults) if defaults is not None else None,
        "competitor_analysis": competitors,
        "financial_result": financial_result,
        "workflow": workflow,
        "conclusion_scope": workflow["status"],
        "feishu_summary": "\n".join(summary),
    }


def _load_json(path: str) -> dict[str, Any]:
    if path == "-":
        value = json.load(sys.stdin)
    else:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SkillRunError(f"{path} must contain one JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one competitor-aware hotel underwriting Skill")
    parser.add_argument("--input", required=True, help="Skill request JSON path, or - for stdin")
    parser.add_argument("--defaults", help="Optional financial benchmark-defaults JSON path")
    parser.add_argument(
        "--format", choices=("json", "feishu", "html", "bitable"), default="json"
    )
    args = parser.parse_args()
    try:
        request = _load_json(args.input)
        defaults = _load_json(args.defaults) if args.defaults else None
        result = run(request, defaults)
        rendered_html = (
            competitor_report.render_competitor_report(result, request)
            if args.format == "html"
            else None
        )
        rendered_bitable = (
            bitable_delivery.build_manifest(
                result,
                request,
                defaults,
            )
            if args.format == "bitable"
            else None
        )
    except (
        bitable_delivery.BitableDeliveryError,
        SkillRunError,
        input_contract.InputContractError,
        competitor_analysis.CompetitorInputError,
        competitor_report.CompetitorReportError,
        calculate.ModelError,
        json.JSONDecodeError,
        OSError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.format == "feishu":
        print(result["feishu_summary"])
    elif args.format == "html":
        print(rendered_html)
    elif args.format == "bitable":
        print(json.dumps(rendered_bitable, ensure_ascii=False, indent=2, allow_nan=False))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
