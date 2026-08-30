"""Financial period normalization (설계서 Phase B §8).

SEC(us-gaap fact 의 start/end/fp/fy)와 OpenDART(reprt_code)의 보고기간을 공통 형태로:
  연간  → "FY2025"
  분기  → "2026Q1" .. "2026Q4"
original_period / fiscal_year / fiscal_period / form 은 별도로 보존한다.
"""
from __future__ import annotations

from datetime import date

# OpenDART reprt_code → (fiscal_period, 사람이 읽는 form)
DART_REPRT = {
    "11011": ("FY", "사업보고서"),
    "11012": ("Q2", "반기보고서"),      # 반기 누적 → Q2 로 취급(누적임을 notes 에)
    "11013": ("Q1", "1분기보고서"),
    "11014": ("Q3", "3분기보고서"),
}


def canon_fy_period(fiscal_year: int, fiscal_period: str) -> str:
    fp = (fiscal_period or "FY").upper()
    if fp in ("FY", "Y", "ANNUAL"):
        return f"FY{fiscal_year}"
    return f"{fiscal_year}{fp}"   # 2026Q1


def sec_frame(fact: dict) -> dict:
    """us-gaap companyconcept 의 fact 1건 → 기간 정보.

    ⚠ fact 의 fy/fp 는 '보고서'의 회계연도/분기이지 **데이터 시점이 아니다**
      (예: FY2026 10-K 에 실린 FY2024 비교치도 fy=2026). → start/end 날짜로 기간을 도출한다.

    반환: fiscal_year(달력, =end.year) · fiscal_period(Q1..Q4|FY, 달력분기) ·
          period("FY2025"|"2026Q2") · original_period("2026-03-01..2026-05-28" 원본 정확) ·
          duration_days · is_ytd · start · end · form · filing_date · accession · frame
    fact 예: {start:'2026-03-01', end:'2026-05-28', val, fy:2026, fp:'Q3', form:'10-Q',
             filed:'2026-06-25', accn:'0000723125-26-...', frame:'CY2026Q2'}
    """
    start = fact.get("start")
    end = fact.get("end")
    dur = None
    end_d = None
    try:
        end_d = date.fromisoformat(end) if end else None
        if start and end:
            dur = (end_d - date.fromisoformat(start)).days
    except ValueError:
        pass

    fp_report = (fact.get("fp") or "").upper()

    if end_d is None:
        return {"fiscal_year": None, "fiscal_period": None, "period": None,
                "original_period": fact.get("frame"), "duration_days": dur, "is_ytd": False,
                "start": start, "end": end, "form": fact.get("form"),
                "filing_date": fact.get("filed"), "accession": fact.get("accn"),
                "frame": fact.get("frame")}

    is_instant = start is None
    is_ytd = False
    if is_instant:
        # 잔액(stock) — 시점. 달력 분기로 라벨.
        fy = end_d.year
        fq = (end_d.month - 1) // 3 + 1
        fiscal_period = f"Q{fq}"
        period = f"{fy}Q{fq}"
    elif dur is not None and 350 <= dur <= 380:
        fy = end_d.year
        fiscal_period = "FY"
        period = f"FY{fy}"
    elif dur is not None and 80 <= dur <= 100:
        fy = end_d.year
        fq = (end_d.month - 1) // 3 + 1
        fiscal_period = f"Q{fq}"
        period = f"{fy}Q{fq}"
    else:
        # 반기/9개월 누적 등
        is_ytd = True
        fy = end_d.year
        fiscal_period = fp_report or "YTD"
        period = None   # 대시보드에 넣지 않음

    return {
        "fiscal_year": fy, "fiscal_period": fiscal_period, "period": period,
        "original_period": (f"{start}..{end}" if start else end),
        "duration_days": dur, "is_ytd": is_ytd,
        "start": start, "end": end,
        "form": fact.get("form"), "filing_date": fact.get("filed"),
        "accession": fact.get("accn"), "frame": fact.get("frame"),
    }


def dart_frame(bsns_year: str, reprt_code: str) -> dict:
    fp, form = DART_REPRT.get(str(reprt_code), ("FY", "보고서"))
    fy = int(bsns_year)
    return {
        "fiscal_year": fy,
        "fiscal_period": fp,
        "period": canon_fy_period(fy, fp),
        "original_period": f"{bsns_year}/{reprt_code}",
        "form": form,
        "cumulative": reprt_code in ("11012",),   # 반기 누적
    }
