"""SEC companyconcept 응답 → 정규화 전 fact 목록.

- flow metric: 분기(duration ~90d) / 연간(~365d) 만 채택, 누적(YTD-Q) 제외.
- stock metric: instant fact 그대로.
- restatement: 같은 (fy, fp) 를 여러 filing 이 보고 → 전부 유지, 최신 filed = 'latest', 이전 = 'superseded'.
"""
from __future__ import annotations

from ..common.periods import sec_frame
from ..common.xbrl_map import METRIC_KIND
from .schema import ANNUAL_DAYS, QUARTER_DAYS


def _in(d, lo_hi):
    return d is not None and lo_hi[0] <= d <= lo_hi[1]


def facts_for_metric(concept_json: dict, metric: str, tag: str) -> list[dict]:
    kind = METRIC_KIND.get(metric, ("USD", "flow"))[1]
    units = concept_json.get("units", {})
    # 단위 키: USD / 'USD/shares' / shares 중 존재하는 것
    unit_key = next(iter(units), None)
    if not unit_key:
        return []

    rows = []
    for f in units[unit_key]:
        fr = sec_frame(f)
        if not fr["fiscal_year"] or not fr["period"]:
            continue   # 기간 식별 불가 → 스킵 (임의 생성 금지)
        keep = False
        if kind == "stock":
            keep = f.get("start") is None or fr["duration_days"] is None or fr["duration_days"] <= 1
            # instant fact 는 start 없음. 있으면 잔액 아님 → 스킵
        else:  # flow
            if fr["is_ytd"]:
                keep = False
            elif fr["fiscal_period"] == "FY" and _in(fr["duration_days"], ANNUAL_DAYS):
                keep = True
            elif fr["fiscal_period"].startswith("Q") and _in(fr["duration_days"], QUARTER_DAYS):
                keep = True
        if not keep:
            continue
        rows.append({
            "metric": metric, "source_metric": tag, "unit": unit_key,
            "value": f.get("val"),
            "fiscal_year": fr["fiscal_year"], "fiscal_period": fr["fiscal_period"],
            "period": fr["period"], "original_period": fr["original_period"],
            "end": fr["end"], "start": fr["start"],
            "form": fr["form"], "filing_date": fr["filing_date"], "accession": fr["accession"],
        })

    # restatement 표시 — 같은 period 를 여러 filing 이 보고
    by_pf: dict[str, list[dict]] = {}
    for r in rows:
        by_pf.setdefault(r["period"], []).append(r)
    out = []
    for _, group in by_pf.items():
        group.sort(key=lambda r: (r["filing_date"] or "", r["accession"] or ""))
        latest = group[-1]
        for r in group:
            if r is latest:
                r["revision_status"] = "latest"
            else:
                r["revision_status"] = "superseded"
                if r["value"] != latest["value"]:
                    r["restatement_note"] = (
                        f"{r['value']} → 최신 filing({latest['filing_date']}) {latest['value']}")
        out.extend(group)
    return out
