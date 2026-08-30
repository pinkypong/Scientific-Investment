"""XBRL / DART 계정 태그 → normalized metric 매핑 (설계서 Phase B §6).

기업마다 다른 태그를 쓰므로 metric 당 후보 태그 리스트(우선순위)를 둔다.
원본 태그는 NormalizedRecord.source_metric 에 보존한다 (삭제 금지).
"""
from __future__ import annotations

# ── SEC us-gaap ────────────────────────────────────────────────────────
SEC_TAGS: dict[str, list[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "eps_basic": ["EarningsPerShareBasic"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "debt": [
        "LongTermDebt",
        "LongTermDebtAndCapitalLeaseObligations",
        "DebtLongtermAndShorttermCombinedAmount",
        "LongTermDebtNoncurrent",
    ],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "inventory": ["InventoryNet"],
    "shares_outstanding": [
        "CommonStockSharesOutstanding",
        "EntityCommonStockSharesOutstanding",
    ],
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
}

# metric → (unit 종류, 흐름/잔액). 흐름(flow)=기간, 잔액(stock)=시점.
METRIC_KIND = {
    "revenue": ("USD", "flow"), "operating_income": ("USD", "flow"),
    "net_income": ("USD", "flow"), "operating_cash_flow": ("USD", "flow"),
    "capex": ("USD", "flow"),
    "eps_basic": ("USD/shares", "flow"), "eps_diluted": ("USD/shares", "flow"),
    "cash": ("USD", "stock"), "debt": ("USD", "stock"),
    "total_assets": ("USD", "stock"), "total_liabilities": ("USD", "stock"),
    "equity": ("USD", "stock"), "inventory": ("USD", "stock"),
    "shares_outstanding": ("shares", "stock"),
}


# ── OpenDART 표준계정ID (account_id) / 계정명(account_nm) ──────────────
# fnlttSinglAcntAll 응답의 account_id (IFRS 표준계정) 우선, 없으면 account_nm 매칭.
DART_ACCOUNT_ID: dict[str, list[str]] = {
    "revenue": ["ifrs-full_Revenue", "ifrs_Revenue", "dart_OperatingRevenue"],
    "operating_income": ["dart_OperatingIncomeLoss", "ifrs-full_ProfitLossFromOperatingActivities"],
    "net_income": ["ifrs-full_ProfitLoss", "ifrs-full_ProfitLossAttributableToOwnersOfParent"],
    "eps_actual": ["ifrs-full_BasicEarningsLossPerShare"],
    "cash": ["ifrs-full_CashAndCashEquivalents"],
    "debt": ["ifrs-full_Borrowings", "dart_ShortTermBorrowings", "ifrs-full_LongtermBorrowings"],
    "total_assets": ["ifrs-full_Assets"],
    "total_liabilities": ["ifrs-full_Liabilities"],
    "equity": ["ifrs-full_Equity", "ifrs-full_EquityAttributableToOwnersOfParent"],
    "inventory": ["ifrs-full_Inventories"],
    "operating_cash_flow": ["ifrs-full_CashFlowsFromUsedInOperatingActivities"],
    "capex": ["dart_PurchaseOfPropertyPlantAndEquipment"],
}

DART_ACCOUNT_NM: dict[str, list[str]] = {
    "revenue": ["매출액", "수익(매출액)", "영업수익"],
    "operating_income": ["영업이익", "영업이익(손실)"],
    "net_income": ["당기순이익", "당기순이익(손실)", "연결당기순이익"],
    "eps_actual": ["기본주당이익", "기본주당순이익"],
    "cash": ["현금및현금성자산"],
    "debt": ["차입금", "단기차입금", "장기차입금", "사채"],
    "total_assets": ["자산총계"],
    "total_liabilities": ["부채총계"],
    "equity": ["자본총계", "지배기업 소유주지분"],
    "inventory": ["재고자산"],
    "operating_cash_flow": ["영업활동현금흐름", "영업활동으로인한현금흐름"],
    "capex": ["유형자산의취득"],
}


def sec_metric_for_tag(tag: str) -> str | None:
    for metric, tags in SEC_TAGS.items():
        if tag in tags:
            return metric
    return None


def sec_tags_for_metric(metric: str) -> list[str]:
    return SEC_TAGS.get(metric, [])


def dart_metric_for(account_id: str | None, account_nm: str | None) -> str | None:
    if account_id:
        for m, ids in DART_ACCOUNT_ID.items():
            if account_id in ids:
                return m
    if account_nm:
        nm = account_nm.replace(" ", "")
        for m, nms in DART_ACCOUNT_NM.items():
            if any(x.replace(" ", "") == nm for x in nms):
                return m
    return None
