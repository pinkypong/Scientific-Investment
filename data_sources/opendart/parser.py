"""OpenDART fnlttSinglAcntAll 응답 → 정규화 전 fact 목록.

- account_id(IFRS 표준계정) 우선, 없으면 account_nm 로 매핑.
- thstrm_amount 는 절대값(원 단위) 문자열 → 숫자. 억/조 축약 아님.
- 연결(CFS) 우선. 없으면 별도(OFS) fallback (호출측에서 fs_div 지정, notes 표기).
"""
from __future__ import annotations

from datetime import date

from ..common.normalization import parse_num
from ..common.periods import dart_frame
from ..common.xbrl_map import dart_metric_for


def _period_end(bsns_year: str, reprt_code: str) -> str | None:
    try:
        year = int(bsns_year)
    except (TypeError, ValueError):
        return None
    month_day = {
        "11013": (3, 31),
        "11012": (6, 30),
        "11014": (9, 30),
        "11011": (12, 31),
    }.get(str(reprt_code))
    if not month_day:
        return None
    return date(year, month_day[0], month_day[1]).isoformat()


def _filing_date(rcept_no: str | None) -> str | None:
    if not rcept_no or len(str(rcept_no)) < 8:
        return None
    s = str(rcept_no)[:8]
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8])).isoformat()
    except ValueError:
        return None


def parse_acnt_all(payload: dict, *, bsns_year: str, reprt_code: str,
                   fs_div: str) -> list[dict]:
    if payload.get("status") != "000":
        return []
    fr = dart_frame(bsns_year, reprt_code)
    out = []
    for row in payload.get("list", []):
        metric = dart_metric_for(row.get("account_id"), row.get("account_nm"))
        if not metric:
            continue
        # IS/CIS 는 손익(누적 여부는 reprt_code 로), BS 는 잔액
        amount = row.get("thstrm_amount")
        val = parse_num(amount)
        out.append({
            "metric": metric,
            "source_metric": row.get("account_id") or row.get("account_nm"),
            "account_nm": row.get("account_nm"),
            "sj_div": row.get("sj_div"),
            "value": val, "raw_value": amount,
            "currency": row.get("currency") or "KRW",
            "unit": "KRW",
            "period": fr["period"], "original_period": fr["original_period"],
            "period_end": _period_end(bsns_year, reprt_code),
            "fiscal_year": fr["fiscal_year"], "fiscal_period": fr["fiscal_period"],
            "form": fr["form"],
            "fs_div": fs_div,
            "cumulative": fr.get("cumulative", False),
            "rcept_no": row.get("rcept_no"),
            "filing_date": _filing_date(row.get("rcept_no")),
        })
    # 같은 metric 중복(별도항목/집계) → 첫 표준계정 우선, 나머지는 alt 로 버리지 않되 여기선 dedup
    seen, dedup = set(), []
    for r in sorted(out, key=lambda x: (x["metric"], 0 if str(x["source_metric"]).startswith("ifrs") else 1)):
        if r["metric"] in seen:
            continue
        seen.add(r["metric"])
        dedup.append(r)
    return dedup
