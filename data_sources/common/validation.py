"""Validation (스펙 §16). 이상치라고 자동 삭제하지 않는다 — 상태로 표시만 한다.

validation_status ∈ {VALID, WARNING, ERROR} + 사유 리스트.
검증시스템_설명.md 의 "오염 데이터 차단(DATA CONFLICT)" 개념을 이 레이어로 흡수.
"""
from __future__ import annotations

import math
from typing import Iterable

from .schema import NormalizedRecord

VALID = "VALID"
WARNING = "WARNING"
ERROR = "ERROR"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

# 비율성 metric 은 음수 가능(예: 성장률). 아래는 "음수면 이상" 대상.
_NON_NEGATIVE = {"revenue", "ebitda", "target_price", "price", "pe", "pe_forward", "pb", "ev_ebitda"}
# 전기 대비 |변화율| 이 이 값을 넘으면 WARNING (스펙 §16 "extreme EPS change")
_EXTREME_CHANGE = 3.0  # +300%


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def validate_record(r: NormalizedRecord, *, prev_value=None) -> tuple[str, list[str]]:
    notes: list[str] = []
    status = VALID
    v = _num(r.value)

    # 0) 파생 레코드 완전성 (스펙 §8/§9) — formula/input_ids 없으면 ERROR
    if getattr(r, "is_derived", False):
        if not r.formula or not r.input_record_ids:
            return ERROR, [f"{r.metric}: derived 인데 formula/input_record_ids 누락"]

    # 0b) 공식 official 레코드 provenance 완전성 (스펙 §8) — 원문 링크/식별자 필수
    if r.source_type == "PRIMARY_OFFICIAL":
        if not (r.original_url and (r.accession or r.report_id)):
            status = WARNING
            notes.append("provenance incomplete: original_url + accession 필요")
        if not r.raw_ref:
            status = _max(status, WARNING)
            notes.append("raw_ref 없음: normalized→raw 추적 불가")

    # 0c) 계정 매핑 불확실 (스펙 §6/§10)
    if any("uncertain_account_mapping" in str(n) for n in (r.missing or [])):
        status = _max(status, WARNING)
        notes.append("ambiguous_account_mapping")

    # 1) null / NaN / inf
    if r.value is None:
        # Missing 은 정상 상태(≠ 0). 단 metric 이 있는데 값이 없으면 INSUFFICIENT_DATA.
        if r.metric:
            notes.append(f"{r.metric}: 값 없음 (INSUFFICIENT_DATA — 0 대체 금지)")
            return INSUFFICIENT_DATA, notes
        return status, notes
    if v is not None and (math.isnan(v) or math.isinf(v)):
        return ERROR, [f"{r.metric}: NaN/Inf"]

    # 2) 음수 매출 등
    if v is not None and r.metric in _NON_NEGATIVE and v < 0:
        status = ERROR
        notes.append(f"{r.metric}: 음수({v}) — 불가")

    # 3) 통화 불일치
    if r.currency and r.unit and r.currency not in (r.unit, None) and r.unit in ("KRW", "USD"):
        status = _max(status, WARNING)
        notes.append(f"통화 불일치: currency={r.currency} vs unit={r.unit}")

    # 4) 극단 변화
    pv = _num(prev_value)
    if v is not None and pv not in (None, 0):
        chg = (v - pv) / abs(pv)
        if abs(chg) >= _EXTREME_CHANGE:
            status = _max(status, WARNING)
            notes.append(f"{r.metric}: 전기 대비 {chg:+.0%} — 극단 변화(검토 필요, 삭제 아님)")

    # 5) 기간 형식
    if r.period and not any(t in r.period for t in ("FY", "Q", "-", "TTM")):
        status = _max(status, WARNING)
        notes.append(f"period 형식 비표준: {r.period}")

    return status, notes


def _rank(s: str) -> int:
    return {VALID: 0, INSUFFICIENT_DATA: 1, WARNING: 2, ERROR: 3}.get(s, 0)


def _max(a: str, b: str) -> str:
    return a if _rank(a) >= _rank(b) else b


def validate_batch(records: Iterable[NormalizedRecord],
                   prev_by_key: dict | None = None) -> list[NormalizedRecord]:
    prev_by_key = prev_by_key or {}
    out = []
    for r in records:
        key = (r.slug or r.ticker, r.metric, r.period)
        status, notes = validate_record(r, prev_value=prev_by_key.get(key))
        r.validation_status = status
        r.validation_notes = notes
        out.append(r)
    return out


def summarize(records: Iterable[NormalizedRecord]) -> dict:
    c: dict = {VALID: 0, INSUFFICIENT_DATA: 0, WARNING: 0, ERROR: 0}
    for r in records:
        c[r.validation_status] = c.get(r.validation_status, 0) + 1
    return {k: v for k, v in c.items() if v}
