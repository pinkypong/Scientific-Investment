"""Deterministic valuation, quality, risk, and ranking engine.

Raw facts and human assumptions are intentionally accepted in separate branches.
The engine never writes calculated values back into either branch.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from math import isfinite
from typing import Any, Iterable


DEFAULT_CONFIG: dict[str, Any] = {
    "gates": {
        "minimum_objective_score": 65,
        "minimum_margin_of_safety": 0.15,
        "minimum_completeness": 0.70,
        "minimum_provenance_coverage": 0.80,
        "maximum_critical_flags": 0,
    },
    "quality_thresholds": {
        "ocf_to_net_income_warning": 0.60,
        "accrual_ratio_warning": 0.05,
        "accrual_ratio_critical": 0.10,
        "debt_to_ebitda_warning": 4.0,
        "interest_coverage_warning": 3.0,
        "share_dilution_warning": 0.05,
        "roic_wacc_spread_warning": 0.0,
    },
}

REQUIRED_FACTS = (
    "market.price", "market.cash", "market.debt", "market.diluted_shares",
    "financials.revenue_ttm", "financials.ebit_margin_ttm",
    "financials.ocf_ttm", "financials.net_income_ttm",
    "ratios.roic", "ratios.wacc", "ratios.debt_to_ebitda",
    "ratios.interest_coverage", "ratios.accrual_ratio",
    "ratios.share_dilution_yoy", "ratios.ocf_to_net_income",
    "consensus.revenue_growth_3y", "consensus.eps_growth_3y",
    "consensus.revision_90d", "risk.beta", "risk.max_drawdown_1y",
    "portfolio.correlation", "portfolio.concentration_reduction",
)


@dataclass(frozen=True)
class Flag:
    severity: str
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code, "message": self.message}


def _merge(base: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _get(data: dict[str, Any], path: str, default: Any = None) -> Any:
    value: Any = data
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def _leaf_paths(data: dict[str, Any], prefix: str = "objective") -> list[str]:
    paths: list[str] = []
    for key, value in data.items():
        path = f"{prefix}.{key}"
        if isinstance(value, dict):
            paths.extend(_leaf_paths(value, path))
        else:
            paths.append(path)
    return paths


def _provenance_coverage(objective: dict[str, Any], sources: list[dict[str, Any]]) -> float:
    paths = _leaf_paths(objective)
    if not paths:
        return 0.0
    patterns: list[str] = []
    for source in sources:
        patterns.extend(str(field) for field in source.get("fields", []))
    def covered(path: str) -> bool:
        short = path.removeprefix("objective.")
        for pattern in patterns:
            normalized = pattern if pattern.startswith("objective.") else f"objective.{pattern}"
            if normalized == "objective.*" or normalized == path:
                return True
            if normalized.endswith(".*") and path.startswith(normalized[:-1]):
                return True
            if pattern == short:
                return True
        return False
    return sum(covered(path) for path in paths) / len(paths)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _linear(value: float | None, bad: float, good: float) -> float:
    if value is None:
        return 0.0
    if bad == good:
        return 1.0 if value >= good else 0.0
    return _clamp((value - bad) / (good - bad))


def _fcff_value(objective: dict[str, Any], scenario: dict[str, Any]) -> dict[str, float]:
    market = objective.get("market", {})
    financials = objective.get("financials", {})
    revenue = float(financials["revenue_ttm"])
    margin = float(financials["ebit_margin_ttm"])
    cash = float(market["cash"])
    debt = float(market["debt"])
    shares = float(market["diluted_shares"])
    years = int(scenario.get("forecast_years", 5))
    start_growth = float(scenario["revenue_growth_start"])
    end_growth = float(scenario["revenue_growth_end"])
    target_margin = float(scenario["target_ebit_margin"])
    tax_rate = float(scenario["tax_rate"])
    sales_to_capital = float(scenario["sales_to_capital"])
    wacc = float(scenario["wacc"])
    terminal_growth = float(scenario["terminal_growth"])
    terminal_roic = float(scenario["terminal_roic"])
    if years < 1 or shares <= 0 or sales_to_capital <= 0 or terminal_roic <= 0:
        raise ValueError("years, shares, sales_to_capital, and terminal_roic must be positive")
    if wacc <= terminal_growth:
        raise ValueError("WACC must be greater than terminal growth")

    pv_explicit = 0.0
    prior_revenue = revenue
    last_nopat = 0.0
    for year in range(1, years + 1):
        growth_progress = (year - 1) / (years - 1) if years > 1 else 1.0
        margin_progress = year / years
        growth = start_growth + (end_growth - start_growth) * growth_progress
        year_margin = margin + (target_margin - margin) * margin_progress
        revenue *= 1.0 + growth
        reinvestment = (revenue - prior_revenue) / sales_to_capital
        nopat = revenue * year_margin * (1.0 - tax_rate)
        fcff = nopat - reinvestment
        pv_explicit += fcff / ((1.0 + wacc) ** year)
        prior_revenue = revenue
        last_nopat = nopat

    terminal_nopat = last_nopat * (1.0 + terminal_growth)
    terminal_reinvestment = terminal_nopat * terminal_growth / terminal_roic
    terminal_fcff = terminal_nopat - terminal_reinvestment
    terminal_value = terminal_fcff / (wacc - terminal_growth)
    pv_terminal = terminal_value / ((1.0 + wacc) ** years)
    enterprise_value = pv_explicit + pv_terminal
    equity_value = enterprise_value - debt + cash
    return {
        "enterprise_value": enterprise_value,
        "equity_value": equity_value,
        "fair_value_per_share": equity_value / shares,
        "terminal_value_share": pv_terminal / enterprise_value if enterprise_value else 0.0,
    }


def _wacc_build(objective: dict[str, Any]) -> dict[str, float] | None:
    """Build a market-value WACC from observable capital-market inputs when supplied."""
    capital = objective.get("capital", {})
    required = ("risk_free_rate", "beta", "equity_risk_premium", "pre_tax_cost_debt",
                "tax_rate", "debt_value", "equity_value")
    if any(_number(capital.get(key)) is None for key in required):
        return None
    risk_free = float(capital["risk_free_rate"])
    beta = float(capital["beta"])
    erp = float(capital["equity_risk_premium"])
    country_risk = float(capital.get("country_risk_premium", 0.0))
    pre_tax_debt = float(capital["pre_tax_cost_debt"])
    tax_rate = float(capital["tax_rate"])
    debt_value = float(capital["debt_value"])
    equity_value = float(capital["equity_value"])
    total = debt_value + equity_value
    if total <= 0:
        return None
    cost_of_equity = risk_free + beta * erp + country_risk
    after_tax_cost_debt = pre_tax_debt * (1.0 - tax_rate)
    debt_weight = debt_value / total
    equity_weight = equity_value / total
    return {
        "cost_of_equity": cost_of_equity,
        "after_tax_cost_of_debt": after_tax_cost_debt,
        "debt_weight": debt_weight,
        "equity_weight": equity_weight,
        "wacc": equity_weight * cost_of_equity + debt_weight * after_tax_cost_debt,
    }


def _relative_value(objective: dict[str, Any], scenario: dict[str, Any], method: str) -> dict[str, float]:
    market = objective.get("market", {})
    consensus = objective.get("consensus", {})
    financials = objective.get("financials", {})
    shares = float(market["diluted_shares"])
    cash = float(market.get("cash", 0.0))
    debt = float(market.get("debt", 0.0))
    if method == "pe":
        eps = float(scenario.get("forward_eps", consensus["forward_eps"]))
        fair = eps * float(scenario["target_multiple"])
        return {"equity_value": fair * shares, "fair_value_per_share": fair}
    if method == "ev_ebitda":
        ebitda = float(scenario.get("forward_ebitda", financials["ebitda_ttm"]))
        enterprise_value = ebitda * float(scenario["target_multiple"])
        equity_value = enterprise_value - debt + cash
        return {"enterprise_value": enterprise_value, "equity_value": equity_value,
                "fair_value_per_share": equity_value / shares}
    if method == "p_tbv":
        tangible_book = float(scenario.get("tangible_book_value", financials["tangible_book_value"]))
        equity_value = tangible_book * float(scenario["target_multiple"])
        return {"equity_value": equity_value, "fair_value_per_share": equity_value / shares}
    if method == "etf_lookthrough_pe":
        price = float(market["price"])
        current_multiple = float(scenario.get("current_multiple", objective["etf"]["lookthrough_forward_pe"]))
        target_multiple = float(scenario["target_multiple"])
        earnings_growth = float(scenario.get("earnings_growth_horizon", 0.0))
        if current_multiple <= 0:
            raise ValueError("ETF look-through current multiple must be positive")
        fair = price * (target_multiple / current_multiple) * (1.0 + earnings_growth)
        return {"equity_value": fair * shares, "fair_value_per_share": fair}
    raise ValueError(f"unsupported valuation method: {method}")


def _scenario_values(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[Flag]]:
    objective = payload["objective"]
    assumptions = payload["assumptions"]
    method = assumptions.get("valuation_method", "fcff")
    scenarios = assumptions.get("scenarios", {})
    flags: list[Flag] = []
    if not scenarios:
        return [], [Flag("critical", "NO_SCENARIOS", "No valuation scenarios were supplied.")]
    rows: list[dict[str, Any]] = []
    probability_sum = sum(float(s.get("probability", 0.0)) for s in scenarios.values())
    if abs(probability_sum - 1.0) > 1e-6:
        flags.append(Flag("critical", "BAD_PROBABILITIES", "Scenario probabilities must sum to 1.0."))
    price = _number(_get(objective, "market.price"))
    for name, scenario in scenarios.items():
        try:
            value = _fcff_value(objective, scenario) if method == "fcff" else _relative_value(objective, scenario, method)
            fair = value["fair_value_per_share"]
            probability = float(scenario.get("probability", 0.0))
            rows.append({"name": name, "probability": probability, **value,
                         "upside": fair / price - 1.0 if price and price > 0 else None})
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
            flags.append(Flag("critical", "VALUATION_INPUT", f"{name}: {exc}"))
    return rows, flags


def _reverse_dcf(objective: dict[str, Any], base: dict[str, Any]) -> float | None:
    price = _number(_get(objective, "market.price"))
    if not price:
        return None
    def gap(growth: float) -> float:
        trial = deepcopy(base)
        trial["revenue_growth_start"] = growth
        return _fcff_value(objective, trial)["fair_value_per_share"] - price
    low, high = -0.30, 1.00
    try:
        low_gap, high_gap = gap(low), gap(high)
        if low_gap * high_gap > 0:
            return None
        for _ in range(80):
            mid = (low + high) / 2.0
            mid_gap = gap(mid)
            if abs(mid_gap) < 1e-7:
                return mid
            if low_gap * mid_gap <= 0:
                high = mid
            else:
                low, low_gap = mid, mid_gap
        return (low + high) / 2.0
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def _quality_flags(objective: dict[str, Any], config: dict[str, Any]) -> list[Flag]:
    t = config["quality_thresholds"]
    flags: list[Flag] = []
    basics = (
        ("market.price", "BAD_PRICE", "Current price is missing or non-positive."),
        ("financials.revenue_ttm", "BAD_REVENUE", "TTM revenue is missing or non-positive."),
        ("market.diluted_shares", "BAD_SHARES", "Diluted shares are missing or non-positive."),
    )
    for path, code, message in basics:
        value = _number(_get(objective, path))
        if value is None or value <= 0:
            flags.append(Flag("critical", code, message))
    margin = _number(_get(objective, "financials.ebit_margin_ttm"))
    if margin is not None and not -1.0 <= margin <= 1.0:
        flags.append(Flag("critical", "BAD_MARGIN", "EBIT margin is outside the valid decimal range."))
    tests = (
        ("ratios.ocf_to_net_income", t["ocf_to_net_income_warning"], "warning", "LOW_CASH_CONVERSION", "OCF/net income is below 0.60.", lambda x, y: x < y),
        ("ratios.accrual_ratio", t["accrual_ratio_critical"], "critical", "HIGH_ACCRUALS", "Accrual ratio exceeds 0.10.", lambda x, y: x > y),
        ("ratios.debt_to_ebitda", t["debt_to_ebitda_warning"], "warning", "HIGH_LEVERAGE", "Debt/EBITDA exceeds 4x.", lambda x, y: x > y),
        ("ratios.interest_coverage", t["interest_coverage_warning"], "warning", "LOW_COVERAGE", "Interest coverage is below 3x.", lambda x, y: x < y),
        ("ratios.share_dilution_yoy", t["share_dilution_warning"], "warning", "DILUTION", "YoY diluted share growth exceeds 5%.", lambda x, y: x > y),
    )
    for path, threshold, severity, code, message, predicate in tests:
        value = _number(_get(objective, path))
        if value is not None and predicate(value, threshold):
            flags.append(Flag(severity, code, message))
    accrual = _number(_get(objective, "ratios.accrual_ratio"))
    if accrual is not None and t["accrual_ratio_warning"] < accrual <= t["accrual_ratio_critical"]:
        flags.append(Flag("warning", "ELEVATED_ACCRUALS", "Accrual ratio is between 0.05 and 0.10."))
    roic = _number(_get(objective, "ratios.roic"))
    wacc = _number(_get(objective, "ratios.wacc"))
    if roic is not None and wacc is not None and roic - wacc < t["roic_wacc_spread_warning"]:
        flags.append(Flag("warning", "VALUE_DESTRUCTION", "ROIC is below WACC."))
    return flags


def _objective_score(objective: dict[str, Any], critical_count: int) -> dict[str, float]:
    roic = _number(_get(objective, "ratios.roic")); wacc = _number(_get(objective, "ratios.wacc"))
    spread = roic - wacc if roic is not None and wacc is not None else None
    quality = 30 * (
        0.40 * _linear(spread, -0.03, 0.12)
        + 0.30 * _linear(_number(_get(objective, "ratios.ocf_to_net_income")), 0.50, 1.20)
        + 0.20 * _linear(_number(_get(objective, "ratios.accrual_ratio")), 0.12, -0.03)
        + 0.10 * _linear(_number(_get(objective, "ratios.share_dilution_yoy")), 0.08, -0.02)
    )
    growth = 20 * (
        0.40 * _linear(_number(_get(objective, "consensus.revenue_growth_3y")), -0.03, 0.18)
        + 0.40 * _linear(_number(_get(objective, "consensus.eps_growth_3y")), -0.05, 0.22)
        + 0.20 * _linear(_number(_get(objective, "consensus.revision_90d")), -0.10, 0.10)
    )
    balance = 20 * (
        0.55 * _linear(_number(_get(objective, "ratios.debt_to_ebitda")), 5.0, 0.0)
        + 0.45 * _linear(_number(_get(objective, "ratios.interest_coverage")), 1.5, 15.0)
    )
    drawdown = _number(_get(objective, "risk.max_drawdown_1y"))
    market_risk = 20 * (
        0.25 * _linear(_number(_get(objective, "risk.beta")), 2.0, 0.7)
        + 0.25 * _linear(abs(drawdown) if drawdown is not None else None, 0.60, 0.10)
        + 0.25 * _linear(_number(_get(objective, "portfolio.correlation")), 0.95, 0.20)
        + 0.25 * _linear(_number(_get(objective, "portfolio.concentration_reduction")), -0.05, 0.15)
    )
    auxiliary = 10 * (
        0.40 * _linear(_number(_get(objective, "signals.institutional_change_pct")), -0.10, 0.10)
        + 0.25 * _linear(_number(_get(objective, "signals.workforce_yoy_pct")), -0.15, 0.20)
        + 0.35 * _linear(_number(_get(objective, "signals.ravenpack_sentiment")), -1.0, 1.0)
    )
    if critical_count:
        auxiliary = 0.0
    parts = {"quality": round(quality, 2), "growth_and_revisions": round(growth, 2),
             "balance_sheet": round(balance, 2), "market_risk_and_diversification": round(market_risk, 2),
             "auxiliary_signals": round(auxiliary, 2)}
    parts["total"] = round(sum(parts.values()), 2)
    return parts


def analyze_security(payload: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Analyze one normalized security payload without mutating it."""
    cfg = _merge(DEFAULT_CONFIG, config)
    objective = payload.get("objective", {})
    assumptions = payload.get("assumptions", {})
    flags = _quality_flags(objective, cfg)
    scenarios, valuation_flags = _scenario_values(payload)
    flags.extend(valuation_flags)
    for row in scenarios:
        if row.get("terminal_value_share", 0.0) > 0.75:
            flags.append(Flag("warning", "TERMINAL_DEPENDENCE",
                              f"{row['name']}: terminal value exceeds 75% of enterprise value."))
    price = _number(_get(objective, "market.price"))
    weighted_fair = sum(row["fair_value_per_share"] * row["probability"] for row in scenarios) if scenarios else None
    base_row = next((row for row in scenarios if row["name"].lower() == "base"), None)
    anchor_fair = base_row["fair_value_per_share"] if base_row else weighted_fair
    upside = weighted_fair / price - 1.0 if weighted_fair is not None and price and price > 0 else None
    margin_of_safety = (anchor_fair - price) / anchor_fair if anchor_fair and price is not None and anchor_fair > 0 else None
    wacc_build = _wacc_build(objective)
    reverse_growth = None
    if assumptions.get("valuation_method", "fcff") == "fcff" and "base" in assumptions.get("scenarios", {}):
        reverse_growth = _reverse_dcf(objective, assumptions["scenarios"]["base"])
        base_wacc = _number(assumptions["scenarios"]["base"].get("wacc"))
        if wacc_build and base_wacc is not None and abs(base_wacc - wacc_build["wacc"]) > 0.02:
            flags.append(Flag("warning", "WACC_ASSUMPTION_GAP",
                              "Base-case WACC differs from the market-input WACC build by more than 200 bps."))
    relative_cross_check = None
    cross = assumptions.get("relative_cross_check")
    if cross:
        try:
            relative_cross_check = _relative_value(objective, cross, cross["method"])
            relative_cross_check["method"] = cross["method"]
            relative_cross_check["upside"] = (
                relative_cross_check["fair_value_per_share"] / price - 1.0 if price and price > 0 else None
            )
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
            flags.append(Flag("warning", "RELATIVE_CROSS_CHECK", str(exc)))
    present = sum(_get(objective, path) is not None for path in REQUIRED_FACTS)
    completeness = present / len(REQUIRED_FACTS)
    provenance_coverage = _provenance_coverage(objective, payload.get("sources", []))
    critical_count = sum(flag.severity == "critical" for flag in flags)
    warning_count = sum(flag.severity == "warning" for flag in flags)
    score = _objective_score(objective, critical_count)
    opportunity_score = (
        0.45 * score["total"]
        + 0.25 * (100.0 * _clamp((upside or 0.0) / 0.50))
        + 0.15 * (100.0 * _clamp((margin_of_safety or 0.0) / 0.30))
        + 0.075 * (100.0 * completeness)
        + 0.075 * (100.0 * provenance_coverage)
        - 3.0 * warning_count
        - 25.0 * critical_count
    )
    opportunity_score = round(_clamp(opportunity_score, 0.0, 100.0), 2)
    gates = cfg["gates"]
    passed = (score["total"] >= gates["minimum_objective_score"]
              and margin_of_safety is not None and margin_of_safety >= gates["minimum_margin_of_safety"]
              and completeness >= gates["minimum_completeness"]
              and provenance_coverage >= gates["minimum_provenance_coverage"]
              and critical_count <= gates["maximum_critical_flags"])
    return {
        "security": deepcopy(payload.get("security", {})), "as_of": payload.get("as_of"),
        "computed": {"scenario_valuation": scenarios, "probability_weighted_fair_value": weighted_fair,
                     "base_fair_value": anchor_fair, "upside": upside, "margin_of_safety": margin_of_safety,
                     "reverse_dcf_implied_initial_growth": reverse_growth,
                     "relative_cross_check": relative_cross_check, "wacc_build": wacc_build,
                     "objective_score": score, "risk_adjusted_opportunity_score": opportunity_score,
                     "data_completeness": completeness, "provenance_coverage": provenance_coverage,
                     "decision": "PASS_DEEP_DIVE" if passed else "WATCH_OR_REJECT"},
        "objective": deepcopy(objective), "assumptions": deepcopy(assumptions),
        "flags": [flag.as_dict() for flag in flags], "sources": deepcopy(payload.get("sources", [])),
    }


def rank_results(results: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank with gates first, then expected upside, MOS, objective score, completeness."""
    def key(result: dict[str, Any]) -> tuple[float, ...]:
        c = result["computed"]
        return (1.0 if c["decision"] == "PASS_DEEP_DIVE" else 0.0,
                c["risk_adjusted_opportunity_score"], c["objective_score"]["total"],
                c.get("margin_of_safety") if c.get("margin_of_safety") is not None else -999.0,
                c["data_completeness"])
    return sorted(results, key=key, reverse=True)
