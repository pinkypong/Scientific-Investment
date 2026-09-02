"""Point-in-time normalization of SEC companyfacts into quarters and TTM snapshots."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Any


FLOW_TAGS = {
    "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capital_expenditure": ("PaymentsToAcquirePropertyPlantAndEquipment",),
}
INSTANT_TAGS = {
    "cash": ("CashAndCashEquivalentsAtCarryingValue",),
    "assets": ("Assets",),
    "debt": ("LongTermDebtAndFinanceLeaseObligations", "LongTermDebt", "LongTermDebtAndCapitalLeaseObligations"),
    "diluted_shares": ("EntityCommonStockSharesOutstanding",),
}


@dataclass(frozen=True)
class NormalizedFact:
    metric: str
    value: float
    unit: str
    period_start: str | None
    period_end: str
    filed: str
    form: str
    fiscal_year: int | None
    fiscal_period: str | None
    accession: str | None
    source_tag: str
    derived: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _duration_days(item: NormalizedFact) -> int | None:
    if not item.period_start:
        return None
    return (date.fromisoformat(item.period_end) - date.fromisoformat(item.period_start)).days


def _available_fact_rows(companyfacts: dict[str, Any], metric: str, tags: tuple[str, ...],
                         as_of: str, unit_preferences: tuple[str, ...]) -> list[NormalizedFact]:
    us_gaap = companyfacts.get("facts", {}).get("us-gaap", {})
    for tag in tags:  # first usable synonym wins to prevent double counting
        concept = us_gaap.get(tag, {})
        units = concept.get("units", {})
        unit = next((candidate for candidate in unit_preferences if units.get(candidate)), None)
        if unit is None:
            continue
        rows = []
        for item in units[unit]:
            if item.get("filed", "9999-12-31") > as_of or item.get("form") not in {"10-Q", "10-K", "10-Q/A", "10-K/A"}:
                continue
            try:
                value = float(item["val"])
            except (KeyError, TypeError, ValueError):
                continue
            rows.append(NormalizedFact(
                metric=metric, value=value, unit=unit, period_start=item.get("start"),
                period_end=item["end"], filed=item["filed"], form=item["form"],
                fiscal_year=item.get("fy"), fiscal_period=item.get("fp"), accession=item.get("accn"),
                source_tag=tag))
        if rows:
            # Keep latest filing available for an identical economic period.
            dedup: dict[tuple[str | None, str], NormalizedFact] = {}
            for row in sorted(rows, key=lambda value: (value.filed, value.accession or "")):
                dedup[(row.period_start, row.period_end)] = row
            return list(dedup.values())
    return []


def normalize_companyfacts(companyfacts: dict[str, Any], as_of: str) -> dict[str, Any]:
    """Build point-in-time discrete quarters, TTM flows, and latest instant balances."""
    date.fromisoformat(as_of)
    quarters: dict[str, list[NormalizedFact]] = {}
    ttm: dict[str, float | None] = {}
    sources: dict[str, list[str]] = {}
    for metric, tags in FLOW_TAGS.items():
        rows = _available_fact_rows(companyfacts, metric, tags, as_of, ("USD",))
        discrete = [row for row in rows if (days := _duration_days(row)) is not None and 60 <= days <= 120]
        annual = [row for row in rows if (days := _duration_days(row)) is not None and 300 <= days <= 400]
        # Companyfacts often provides no discrete Q4. Derive it from FY minus Q1-Q3,
        # but only when all facts share the same SEC fiscal year.
        by_fy: dict[int, dict[str, NormalizedFact]] = {}
        for row in discrete:
            if row.fiscal_year and row.fiscal_period in {"Q1", "Q2", "Q3"}:
                existing = by_fy.setdefault(row.fiscal_year, {}).get(row.fiscal_period)
                if existing is None or row.filed > existing.filed:
                    by_fy[row.fiscal_year][row.fiscal_period] = row
        for fy, parts in by_fy.items():
            fy_rows = [row for row in annual if row.fiscal_year == fy and row.fiscal_period == "FY"]
            if len(parts) == 3 and fy_rows:
                full = max(fy_rows, key=lambda row: row.filed)
                value = full.value - sum(parts[key].value for key in ("Q1", "Q2", "Q3"))
                discrete.append(NormalizedFact(metric, value, full.unit, None, full.period_end,
                                                full.filed, full.form, fy, "Q4", full.accession,
                                                full.source_tag, True))
        latest_by_end: dict[str, NormalizedFact] = {}
        for row in sorted(discrete, key=lambda value: (value.period_end, value.filed)):
            latest_by_end[row.period_end] = row
        ordered = sorted(latest_by_end.values(), key=lambda value: value.period_end)[-4:]
        quarters[metric] = ordered
        ttm[metric] = sum(row.value for row in ordered) if len(ordered) == 4 else None
        sources[metric] = sorted({row.source_tag for row in ordered})
    instants: dict[str, dict[str, Any] | None] = {}
    for metric, tags in INSTANT_TAGS.items():
        units = ("shares",) if metric == "diluted_shares" else ("USD",)
        rows = _available_fact_rows(companyfacts, metric, tags, as_of, units)
        available = [row for row in rows if row.period_start is None and row.period_end <= as_of]
        latest = max(available, key=lambda row: (row.period_end, row.filed)) if available else None
        instants[metric] = latest.as_dict() if latest else None
    ocf, capex = ttm.get("operating_cash_flow"), ttm.get("capital_expenditure")
    ttm["free_cash_flow"] = ocf - capex if ocf is not None and capex is not None else None
    return {
        "entity": companyfacts.get("entityName"), "cik": str(companyfacts.get("cik", "")).zfill(10),
        "as_of": as_of, "generated_at": datetime.now(timezone.utc).isoformat(),
        "ttm": ttm, "latest": instants,
        "quarters": {metric: [row.as_dict() for row in rows] for metric, rows in quarters.items()},
        "source_tags": sources,
        "methodology": "filed<=as_of; discrete 60-120d quarters; Q4=FY-Q1-Q2-Q3 when necessary",
    }
