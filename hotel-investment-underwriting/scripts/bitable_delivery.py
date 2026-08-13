"""Build the portable Feishu Bitable delivery manifest for underwriting.

This module is intentionally dependency-free and never calls Feishu.  The
published Skill remains the calculation owner; an authorised host turns this
manifest into Base tables and records using its own Feishu identity.
"""

from __future__ import annotations

from copy import deepcopy
import math
import re
from typing import Any, Iterable, Mapping

import calculate
import competitor_report


MANIFEST_VERSION = "1.1"
BASE_NAME = "智竞酒店投资分析交付"
_DELIVERY_COMPLETENESS = ("待写入核验", "可交付", "待补证据")
_DELIVERY_RECORD_STATUSES = (
    "已提供",
    "待补房型",
    "待补2km竞品",
    "待补视觉图片",
    "检索完成无正式竞品",
)


class BitableDeliveryError(ValueError):
    """Raised when a Skill result cannot be expressed as a safe Base delivery."""


def _text(name: str, *, url: bool = False) -> dict[str, Any]:
    field: dict[str, Any] = {"type": "text", "name": name}
    if url:
        field["style"] = {"type": "url"}
    return field


def _number(
    name: str, *, percentage: bool = False, currency: bool = False, precision: int = 2
) -> dict[str, Any]:
    if currency:
        style: dict[str, Any] = {
            "type": "currency",
            "precision": precision,
            "currency_code": "CNY",
        }
    else:
        style = {
            "type": "plain",
            "precision": precision,
            "percentage": percentage,
            "thousands_separator": not percentage,
        }
    return {"type": "number", "name": name, "style": style}


def _select(name: str, options: Iterable[str], *, multiple: bool = False) -> dict[str, Any]:
    return {
        "type": "select",
        "name": name,
        "multiple": multiple,
        "options": [{"name": option} for option in options],
    }


def _link(name: str, table: str) -> dict[str, Any]:
    return {"type": "link", "name": name, "link_table": table, "bidirectional": False}


def _table(name: str, key: str, fields: list[dict[str, Any]]) -> dict[str, Any]:
    return {"name": name, "record_key_field": key, "fields": fields}


def standard_template() -> dict[str, Any]:
    """Return a new copy of the standard, calculation-free Base template."""

    tables = [
        _table(
            "项目测算总表",
            "项目运行ID",
            [
                _text("项目运行ID"),
                _text("项目名称"),
                _text("资料截至"),
                _select("结论范围", ("ready_for_review", "pre_evaluation_only")),
                _select("交付完整性", _DELIVERY_COMPLETENESS),
                _text("交付待补项"),
                _select("决策评级", ("建议合作", "条件性推进", "审慎推进", "不建议合作")),
                _select("数据置信度", ("high", "medium", "low")),
                _select("准入状态", ("pass", "conditional", "fail", "not_evaluated")),
                _number("准入加权评分", precision=2),
                _select(
                    "2km竞品状态",
                    ("complete", "evidence_insufficient", "needs_location_confirmation"),
                ),
                _number("正式竞品数（家）", precision=0),
                _text("2km中心提供商"),
                _text("2km中心地点ID"),
                _number("合作房间数（间）", precision=0),
                _number("总机位数（台）", precision=0),
                _number("合作年限（年）", precision=0),
                _number("经营天数（天）", precision=0),
                _number("首年OCC", percentage=True, precision=4),
                _number("首年ADR（元）", currency=True),
                _number("首年RevPAR（元）", currency=True),
                _number("首年营业总收入（元）", currency=True),
                _number("首年公共成本（元）", currency=True),
                _number("首年可分配净收入（元）", currency=True),
                _number("智竞初始投入（元）", currency=True),
                _number("智竞首年经营净现金（元）", currency=True),
                _number("智竞静态回本（月，测算值）", precision=2),
                _number("智竞静态回本（月，向上取整）", precision=0),
                _number("智竞动态回本（月，测算值）", precision=2),
                _number("智竞动态回本（月，向上取整）", precision=0),
                _number("智竞IRR", percentage=True, precision=4),
                _number("智竞NPV（元）", currency=True),
                _number("智竞盈亏平衡OCC", percentage=True, precision=4),
                _number("业主初始投入（元）", currency=True),
                _number("业主完全成本首年净现金（元）", currency=True),
                _number("业主完全成本静态回本（月，向上取整）", precision=0),
                _number("业主完全成本动态回本（月，向上取整）", precision=0),
                _number("业主完全成本IRR", percentage=True, precision=4),
                _number("业主完全成本NPV（元）", currency=True),
                _number("合同退出红线OCC", percentage=True, precision=4),
                _text("风险与待办"),
                _text("输入SHA256"),
                _text("Skill版本"),
                {"type": "created_at", "name": "飞书创建时间", "style": {"format": "yyyy-MM-dd HH:mm"}},
            ],
        ),
        _table(
            "输入参数与来源",
            "参数记录ID",
            [
                _text("参数记录ID"),
                _link("关联项目运行", "项目测算总表"),
                _text("模型路径"),
                _text("参数名称"),
                _text("模块"),
                _number("数值（数字）", precision=4),
                _text("数值（文本）"),
                _text("单位"),
                _select("取值来源", ("项目输入", "基准默认")),
                _text("证据来源类别"),
                _text("证据来源"),
                _text("证据日期"),
                _text("证据状态"),
                _text("证据审批人"),
            ],
        ),
        _table(
            "投资与成本明细",
            "成本记录ID",
            [
                _text("成本记录ID"),
                _link("关联项目运行", "项目测算总表"),
                _select(
                    "成本类别",
                    (
                        "智竞CapEx",
                        "智竞设备重置",
                        "业主CapEx",
                        "智竞年现金OpEx",
                        "业主年增量现金OpEx",
                        "业主年完全成本现金OpEx",
                    ),
                ),
                _select("所属方", ("智竞", "业主")),
                _text("成本项目"),
                _number("对应年度", precision=0),
                _number("金额（元）", currency=True),
                _text("口径说明"),
            ],
        ),
        _table(
            "年度收入与现金流",
            "年度记录ID",
            [
                _text("年度记录ID"),
                _link("关联项目运行", "项目测算总表"),
                _number("预测年度", precision=0),
                _number("OCC", percentage=True, precision=4),
                _number("ADR（元）", currency=True),
                _number("RevPAR（元）", currency=True),
                _number("可售房晚（间夜）", precision=2),
                _number("已售房晚（间夜）", precision=2),
                _number("过夜房费收入（元）", currency=True),
                _number("钟点/包场收入（元）", currency=True),
                _number("衍生收入（元）", currency=True),
                _number("其他收入（元）", currency=True),
                _number("营业总收入（元）", currency=True),
                _number("OTA佣金（元）", currency=True),
                _number("投流费（元）", currency=True),
                _number("刷单/探店费（元）", currency=True),
                _number("线下推广费（元）", currency=True),
                _number("OTA运营绩效（元）", currency=True),
                _number("共享经理成本（元）", currency=True),
                _number("流转税（元）", currency=True),
                _number("公共成本合计（元）", currency=True),
                _number("可分配净收入（元）", currency=True),
                _number("智竞分成收入（元）", currency=True),
                _number("智竞现金OpEx（元）", currency=True),
                _number("智竞折旧（元）", currency=True),
                _number("智竞会计利润（元）", currency=True),
                _number("智竞设备重置（元）", currency=True),
                _number("智竞净现金流（元）", currency=True),
                _number("业主分成收入（元）", currency=True),
                _number("业主增量现金OpEx（元）", currency=True),
                _number("业主完全成本现金OpEx（元）", currency=True),
                _number("业主折旧（元）", currency=True),
                _number("业主增量净现金流（元）", currency=True),
                _number("业主完全成本净现金流（元）", currency=True),
                _number("传统房基线收入（元）", currency=True),
                _number("被替代传统房贡献（元）", currency=True),
                _number("业主经济增量净现金流（元）", currency=True),
            ],
        ),
        _table(
            "情景与敏感性",
            "分析记录ID",
            [
                _text("分析记录ID"),
                _link("关联项目运行", "项目测算总表"),
                _select("分析类型", ("情景", "敏感性")),
                _text("分析名称"),
                _text("变量路径"),
                _number("基准值", precision=4),
                _number("入住率OCC", percentage=True, precision=4),
                _number("首年营业总收入（元）", currency=True),
                _number("智竞首年净现金流（元）", currency=True),
                _number("智竞静态回本（月，向上取整）", precision=0),
                _number("智竞动态回本（月，向上取整）", precision=0),
                _number("智竞IRR", percentage=True, precision=4),
                _number("智竞NPV（元）", currency=True),
                _number("NPV下调10%情景（元）", currency=True),
                _number("NPV上调10%情景（元）", currency=True),
                _number("NPV波动（元）", currency=True),
                _number("影响排序值", currency=True),
            ],
        ),
        _table(
            "房型配置",
            "房型记录ID",
            [
                _text("房型记录ID"),
                _link("关联项目运行", "项目测算总表"),
                _select("交付状态", _DELIVERY_RECORD_STATUSES),
                _text("房型名称"),
                _number("房间数", precision=0),
                _number("每间机位数", precision=2),
                _number("电竞ADR（元）", currency=True),
                _number("电竞RevPAR（元）", currency=True),
                _number("电竞OCC", percentage=True, precision=4),
                _number("传统ADR（元）", currency=True),
                _number("传统RevPAR（元）", currency=True),
                _number("传统OCC", percentage=True, precision=4),
                _number("传统贡献毛利率", percentage=True, precision=4),
            ],
        ),
        _table(
            "2km竞品",
            "竞品记录ID",
            [
                _text("竞品记录ID"),
                _link("关联项目运行", "项目测算总表"),
                _select("交付状态", _DELIVERY_RECORD_STATUSES),
                _text("竞品名称"),
                _text("地图提供商"),
                _text("提供商地点ID"),
                _text("分类"),
                {"type": "checkbox", "name": "正式竞品"},
                _number("直线距离（米）", precision=3),
                _text("美团等级/冠"),
                _text("开业/装修"),
                _number("房间数", precision=0),
                _text("图片质量"),
                _text("基础设施"),
                _text("酒店特色"),
                _number("平台评分", precision=2),
                _number("评论数", precision=0),
                _text("周边说明"),
                _number("房型报价数", precision=0),
                _text("OTA平台"),
                _text("OTA酒店ID"),
                _text("OTA匹配方式"),
                _text("调研来源平台"),
                _text("来源URL", url=True),
                _text("采集时间"),
                _select("证据置信度", ("low", "medium", "high")),
                _text("排除/提示原因"),
                _text("待补齐字段"),
            ],
        ),
        _table(
            "竞品报价与视觉证据",
            "证据记录ID",
            [
                _text("证据记录ID"),
                _link("关联项目运行", "项目测算总表"),
                _link("关联竞品", "2km竞品"),
                _select("交付状态", _DELIVERY_RECORD_STATUSES),
                _select("证据类型", ("报价", "价格观察", "视觉")),
                _text("竞品记录ID"),
                _text("竞品名称"),
                _text("OTA平台"),
                _text("OTA酒店ID"),
                _text("房型"),
                _text("房型来源ID"),
                _number("机位数", precision=0),
                _number("报价（元/晚）", currency=True),
                _text("价格级别"),
                _select("可订状态", ("available", "sold_out", "unknown")),
                _text("税费口径"),
                _text("取消政策"),
                {"type": "checkbox", "name": "Network已验证"},
                {"type": "checkbox", "name": "DOM已验证"},
                {"type": "checkbox", "name": "价格一致"},
                {"type": "checkbox", "name": "可进入ADR"},
                _text("ADR排除原因"),
                _text("入住日期"),
                _number("晚数", precision=0),
                _number("入住人数", precision=0),
                _text("币种"),
                _text("装修/图片观察"),
                _text("图片说明"),
                _text("图片MIME"),
                _text("图片SHA-256"),
                _text("来源URL", url=True),
                _text("采集时间"),
                _select("证据置信度", ("low", "medium", "high")),
                _select("附件状态", ("无附件", "待上传", "已上传")),
                {"type": "attachment", "name": "视觉图片"},
            ],
        ),
    ]
    return {"base_name": BASE_NAME, "tables": deepcopy(tables)}


_PATH_LABELS = {
    "project.name": "项目名称",
    "project.rooms": "合作房间数",
    "project.workstations": "总机位数",
    "project.term_years": "合作年限",
    "project.operating_days": "年经营天数",
    "project.opening_date": "计划开业日期",
    "contract.jwl_share": "智竞分成比例",
    "contract.owner_share": "业主分成比例",
    "contract.exit_occ_threshold": "退出红线入住率",
    "contract.equipment_depreciation_years": "设备折旧年限",
    "contract.renovation_depreciation_years": "装修折旧年限",
    "contract.high_season_share": "旺季占比",
    "contract.high_season_premium": "旺季溢价系数",
    "contract.low_season_premium": "淡季溢价系数",
    "revenue.mode": "收入测算模式",
    "revenue.base_occ": "电竞房平均入住率OCC",
    "revenue.egame_adr": "电竞房ADR",
    "revenue.egame_revpar": "电竞房RevPAR",
    "revenue.hourly_eligible_room_share": "钟点房可用房比例",
    "revenue.hourly_turnovers_per_room_day": "钟点房日均翻台次数",
    "revenue.hourly_rate": "钟点房单价",
    "revenue.ancillary_rate": "衍生收入占比",
    "revenue.online_share": "线上营收占比",
    "public_costs.ota_commission_rate": "OTA佣金率",
    "public_costs.traffic_rate": "投流费率",
    "public_costs.mystery_shopper_kol_rate": "刷单/探店费率",
    "public_costs.offline_promotion_rate": "线下推广费率",
    "public_costs.ota_performance_monthly": "OTA运营绩效提成基准",
    "public_costs.turnover_tax_rate": "综合税费率",
    "finance.discount_rate": "折现率WACC",
    "finance.hurdle_irr": "目标IRR",
    "finance.maximum_discounted_payback_years": "最大动态回收年限",
    "finance.exit_occ_safety_buffer": "退出OCC安全垫",
}

_COMPONENT_LABELS = {
    "cloud_box": "瘦终端云盒",
    "monitor": "显示器",
    "peripherals": "外设",
    "furniture": "电竞桌椅",
    "install": "安装调试",
    "platform_fixed": "平台部署一次性",
    "other_fixed": "其他固定投入",
    "renovation": "业主装修",
    "weak_current": "弱电改造",
}

_MARKET_PROFILE_TEXT_LIMITS = {
    "meituan_badge": 100,
    "opening_or_renovation": 300,
    "image_quality": 500,
    "facilities": 2000,
    "features": 2000,
    "surroundings": 2000,
}

_ANNUAL_FIELDS = (
    ("occ", "OCC"),
    ("adr", "ADR（元）"),
    ("revpar", "RevPAR（元）"),
    ("available_room_nights", "可售房晚（间夜）"),
    ("occupied_room_nights", "已售房晚（间夜）"),
    ("overnight_revenue", "过夜房费收入（元）"),
    ("hourly_revenue", "钟点/包场收入（元）"),
    ("ancillary_revenue", "衍生收入（元）"),
    ("other_revenue", "其他收入（元）"),
    ("gross_revenue", "营业总收入（元）"),
    ("ota_commission", "OTA佣金（元）"),
    ("traffic_cost", "投流费（元）"),
    ("mystery_shopper_kol_cost", "刷单/探店费（元）"),
    ("offline_promotion_cost", "线下推广费（元）"),
    ("ota_performance_cost", "OTA运营绩效（元）"),
    ("shared_manager_cost", "共享经理成本（元）"),
    ("turnover_tax", "流转税（元）"),
    ("public_cost_total", "公共成本合计（元）"),
    ("distributable_net_revenue", "可分配净收入（元）"),
    ("jwl_share_revenue", "智竞分成收入（元）"),
    ("jwl_cash_opex", "智竞现金OpEx（元）"),
    ("jwl_depreciation", "智竞折旧（元）"),
    ("jwl_accounting_profit", "智竞会计利润（元）"),
    ("jwl_replacement_capex", "智竞设备重置（元）"),
    ("jwl_net_cashflow", "智竞净现金流（元）"),
    ("owner_share_revenue", "业主分成收入（元）"),
    ("owner_incremental_cash_opex", "业主增量现金OpEx（元）"),
    ("owner_fully_loaded_cash_opex", "业主完全成本现金OpEx（元）"),
    ("owner_depreciation", "业主折旧（元）"),
    ("owner_incremental_net_cashflow", "业主增量净现金流（元）"),
    ("owner_fully_loaded_net_cashflow", "业主完全成本净现金流（元）"),
    ("traditional_baseline_revenue", "传统房基线收入（元）"),
    ("replaced_traditional_contribution", "被替代传统房贡献（元）"),
    ("owner_economic_incremental_net_cashflow", "业主经济增量净现金流（元）"),
)


def _required_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BitableDeliveryError(f"{label} must be an object")
    return value


def _omit_none(record: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if value is not None}


def _path_label(path: str) -> str:
    return _PATH_LABELS.get(path, path)


def _unit_for_path(path: str) -> str:
    if path.endswith(("_rate", "_share", ".base_occ", ".traditional_occ", ".hurdle_irr")):
        return "%"
    if path.endswith((".rooms", ".workstations", ".seats_per_room")):
        return "间/台"
    if path.endswith("_years") or path.endswith(".year"):
        return "年"
    if path.endswith("operating_days"):
        return "天"
    if "monthly" in path:
        return "元/月"
    if any(token in path for token in ("capex", "adr", "revpar", "fee", "rate", "cost", "value")):
        return "元"
    return ""


def _flatten(value: Any, path: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(value, Mapping):
        for key in sorted(value):
            next_path = f"{path}.{key}" if path else str(key)
            yield from _flatten(value[key], next_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _flatten(item, f"{path}[{index}]")
    else:
        yield path, value


def _is_default_path(path: str, defaults: set[str]) -> bool:
    return any(path == candidate or path.startswith(f"{candidate}[") for candidate in defaults)


def _safe_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if value is None:
        return None
    return str(value)


def _image_extension(data_uri: str) -> str:
    mime = data_uri.split(";", 1)[0].lower()
    extensions = {
        "data:image/jpeg": "jpg",
        "data:image/png": "png",
        "data:image/webp": "webp",
    }
    try:
        return extensions[mime]
    except KeyError as exc:
        raise BitableDeliveryError(f"unsupported attachment image MIME type: {mime}") from exc


def _attachment_filename(place_id: str, index: int, data_uri: str) -> str:
    safe_place_id = re.sub(r"[^A-Za-z0-9._-]+", "_", place_id).strip("._-")
    return f"{safe_place_id[:100] or 'competitor'}-room-{index}.{_image_extension(data_uri)}"


def _record_key(run_id: str, *parts: Any) -> str:
    return "|".join([run_id, *(str(part) for part in parts)])


def _merged_input(request: Mapping[str, Any], defaults: Mapping[str, Any] | None) -> dict[str, Any]:
    project_input = _required_mapping(request.get("project_input"), "request.project_input")
    return calculate.deep_merge(dict(defaults or {}), dict(project_input))


def _run_id(result: Mapping[str, Any], project_name: str) -> str:
    fingerprint = result.get("input_sha256")
    if not isinstance(fingerprint, str) or len(fingerprint) < 12:
        raise BitableDeliveryError("result.input_sha256 is required")
    return f"{project_name}｜{fingerprint[:12]}"


def _main_record(
    result: Mapping[str, Any],
    data: Mapping[str, Any],
    run_id: str,
    delivery_gate: Mapping[str, Any],
) -> dict[str, Any]:
    financial = _required_mapping(result.get("financial_result"), "result.financial_result")
    base = _required_mapping(financial.get("base_case"), "financial_result.base_case")
    annual = base.get("annual")
    if not isinstance(annual, list) or not annual or not isinstance(annual[0], Mapping):
        raise BitableDeliveryError("financial_result.base_case.annual[0] is required")
    first = annual[0]
    jwl = _required_mapping(base.get("jwl"), "base_case.jwl")
    owner = _required_mapping(base.get("owner_fully_loaded"), "base_case.owner_fully_loaded")
    project = _required_mapping(data.get("project"), "merged project")
    decision = _required_mapping(financial.get("decision"), "financial_result.decision")
    admission = _required_mapping(financial.get("admission"), "financial_result.admission")
    competitors = _required_mapping(result.get("competitor_analysis"), "result.competitor_analysis")
    workflow = _required_mapping(result.get("workflow"), "result.workflow")
    center = competitors.get("center") if isinstance(competitors.get("center"), Mapping) else {}
    warnings = [
        *[str(item) for item in decision.get("hard_failures", [])],
        *[str(item) for item in decision.get("cautions", [])],
        *[str(item) for item in decision.get("warnings", [])],
        *[str(item) for item in workflow.get("conditions", [])],
    ]
    return _omit_none(
        {
            "项目运行ID": run_id,
            "项目名称": financial.get("project_name"),
            "资料截至": _safe_text(
                _required_mapping(data.get("metadata", {}), "merged metadata").get("as_of")
            ),
            "结论范围": result.get("conclusion_scope"),
            "交付完整性": (
                "待写入核验"
                if delivery_gate.get("final_delivery_eligible")
                else "待补证据"
            ),
            "交付待补项": (
                "；".join(str(item) for item in delivery_gate.get("blocking_items", []))
                or None
            ),
            "决策评级": decision.get("rating"),
            "数据置信度": decision.get("data_confidence"),
            "准入状态": admission.get("status"),
            "准入加权评分": admission.get("weighted_score"),
            "2km竞品状态": competitors.get("status"),
            "正式竞品数（家）": competitors.get("formal_competitor_count"),
            "2km中心提供商": center.get("provider"),
            "2km中心地点ID": center.get("provider_place_id"),
            "合作房间数（间）": project.get("rooms"),
            "总机位数（台）": calculate.project_inventory(dict(data))[1],
            "合作年限（年）": project.get("term_years"),
            "经营天数（天）": project.get("operating_days"),
            "首年OCC": first.get("occ"),
            "首年ADR（元）": first.get("adr"),
            "首年RevPAR（元）": first.get("revpar"),
            "首年营业总收入（元）": first.get("gross_revenue"),
            "首年公共成本（元）": first.get("public_cost_total"),
            "首年可分配净收入（元）": first.get("distributable_net_revenue"),
            "智竞初始投入（元）": jwl.get("initial_capex"),
            "智竞首年经营净现金（元）": jwl.get("first_year_average_monthly_operating_net_cashflow", 0) * 12,
            "智竞静态回本（月，测算值）": jwl.get("static_payback_months"),
            "智竞静态回本（月，向上取整）": jwl.get("static_payback_months_rounded_up"),
            "智竞动态回本（月，测算值）": jwl.get("discounted_payback_months"),
            "智竞动态回本（月，向上取整）": jwl.get("discounted_payback_months_rounded_up"),
            "智竞IRR": jwl.get("irr"),
            "智竞NPV（元）": jwl.get("npv"),
            "智竞盈亏平衡OCC": jwl.get("break_even_occ"),
            "业主初始投入（元）": owner.get("initial_capex"),
            "业主完全成本首年净现金（元）": first.get("owner_fully_loaded_net_cashflow"),
            "业主完全成本静态回本（月，向上取整）": owner.get("static_payback_months_rounded_up"),
            "业主完全成本动态回本（月，向上取整）": owner.get("discounted_payback_months_rounded_up"),
            "业主完全成本IRR": owner.get("irr"),
            "业主完全成本NPV（元）": owner.get("npv"),
            "合同退出红线OCC": financial.get("contract_exit_occ_threshold"),
            "风险与待办": "\n".join(dict.fromkeys(warnings)) or None,
            "输入SHA256": result.get("input_sha256"),
            "Skill版本": result.get("skill_version"),
        }
    )


def _input_records(
    data: Mapping[str, Any], financial: Mapping[str, Any], run_id: str
) -> list[dict[str, Any]]:
    default_paths = {str(path) for path in financial.get("used_default_paths", [])}
    metadata = data.get("metadata") if isinstance(data.get("metadata"), Mapping) else {}
    evidence = metadata.get("evidence") if isinstance(metadata.get("evidence"), Mapping) else {}
    records: list[dict[str, Any]] = []
    for path, value in _flatten(data):
        if path.startswith("metadata.evidence"):
            continue
        evidence_row = evidence.get(path) if isinstance(evidence.get(path), Mapping) else {}
        record: dict[str, Any] = {
            "参数记录ID": _record_key(run_id, "input", path),
            "模型路径": path,
            "参数名称": _path_label(path),
            "模块": path.split(".", 1)[0].split("[", 1)[0],
            "单位": _unit_for_path(path) or None,
            "取值来源": "基准默认" if _is_default_path(path, default_paths) else "项目输入",
            "证据来源类别": evidence_row.get("source_class"),
            "证据来源": evidence_row.get("source"),
            "证据日期": evidence_row.get("as_of"),
            "证据状态": evidence_row.get("status"),
            "证据审批人": evidence_row.get("approved_by"),
        }
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            record["数值（数字）"] = value
        elif value is not None:
            record["数值（文本）"] = "是" if value is True else "否" if value is False else str(value)
        records.append(_omit_none(record))
    return records


def _cost_records(financial: Mapping[str, Any], run_id: str) -> list[dict[str, Any]]:
    base = _required_mapping(financial.get("base_case"), "financial_result.base_case")
    jwl = _required_mapping(base.get("jwl"), "base_case.jwl")
    owner = _required_mapping(base.get("owner_fully_loaded"), "base_case.owner_fully_loaded")
    records: list[dict[str, Any]] = []

    def add(category: str, owner_name: str, component: str, amount: Any, year: int | None = None, note: str | None = None) -> None:
        if not isinstance(amount, (int, float)) or isinstance(amount, bool):
            return
        records.append(
            _omit_none(
                {
                    "成本记录ID": _record_key(run_id, "cost", category, year or 0, component),
                    "成本类别": category,
                    "所属方": owner_name,
                    "成本项目": _COMPONENT_LABELS.get(component, component),
                    "对应年度": year,
                    "金额（元）": amount,
                    "口径说明": note,
                }
            )
        )

    for component, amount in _required_mapping(jwl.get("capex_components"), "jwl.capex_components").items():
        add("智竞CapEx", "智竞", str(component), amount, note="一次性投入")
    add("智竞设备重置", "智竞", "equipment_replacement", jwl.get("replacement_capex"), int(jwl.get("replacement_year") or 0) or None, "设备重置")
    for component, amount in _required_mapping(owner.get("capex_components"), "owner.capex_components").items():
        add("业主CapEx", "业主", str(component), amount, note="一次性投入")
    for row in base.get("annual", []):
        if not isinstance(row, Mapping):
            continue
        year = row.get("year")
        add("智竞年现金OpEx", "智竞", "cash_opex", row.get("jwl_cash_opex"), year, "年度现金口径")
        add("业主年增量现金OpEx", "业主", "incremental_cash_opex", row.get("owner_incremental_cash_opex"), year, "年度现金口径")
        add("业主年完全成本现金OpEx", "业主", "fully_loaded_cash_opex", row.get("owner_fully_loaded_cash_opex"), year, "年度现金口径")
    return records


def _annual_records(financial: Mapping[str, Any], run_id: str) -> list[dict[str, Any]]:
    base = _required_mapping(financial.get("base_case"), "financial_result.base_case")
    records: list[dict[str, Any]] = []
    for row in base.get("annual", []):
        if not isinstance(row, Mapping):
            continue
        year = row.get("year")
        record: dict[str, Any] = {
            "年度记录ID": _record_key(run_id, "annual", year),
            "预测年度": year,
        }
        for source, destination in _ANNUAL_FIELDS:
            record[destination] = row.get(source)
        records.append(_omit_none(record))
    return records


def _scenario_records(financial: Mapping[str, Any], run_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, scenario in enumerate(financial.get("scenarios", []), start=1):
        if not isinstance(scenario, Mapping):
            continue
        records.append(
            _omit_none(
                {
                    "分析记录ID": _record_key(run_id, "scenario", index),
                    "分析类型": "情景",
                    "分析名称": scenario.get("name"),
                    "入住率OCC": scenario.get("occ"),
                    "首年营业总收入（元）": scenario.get("gross_revenue_year_1"),
                    "智竞首年净现金流（元）": scenario.get("jwl_cashflow_year_1"),
                    "智竞静态回本（月，向上取整）": scenario.get("jwl_static_payback_months_rounded_up"),
                    "智竞动态回本（月，向上取整）": scenario.get("jwl_discounted_payback_months_rounded_up"),
                    "智竞IRR": scenario.get("jwl_irr"),
                    "智竞NPV（元）": scenario.get("jwl_npv"),
                }
            )
        )
    for index, sensitivity in enumerate(financial.get("sensitivity", []), start=1):
        if not isinstance(sensitivity, Mapping):
            continue
        records.append(
            _omit_none(
                {
                    "分析记录ID": _record_key(run_id, "sensitivity", index),
                    "分析类型": "敏感性",
                    "分析名称": sensitivity.get("driver"),
                    "变量路径": sensitivity.get("path"),
                    "基准值": sensitivity.get("base_value"),
                    "智竞NPV（元）": sensitivity.get("base_npv"),
                    "NPV下调10%情景（元）": sensitivity.get("npv_at_minus_10pct"),
                    "NPV上调10%情景（元）": sensitivity.get("npv_at_plus_10pct"),
                    "NPV波动（元）": sensitivity.get("npv_swing"),
                    "影响排序值": sensitivity.get("absolute_impact_rank_value"),
                }
            )
        )
    return records


def _room_type_records(data: Mapping[str, Any], run_id: str) -> list[dict[str, Any]]:
    revenue = data.get("revenue") if isinstance(data.get("revenue"), Mapping) else {}
    room_types = revenue.get("room_types") if isinstance(revenue.get("room_types"), list) else []
    records: list[dict[str, Any]] = []
    for index, room_type in enumerate(room_types, start=1):
        if not isinstance(room_type, Mapping):
            continue
        records.append(
            _omit_none(
                {
                    "房型记录ID": _record_key(run_id, "room_type", index),
                    "交付状态": "已提供",
                    "房型名称": room_type.get("name"),
                    "房间数": room_type.get("rooms"),
                    "每间机位数": room_type.get("workstations_per_room"),
                    "电竞ADR（元）": room_type.get("egame_adr"),
                    "电竞RevPAR（元）": room_type.get("egame_revpar"),
                    "电竞OCC": room_type.get("base_occ"),
                    "传统ADR（元）": room_type.get("traditional_adr"),
                    "传统RevPAR（元）": room_type.get("traditional_revpar"),
                    "传统OCC": room_type.get("traditional_occ"),
                    "传统贡献毛利率": room_type.get("traditional_contribution_margin_rate"),
                }
            )
        )
    if not records:
        records.append(
            {
                "房型记录ID": _record_key(run_id, "room_type_gap"),
                "交付状态": "待补房型",
                "房型名称": "待补：未提供结构化房型配置（非房型数据）",
            }
        )
    return records


def _validated_market_profile(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise BitableDeliveryError(f"{label} must be an object")
    allowed = set(_MARKET_PROFILE_TEXT_LIMITS) | {"room_count", "rating", "review_count"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise BitableDeliveryError(f"unknown field(s) in {label}: {unknown}")
    profile: dict[str, Any] = {}
    for field, maximum_length in _MARKET_PROFILE_TEXT_LIMITS.items():
        text = value.get(field)
        if text is None:
            continue
        if not isinstance(text, str) or not text.strip() or len(text) > maximum_length:
            raise BitableDeliveryError(f"{label}.{field} must be a non-empty string within {maximum_length} characters")
        profile[field] = text.strip()
    for field, minimum, maximum in (("room_count", 1, None), ("review_count", 0, None), ("rating", 0, 5)):
        number = value.get(field)
        if number is None:
            continue
        if (
            not isinstance(number, (int, float))
            or isinstance(number, bool)
            or not math.isfinite(float(number))
            or number < minimum
            or (maximum is not None and number > maximum)
            or (field != "rating" and not isinstance(number, int))
        ):
            raise BitableDeliveryError(f"{label}.{field} is invalid")
        profile[field] = number
    return profile


def _raw_candidate_profiles(request: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    analysis = request.get("competitor_analysis")
    candidates = analysis.get("candidates") if isinstance(analysis, Mapping) else []
    profiles: dict[str, Mapping[str, Any]] = {}
    if not isinstance(candidates, list):
        return profiles
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            continue
        place_id = candidate.get("provider_place_id")
        if not isinstance(place_id, str) or not place_id.strip():
            continue
        profiles[place_id.strip()] = _validated_market_profile(
            candidate.get("market_profile"),
            f"competitor_analysis.candidates[{index}].market_profile",
        )
    return profiles


def _competitor_records(
    result: Mapping[str, Any], request: Mapping[str, Any], run_id: str
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    analysis = _required_mapping(result.get("competitor_analysis"), "result.competitor_analysis")
    profiles = _raw_candidate_profiles(request)
    records: list[dict[str, Any]] = []
    record_keys: dict[str, str] = {}
    for index, candidate in enumerate(
        [*analysis.get("competitors", []), *analysis.get("excluded", [])], start=1
    ):
        if not isinstance(candidate, Mapping):
            continue
        place_id = _safe_text(candidate.get("provider_place_id")) or f"candidate-{index}"
        profile = profiles.get(place_id, {})
        record_id = _record_key(run_id, "competitor", place_id)
        record_keys[place_id] = record_id
        source = candidate.get("source") if isinstance(candidate.get("source"), Mapping) else {}
        booking = (
            candidate.get("booking_evidence", [])[0]
            if isinstance(candidate.get("booking_evidence"), list)
            and candidate.get("booking_evidence")
            and isinstance(candidate.get("booking_evidence")[0], Mapping)
            else {}
        )
        records.append(
            _omit_none(
                {
                    "竞品记录ID": record_id,
                    "交付状态": "已提供",
                    "竞品名称": candidate.get("name") or place_id,
                    "地图提供商": candidate.get("provider"),
                    "提供商地点ID": place_id,
                    "分类": candidate.get("classification"),
                    "正式竞品": candidate.get("formal_competitor_allowed"),
                    "直线距离（米）": candidate.get("distance_meters"),
                    "美团等级/冠": profile.get("meituan_badge"),
                    "开业/装修": profile.get("opening_or_renovation"),
                    "房间数": profile.get("room_count"),
                    "图片质量": profile.get("image_quality"),
                    "基础设施": profile.get("facilities"),
                    "酒店特色": profile.get("features"),
                    "平台评分": profile.get("rating"),
                    "评论数": profile.get("review_count"),
                    "周边说明": profile.get("surroundings"),
                    "房型报价数": len(candidate.get("room_offers", [])),
                    "OTA平台": booking.get("platform"),
                    "OTA酒店ID": booking.get("property_id"),
                    "OTA匹配方式": booking.get("match_method"),
                    "调研来源平台": source.get("source_platform"),
                    "来源URL": source.get("source_url"),
                    "采集时间": source.get("observed_at"),
                    "证据置信度": source.get("confidence"),
                    "排除/提示原因": "; ".join(str(item) for item in candidate.get("reason_codes", [])) or None,
                    "待补齐字段": "; ".join(str(item) for item in candidate.get("pending_fields", [])) or None,
                }
            )
        )
    if not records:
        missing = [str(item) for item in analysis.get("missing_inputs", [])]
        collection_complete_without_candidates = analysis.get("status") == "complete"
        records.append(
            _omit_none(
                {
                    "竞品记录ID": _record_key(run_id, "competitor_collection_gap"),
                    "交付状态": (
                        "检索完成无正式竞品"
                        if collection_complete_without_candidates
                        else "待补2km竞品"
                    ),
                    "竞品名称": (
                        "2km检索完成：无可写入的正式竞品"
                        if collection_complete_without_candidates
                        else "待补：2km竞品采集（非竞品记录）"
                    ),
                    "分类": (
                        "collection_complete_zero_formal_competitor"
                        if collection_complete_without_candidates
                        else "delivery_gap"
                    ),
                    "正式竞品": False,
                    "排除/提示原因": "；".join(missing) or None,
                    "待补齐字段": "；".join(missing) or None,
                }
            )
        )
    elif analysis.get("status") != "complete":
        missing = [str(item) for item in analysis.get("missing_inputs", [])]
        records.append(
            _omit_none(
                {
                    "竞品记录ID": _record_key(run_id, "competitor_collection_gap"),
                    "交付状态": "待补2km竞品",
                    "竞品名称": "待补：2km竞品集合尚未完成（非竞品记录）",
                    "分类": "delivery_gap",
                    "正式竞品": False,
                    "排除/提示原因": "；".join(missing) or "collection_incomplete",
                    "待补齐字段": "；".join(missing) or "collection_status=complete",
                }
            )
        )
    return records, record_keys


def _evidence_records(
    result: Mapping[str, Any],
    request: Mapping[str, Any],
    run_id: str,
    competitor_keys: Mapping[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    analysis = _required_mapping(result.get("competitor_analysis"), "result.competitor_analysis")
    formal = {
        str(candidate.get("provider_place_id")): candidate
        for candidate in analysis.get("competitors", [])
        if isinstance(candidate, Mapping) and candidate.get("provider_place_id")
    }
    context = analysis.get("pricing_context") if isinstance(analysis.get("pricing_context"), Mapping) else {}
    records: list[dict[str, Any]] = []
    attachments: list[dict[str, Any]] = []
    for place_id, candidate in formal.items():
        source = (
            candidate.get("source")
            if isinstance(candidate.get("source"), Mapping)
            else {}
        )
        booking = (
            candidate.get("booking_evidence", [])[0]
            if isinstance(candidate.get("booking_evidence"), list)
            and candidate.get("booking_evidence")
            and isinstance(candidate.get("booking_evidence")[0], Mapping)
            else {}
        )
        for index, offer in enumerate(candidate.get("room_offers", []), start=1):
            if not isinstance(offer, Mapping):
                continue
            evidence_id = _record_key(run_id, "offer", place_id, index)
            records.append(
                _omit_none(
                    {
                        "证据记录ID": evidence_id,
                        "交付状态": "已提供",
                        "证据类型": "报价",
                        "竞品记录ID": competitor_keys.get(place_id),
                        "竞品名称": candidate.get("name") or place_id,
                        "OTA平台": booking.get("platform"),
                        "OTA酒店ID": booking.get("property_id"),
                        "房型": offer.get("room_type"),
                        "房型来源ID": offer.get("room_type_provider_id"),
                        "机位数": offer.get("workstations"),
                        "报价（元/晚）": offer.get("nightly_price"),
                        "价格级别": "P2",
                        "可订状态": offer.get("availability"),
                        "税费口径": (
                            "含税" if offer.get("tax_included") is True else
                            ("不含税/另付税费" if offer.get("tax_included") is False else None)
                        ),
                        "取消政策": offer.get("cancellation_policy"),
                        "Network已验证": True,
                        "DOM已验证": True,
                        "价格一致": True,
                        "可进入ADR": True,
                        "入住日期": offer.get("pricing_context", context).get("check_in_date") if isinstance(offer.get("pricing_context", context), Mapping) else context.get("check_in_date"),
                        "晚数": offer.get("pricing_context", context).get("nights") if isinstance(offer.get("pricing_context", context), Mapping) else context.get("nights"),
                        "入住人数": offer.get("pricing_context", context).get("guests") if isinstance(offer.get("pricing_context", context), Mapping) else context.get("guests"),
                        "币种": offer.get("currency") or context.get("currency"),
                        "来源URL": offer.get("source_url") or source.get("source_url"),
                        "采集时间": offer.get("observed_at") or source.get("observed_at"),
                        "证据置信度": source.get("confidence"),
                        "附件状态": "无附件",
                    }
                )
            )
        for index, observation in enumerate(candidate.get("pricing_observations", []), start=1):
            if not isinstance(observation, Mapping):
                continue
            observation_id = _record_key(run_id, "price_observation", place_id, index)
            raw_gaps = observation.get("qualification_gaps")
            gaps = "；".join(str(item) for item in raw_gaps) if isinstance(raw_gaps, list) else None
            records.append(
                _omit_none(
                    {
                        "证据记录ID": observation_id,
                        "交付状态": "已提供",
                        "证据类型": "价格观察",
                        "竞品记录ID": competitor_keys.get(place_id),
                        "竞品名称": candidate.get("name") or place_id,
                        "OTA平台": booking.get("platform"),
                        "OTA酒店ID": booking.get("property_id"),
                        "房型": observation.get("room_type"),
                        "房型来源ID": observation.get("room_type_provider_id"),
                        "机位数": observation.get("workstations"),
                        "报价（元/晚）": observation.get("display_price"),
                        "价格级别": observation.get("price_type"),
                        "可订状态": observation.get("availability"),
                        "取消政策": observation.get("cancellation_policy"),
                        "Network已验证": observation.get("network_verified"),
                        "DOM已验证": observation.get("dom_verified"),
                        "价格一致": observation.get("price_match"),
                        "可进入ADR": observation.get("adr_eligible"),
                        "ADR排除原因": gaps,
                        "入住日期": observation.get("pricing_context", context).get("check_in_date") if isinstance(observation.get("pricing_context", context), Mapping) else context.get("check_in_date"),
                        "晚数": observation.get("pricing_context", context).get("nights") if isinstance(observation.get("pricing_context", context), Mapping) else context.get("nights"),
                        "入住人数": observation.get("pricing_context", context).get("guests") if isinstance(observation.get("pricing_context", context), Mapping) else context.get("guests"),
                        "币种": observation.get("currency") or context.get("currency"),
                        "来源URL": observation.get("source_url") or source.get("source_url"),
                        "采集时间": observation.get("observed_at") or source.get("observed_at"),
                        "证据置信度": source.get("confidence"),
                        "附件状态": "无附件",
                    }
                )
            )

    media = competitor_report.validate_report_evidence(request.get("competitor_report"))
    media_ids = {item["provider_place_id"] for item in media["candidate_media"]}
    invalid = sorted(media_ids - set(formal))
    if invalid:
        raise BitableDeliveryError(
            "competitor_report references candidates absent from the formal competitor set: "
            f"{invalid}"
        )
    image_evidence_place_ids: set[str] = set()
    for candidate_media in media["candidate_media"]:
        place_id = candidate_media["provider_place_id"]
        candidate = formal[place_id]
        booking = (
            candidate.get("booking_evidence", [])[0]
            if isinstance(candidate.get("booking_evidence"), list)
            and candidate.get("booking_evidence")
            and isinstance(candidate.get("booking_evidence")[0], Mapping)
            else {}
        )
        observation = candidate_media.get("renovation_observation")
        observation_url = candidate_media.get("observation_source_url")
        if observation:
            observation_id = _record_key(run_id, "visual_observation", place_id)
            records.append(
                _omit_none(
                    {
                        "证据记录ID": observation_id,
                        "交付状态": "已提供",
                        "证据类型": "视觉",
                        "竞品记录ID": competitor_keys.get(place_id),
                        "竞品名称": candidate.get("name") or place_id,
                        "OTA平台": booking.get("platform"),
                        "OTA酒店ID": booking.get("property_id"),
                        "装修/图片观察": observation,
                        "来源URL": observation_url,
                        "附件状态": "无附件",
                    }
                )
            )
        for image_index, image in enumerate(candidate_media.get("images", []), start=1):
            image_evidence_place_ids.add(place_id)
            evidence_id = _record_key(run_id, "visual_image", place_id, image_index)
            records.append(
                _omit_none(
                    {
                        "证据记录ID": evidence_id,
                        "交付状态": "已提供",
                        "证据类型": "视觉",
                        "竞品记录ID": competitor_keys.get(place_id),
                        "竞品名称": candidate.get("name") or place_id,
                        "OTA平台": booking.get("platform"),
                        "OTA酒店ID": booking.get("property_id"),
                        "图片说明": image.get("caption"),
                        "房型来源ID": image.get("room_type_provider_id"),
                        "图片MIME": image.get("mime_type"),
                        "图片SHA-256": image.get("sha256"),
                        "来源URL": image.get("source_url"),
                        "采集时间": image.get("observed_at"),
                        "附件状态": "待上传",
                    }
                )
            )
            attachments.append(
                {
                    "table": "竞品报价与视觉证据",
                    "record_key_field": "证据记录ID",
                    "record_key": evidence_id,
                    "field": "视觉图片",
                    "filename": _attachment_filename(place_id, image_index, image["data_uri"]),
                    "data_uri": image["data_uri"],
                    "source_url": image["source_url"],
                    "status_after_upload": "已上传",
                }
            )
    if not formal:
        analysis_complete = analysis.get("status") == "complete"
        records.append(
            {
                "证据记录ID": _record_key(run_id, "visual_gap_no_formal_competitor"),
                "交付状态": (
                    "检索完成无正式竞品" if analysis_complete else "待补视觉图片"
                ),
                "证据类型": "视觉",
                "竞品名称": (
                    "无正式竞品，未生成图片证据"
                    if analysis_complete
                    else "待补：先完成2km竞品采集，再绑定图片证据"
                ),
                "装修/图片观察": (
                    "2km检索已完成且无正式竞品；没有可绑定的竞品房图。"
                    if analysis_complete
                    else "当前没有可绑定的正式竞品；不得以未核验图片进行装修判断。"
                ),
                "附件状态": "无附件",
            }
        )
    else:
        for place_id, candidate in formal.items():
            if place_id in image_evidence_place_ids:
                continue
            source = (
                candidate.get("source")
                if isinstance(candidate.get("source"), Mapping)
                else {}
            )
            records.append(
                _omit_none(
                    {
                        "证据记录ID": _record_key(run_id, "visual_gap", place_id),
                        "交付状态": "待补视觉图片",
                        "证据类型": "视觉",
                        "竞品记录ID": competitor_keys.get(place_id),
                        "竞品名称": candidate.get("name") or place_id,
                        "装修/图片观察": "未提供可嵌入的公开房型图；不得据此作装修、设备或价格判断。",
                        "来源URL": source.get("source_url"),
                        "采集时间": source.get("observed_at"),
                        "附件状态": "无附件",
                    }
                )
            )
    return records, attachments


def _delivery_gate(
    records: Mapping[str, list[Mapping[str, Any]]], attachments: list[Mapping[str, Any]]
) -> dict[str, Any]:
    """Expose and preserve visible gaps instead of allowing empty topic tables."""

    required = (
        ("房型配置", "待补房型", "房型配置"),
        ("2km竞品", "待补2km竞品", "2km竞品"),
        ("竞品报价与视觉证据", "待补视觉图片", "竞品图片证据"),
    )
    table_status: dict[str, dict[str, Any]] = {}
    blocking_items: list[str] = []
    for table, pending_status, label in required:
        rows = records.get(table, [])
        states = [str(row.get("交付状态")) for row in rows if isinstance(row, Mapping)]
        is_blocked = not rows or pending_status in states
        if is_blocked:
            blocking_items.append(label)
        table_status[table] = {
            "record_count": len(rows),
            "status": "待补证据" if is_blocked else "可交付",
            "record_statuses": sorted(set(states)),
        }
    final_eligible = not blocking_items
    return {
        "status": "可交付" if final_eligible else "待补证据",
        "final_delivery_eligible": final_eligible,
        "blocking_items": blocking_items,
        "expected_visual_attachment_count": len(attachments),
        "post_write_completion": {
            "initial_summary_status": (
                "待写入核验" if final_eligible else "待补证据"
            ),
            "success_summary_status": "可交付",
            "required_readback": (
                "all_manifest_record_keys_links_and_visual_attachments"
            ),
        },
        "tables": table_status,
    }


def _links(records: Mapping[str, list[Mapping[str, Any]]], run_id: str) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    key_fields = {
        "输入参数与来源": "参数记录ID",
        "投资与成本明细": "成本记录ID",
        "年度收入与现金流": "年度记录ID",
        "情景与敏感性": "分析记录ID",
        "房型配置": "房型记录ID",
        "2km竞品": "竞品记录ID",
        "竞品报价与视觉证据": "证据记录ID",
    }
    for table, key_field in key_fields.items():
        for row in records.get(table, []):
            key = row.get(key_field)
            if key:
                links.append(
                    {
                        "from_table": table,
                        "from_key_field": key_field,
                        "from_key": key,
                        "field": "关联项目运行",
                        "to_table": "项目测算总表",
                        "to_key_field": "项目运行ID",
                        "to_key": run_id,
                    }
                )
    for row in records.get("竞品报价与视觉证据", []):
        competitor_key = row.get("竞品记录ID")
        if competitor_key:
            links.append(
                {
                    "from_table": "竞品报价与视觉证据",
                    "from_key_field": "证据记录ID",
                    "from_key": row["证据记录ID"],
                    "field": "关联竞品",
                    "to_table": "2km竞品",
                    "to_key_field": "竞品记录ID",
                    "to_key": competitor_key,
                }
            )
    return links


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    """Reject malformed manifests before an authorised host writes anything."""

    template = _required_mapping(manifest.get("template"), "manifest.template")
    tables = template.get("tables")
    records = _required_mapping(manifest.get("records"), "manifest.records")
    delivery_gate = _required_mapping(manifest.get("delivery_gate"), "manifest.delivery_gate")
    if delivery_gate.get("status") not in _DELIVERY_COMPLETENESS:
        raise BitableDeliveryError("manifest.delivery_gate.status is invalid")
    if not isinstance(delivery_gate.get("final_delivery_eligible"), bool):
        raise BitableDeliveryError("manifest.delivery_gate.final_delivery_eligible must be boolean")
    blocking_items = delivery_gate.get("blocking_items")
    if not isinstance(blocking_items, list) or not all(
        isinstance(item, str) for item in blocking_items
    ):
        raise BitableDeliveryError("manifest.delivery_gate.blocking_items must be a string array")
    if not isinstance(delivery_gate.get("expected_visual_attachment_count"), int) or delivery_gate[
        "expected_visual_attachment_count"
    ] < 0:
        raise BitableDeliveryError("manifest.delivery_gate.expected_visual_attachment_count is invalid")
    completion = _required_mapping(
        delivery_gate.get("post_write_completion"),
        "manifest.delivery_gate.post_write_completion",
    )
    if completion.get("initial_summary_status") not in _DELIVERY_COMPLETENESS:
        raise BitableDeliveryError("manifest.delivery_gate.post_write_completion.initial_summary_status is invalid")
    if completion.get("success_summary_status") != "可交付":
        raise BitableDeliveryError("manifest.delivery_gate.post_write_completion.success_summary_status is invalid")
    if delivery_gate["final_delivery_eligible"] != (delivery_gate["status"] == "可交付"):
        raise BitableDeliveryError("manifest.delivery_gate eligibility/status mismatch")
    if not isinstance(tables, list) or not tables:
        raise BitableDeliveryError("manifest.template.tables must be a non-empty array")
    table_names = set()
    for table in tables:
        if not isinstance(table, Mapping):
            raise BitableDeliveryError("manifest template table must be an object")
        name = table.get("name")
        key = table.get("record_key_field")
        fields = table.get("fields")
        if not isinstance(name, str) or not isinstance(key, str) or not isinstance(fields, list):
            raise BitableDeliveryError("manifest template table is incomplete")
        if name in table_names:
            raise BitableDeliveryError(f"duplicate manifest table: {name}")
        table_names.add(name)
        field_names = [field.get("name") for field in fields if isinstance(field, Mapping)]
        if not field_names or field_names[0] != key or len(field_names) != len(set(field_names)):
            raise BitableDeliveryError(f"invalid field layout for table: {name}")
        if {field.get("type") for field in fields if isinstance(field, Mapping)} & {"formula", "lookup"}:
            raise BitableDeliveryError("Bitable delivery must not contain a second calculation model")
        table_records = records.get(name)
        if not isinstance(table_records, list):
            raise BitableDeliveryError(f"manifest.records.{name} must be an array")
        writable = set(field_names) - {"飞书创建时间", "视觉图片", "关联项目运行", "关联竞品"}
        for row in table_records:
            if not isinstance(row, Mapping) or key not in row:
                raise BitableDeliveryError(f"record missing {key} in table: {name}")
            unknown = set(row) - writable
            if unknown:
                raise BitableDeliveryError(f"record has unknown/non-writable fields in {name}: {sorted(unknown)}")
    if set(records) != table_names:
        raise BitableDeliveryError("manifest records must exactly match template tables")


def build_manifest(
    result: Mapping[str, Any],
    request: Mapping[str, Any],
    defaults: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Map one completed Skill run to a Feishu-agnostic Bitable write manifest."""

    result = _required_mapping(result, "result")
    request = _required_mapping(request, "request")
    data = _merged_input(request, defaults)
    financial = _required_mapping(result.get("financial_result"), "result.financial_result")
    project_name = financial.get("project_name")
    if not isinstance(project_name, str) or not project_name.strip():
        raise BitableDeliveryError("financial_result.project_name is required")
    run_id = _run_id(result, project_name.strip())
    competitor_rows, competitor_keys = _competitor_records(result, request, run_id)
    evidence_rows, attachments = _evidence_records(result, request, run_id, competitor_keys)
    room_rows = _room_type_records(data, run_id)
    delivery_rows: dict[str, list[dict[str, Any]]] = {
        "房型配置": room_rows,
        "2km竞品": competitor_rows,
        "竞品报价与视觉证据": evidence_rows,
    }
    delivery_gate = _delivery_gate(delivery_rows, attachments)
    records: dict[str, list[dict[str, Any]]] = {
        "项目测算总表": [_main_record(result, data, run_id, delivery_gate)],
        "输入参数与来源": _input_records(data, financial, run_id),
        "投资与成本明细": _cost_records(financial, run_id),
        "年度收入与现金流": _annual_records(financial, run_id),
        "情景与敏感性": _scenario_records(financial, run_id),
        "房型配置": room_rows,
        "2km竞品": competitor_rows,
        "竞品报价与视觉证据": evidence_rows,
    }
    manifest: dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "delivery_type": "feishu_bitable",
        "write_policy": {
            "calculation_owner": "skill_is_calculation_owner",
            "upsert_policy": "lookup_record_key_then_create_or_patch",
            "input_fingerprint_policy": "same_input_sha256_is_idempotent; changed_input_creates_a_new_project_run",
            "attachment_policy": "upload_only_manifest_data_uri; never_fetch_remote_image_url",
            "link_policy": "create_records_first_then_resolve_logical_links",
            "delivery_completion_policy": (
                "write visible gap records; begin an eligible manifest as 待写入核验 and "
                "change the summary to 可交付 only after the host readback verifies all "
                "required records, links and attachments"
            ),
        },
        "template": standard_template(),
        "project_run_id": run_id,
        "delivery_gate": delivery_gate,
        "records": records,
        "links": _links(records, run_id),
        "attachments": attachments,
    }
    validate_manifest(manifest)
    return manifest
