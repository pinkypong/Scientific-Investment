"""Derived metrics — **actual data 로부터만** 계산 (설계서 Phase B §14).

Forward/consensus/target/assumption 입력 금지. 입력이 없으면 계산하지 않는다(Missing 유지).
각 결과에 is_derived · formula · input_record_ids · calculated_at 보존 (§9).

실행:  python -m data_sources.common.derive
"""
from __future__ import annotations

import re

from .classification import NumberType, SourceClass
from .schema import NormalizedRecord, now_iso
from . import store

ACTUAL_PROVIDERS = ("sec_edgar", "opendart")


def _prev_period(period: str) -> str | None:
    m = re.fullmatch(r"FY(\d{4})", period)
    if m:
        return f"FY{int(m.group(1)) - 1}"
    m = re.fullmatch(r"(\d{4})Q([1-4])", period)
    if m:
        return f"{int(m.group(1)) - 1}Q{m.group(2)}"
    return None


def _prev_q(period: str) -> str | None:
    m = re.fullmatch(r"(\d{4})Q([1-4])", period)
    if not m:
        return None
    y, q = int(m.group(1)), int(m.group(2))
    return f"{y - 1}Q4" if q == 1 else f"{y}Q{q - 1}"


def _load_actual():
    """(slug, metric) → {period: record}  (latest revision, FACT 만)."""
    recs = []
    for p in ACTUAL_PROVIDERS:
        recs += store.load_normalized(p)
    series: dict[tuple, dict[str, NormalizedRecord]] = {}
    for r in recs:
        if r.number_type != NumberType.FACT or not r.period or r.value is None:
            continue
        if r.revision_status not in (None, "latest"):
            continue
        d = series.setdefault((r.slug, r.metric), {})
        cur = d.get(r.period)
        if cur is None or (r.filing_date or "") >= (cur.filing_date or ""):
            d[r.period] = r
    return series


def _mk(slug, metric, value, formula, inputs, unit=None, period=None, notes=None):
    ref = inputs[0]
    return NormalizedRecord(
        source="derived", provider="analytics_engine",
        source_type=SourceClass.DERIVED, number_type=NumberType.MODEL,
        is_derived=True, formula=formula,
        input_record_ids=[getattr(i, "record_id", str(i)) for i in inputs],
        calculated_at=now_iso(),
        slug=slug, ticker=ref.ticker, company_name=ref.company_name,
        market=ref.market, currency=ref.currency,
        metric=metric, value=value, unit=unit, period=period,
        as_of_date=ref.as_of_date, retrieved_at=now_iso(),
        confidence="High", verification="Model-Derived",
        why=notes or [])


def compute() -> list[NormalizedRecord]:
    S = _load_actual()
    out: list[NormalizedRecord] = []

    def series(slug, metric):
        return S.get((slug, metric), {})

    slugs = {k[0] for k in S}
    for slug in sorted(s for s in slugs if s):
        rev = series(slug, "revenue")
        opi = series(slug, "operating_income")
        ni = series(slug, "net_income")
        eps = series(slug, "eps_diluted") or series(slug, "eps_basic") or series(slug, "eps_actual")
        ocf = series(slug, "operating_cash_flow")
        capex = series(slug, "capex")
        debt = series(slug, "debt")
        eq = series(slug, "equity")

        # ── Growth (YoY) ─────────────────────────────────────────────
        for metric, s in (("revenue", rev), ("operating_income", opi), ("net_income", ni), ("eps", eps)):
            for per, rec in s.items():
                pp = _prev_period(per)
                base = s.get(pp)
                if base and base.value not in (None, 0):
                    notes = [f"{rec.value:,} / {base.value:,}"]
                    if base.value < 0 or rec.value < 0:
                        notes.append("⚠ 기준/당기 값이 음수 → YoY 비율 해석 주의(부호 전환)")
                    out.append(_mk(slug, f"{metric}_yoy", round(rec.value / base.value - 1, 4),
                                   f"{metric}[{per}] / {metric}[{pp}] - 1", [rec, base],
                                   unit="ratio", period=per, notes=notes))
            # QoQ (분기만)
            for per, rec in s.items():
                pq = _prev_q(per)
                base = s.get(pq)
                if base and base.value not in (None, 0):
                    out.append(_mk(slug, f"{metric}_qoq", round(rec.value / base.value - 1, 4),
                                   f"{metric}[{per}] / {metric}[{pq}] - 1", [rec, base],
                                   unit="ratio", period=per))

        # ── Margins ─────────────────────────────────────────────────
        for per, rrec in rev.items():
            if rrec.value in (None, 0):
                continue
            if per in opi and opi[per].value is not None:
                out.append(_mk(slug, "operating_margin", round(opi[per].value / rrec.value, 4),
                               f"operating_income[{per}] / revenue[{per}]", [opi[per], rrec],
                               unit="ratio", period=per))
            if per in ni and ni[per].value is not None:
                out.append(_mk(slug, "net_margin", round(ni[per].value / rrec.value, 4),
                               f"net_income[{per}] / revenue[{per}]", [ni[per], rrec],
                               unit="ratio", period=per))
            if per in ocf and per in capex and ocf[per].value is not None and capex[per].value is not None:
                fcf = ocf[per].value - capex[per].value
                out.append(_mk(slug, "fcf_margin", round(fcf / rrec.value, 4),
                               f"(operating_cash_flow[{per}] - capex[{per}]) / revenue[{per}]",
                               [ocf[per], capex[per], rrec], unit="ratio", period=per,
                               notes=[f"FCF={fcf:,}"]))

        # ── Balance sheet ratios ───────────────────────────────────
        for per, drec in debt.items():
            erec = eq.get(per)
            if erec and erec.value not in (None, 0) and drec.value is not None:
                out.append(_mk(slug, "debt_to_equity", round(drec.value / erec.value, 4),
                               f"debt[{per}] / equity[{per}]", [drec, erec],
                               unit="ratio", period=per))
    return out


def main():
    recs = compute()
    n = store.append_derived("actual_metrics", recs)
    by = {}
    for r in recs:
        by.setdefault(r.metric, 0)
        by[r.metric] += 1
    print(f"actual 기반 derived {len(recs)}건 계산, 신규 {n} → data_sources/store/derived/actual_metrics.jsonl")
    for m, c in sorted(by.items()):
        print(f"   {m:22} {c}")
    if not recs:
        print("   (actual 재무 스토어가 비어 있음 — 먼저 sec_edgar / opendart 수집)")


if __name__ == "__main__":
    main()
