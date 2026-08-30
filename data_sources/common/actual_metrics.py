"""Actual-data-first: 이번 Phase 에서 파이프라인이 다루는 '실제 관측/공식 발표' metric 과
현재 연결 가능한 source 조사 결과.

존재하지 않는 데이터는 임의 생성하지 않는다. source 미연결 metric 은 '슬롯'만 두고 구현 안 함.
"""
from __future__ import annotations

# 이번 Phase 대상 (설계서 §2). unit 은 종목 통화 또는 명시 단위.
ACTUAL_METRICS = [
    # 시장 관측
    "price", "volume", "market_cap",
    # 공식 발표 재무 (실적)
    "revenue", "operating_income", "net_income", "eps_actual",
    "shares_outstanding", "book_value",
    "cash", "debt", "capex", "inventory",
    # 향후 산업 actual
    "asp", "shipment", "capacity", "industry_inventory",
]

# 현재 연결 가능한 source 조사 (2026-08-27 시점)
#   live  = 지금 값을 받을 수 있음
#   maybe = provider 가 제공할 가능성 (tearsheet financial 섹션) — 스냅샷으로 검증 필요
#   none  = 연결된 source 없음 → 구현 안 함
SOURCE_AVAILABILITY = {
    "price":              {"status": "live",  "provider": "bigdata", "path": "price_performance.current_market.current_price"},
    "market_cap":         {"status": "live",  "provider": "bigdata", "path": "company_overview.market_cap"},
    "volume":             {"status": "maybe", "provider": "bigdata", "path": "price_performance.volume (미검증)"},
    "revenue":            {"status": "maybe", "provider": "bigdata", "path": "financials.income_statement (미검증)"},
    "operating_income":   {"status": "maybe", "provider": "bigdata", "path": "financials.income_statement (미검증)"},
    "net_income":         {"status": "maybe", "provider": "bigdata", "path": "financials.income_statement (미검증)"},
    "eps_actual":         {"status": "maybe", "provider": "bigdata", "path": "financials.per_share (미검증)"},
    "shares_outstanding": {"status": "maybe", "provider": "bigdata", "path": "company_overview.shares (미검증)"},
    "book_value":         {"status": "maybe", "provider": "bigdata", "path": "financials.balance_sheet (미검증)"},
    "cash":              {"status": "maybe", "provider": "bigdata", "path": "financials.balance_sheet (미검증)"},
    "debt":             {"status": "maybe", "provider": "bigdata", "path": "financials.balance_sheet (미검증)"},
    "capex":            {"status": "maybe", "provider": "bigdata", "path": "financials.cash_flow (미검증)"},
    "inventory":        {"status": "maybe", "provider": "bigdata", "path": "financials.balance_sheet (미검증)"},
    "asp":              {"status": "none",  "provider": None, "path": "산업 데이터 source 미연결 (TrendForce 등)"},
    "shipment":         {"status": "none",  "provider": None, "path": "산업 데이터 source 미연결"},
    "capacity":         {"status": "none",  "provider": None, "path": "산업 데이터 source 미연결"},
    "industry_inventory": {"status": "none", "provider": None, "path": "산업 데이터 source 미연결"},
}


def is_actual(metric: str) -> bool:
    return metric in ACTUAL_METRICS


def availability(metric: str) -> dict:
    return SOURCE_AVAILABILITY.get(metric, {"status": "none", "provider": None, "path": "미조사"})


def implemented_now() -> list[str]:
    return [m for m, a in SOURCE_AVAILABILITY.items() if a["status"] == "live"]
