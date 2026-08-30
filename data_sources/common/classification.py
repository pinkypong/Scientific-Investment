"""Source Classification (스펙 §3) + Number Types (데이터계보_감사_설계서 §B) + Source Priority (스펙 §23).

값을 강제로 합치지 않는다. source 별 값을 모두 보관하고 preferred 를 지정만 한다.
"""
from __future__ import annotations


class SourceClass:
    PRIMARY_OFFICIAL = "PRIMARY_OFFICIAL"          # 규제공시·XBRL (SEC/OpenDART) — 향후
    SECONDARY_PROFESSIONAL = "SECONDARY_PROFESSIONAL"  # sell-side 리서치, 애널리스트 추정
    MARKET_DATA = "MARKET_DATA"                    # 가격·비율·컨센서스 집계 (bigdata.com)
    NEWS = "NEWS"                                  # 기사·와이어
    DERIVED = "DERIVED"                            # 계산값
    AI_GENERATED = "AI_GENERATED"                  # LLM 분류/요약 — 원본과 분리 저장 (스펙 §6)

    ALL = [PRIMARY_OFFICIAL, SECONDARY_PROFESSIONAL, MARKET_DATA, NEWS, DERIVED, AI_GENERATED]


class NumberType:
    """대시보드 .lbc 배지와 매핑 (index.html badge())."""

    FACT = "FACT"
    CONSENSUS = "CONSENSUS"
    ESTIMATE = "ESTIMATE"
    MODEL = "MODEL"
    ASSUMPTION = "ASSUMPTION"
    SCENARIO = "SCENARIO"
    IMPLIED = "IMPLIED"          # 주가 역산
    UNVERIFIED = "UNVERIFIED"
    INSUFFICIENT = "INSUFF"


# provider → 기본 SourceClass. config/data_sources.json 의 classification_override 로 덮어쓸 수 있음.
PROVIDER_DEFAULT_CLASS = {
    "hankyung_consensus": SourceClass.SECONDARY_PROFESSIONAL,
    "hankyung_global": SourceClass.NEWS,          # 예상실적 "수치" 레코드는 아래 override
    "bigdata": SourceClass.MARKET_DATA,
    "analytics_engine": SourceClass.DERIVED,
    # 향후:
    "sec_edgar": SourceClass.PRIMARY_OFFICIAL,
    "opendart": SourceClass.PRIMARY_OFFICIAL,
    "fred": SourceClass.PRIMARY_OFFICIAL,
}

# (provider, document_type) 단위 예외
CLASS_OVERRIDE = {
    ("hankyung_global", "market"): SourceClass.SECONDARY_PROFESSIONAL,   # 예상실적 컨센서스 수치
    ("hankyung_global", "estimate"): SourceClass.SECONDARY_PROFESSIONAL,
}

# Source Priority (스펙 §23) — 동일 metric 다중 소스일 때 preferred 선정용. 낮을수록 우선.
CLASS_PRIORITY = {
    SourceClass.PRIMARY_OFFICIAL: 1,
    SourceClass.MARKET_DATA: 2,          # 라이선스 시장데이터
    SourceClass.SECONDARY_PROFESSIONAL: 3,
    SourceClass.NEWS: 4,
    SourceClass.DERIVED: 5,
    SourceClass.AI_GENERATED: 6,
}


def classify(provider: str, document_type: str | None = None,
             overrides: dict | None = None) -> str:
    if overrides and provider in overrides:
        return overrides[provider]
    if document_type and (provider, document_type) in CLASS_OVERRIDE:
        return CLASS_OVERRIDE[(provider, document_type)]
    return PROVIDER_DEFAULT_CLASS.get(provider, SourceClass.NEWS)


def priority(source_class: str) -> int:
    return CLASS_PRIORITY.get(source_class, 99)


# ─────────────────────────────────────────────────────────────────────────────
# Metric Layer 분류 (Phase A: actual-data-first)
#   ACTUAL     = 실제 관측/공식 발표 (price·volume·revenue·eps_actual ...)
#   DERIVED    = 대시보드가 actual 로부터 계산 (YoY·margin·trailing PER·drawdown ...)
#   ASSUMPTION = 주관적 가정 (cycle P/E·WACC·terminal g)
#   REPORT     = 증권사 리포트/컨센서스 유래 (target_price·analyst fwd EPS·optimism check·regime prose)
#   META       = 점수/상태 (valuation confidence)
# 이번 Phase 에서 REPORT 는 파이프라인에서 분리(아카이브), ASSUMPTION/DERIVED 는 별도 레이어로.
# ─────────────────────────────────────────────────────────────────────────────
class MetricClass:
    ACTUAL = "ACTUAL"
    DERIVED = "DERIVED"
    ASSUMPTION = "ASSUMPTION"
    REPORT = "REPORT"
    META = "META"


METRIC_CLASS = {
    # ── ACTUAL (관측/공식) ────────────────────────────────────────────
    "price": MetricClass.ACTUAL,
    "volume": MetricClass.ACTUAL,
    "market_cap": MetricClass.ACTUAL,
    "revenue": MetricClass.ACTUAL,
    "operating_income": MetricClass.ACTUAL,
    "net_income": MetricClass.ACTUAL,
    "eps_actual": MetricClass.ACTUAL,
    "eps_basic": MetricClass.ACTUAL,
    "eps_diluted": MetricClass.ACTUAL,
    "shares_outstanding": MetricClass.ACTUAL,
    "cash": MetricClass.ACTUAL,
    "debt": MetricClass.ACTUAL,
    "capex": MetricClass.ACTUAL,
    "inventory": MetricClass.ACTUAL,
    "book_value": MetricClass.ACTUAL,
    "total_assets": MetricClass.ACTUAL,
    "total_liabilities": MetricClass.ACTUAL,
    "equity": MetricClass.ACTUAL,
    "operating_cash_flow": MetricClass.ACTUAL,
    # 향후 산업 actual
    "asp": MetricClass.ACTUAL, "shipment": MetricClass.ACTUAL,
    "capacity": MetricClass.ACTUAL, "industry_inventory": MetricClass.ACTUAL,
    # ── DERIVED (대시보드 계산) ──────────────────────────────────────
    "revenue_yoy": MetricClass.DERIVED, "revenue_qoq": MetricClass.DERIVED,
    "eps_yoy": MetricClass.DERIVED, "eps_qoq": MetricClass.DERIVED,
    "operating_income_yoy": MetricClass.DERIVED, "operating_income_qoq": MetricClass.DERIVED,
    "net_income_yoy": MetricClass.DERIVED, "net_income_qoq": MetricClass.DERIVED,
    "operating_margin": MetricClass.DERIVED, "net_margin": MetricClass.DERIVED,
    "fcf_margin": MetricClass.DERIVED, "debt_to_equity": MetricClass.DERIVED,
    "margin_change": MetricClass.DERIVED,
    "trailing_pe": MetricClass.DERIVED, "pb": MetricClass.DERIVED, "ps": MetricClass.DERIVED,
    "price_return": MetricClass.DERIVED, "momentum": MetricClass.DERIVED,
    "drawdown": MetricClass.DERIVED, "dist_52w_high": MetricClass.DERIVED,
    "volatility": MetricClass.DERIVED, "volume_change": MetricClass.DERIVED,
    "daily_change_pct": MetricClass.DERIVED,
    # 기존 대시보드 파생 (MC/DCF)
    "mc_fair_value_mean": MetricClass.DERIVED, "mc_fair_value_p50": MetricClass.DERIVED,
    "expected_return": MetricClass.DERIVED, "p_up": MetricClass.DERIVED,
    "fwd_pe": MetricClass.DERIVED, "reverse_dcf_fcff": MetricClass.DERIVED,
    "expectations_gap": MetricClass.DERIVED,
    # ── ASSUMPTION ─────────────────────────────────────────────────────
    "cycle_pe_mid": MetricClass.ASSUMPTION, "wacc": MetricClass.ASSUMPTION,
    "terminal_growth": MetricClass.ASSUMPTION,
    # ── REPORT (이번 Phase 파이프라인에서 분리) ─────────────────────
    "target_price": MetricClass.REPORT, "prev_target_price": MetricClass.REPORT,
    "rating": MetricClass.REPORT, "eps": MetricClass.REPORT,   # eps = analyst forward/consensus (eps_actual 아님)
    "eps_forward": MetricClass.REPORT, "eps_fwd": MetricClass.REPORT,
    "pe_fwd": MetricClass.REPORT, "ebitda_fwd": MetricClass.REPORT,
    "optimism_check": MetricClass.REPORT, "target_price_upside": MetricClass.REPORT,
    "regime": MetricClass.REPORT, "regime_hbm": MetricClass.REPORT,
    "regime_dram": MetricClass.REPORT, "regime_china": MetricClass.REPORT,
    "regime_capex": MetricClass.REPORT,
    # ── META ──────────────────────────────────────────────────────────
    "valuation_confidence": MetricClass.META, "data_coverage": MetricClass.META,
}


def metric_class(metric: str | None) -> str:
    if not metric:
        return MetricClass.REPORT  # metric 없는 문서 레코드(리포트 제목 등) = REPORT 취급
    return METRIC_CLASS.get(metric, MetricClass.REPORT)


# NumberType → 대시보드 badge() 클래스 (참고용; 실제 매핑은 index.html badge())
BADGE = {
    NumberType.FACT: "fact",
    NumberType.CONSENSUS: "cons",
    NumberType.ESTIMATE: "cons",
    NumberType.MODEL: "model",
    NumberType.ASSUMPTION: "assum",
    NumberType.SCENARIO: "scen",
    NumberType.IMPLIED: "model",
    NumberType.UNVERIFIED: "ins",
    NumberType.INSUFFICIENT: "ins",
}
