"""Internal deterministic underwriting engine for JWL co-operated esports hotels."""

from __future__ import annotations

import calendar
import copy
import math
import sys
from datetime import date
from typing import Any, Callable


class ModelError(ValueError):
    pass


CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


def confidence_at_most(left: str, right: str) -> str:
    return left if CONFIDENCE_RANK[left] <= CONFIDENCE_RANK[right] else right


def infer_evidence_confidence(data: dict[str, Any]) -> str:
    """Infer source-backed confidence without treating approval as validation."""
    evidence = get_path(data, "metadata.evidence", {})
    if not isinstance(evidence, dict) or not evidence:
        return "low"
    source_classes = {
        record.get("source_class")
        for record in evidence.values()
        if isinstance(record, dict)
    }
    if "project_benchmark" in source_classes:
        return "low"
    if source_classes.intersection({"verified_comparable", "market_research", "assumption"}):
        return "medium"
    return "high"


def forecast_confidence(data: dict[str, Any], warnings: list[str]) -> str:
    """Cap predictive confidence until a separately approved backtest exists."""
    metadata = get_path(data, "metadata", {})
    if not isinstance(metadata, dict):
        return "low"
    declared = str(metadata.get("forecast_confidence", "low")).lower()
    if declared not in CONFIDENCE_RANK:
        warnings.append("metadata.forecast_confidence无效，已按low处理")
        return "low"
    validation = metadata.get("forecast_validation")
    if not isinstance(validation, dict):
        if declared != "low":
            warnings.append("缺少已批准的历史回测验证，预测置信度已降为低")
        return "low"
    validation_status = validation.get("status", "unvalidated")
    validation_cap = {"unvalidated": "low", "backtested": "medium", "approved": "high"}.get(
        validation_status
    )
    if validation_cap is None:
        warnings.append("metadata.forecast_validation.status无效，预测置信度已降为低")
        return "low"
    if validation_status in {"backtested", "approved"}:
        if not isinstance(validation.get("sample_size"), int) or validation["sample_size"] <= 0:
            warnings.append("预测回测缺少有效sample_size，预测置信度已降为低")
            return "low"
        if not isinstance(validation.get("method"), str) or not validation["method"].strip():
            warnings.append("预测回测缺少method，预测置信度已降为低")
            return "low"
    if validation_status == "approved" and (
        not isinstance(validation.get("approved_by"), str)
        or not validation["approved_by"].strip()
        or not isinstance(validation.get("approved_at"), str)
        or not validation["approved_at"].strip()
    ):
        warnings.append("预测回测缺少独立批准身份，预测置信度已降为低")
        return "low"
    effective = confidence_at_most(declared, validation_cap)
    if effective != declared:
        warnings.append("预测置信度声明超过回测验证等级，已按验证等级处理")
    return effective


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def get_path(data: dict[str, Any], path: str, default: Any = None) -> Any:
    node: Any = data
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def set_path(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    node = data
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def leaf_paths(data: dict[str, Any], prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            paths.update(leaf_paths(value, path))
        else:
            paths.add(path)
    return paths


def number(data: dict[str, Any], path: str, default: float | None = None) -> float:
    value = get_path(data, path, default)
    if value is None or isinstance(value, bool):
        raise ModelError(f"缺少数值字段: {path}")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ModelError(f"字段必须为数值: {path}={value!r}") from exc
    if not math.isfinite(result):
        raise ModelError(f"字段必须为有限数值: {path}")
    return result


def rate(data: dict[str, Any], path: str, default: float = 0.0) -> float:
    result = number(data, path, default)
    if not 0 <= result <= 1:
        raise ModelError(f"比例字段应在0到1之间: {path}={result}")
    return result


def require_nonnegative(data: dict[str, Any], paths: list[str]) -> None:
    for path in paths:
        if number(data, path, 0) < 0:
            raise ModelError(f"成本或数量不得为负: {path}")


def npv(rate_value: float, cashflows: list[float]) -> float:
    if rate_value <= -1:
        raise ModelError("折现率必须大于-100%")
    return sum(cf / ((1 + rate_value) ** year) for year, cf in enumerate(cashflows))


def irr_roots(cashflows: list[float]) -> list[float]:
    if not any(cf < 0 for cf in cashflows) or not any(cf > 0 for cf in cashflows):
        return []

    grid = [-0.9999]
    grid.extend(-0.99 + i * 0.01 for i in range(99))
    grid.extend(i * 0.01 for i in range(0, 101))
    grid.extend((1.08**i) - 1 for i in range(1, 151))
    grid = sorted(set(grid))

    roots: list[float] = []
    previous_rate = grid[0]
    previous_value = npv(previous_rate, cashflows)
    for current_rate in grid[1:]:
        current_value = npv(current_rate, cashflows)
        if abs(current_value) < 1e-8:
            roots.append(current_rate)
        elif previous_value * current_value < 0:
            low, high = previous_rate, current_rate
            low_value = previous_value
            for _ in range(120):
                mid = (low + high) / 2
                mid_value = npv(mid, cashflows)
                if abs(mid_value) < 1e-10:
                    low = high = mid
                    break
                if low_value * mid_value <= 0:
                    high = mid
                else:
                    low, low_value = mid, mid_value
            roots.append((low + high) / 2)
        previous_rate, previous_value = current_rate, current_value

    unique: list[float] = []
    for root in roots:
        if not unique or abs(root - unique[-1]) > 1e-6:
            unique.append(root)
    return unique


def sustained_payback(cashflows: list[float], discount_rate: float = 0.0) -> float | None:
    adjusted = [cf / ((1 + discount_rate) ** year) for year, cf in enumerate(cashflows)]
    cumulative: list[float] = []
    running = 0.0
    for cf in adjusted:
        running += cf
        cumulative.append(running)
    if cumulative[-1] < 0:
        return None
    last_negative = max((i for i, value in enumerate(cumulative) if value < 0), default=-1)
    crossing_year = last_negative + 1
    if crossing_year <= 0:
        return 0.0
    prior = cumulative[crossing_year - 1]
    current_flow = adjusted[crossing_year]
    if current_flow <= 0:
        return float(crossing_year)
    return (crossing_year - 1) + (-prior / current_flow)


def _whole_months(value: float | None) -> int | None:
    """Return the conservative whole-month delivery value without hiding the raw result."""

    if value is None:
        return None
    return max(0, int(math.ceil(value - 1e-12)))


def static_monthly_payback(
    initial_capex: float, first_year_operating_cashflow: float
) -> tuple[float, float | None, int | None]:
    """Return the historic workbook's CapEx / monthly operating-cash payback.

    The company workbook's `回款周期/月` uses one-time fixed investment divided
    by monthly net operating profit.  Keep that simple, reviewable view
    separate from the model's sustained annual cash-flow payback, which also
    captures later replacement CapEx and any terminal value.
    """

    monthly_cashflow = first_year_operating_cashflow / 12
    if initial_capex <= 0:
        return monthly_cashflow, 0.0, 0
    if monthly_cashflow <= 0:
        return monthly_cashflow, None, None
    exact_months = initial_capex / monthly_cashflow
    return monthly_cashflow, exact_months, _whole_months(exact_months)


def straight_line(amount: float, start_year: int, life: int, term: int) -> list[float]:
    schedule = [0.0] * (term + 1)
    if amount <= 0 or life <= 0:
        return schedule
    annual = amount / life
    for year in range(start_year, min(term, start_year + life - 1) + 1):
        schedule[year] += annual
    return schedule


def project_inventory(data: dict[str, Any]) -> tuple[float, float]:
    rooms = number(data, "project.rooms")
    room_types = get_path(data, "revenue.room_types")
    if not room_types:
        seats = number(data, "project.workstations", rooms * number(data, "project.seats_per_room", 2))
        return rooms, seats
    if not isinstance(room_types, list):
        raise ModelError("revenue.room_types 必须为数组")
    if not room_types:
        raise ModelError("revenue.room_types 不得为空")
    names: set[str] = set()
    typed_rooms = 0.0
    typed_seats = 0.0
    for index, room_type in enumerate(room_types):
        if not isinstance(room_type, dict):
            raise ModelError(f"revenue.room_types[{index}] 必须为对象")
        name = str(room_type.get("name", "")).strip()
        if not name:
            raise ModelError(f"revenue.room_types[{index}].name 不得为空")
        if name in names:
            raise ModelError(f"房型名称不得重复: {name}")
        names.add(name)
        type_rooms = float(room_type.get("rooms", 0))
        workstations_per_room = float(room_type.get("workstations_per_room", 0))
        if (
            not math.isfinite(type_rooms)
            or not math.isfinite(workstations_per_room)
            or type_rooms <= 0
            or workstations_per_room <= 0
            or not type_rooms.is_integer()
            or not workstations_per_room.is_integer()
        ):
            raise ModelError(f"房型房间数和每房机位数必须大于0: {name}")
        typed_rooms += type_rooms
        typed_seats += type_rooms * workstations_per_room
    if abs(typed_rooms - rooms) > 1e-6:
        raise ModelError(f"房型房间数合计{typed_rooms:g}与项目房间数{rooms:g}不一致")
    declared_seats = get_path(data, "project.workstations")
    if declared_seats is not None and abs(typed_seats - float(declared_seats)) > 1e-6:
        raise ModelError(f"房型机位数合计{typed_seats:g}与项目机位数{float(declared_seats):g}不一致")
    return rooms, typed_seats


def validate(data: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    rooms, seats = project_inventory(data)
    term = int(number(data, "project.term_years"))
    days = number(data, "project.operating_days", 365)
    if rooms <= 0 or term <= 0 or days <= 0 or seats <= 0:
        raise ModelError("房间数、机位数、合作期和经营天数必须大于0")
    if term != number(data, "project.term_years"):
        raise ModelError("合作期必须为整数年")

    jwl_share = rate(data, "contract.jwl_share")
    owner_share = rate(data, "contract.owner_share")
    if abs(jwl_share + owner_share - 1) > 1e-6:
        raise ModelError("双方分成比例之和必须等于100%")
    rate(data, "contract.exit_occ_threshold")
    rate(data, "revenue.base_occ")

    for path in [
        "revenue.ancillary_rate",
        "revenue.online_share",
        "public_costs.ota_commission_rate",
        "public_costs.traffic_rate",
        "public_costs.mystery_shopper_kol_rate",
        "public_costs.offline_promotion_rate",
        "public_costs.turnover_tax_rate",
        "jwl.replacement.rate",
    ]:
        rate(data, path, 0)

    require_nonnegative(data, [
        "revenue.egame_adr",
        "revenue.egame_revpar",
        "revenue.hourly_turnovers_per_room_day",
        "revenue.hourly_rate",
        "jwl.capex.cloud_box_per_seat",
        "jwl.capex.monitor_per_seat",
        "jwl.capex.peripherals_per_seat",
        "jwl.capex.peripherals_per_room",
        "jwl.capex.furniture_per_seat",
        "jwl.capex.furniture_per_room",
        "jwl.capex.install_per_room",
        "jwl.capex.platform_fixed",
        "jwl.opex_monthly.cloud_fee_per_seat",
        "owner.capex.renovation_per_room",
    ])

    mode = get_path(data, "revenue.mode", "adr_occ")
    if mode not in {"adr_occ", "revpar"}:
        raise ModelError("revenue.mode 仅支持 adr_occ 或 revpar")
    room_types = get_path(data, "revenue.room_types") or []
    if mode == "adr_occ" and get_path(data, "revenue.egame_adr") is None and not room_types:
        traditional_revpar = get_path(data, "revenue.traditional_revpar")
        traditional_adr = get_path(data, "revenue.traditional_adr")
        traditional_occ = get_path(data, "revenue.traditional_occ")
        if traditional_revpar is None and (traditional_adr is None or traditional_occ is None):
            raise ModelError("adr_occ模式需要egame_adr，或可推导的traditional_revpar/传统ADR+OCC")
        warnings.append("电竞ADR由合同RevPAR溢价底线反推，需用真实报价确认")
    if mode == "revpar" and get_path(data, "revenue.egame_revpar") is None and not room_types:
        raise ModelError("revpar模式需要revenue.egame_revpar")

    for index, room_type in enumerate(room_types):
        name = str(room_type.get("name", index))
        if "base_occ" not in room_type:
            raise ModelError(f"房型{name}缺少base_occ")
        type_occ = float(room_type["base_occ"])
        if not math.isfinite(type_occ) or not 0 <= type_occ <= 1:
            raise ModelError(f"房型{name}的base_occ必须在0到1之间")
        required_revenue_field = "egame_adr" if mode == "adr_occ" else "egame_revpar"
        if required_revenue_field not in room_type:
            raise ModelError(f"房型{name}缺少{required_revenue_field}")
        type_revenue = float(room_type[required_revenue_field])
        if not math.isfinite(type_revenue) or type_revenue < 0:
            raise ModelError(f"房型{name}的{required_revenue_field}必须为非负有限数值")
        if "traditional_contribution_margin_rate" in room_type:
            margin = float(room_type["traditional_contribution_margin_rate"])
            if not math.isfinite(margin) or not 0 <= margin <= 1:
                raise ModelError(f"房型{name}的传统房贡献毛利率必须在0到1之间")

    if get_path(data, "revenue.traditional_contribution_margin_rate") is not None:
        rate(data, "revenue.traditional_contribution_margin_rate")
    if get_path(data, "revenue.first_year_monthly_occ_schedule") is not None:
        if mode == "revpar":
            raise ModelError("首年月度OCC爬坡不适用于收入固定的revpar模式")
        monthly_rows = first_year_monthly_business(data)
        calendar_days = sum(int(row["calendar_days"]) for row in monthly_rows)
        if abs(calendar_days - days) > 1e-6:
            raise ModelError(
                f"首年自然日合计{calendar_days}与project.operating_days={days:g}不一致"
            )

    if number(data, "revenue.hourly_turnovers_per_room_day", 0) > 0:
        warnings.append("钟点/包场与过夜房共用库存；当前模型按独立增量收入计算，请核实不存在重复占房")
    if get_path(data, "revenue.traditional_revpar") is None and (
        get_path(data, "revenue.traditional_adr") is None
        or get_path(data, "revenue.traditional_occ") is None
    ):
        warnings.append("缺少传统房RevPAR或传统ADR+OCC，无法执行合同定价底线校验")
    return warnings


def contract_price_floor(data: dict[str, Any], occ: float, esports_revpar: float) -> dict[str, Any]:
    traditional_revpar = get_path(data, "revenue.traditional_revpar")
    if traditional_revpar is None:
        traditional_adr = get_path(data, "revenue.traditional_adr")
        traditional_occ = get_path(data, "revenue.traditional_occ")
        if traditional_adr is not None and traditional_occ is not None:
            traditional_revpar = float(traditional_adr) * float(traditional_occ)
    if traditional_revpar is None:
        return {"status": "not_checked", "reason": "缺少传统房RevPAR或传统ADR+OCC"}

    high_share = rate(data, "contract.high_season_share", 0.4)
    high_premium = rate(data, "contract.high_season_premium", 0.3)
    low_premium = rate(data, "contract.low_season_premium", 0.1)
    weighted_multiplier = high_share * (1 + high_premium) + (1 - high_share) * (1 + low_premium)
    required_revpar = float(traditional_revpar) * weighted_multiplier
    margin = esports_revpar - required_revpar
    return {
        "status": "pass" if margin >= -1e-6 else "fail",
        "traditional_revpar": float(traditional_revpar),
        "weighted_contract_multiplier": weighted_multiplier,
        "required_esports_revpar": required_revpar,
        "actual_esports_revpar": esports_revpar,
        "margin": margin,
        "implied_minimum_adr_at_current_occ": required_revpar / occ if occ > 0 else None,
    }


def traditional_opportunity_cost(
    data: dict[str, Any], year: int, rooms: float, days: float
) -> dict[str, float] | None:
    room_types = get_path(data, "revenue.room_types")
    global_margin = get_path(data, "revenue.traditional_contribution_margin_rate")
    has_type_margin = bool(
        room_types
        and any("traditional_contribution_margin_rate" in room_type for room_type in room_types)
    )
    if global_margin is None and not has_type_margin:
        return None

    revenue_factor = (1 + number(data, "finance.revenue_growth", 0)) ** (year - 1)
    baseline_revenue = 0.0
    contribution = 0.0
    if room_types:
        for room_type in room_types:
            type_rooms = float(room_type["rooms"])
            type_revpar = room_type.get("traditional_revpar", get_path(data, "revenue.traditional_revpar"))
            if type_revpar is None:
                type_adr = room_type.get("traditional_adr", get_path(data, "revenue.traditional_adr"))
                type_occ = room_type.get("traditional_occ", get_path(data, "revenue.traditional_occ"))
                if type_adr is None or type_occ is None:
                    raise ModelError("计算传统房机会成本需要每个房型或全店的传统ADR与OCC")
                type_revpar = float(type_adr) * float(type_occ)
            margin = room_type.get("traditional_contribution_margin_rate", global_margin)
            if margin is None:
                raise ModelError("计算传统房机会成本需要传统房贡献毛利率")
            type_revenue = float(type_revpar) * type_rooms * days * revenue_factor
            baseline_revenue += type_revenue
            contribution += type_revenue * float(margin)
    else:
        traditional_revpar = get_path(data, "revenue.traditional_revpar")
        if traditional_revpar is None:
            traditional_adr = get_path(data, "revenue.traditional_adr")
            traditional_occ = get_path(data, "revenue.traditional_occ")
            if traditional_adr is None or traditional_occ is None:
                raise ModelError("计算传统房机会成本需要传统房RevPAR或传统ADR与OCC")
            traditional_revpar = float(traditional_adr) * float(traditional_occ)
        baseline_revenue = float(traditional_revpar) * rooms * days * revenue_factor
        contribution = baseline_revenue * float(global_margin)
    return {
        "traditional_baseline_revenue": baseline_revenue,
        "replaced_traditional_contribution": contribution,
    }


def jwl_capex(data: dict[str, Any], rooms: float, seats: float) -> tuple[dict[str, float], float]:
    components = {
        "cloud_box_per_seat": number(data, "jwl.capex.cloud_box_per_seat", 0) * seats,
        "monitor_per_seat": number(data, "jwl.capex.monitor_per_seat", 0) * seats,
        "peripherals_per_seat": number(data, "jwl.capex.peripherals_per_seat", 0) * seats,
        "peripherals_per_room": number(data, "jwl.capex.peripherals_per_room", 0) * rooms,
        "furniture_per_seat": number(data, "jwl.capex.furniture_per_seat", 0) * seats,
        "furniture_per_room": number(data, "jwl.capex.furniture_per_room", 0) * rooms,
        "install_per_room": number(data, "jwl.capex.install_per_room", 0) * rooms,
        "platform_fixed": number(data, "jwl.capex.platform_fixed", 0),
        "other_fixed": number(data, "jwl.capex.other_fixed", 0),
    }
    return components, sum(components.values())


def owner_capex(data: dict[str, Any], rooms: float) -> tuple[dict[str, float], float]:
    components = {
        "renovation_per_room": number(data, "owner.capex.renovation_per_room", 0) * rooms,
        "weak_current_per_room": number(data, "owner.capex.weak_current_per_room", 0) * rooms,
        "other_fixed": number(data, "owner.capex.other_fixed", 0),
    }
    return components, sum(components.values())


def replacement_amount(data: dict[str, Any], capex_components: dict[str, float]) -> float:
    override = get_path(data, "jwl.replacement.amount")
    if override is not None:
        return float(override)
    basis = get_path(
        data,
        "jwl.replacement.basis_components",
        ["peripherals_per_seat", "peripherals_per_room", "furniture_per_seat", "furniture_per_room"],
    )
    if not isinstance(basis, list):
        raise ModelError("jwl.replacement.basis_components 必须为数组")
    unknown = [name for name in basis if name not in capex_components]
    if unknown:
        raise ModelError(f"未知的设备重置基数项: {', '.join(unknown)}")
    return sum(capex_components[name] for name in basis) * rate(data, "jwl.replacement.rate", 0)


def resolve_adr(data: dict[str, Any], occ: float) -> float:
    adr = get_path(data, "revenue.egame_adr")
    if adr is not None:
        return float(adr)
    traditional_revpar = get_path(data, "revenue.traditional_revpar")
    if traditional_revpar is None:
        traditional_revpar = number(data, "revenue.traditional_adr") * rate(data, "revenue.traditional_occ")
    high_share = rate(data, "contract.high_season_share", 0.4)
    multiplier = high_share * (1 + rate(data, "contract.high_season_premium", 0.3))
    multiplier += (1 - high_share) * (1 + rate(data, "contract.low_season_premium", 0.1))
    if occ <= 0:
        raise ModelError("OCC为0时无法从合同RevPAR底线反推ADR")
    return float(traditional_revpar) * multiplier / occ


def year_business(
    data: dict[str, Any],
    year: int,
    occ: float,
    force_room_type_occ: bool = False,
    days_override: float | None = None,
    fixed_months: float = 12,
    other_annual_share: float = 1,
) -> dict[str, float]:
    rooms = number(data, "project.rooms")
    days = number(data, "project.operating_days", 365) if days_override is None else float(days_override)
    revenue_growth = number(data, "finance.revenue_growth", 0)
    inflation = number(data, "finance.cost_inflation", 0)
    revenue_factor = (1 + revenue_growth) ** (year - 1)
    cost_factor = (1 + inflation) ** (year - 1)
    mode = get_path(data, "revenue.mode", "adr_occ")

    room_types = get_path(data, "revenue.room_types")
    if room_types:
        available_room_nights = 0.0
        occupied_room_nights = 0.0
        overnight = 0.0
        for room_type in room_types:
            type_rooms = float(room_type["rooms"])
            type_occ = occ if force_room_type_occ else float(room_type.get("base_occ", occ))
            available = type_rooms * days
            occupied = available * type_occ
            if mode == "revpar":
                type_revpar = (
                    float(room_type["egame_revpar"])
                    if "egame_revpar" in room_type
                    else number(data, "revenue.egame_revpar")
                )
                type_revpar *= revenue_factor
                type_revenue = type_revpar * available
            else:
                type_adr = (
                    float(room_type["egame_adr"])
                    if "egame_adr" in room_type
                    else resolve_adr(data, type_occ)
                )
                type_adr *= revenue_factor
                type_revenue = type_adr * occupied
            available_room_nights += available
            occupied_room_nights += occupied
            overnight += type_revenue
        occ = occupied_room_nights / available_room_nights if available_room_nights else 0.0
        adr = overnight / occupied_room_nights if occupied_room_nights else 0.0
        revpar = overnight / available_room_nights if available_room_nights else 0.0
    elif mode == "revpar":
        revpar = number(data, "revenue.egame_revpar") * revenue_factor
        adr = revpar / occ if occ > 0 else 0.0
        overnight = revpar * rooms * days
        available_room_nights = rooms * days
        occupied_room_nights = available_room_nights * occ
    else:
        adr = resolve_adr(data, occ) * revenue_factor
        overnight = adr * rooms * occ * days
        revpar = adr * occ
        available_room_nights = rooms * days
        occupied_room_nights = available_room_nights * occ

    hourly = (
        rooms
        * rate(data, "revenue.hourly_eligible_room_share", 1)
        * number(data, "revenue.hourly_turnovers_per_room_day", 0)
        * number(data, "revenue.hourly_rate", 0)
        * days
        * revenue_factor
    )
    ancillary = (overnight + hourly) * rate(data, "revenue.ancillary_rate", 0)
    other = number(data, "revenue.other_annual", 0) * revenue_factor * other_annual_share
    gross = overnight + hourly + ancillary + other

    ota_commission = gross * rate(data, "revenue.online_share", 0) * rate(
        data, "public_costs.ota_commission_rate", 0
    )
    traffic = gross * rate(data, "public_costs.traffic_rate", 0)
    mystery_kol = gross * rate(data, "public_costs.mystery_shopper_kol_rate", 0)
    offline_promotion = gross * rate(data, "public_costs.offline_promotion_rate", 0)
    ota_performance = number(data, "public_costs.ota_performance_monthly", 0) * fixed_months * cost_factor
    manager = 0.0
    if rooms >= number(data, "public_costs.shared_manager_room_threshold", 25):
        manager = number(data, "public_costs.shared_manager_monthly", 0) * fixed_months * cost_factor
    public_pre_tax = ota_commission + traffic + mystery_kol + offline_promotion + ota_performance + manager
    tax_base = max(0.0, gross - public_pre_tax)
    turnover_tax = tax_base * rate(data, "public_costs.turnover_tax_rate", 0)
    public_total = public_pre_tax + turnover_tax
    distributable = gross - public_total

    return {
        "occ": occ,
        "adr": adr,
        "revpar": revpar,
        "available_room_nights": available_room_nights,
        "occupied_room_nights": occupied_room_nights,
        "overnight_revenue": overnight,
        "hourly_revenue": hourly,
        "ancillary_revenue": ancillary,
        "other_revenue": other,
        "gross_revenue": gross,
        "ota_commission": ota_commission,
        "traffic_cost": traffic,
        "mystery_shopper_kol_cost": mystery_kol,
        "offline_promotion_cost": offline_promotion,
        "ota_performance_cost": ota_performance,
        "shared_manager_cost": manager,
        "turnover_tax": turnover_tax,
        "public_cost_total": public_total,
        "distributable_net_revenue": distributable,
    }


def first_year_monthly_business(data: dict[str, Any]) -> list[dict[str, float | int | str]]:
    schedule = get_path(data, "revenue.first_year_monthly_occ_schedule")
    if schedule is None:
        return []
    if not isinstance(schedule, list) or len(schedule) != 12:
        raise ModelError("revenue.first_year_monthly_occ_schedule 必须恰好包含12个月")
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0 <= float(value) <= 1
        for value in schedule
    ):
        raise ModelError("首年月度OCC必须为0到1之间的有限数值")
    opening_text = str(get_path(data, "project.opening_date", ""))
    try:
        opening = date.fromisoformat(opening_text)
    except ValueError as exc:
        raise ModelError("首年月度爬坡需要有效的 project.opening_date") from exc
    if opening.day != 1:
        raise ModelError("当前月度爬坡仅支持每月1日开业")
    rows: list[dict[str, float | int | str]] = []
    for index, value in enumerate(schedule):
        month_index = opening.month - 1 + index
        calendar_year = opening.year + month_index // 12
        calendar_month = month_index % 12 + 1
        days = calendar.monthrange(calendar_year, calendar_month)[1]
        business = year_business(
            data,
            1,
            float(value),
            force_room_type_occ=True,
            days_override=days,
            fixed_months=1,
            other_annual_share=1 / 12,
        )
        rows.append({
            "month_index": index + 1,
            "month": f"{calendar_year:04d}-{calendar_month:02d}",
            "calendar_days": days,
            **business,
        })
    return rows


def aggregate_business(rows: list[dict[str, Any]]) -> dict[str, float]:
    sum_fields = [
        "available_room_nights",
        "occupied_room_nights",
        "overnight_revenue",
        "hourly_revenue",
        "ancillary_revenue",
        "other_revenue",
        "gross_revenue",
        "ota_commission",
        "traffic_cost",
        "mystery_shopper_kol_cost",
        "offline_promotion_cost",
        "ota_performance_cost",
        "shared_manager_cost",
        "turnover_tax",
        "public_cost_total",
        "distributable_net_revenue",
    ]
    result = {field: sum(float(row[field]) for row in rows) for field in sum_fields}
    available = result["available_room_nights"]
    occupied = result["occupied_room_nights"]
    overnight = result["overnight_revenue"]
    result["occ"] = occupied / available if available else 0.0
    result["adr"] = overnight / occupied if occupied else 0.0
    result["revpar"] = overnight / available if available else 0.0
    return result


def rolling_exit_assessment(
    data: dict[str, Any], monthly_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Check the contract's six-consecutive-month OCC exit condition.

    The contract trigger is a rolling operating condition, not a first-year
    average.  Use room-night weighting so months with different calendar days
    are compared on the same inventory basis.
    """
    threshold = rate(data, "contract.exit_occ_threshold")
    window_months = 6
    if len(monthly_rows) < window_months:
        return {
            "status": "not_checked",
            "reason": "缺少至少六个月的月度OCC计划",
            "threshold": threshold,
            "window_months": window_months,
            "triggered_window_start_months": [],
            "windows": [],
        }

    windows: list[dict[str, Any]] = []
    triggered: list[int] = []
    for start in range(len(monthly_rows) - window_months + 1):
        rows = monthly_rows[start : start + window_months]
        available = sum(float(row["available_room_nights"]) for row in rows)
        occupied = sum(float(row["occupied_room_nights"]) for row in rows)
        rolling_occ = occupied / available if available else 0.0
        start_month = int(rows[0]["month_index"])
        end_month = int(rows[-1]["month_index"])
        below_threshold = rolling_occ < threshold - 1e-12
        if below_threshold:
            triggered.append(start_month)
        windows.append(
            {
                "start_month": start_month,
                "end_month": end_month,
                "rolling_occ": rolling_occ,
                "below_threshold": below_threshold,
            }
        )

    return {
        "status": "triggered" if triggered else "not_triggered",
        "threshold": threshold,
        "window_months": window_months,
        "triggered_window_start_months": triggered,
        "windows": windows,
    }


def jwl_cash_opex(data: dict[str, Any], year: int, rooms: float, seats: float) -> float:
    monthly = number(data, "jwl.opex_monthly.cloud_fee_per_seat", 0) * seats
    monthly += number(data, "jwl.opex_monthly.accelerator_fixed", 0)
    monthly += number(data, "jwl.opex_monthly.system_fixed", 0)
    monthly += number(data, "jwl.opex_monthly.ota_team_fixed", 0)
    monthly += number(data, "jwl.opex_monthly.maintenance_fixed", 0)
    monthly += number(data, "jwl.opex_monthly.other_fixed", 0)
    monthly += number(data, "jwl.opex_monthly.other_per_room", 0) * rooms
    return monthly * 12 * ((1 + number(data, "finance.cost_inflation", 0)) ** (year - 1))


def owner_cash_opex(data: dict[str, Any], year: int, rooms: float, fully_loaded: bool) -> float:
    monthly = number(data, "owner.incremental_opex_monthly.electricity_per_room", 0) * rooms
    monthly += number(data, "owner.incremental_opex_monthly.linen_consumables_per_room", 0) * rooms
    monthly += number(data, "owner.incremental_opex_monthly.labor_fixed", 0)
    monthly += number(data, "owner.incremental_opex_monthly.other_fixed", 0)
    if fully_loaded:
        monthly += number(data, "owner.allocated_opex_monthly.rent_property_per_room", 0) * rooms
        monthly += number(data, "owner.allocated_opex_monthly.base_staffing_fixed", 0)
        monthly += number(data, "owner.allocated_opex_monthly.other_fixed", 0)
    return monthly * 12 * ((1 + number(data, "finance.cost_inflation", 0)) ** (year - 1))


def occ_schedule(data: dict[str, Any], term: int, fixed_occ: float | None = None) -> list[float]:
    if fixed_occ is not None:
        return [fixed_occ] * term
    schedule = get_path(data, "revenue.annual_occ_schedule")
    if schedule is None:
        return [rate(data, "revenue.base_occ")] * term
    if not isinstance(schedule, list) or not schedule:
        raise ModelError("revenue.annual_occ_schedule 必须为非空数组")
    values = [float(value) for value in schedule]
    if any(value < 0 or value > 1 for value in values):
        raise ModelError("年度OCC计划必须在0到1之间")
    if len(values) < term:
        values.extend([values[-1]] * (term - len(values)))
    return values[:term]


def side_metrics(
    cashflows: list[float],
    discount_rate: float,
    total_invested: float,
    *,
    first_year_operating_cashflow: float,
) -> dict[str, Any]:
    roots = irr_roots(cashflows)
    nonnegative_roots = [root for root in roots if root >= 0]
    selected_irr = nonnegative_roots[0] if nonnegative_roots else (roots[0] if roots else None)
    net_gain = sum(cashflows)
    static_payback_years = sustained_payback(cashflows)
    discounted_payback_years = sustained_payback(cashflows, discount_rate)
    (
        first_year_average_monthly_operating_net_cashflow,
        static_payback_months,
        static_payback_months_rounded_up,
    ) = static_monthly_payback(-cashflows[0], first_year_operating_cashflow)
    discounted_payback_months = (
        discounted_payback_years * 12
        if discounted_payback_years is not None
        else None
    )
    return {
        "cashflows": cashflows,
        "npv": npv(discount_rate, cashflows),
        "irr": selected_irr,
        "irr_all_roots": roots,
        "static_payback_years": static_payback_years,
        "discounted_payback_years": discounted_payback_years,
        "first_year_average_monthly_operating_net_cashflow": (
            first_year_average_monthly_operating_net_cashflow
        ),
        "static_payback_months": static_payback_months,
        "static_payback_months_rounded_up": static_payback_months_rounded_up,
        "discounted_payback_months": discounted_payback_months,
        "discounted_payback_months_rounded_up": _whole_months(
            discounted_payback_months
        ),
        "total_capital_invested": total_invested,
        "cumulative_net_cash": net_gain,
        "roi_total": net_gain / total_invested if total_invested > 0 else None,
    }


def solve_break_even(function: Callable[[float], float]) -> float | None:
    low, high = 0.0, 1.0
    low_value, high_value = function(low), function(high)
    if low_value >= 0:
        return 0.0
    if high_value < 0:
        return None
    for _ in range(100):
        mid = (low + high) / 2
        value = function(mid)
        if abs(value) < 1e-7:
            return mid
        if value >= 0:
            high = mid
        else:
            low = mid
    return (low + high) / 2


def compute_case(data: dict[str, Any], fixed_occ: float | None = None) -> dict[str, Any]:
    rooms, seats = project_inventory(data)
    term = int(number(data, "project.term_years"))
    discount_rate = number(data, "finance.discount_rate", 0.1)
    jwl_share = rate(data, "contract.jwl_share")
    owner_share = rate(data, "contract.owner_share")
    schedule = occ_schedule(data, term, fixed_occ)

    jwl_components, jwl_initial = jwl_capex(data, rooms, seats)
    owner_components, owner_initial = owner_capex(data, rooms)
    replacement = replacement_amount(data, jwl_components)
    replacement_year = int(number(data, "jwl.replacement.year", 3))
    if replacement_year < 1 or replacement_year > term:
        replacement = 0.0
        replacement_year = 0

    jwl_depreciable = jwl_initial - jwl_components["platform_fixed"] - jwl_components["other_fixed"]
    jwl_depreciation = straight_line(
        jwl_depreciable, 1, int(number(data, "contract.equipment_depreciation_years", 3)), term
    )
    if replacement > 0 and replacement_year < term:
        extra = straight_line(
            replacement,
            replacement_year + 1,
            int(number(data, "contract.equipment_depreciation_years", 3)),
            term,
        )
        jwl_depreciation = [a + b for a, b in zip(jwl_depreciation, extra)]
    owner_depreciation = straight_line(
        owner_initial, 1, int(number(data, "contract.renovation_depreciation_years", term)), term
    )

    annual: list[dict[str, Any]] = []
    jwl_cf = [-jwl_initial]
    owner_incremental_cf = [-owner_initial]
    owner_full_cf = [-owner_initial]
    opportunity_enabled = traditional_opportunity_cost(data, 1, rooms, days=number(data, "project.operating_days", 365)) is not None
    owner_economic_cf = [-owner_initial] if opportunity_enabled else None
    monthly = first_year_monthly_business(data) if fixed_occ is None else []
    contract_exit_assessment = rolling_exit_assessment(data, monthly)
    for year, occ in enumerate(schedule, start=1):
        business = (
            aggregate_business(monthly)
            if year == 1 and monthly
            else year_business(data, year, occ, force_room_type_occ=fixed_occ is not None)
        )
        jwl_share_revenue = business["distributable_net_revenue"] * jwl_share
        owner_share_revenue = business["distributable_net_revenue"] * owner_share
        jwl_opex = jwl_cash_opex(data, year, rooms, seats)
        owner_incremental_opex = owner_cash_opex(data, year, rooms, False)
        owner_full_opex = owner_cash_opex(data, year, rooms, True)
        replacement_cash = replacement if year == replacement_year else 0.0
        jwl_year_cf = jwl_share_revenue - jwl_opex - replacement_cash
        owner_incremental_year_cf = owner_share_revenue - owner_incremental_opex
        owner_full_year_cf = owner_share_revenue - owner_full_opex
        opportunity = traditional_opportunity_cost(
            data, year, rooms, days=number(data, "project.operating_days", 365)
        )
        if year == term:
            jwl_year_cf += number(data, "finance.jwl_salvage_value", 0)
            owner_incremental_year_cf += number(data, "finance.owner_terminal_value", 0)
            owner_full_year_cf += number(data, "finance.owner_terminal_value", 0)
        owner_economic_year_cf = None
        if opportunity is not None:
            owner_economic_year_cf = (
                owner_incremental_year_cf - opportunity["replaced_traditional_contribution"]
            )
        jwl_cf.append(jwl_year_cf)
        owner_incremental_cf.append(owner_incremental_year_cf)
        owner_full_cf.append(owner_full_year_cf)
        if owner_economic_cf is not None and owner_economic_year_cf is not None:
            owner_economic_cf.append(owner_economic_year_cf)
        annual.append({
            "year": year,
            **business,
            "jwl_share_revenue": jwl_share_revenue,
            "jwl_cash_opex": jwl_opex,
            "jwl_depreciation": jwl_depreciation[year],
            "jwl_accounting_profit": jwl_share_revenue - jwl_opex - jwl_depreciation[year],
            "jwl_replacement_capex": replacement_cash,
            "jwl_net_cashflow": jwl_year_cf,
            "owner_share_revenue": owner_share_revenue,
            "owner_incremental_cash_opex": owner_incremental_opex,
            "owner_fully_loaded_cash_opex": owner_full_opex,
            "owner_depreciation": owner_depreciation[year],
            "owner_incremental_net_cashflow": owner_incremental_year_cf,
            "owner_fully_loaded_net_cashflow": owner_full_year_cf,
            **(
                {
                    **opportunity,
                    "owner_economic_incremental_net_cashflow": owner_economic_year_cf,
                }
                if opportunity is not None
                else {}
            ),
        })

    if monthly:
        monthly_jwl_opex = jwl_cash_opex(data, 1, rooms, seats) / 12
        monthly_owner_incremental_opex = owner_cash_opex(data, 1, rooms, False) / 12
        monthly_owner_full_opex = owner_cash_opex(data, 1, rooms, True) / 12
        for row in monthly:
            jwl_share_revenue = float(row["distributable_net_revenue"]) * jwl_share
            owner_share_revenue = float(row["distributable_net_revenue"]) * owner_share
            replacement_cash = (
                replacement
                if replacement_year == 1 and int(row["month_index"]) == 12
                else 0.0
            )
            jwl_terminal = (
                number(data, "finance.jwl_salvage_value", 0)
                if term == 1 and int(row["month_index"]) == 12
                else 0.0
            )
            owner_terminal = (
                number(data, "finance.owner_terminal_value", 0)
                if term == 1 and int(row["month_index"]) == 12
                else 0.0
            )
            owner_incremental_month_cf = (
                owner_share_revenue - monthly_owner_incremental_opex + owner_terminal
            )
            row.update({
                "jwl_share_revenue": jwl_share_revenue,
                "jwl_cash_opex": monthly_jwl_opex,
                "jwl_replacement_capex": replacement_cash,
                "jwl_net_cashflow": (
                    jwl_share_revenue - monthly_jwl_opex - replacement_cash + jwl_terminal
                ),
                "owner_share_revenue": owner_share_revenue,
                "owner_incremental_cash_opex": monthly_owner_incremental_opex,
                "owner_fully_loaded_cash_opex": monthly_owner_full_opex,
                "owner_incremental_net_cashflow": owner_incremental_month_cf,
                "owner_fully_loaded_net_cashflow": (
                    owner_share_revenue - monthly_owner_full_opex + owner_terminal
                ),
            })
            opportunity = traditional_opportunity_cost(
                data, 1, rooms, days=float(row["calendar_days"])
            )
            if opportunity is not None:
                row.update({
                    **opportunity,
                    "owner_economic_incremental_net_cashflow": (
                        owner_incremental_month_cf
                        - opportunity["replaced_traditional_contribution"]
                    ),
                })

    total_jwl_invested = jwl_initial + replacement
    base_occ = annual[0]["occ"]
    revenue_mode = get_path(data, "revenue.mode", "adr_occ")

    def break_even_metrics(function: Callable[[float], float]) -> dict[str, Any]:
        if revenue_mode == "revpar":
            return {
                "break_even_occ": None,
                "break_even_occ_status": "not_applicable",
                "break_even_occ_reason": (
                    "RevPAR模式按每可售房夜收入计价，OCC不驱动收入；"
                    "需使用ADR/OCC模式或补充OCC实际数据"
                ),
            }
        return {
            "break_even_occ": solve_break_even(function),
            "break_even_occ_status": "calculated",
            "break_even_occ_reason": "按ADR/OCC模式的完整现金方程求解",
        }

    def jwl_cf_at_occ(candidate_occ: float) -> float:
        business = year_business(data, 1, candidate_occ, force_room_type_occ=True)
        return business["distributable_net_revenue"] * jwl_share - jwl_cash_opex(data, 1, rooms, seats)

    def owner_incremental_cf_at_occ(candidate_occ: float) -> float:
        business = year_business(data, 1, candidate_occ, force_room_type_occ=True)
        return business["distributable_net_revenue"] * owner_share - owner_cash_opex(data, 1, rooms, False)

    def owner_full_cf_at_occ(candidate_occ: float) -> float:
        business = year_business(data, 1, candidate_occ, force_room_type_occ=True)
        return business["distributable_net_revenue"] * owner_share - owner_cash_opex(data, 1, rooms, True)

    def owner_economic_cf_at_occ(candidate_occ: float) -> float:
        opportunity = traditional_opportunity_cost(
            data, 1, rooms, days=number(data, "project.operating_days", 365)
        )
        if opportunity is None:
            raise ModelError("未启用传统房机会成本")
        return owner_incremental_cf_at_occ(candidate_occ) - opportunity["replaced_traditional_contribution"]

    price_floor = contract_price_floor(data, base_occ, annual[0]["revpar"])
    jwl_first_year_operating_cashflow = (
        float(annual[0]["jwl_net_cashflow"])
        + float(annual[0]["jwl_replacement_capex"])
    )
    owner_incremental_first_year_operating_cashflow = float(
        annual[0]["owner_incremental_net_cashflow"]
    )
    owner_full_first_year_operating_cashflow = float(
        annual[0]["owner_fully_loaded_net_cashflow"]
    )
    owner_economic_first_year_operating_cashflow = (
        float(annual[0]["owner_economic_incremental_net_cashflow"])
        if owner_economic_cf is not None
        else None
    )
    if term == 1:
        jwl_first_year_operating_cashflow -= number(
            data, "finance.jwl_salvage_value", 0
        )
        owner_terminal = number(data, "finance.owner_terminal_value", 0)
        owner_incremental_first_year_operating_cashflow -= owner_terminal
        owner_full_first_year_operating_cashflow -= owner_terminal
        if owner_economic_first_year_operating_cashflow is not None:
            owner_economic_first_year_operating_cashflow -= owner_terminal
    return {
        "annual": annual,
        **({"monthly": monthly} if monthly else {}),
        "contract_exit_assessment": contract_exit_assessment,
        "jwl": {
            "initial_capex": jwl_initial,
            "capex_components": jwl_components,
            "replacement_capex": replacement,
            "replacement_year": replacement_year,
            **break_even_metrics(jwl_cf_at_occ),
            **side_metrics(
                jwl_cf,
                discount_rate,
                total_jwl_invested,
                first_year_operating_cashflow=jwl_first_year_operating_cashflow,
            ),
        },
        "owner_incremental": {
            "initial_capex": owner_initial,
            "capex_components": owner_components,
            **break_even_metrics(owner_incremental_cf_at_occ),
            **side_metrics(
                owner_incremental_cf,
                discount_rate,
                owner_initial,
                first_year_operating_cashflow=(
                    owner_incremental_first_year_operating_cashflow
                ),
            ),
        },
        "owner_fully_loaded": {
            "initial_capex": owner_initial,
            "capex_components": owner_components,
            **break_even_metrics(owner_full_cf_at_occ),
            **side_metrics(
                owner_full_cf,
                discount_rate,
                owner_initial,
                first_year_operating_cashflow=owner_full_first_year_operating_cashflow,
            ),
        },
        "owner_economic_incremental": (
            {
                "status": "calculated",
                "initial_capex": owner_initial,
                "capex_components": owner_components,
                **break_even_metrics(owner_economic_cf_at_occ),
                **side_metrics(
                    owner_economic_cf,
                    discount_rate,
                    owner_initial,
                    first_year_operating_cashflow=(
                        owner_economic_first_year_operating_cashflow
                    ),
                ),
            }
            if owner_economic_cf is not None
            else {
                "status": "not_calculated",
                "reason": "缺少传统房贡献毛利率，未扣除被替代客房机会成本",
            }
        ),
        "contract_price_floor": price_floor,
    }


def compact_scenario(data: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    scenario_data = deep_merge(data, scenario.get("overrides", {}))
    occ = scenario.get("occ")
    case = compute_case(scenario_data, float(occ) if occ is not None else None)
    first = case["annual"][0]
    return {
        "name": scenario.get("name", "未命名情景"),
        "occ": first["occ"],
        "gross_revenue_year_1": first["gross_revenue"],
        "jwl_cashflow_year_1": first["jwl_net_cashflow"] + first["jwl_replacement_capex"],
        "jwl_npv": case["jwl"]["npv"],
        "jwl_irr": case["jwl"]["irr"],
        "jwl_static_payback_years": case["jwl"]["static_payback_years"],
        "jwl_static_payback_months": case["jwl"]["static_payback_months"],
        "jwl_static_payback_months_rounded_up": case["jwl"][
            "static_payback_months_rounded_up"
        ],
        "jwl_discounted_payback_months": case["jwl"][
            "discounted_payback_months"
        ],
        "jwl_discounted_payback_months_rounded_up": case["jwl"][
            "discounted_payback_months_rounded_up"
        ],
        "owner_full_cashflow_year_1": first["owner_fully_loaded_net_cashflow"],
        "owner_full_npv": case["owner_fully_loaded"]["npv"],
    }


def negotiation_terms(data: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    hurdle = number(data, "finance.hurdle_irr", 0.2)
    if hurdle <= -1:
        raise ModelError("谈判反求的目标收益率必须大于-100%")
    present_value_distributable = 0.0
    present_value_nonshare_costs = 0.0
    present_value_current_operations = 0.0
    current_share = rate(data, "contract.jwl_share")
    annual = base["annual"]
    for row in annual:
        year = int(row["year"])
        factor = (1 + hurdle) ** year
        distributable = float(row["distributable_net_revenue"])
        nonshare_cost = float(row["jwl_cash_opex"]) + float(row["jwl_replacement_capex"])
        terminal = (
            number(data, "finance.jwl_salvage_value", 0)
            if year == len(annual)
            else 0.0
        )
        present_value_distributable += distributable / factor
        present_value_nonshare_costs += (nonshare_cost - terminal) / factor
        present_value_current_operations += (
            distributable * current_share - nonshare_cost + terminal
        ) / factor

    initial_capex = float(base["jwl"]["initial_capex"])
    minimum_share = None
    if present_value_distributable > 0:
        candidate = (initial_capex + present_value_nonshare_costs) / present_value_distributable
        if candidate <= 1 + 1e-12:
            minimum_share = max(0.0, candidate)

    maximum_initial_capex = (
        present_value_current_operations if present_value_current_operations >= 0 else None
    )
    return {
        "hurdle_irr": hurdle,
        "current_jwl_share": current_share,
        "minimum_jwl_share_for_hurdle": minimum_share,
        "jwl_share_headroom": (
            current_share - minimum_share if minimum_share is not None else None
        ),
        "maximum_jwl_initial_capex_at_hurdle": maximum_initial_capex,
        "current_jwl_initial_capex": initial_capex,
        "jwl_initial_capex_headroom": (
            maximum_initial_capex - initial_capex
            if maximum_initial_capex is not None
            else None
        ),
        "status": (
            "feasible"
            if minimum_share is not None and maximum_initial_capex is not None
            else "infeasible"
        ),
    }


def sensitivity(data: dict[str, Any], base_npv: float) -> list[dict[str, Any]]:
    revenue_mode = get_path(data, "revenue.mode", "adr_occ")
    revenue_driver = (
        ("电竞ADR", "revenue.egame_adr", "egame_adr")
        if revenue_mode == "adr_occ"
        else ("电竞RevPAR", "revenue.egame_revpar", "egame_revpar")
    )
    drivers = [
        ("入住率OCC", "revenue.base_occ"),
        revenue_driver[:2],
        ("云算力月费/台", "jwl.opex_monthly.cloud_fee_per_seat"),
        ("OTA佣金率", "public_costs.ota_commission_rate"),
        ("云盒单价/台", "jwl.capex.cloud_box_per_seat"),
    ]
    results: list[dict[str, Any]] = []
    for name, path in drivers:
        value = get_path(data, path)
        room_types = get_path(data, "revenue.room_types") or []
        if value is None and path == revenue_driver[1] and room_types:
            value = sum(
                float(room_type[revenue_driver[2]]) * float(room_type["rooms"])
                for room_type in room_types
            ) / sum(float(room_type["rooms"]) for room_type in room_types)
        if value is None and path == "revenue.base_occ" and room_types:
            value = sum(
                float(room_type["base_occ"]) * float(room_type["rooms"])
                for room_type in room_types
            ) / sum(float(room_type["rooms"]) for room_type in room_types)
        if value is None or float(value) == 0:
            continue
        low_data, high_data = copy.deepcopy(data), copy.deepcopy(data)
        if path == revenue_driver[1] and room_types:
            for low_type, high_type in zip(
                low_data["revenue"]["room_types"], high_data["revenue"]["room_types"]
            ):
                low_type[revenue_driver[2]] = float(low_type[revenue_driver[2]]) * 0.9
                high_type[revenue_driver[2]] = float(high_type[revenue_driver[2]]) * 1.1
        elif path == "revenue.base_occ" and (
            room_types or get_path(data, "revenue.first_year_monthly_occ_schedule") is not None
        ):
            set_path(low_data, path, max(0.0, float(value) * 0.9))
            set_path(high_data, path, min(1.0, float(value) * 1.1))
            if room_types:
                for low_type, high_type in zip(
                    low_data["revenue"]["room_types"], high_data["revenue"]["room_types"]
                ):
                    low_type["base_occ"] = max(0.0, float(low_type["base_occ"]) * 0.9)
                    high_type["base_occ"] = min(1.0, float(high_type["base_occ"]) * 1.1)
            for candidate, factor in ((low_data, 0.9), (high_data, 1.1)):
                monthly_schedule = get_path(candidate, "revenue.first_year_monthly_occ_schedule")
                if monthly_schedule is not None:
                    candidate["revenue"]["first_year_monthly_occ_schedule"] = [
                        min(1.0, max(0.0, float(month_occ) * factor))
                        for month_occ in monthly_schedule
                    ]
        else:
            set_path(low_data, path, float(value) * 0.9)
            set_path(high_data, path, float(value) * 1.1)
        low_npv = compute_case(low_data)["jwl"]["npv"]
        high_npv = compute_case(high_data)["jwl"]["npv"]
        results.append({
            "driver": name,
            "path": path,
            "base_value": float(value),
            "npv_at_minus_10pct": low_npv,
            "npv_at_plus_10pct": high_npv,
            "npv_swing": high_npv - low_npv,
            "absolute_impact_rank_value": abs(high_npv - low_npv),
            "base_npv": base_npv,
        })
    return sorted(results, key=lambda item: item["absolute_impact_rank_value"], reverse=True)


def admission_assessment(data: dict[str, Any]) -> dict[str, Any]:
    admission = get_path(data, "admission", {})
    if not isinstance(admission, dict):
        raise ModelError("admission 必须为对象")
    gates = admission.get("hard_gates", {})
    scores = admission.get("scores", {})
    if not isinstance(gates, dict) or not isinstance(scores, dict):
        raise ModelError("admission.hard_gates 和 admission.scores 必须为对象")

    failed_gates = [name for name, value in gates.items() if value is False]
    unknown_gates = [name for name, value in gates.items() if value is not True and value is not False]
    weights = admission.get("weights", {
        "location_customer": 0.30,
        "property_hardware": 0.25,
        "room_scale": 0.15,
        "operating_basics": 0.20,
        "commercial_terms": 0.10,
    })
    if not isinstance(weights, dict):
        raise ModelError("admission.weights 必须为对象")
    weighted_score = None
    if scores:
        missing = [name for name in weights if name not in scores]
        if missing:
            unknown_gates.append("准入评分缺少: " + ", ".join(missing))
        else:
            weight_sum = sum(float(value) for value in weights.values())
            if abs(weight_sum - 1) > 1e-6:
                raise ModelError("admission.weights 之和必须等于100%")
            for name, value in scores.items():
                if not 0 <= float(value) <= 100:
                    raise ModelError(f"准入评分必须在0到100之间: {name}")
            weighted_score = sum(float(scores[name]) * float(weight) for name, weight in weights.items())

    minimum = float(admission.get("minimum_score", 60))
    priority = float(admission.get("priority_score", 75))
    if failed_gates or (weighted_score is not None and weighted_score < minimum):
        status = "fail"
    elif not gates and not scores:
        status = "not_evaluated"
    elif unknown_gates or weighted_score is None or weighted_score < priority:
        status = "conditional"
    else:
        status = "pass"
    return {
        "status": status,
        "failed_gates": failed_gates,
        "unknown_gates": unknown_gates,
        "weighted_score": weighted_score,
        "minimum_score": minimum,
        "priority_score": priority,
    }


def decide(
    data: dict[str, Any],
    base: dict[str, Any],
    negotiation: dict[str, Any],
    scenarios: list[dict[str, Any]],
    admission: dict[str, Any],
    warnings: list[str],
    used_default_paths: list[str],
) -> dict[str, Any]:
    hard_failures: list[str] = []
    cautions: list[str] = []
    jwl = base["jwl"]
    first = base["annual"][0]
    exit_occ = rate(data, "contract.exit_occ_threshold")
    hurdle = number(data, "finance.hurdle_irr", 0.2)
    max_payback = number(data, "finance.maximum_discounted_payback_years", 3)
    safety_buffer = number(data, "finance.exit_occ_safety_buffer", 0.1)

    if admission["status"] == "fail":
        if admission["failed_gates"]:
            hard_failures.append("准入硬性门槛未通过: " + ", ".join(admission["failed_gates"]))
        if admission["weighted_score"] is not None and admission["weighted_score"] < admission["minimum_score"]:
            hard_failures.append("准入加权评分低于最低合作门槛")
    elif admission["status"] == "conditional":
        cautions.append("准入评估仅条件通过，需补齐硬门槛或提升评分")
    elif admission["status"] == "not_evaluated":
        warnings.append("尚未结构化确认物业、法务、电力、网络和改造准入门槛")

    if first["occ"] < exit_occ:
        hard_failures.append("基准OCC低于合同连续6个月退出红线")
    exit_assessment = base.get("contract_exit_assessment", {})
    if exit_assessment.get("status") == "triggered":
        windows = ", ".join(
            str(month) for month in exit_assessment.get("triggered_window_start_months", [])
        )
        hard_failures.append(
            "月度OCC存在连续六个月低于合同退出红线"
            + (f"（窗口起始月：{windows}）" if windows else "")
        )
    elif exit_assessment.get("status") == "not_checked":
        cautions.append("缺少至少六个月的月度OCC计划，无法验证连续六个月退出红线")
    if first["jwl_net_cashflow"] + first["jwl_replacement_capex"] <= 0:
        hard_failures.append("智竞基准年度经营现金流不为正")
    if jwl["npv"] <= 0:
        hard_failures.append("智竞NPV不为正")
    if jwl["irr"] is None:
        hard_failures.append("现金流不具备可解释的IRR")

    if jwl["irr"] is not None and jwl["irr"] < hurdle:
        cautions.append("智竞IRR低于内部收益率门槛")
    if jwl["discounted_payback_years"] is None or jwl["discounted_payback_years"] > max_payback:
        cautions.append("智竞动态回收期超过门槛")
    if first["occ"] < exit_occ + safety_buffer:
        cautions.append("基准OCC安全垫不足10个百分点")
    break_even_status = jwl.get("break_even_occ_status", "calculated")
    if break_even_status == "not_applicable":
        cautions.append("RevPAR模式下盈亏平衡OCC不适用，需补充OCC或切换ADR/OCC模式")
    elif jwl["break_even_occ"] is None:
        hard_failures.append("即使OCC达到100%，智竞年度经营现金流仍不能盈亏平衡")
    elif jwl["break_even_occ"] > exit_occ:
        cautions.append("智竞盈亏平衡OCC高于合同退出红线")
    if base["contract_price_floor"]["status"] == "fail":
        cautions.append("电竞房RevPAR未达到合同淡旺季加权溢价底线")
    owner_economic = base["owner_economic_incremental"]
    owner_full = base["owner_fully_loaded"]
    if first["owner_fully_loaded_net_cashflow"] <= 0:
        cautions.append("业主完全成本口径首年经营现金流不为正")
    if owner_full["npv"] <= 0:
        cautions.append("业主完全成本口径NPV不为正")
    if owner_economic.get("status") == "calculated":
        if owner_economic["npv"] <= 0:
            cautions.append("业主相对继续经营传统房的经济增量NPV不为正，合作条件缺乏吸引力")
    else:
        warnings.append("缺少传统房贡献毛利率，尚未评价业主相对传统房的真实增量收益")
    if len(jwl["irr_all_roots"]) > 1:
        cautions.append("现金流存在多个IRR根，优先使用NPV与回收期判断")
    minimum_share = negotiation["minimum_jwl_share_for_hurdle"]
    if minimum_share is None:
        hard_failures.append("即使智竞取得100%分成，仍无法达到目标收益率")
    elif negotiation["current_jwl_share"] + 1e-12 < minimum_share:
        cautions.append("当前智竞分成低于达到目标收益率所需的最低分成")
    maximum_initial = negotiation["maximum_jwl_initial_capex_at_hurdle"]
    if maximum_initial is None:
        hard_failures.append("即使初始投资降为0，项目仍无法达到目标收益率")
    elif negotiation["current_jwl_initial_capex"] > maximum_initial + 0.01:
        cautions.append("当前智竞初投超过达到目标收益率可承受的最高初投")
    if scenarios:
        downside = min(scenarios, key=lambda item: item["occ"])
        if downside["occ"] < exit_occ:
            warnings.append(
                f"低OCC情景“{downside['name']}”低于合同退出红线；若连续6个月发生，将触发退出权"
            )
        if downside["jwl_npv"] <= 0:
            cautions.append(f"低OCC情景“{downside['name']}”下智竞NPV为负")

    declared_confidence = str(get_path(data, "metadata.data_confidence", "low")).lower()
    if declared_confidence not in CONFIDENCE_RANK:
        declared_confidence = "low"
        warnings.append("metadata.data_confidence无效，已按low处理")
    evidence_confidence = infer_evidence_confidence(data)
    predictive_confidence = forecast_confidence(data, warnings)
    confidence = confidence_at_most(declared_confidence, evidence_confidence)
    confidence = confidence_at_most(confidence, predictive_confidence)
    if confidence != declared_confidence and predictive_confidence == "low":
        warnings.append("未完成历史回测校准，正式结论的预测置信度已封顶为低")
    if confidence != declared_confidence and evidence_confidence == "low":
        warnings.append("输入证据不足以支持高置信度结论，数据置信度已封顶为低")
    if confidence not in CONFIDENCE_RANK:
        confidence = "low"
    material_prefixes = ("revenue.", "public_costs.", "jwl.", "owner.", "finance.")
    material_defaults = [path for path in used_default_paths if path.startswith(material_prefixes)]
    if material_defaults:
        confidence = "low"
        warnings.append("收入、成本或财务参数使用项目基准默认值，结论置信度已降为低")
    if admission["status"] == "not_evaluated":
        confidence = "low"
    if hard_failures:
        rating = "不建议合作"
    elif cautions:
        rating = "审慎推进"
    elif confidence == "low":
        rating = "条件性推进"
    else:
        rating = "建议合作"
    return {
        "rating": rating,
        "data_confidence": confidence,
        "declared_data_confidence": declared_confidence,
        "evidence_confidence": evidence_confidence,
        "forecast_confidence": predictive_confidence,
        "hard_failures": hard_failures,
        "cautions": cautions,
        "warnings": warnings,
    }


def money(value: float | None) -> str:
    if value is None:
        return "无法计算"
    return f"{value / 10000:,.2f}万元"


def percent(value: float | None) -> str:
    if value is None:
        return "无法计算"
    return f"{value:.1%}"


def months(value: float | None, rounded_up: int | None) -> str:
    if value is None:
        return "不回本"
    if rounded_up is None:
        return f"{value:.1f}个月"
    return f"{rounded_up}个月（测算值{value:.1f}个月）"


def feishu_summary(result: dict[str, Any]) -> str:
    base = result["base_case"]
    decision = result["decision"]
    jwl = base["jwl"]
    owner = base["owner_fully_loaded"]
    owner_economic = base["owner_economic_incremental"]
    negotiation = result["negotiation"]
    first = base["annual"][0]
    exit_assessment = base.get("contract_exit_assessment", {})
    exit_status_label = {
        "triggered": "已触发",
        "not_triggered": "未触发",
        "not_checked": "未检查",
    }.get(exit_assessment.get("status"), "未知")
    confidence_label = {"high": "高", "medium": "中", "low": "低"}.get(
        decision["data_confidence"], "低"
    )
    break_even_label = (
        "不适用（RevPAR模式）"
        if jwl.get("break_even_occ_status") == "not_applicable"
        else percent(jwl["break_even_occ"])
    )
    lines = [
        f"【结论】{decision['rating']}（有效置信度：{confidence_label}；数据声明{decision['declared_data_confidence']}、证据{decision['evidence_confidence']}、预测{decision['forecast_confidence']}）",
        f"智竞：初投{money(jwl['initial_capex'])}；首年经营净现金{money(first['jwl_net_cashflow'] + first['jwl_replacement_capex'])}；静态回本{months(jwl['static_payback_months'], jwl['static_payback_months_rounded_up'])}；动态回本{months(jwl['discounted_payback_months'], jwl['discounted_payback_months_rounded_up'])}（折现）；IRR {percent(jwl['irr'])}；NPV {money(jwl['npv'])}",
        f"业主（完全成本）：初投{money(owner['initial_capex'])}；首年净现金{money(first['owner_fully_loaded_net_cashflow'])}；静态回本{months(owner['static_payback_months'], owner['static_payback_months_rounded_up'])}；动态回本{months(owner['discounted_payback_months'], owner['discounted_payback_months_rounded_up'])}（折现）；NPV {money(owner['npv'])}",
        f"阈值：基准OCC {percent(first['occ'])}；智竞盈亏平衡OCC {break_even_label}；合同退出红线 {percent(result['contract_exit_occ_threshold'])}；六个月滚动检查 {exit_status_label}",
        (
            "谈判底线："
            f"目标IRR {percent(negotiation['hurdle_irr'])}；"
            f"智竞最低分成 {percent(negotiation['minimum_jwl_share_for_hurdle'])}；"
            f"最高初投 {money(negotiation['maximum_jwl_initial_capex_at_hurdle'])}；"
            f"当前初投余量 {money(negotiation['jwl_initial_capex_headroom'])}"
        ),
    ]
    if owner_economic.get("status") == "calculated":
        lines.insert(
            3,
            "业主（相对传统房）："
            f"首年经济增量{money(first['owner_economic_incremental_net_cashflow'])}；"
            f"NPV {money(owner_economic['npv'])}",
        )
    risks = decision["hard_failures"] + decision["cautions"] + decision["warnings"]
    if risks:
        lines.append("关键风险：")
        lines.extend(f"- {item}" for item in risks[:5])
    if result["used_default_paths"]:
        lines.append("待确认：本次使用了基准默认值，优先补齐真实OCC、电竞ADR/RevPAR、机位配置、设备报价和月度成本。")
    return "\n".join(lines)


def run(user_input: dict[str, Any], defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    defaults = defaults or {}
    data = deep_merge(defaults, user_input)
    used_default_paths = sorted(leaf_paths(defaults) - leaf_paths(user_input))
    warnings = validate(data)
    admission = admission_assessment(data)
    base = compute_case(data)
    negotiation = negotiation_terms(data, base)
    scenario_specs = get_path(data, "scenarios", [])
    if not isinstance(scenario_specs, list):
        raise ModelError("scenarios 必须为数组")
    scenarios = [compact_scenario(data, scenario) for scenario in scenario_specs]
    decision = decide(data, base, negotiation, scenarios, admission, warnings, used_default_paths)
    result = {
        "status": "ok",
        "project_name": get_path(data, "project.name", "未命名项目"),
        "contract_exit_occ_threshold": rate(data, "contract.exit_occ_threshold"),
        "used_default_paths": used_default_paths,
        "admission": admission,
        "base_case": base,
        "negotiation": negotiation,
        "scenarios": scenarios,
        "sensitivity": sensitivity(data, base["jwl"]["npv"]),
        "decision": decision,
        "model_conventions": {
            "currency": "CNY",
            "cashflow_frequency": "annual",
            "operating_detail_frequency": (
                "monthly_first_year" if "monthly" in base else "annual"
            ),
            "calculation_precision": "IEEE-754 binary64; no hidden intermediate rounding",
            "money_regression_tolerance": "CNY 0.01",
            "feishu_money_display": "CNY 0.01万元",
            "tax_scope": "仅计入输入的流转税/附加税率，不含企业所得税",
            "payback_definition": "累计现金流在后续期间不再转负的持续回收期",
            "static_payback_months_definition": (
                "历史投资表口径：一次性初投除以首年平均月经营净现金；"
                "排除后续设备重置和末期残值，原始月数与向上取整月数并列"
            ),
            "discounted_payback_months_definition": (
                "年度持续动态回收期按1年=12个月线性换算；"
                "原始月数与向上取整月数并列"
            ),
            "owner_views": "增量成本口径与完全成本口径并列",
            "contract_exit_check": "六个月滚动窗口、按可售/已售房夜加权；月度数据不足时为not_checked",
            "break_even_occ_definition": (
                "ADR/OCC模式按完整现金方程求解；RevPAR模式因OCC不驱动收入而为not_applicable"
            ),
            "confidence_policy": "有效置信度取声明数据、证据和预测验证三者最低值",
        },
    }
    result["feishu_summary"] = feishu_summary(result)
    return result


if __name__ == "__main__":
    print("calculate.py is an internal module; use run.py", file=sys.stderr)
    raise SystemExit(2)
