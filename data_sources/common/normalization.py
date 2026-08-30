"""Normalization helpers — 통화 · 기간 · metric 명 정규화 · 숫자 파싱.

임의 보간 금지: 파싱 불가하면 None (Missing ≠ 0).
"""
from __future__ import annotations

import re

# ── 숫자 ────────────────────────────────────────────────────────────────
_NUM_JUNK = re.compile(r"[,\s원$￦%]")


def parse_num(s):
    """'47,500' / '12.3%' / '  -  ' / '1,059,819.58백만' → float | None."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    t = str(s).strip()
    if t in ("", "-", "—", "–", "N/A", "NA", "n/a", "해당없음"):
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = _NUM_JUNK.sub("", t).strip("()")
    t = t.replace("백만", "").replace("천", "").replace("억", "").replace("조", "")
    try:
        v = float(t)
        return -v if neg else v
    except ValueError:
        return None


# ── 통화 ────────────────────────────────────────────────────────────────
CCY_ALIASES = {
    "원": "KRW", "krw": "KRW", "₩": "KRW", "KRW": "KRW",
    "$": "USD", "usd": "USD", "US$": "USD", "USD": "USD",
}


def canon_currency(s: str | None) -> str | None:
    if not s:
        return None
    return CCY_ALIASES.get(str(s).strip(), str(s).strip().upper())


def market_of_ticker(ticker: str | None) -> str | None:
    if not ticker:
        return None
    t = str(ticker).strip()
    if re.fullmatch(r"\d{6}", t):
        return "KR"
    if re.fullmatch(r"[A-Za-z.\-]{1,6}", t):
        return "US"
    return None


# ── 기간 ────────────────────────────────────────────────────────────────
def canon_period(raw: str | None, *, fiscal_basis: str | None = None):
    """'2027E' / 'FY27' / '27.12' / '2Q26' / '2026-08-15' → 표준 문자열.

    반환 예: 'FY2027' · '2026-Q2' · '2026-08-15' · 'TTM' · None
    """
    if raw is None:
        return None
    t = str(raw).strip().upper().replace(" ", "")
    if t in ("TTM", "LTM"):
        return "TTM"
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return t
    m = re.fullmatch(r"([1-4])Q(\d{2,4})E?", t) or re.fullmatch(r"(\d{4})-?Q([1-4])", t)
    if m:
        a, b = m.groups()
        if len(a) == 1:  # 2Q26
            q, y = a, b
        else:            # 2026-Q2
            y, q = a, b
        y = int(y)
        if y < 100:
            y += 2000
        return f"{y}-Q{q}"
    m = re.fullmatch(r"(?:FY)?(\d{4})E?F?", t) or re.fullmatch(r"(?:FY)?(\d{2})E?F?", t) or re.fullmatch(r"(\d{2})\.\d{2}", t)
    if m:
        y = int(m.group(1))
        if y < 100:
            y += 2000
        tag = f"FY{y}"
        return tag + (f"({fiscal_basis})" if fiscal_basis else "")
    return t or None


# ── metric 명 ──────────────────────────────────────────────────────────
_METRIC_CANON = {
    # 한국어/약어 → canonical
    "매출": "revenue", "매출액": "revenue", "revenue": "revenue", "sales": "revenue",
    "영업이익": "operating_income", "op": "operating_income", "operating income": "operating_income",
    "순이익": "net_income", "당기순이익": "net_income", "ni": "net_income", "net income": "net_income",
    "eps": "eps", "주당순이익": "eps",
    "목표주가": "target_price", "target price": "target_price", "tp": "target_price",
    "투자의견": "rating", "rating": "rating", "opinion": "rating",
    "현재가": "price", "종가": "price", "price": "price",
    "per": "pe", "p/e": "pe", "pe": "pe", "fwd p/e": "pe_forward", "forward pe": "pe_forward",
    "pbr": "pb", "p/b": "pb", "pb": "pb",
    "ebitda": "ebitda", "ev/ebitda": "ev_ebitda",
    "wacc": "wacc", "roe": "roe", "roic": "roic",
    "dram asp": "dram_asp", "nand asp": "nand_asp", "hbm asp": "hbm_asp",
}


def canon_metric(raw: str | None) -> str | None:
    if not raw:
        return None
    k = str(raw).strip().lower()
    return _METRIC_CANON.get(k, k.replace(" ", "_"))


# ── 텍스트 ─────────────────────────────────────────────────────────────
def safe_name(s: str | None) -> str:
    keep = "-_.()[] "
    return "".join(c for c in (s or "") if c.isalnum() or c in keep or ord(c) > 127).strip() or "unknown"
