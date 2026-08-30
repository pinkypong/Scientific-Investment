"""한경 글로벌마켓 예상실적 파서 — 렌더된 HTML(테이블) 또는 XHR JSON → 정규화 전 dict."""
from __future__ import annotations

import re

from ..common.normalization import canon_period, parse_num
from .schema import ROW_LABEL_MAP


def parse_estimates_html(html: str) -> dict:
    """예상실적 탭 렌더 HTML → {by_year:{FY:{metric:val}}, target_price, rating, per, gated_fields[]}."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    out = {"by_year": {}, "target_price": None, "rating": None, "per": None,
           "gated_fields": [], "notes": []}

    # 표 후보: 헤더에 연도(20xx)가 있고 좌측 라벨이 매출/영업이익/순이익/EPS
    for table in soup.select("table"):
        head = [th.get_text(strip=True) for th in table.select("thead th, tr:first-child th, tr:first-child td")]
        years = [h for h in head if re.fullmatch(r"20\d{2}[EFP]?", h)]
        if not years:
            continue
        for tr in table.select("tbody tr, tr"):
            cells = [td.get_text(strip=True) for td in tr.select("td, th")]
            if len(cells) < 2:
                continue
            label = cells[0]
            metric = next((m for k, m in ROW_LABEL_MAP.items() if k in label), None)
            if not metric:
                continue
            for i, y in enumerate(years):
                val = parse_num(cells[i + 1]) if i + 1 < len(cells) else None
                per = canon_period(y)
                out["by_year"].setdefault(per, {})[metric] = val
        if out["by_year"]:
            break

    def _dd(label):
        el = soup.find(string=re.compile(label))
        if not el:
            return None
        sib = getattr(el, "find_next", lambda *_: None)("dd") or getattr(el.parent, "find_next_sibling", lambda *_: None)("dd")
        return sib.get_text(strip=True) if sib else None

    tp = _dd("목표주가")
    rating = _dd("투자의견")
    per = _dd("PER")
    out["target_price"] = parse_num(tp)
    out["rating"] = rating or None
    out["per"] = parse_num(per)
    for name, raw in (("target_price", tp), ("rating", rating), ("per", per)):
        if raw in (None, "", "-", "—"):
            out["gated_fields"].append(name)
    return out


def parse_estimates_json(blob: dict) -> dict:
    """XHR JSON(구조 미확정) → 위와 동일 형태. 키 후보를 관대하게 매칭."""
    out = {"by_year": {}, "target_price": None, "rating": None, "per": None,
           "gated_fields": [], "notes": ["from XHR JSON"]}
    rows = blob.get("estimates") or blob.get("data") or blob.get("list") or []
    for row in rows if isinstance(rows, list) else []:
        y = row.get("year") or row.get("fiscalYear") or row.get("bizYear")
        if not y:
            continue
        per = canon_period(str(y))
        d = out["by_year"].setdefault(per, {})
        for src, metric in (("sales", "revenue"), ("revenue", "revenue"),
                            ("operatingProfit", "operating_income"), ("opProfit", "operating_income"),
                            ("netIncome", "net_income"), ("eps", "eps"),
                            ("analystCount", "n_analysts")):
            if src in row and row[src] is not None:
                d[metric] = parse_num(row[src]) if metric != "n_analysts" else int(row[src])
    for k_src, k_out in (("targetPrice", "target_price"), ("opinion", "rating"), ("per", "per")):
        if blob.get(k_src) not in (None, "", "-"):
            out[k_out] = parse_num(blob[k_src]) if k_out != "rating" else blob[k_src]
        else:
            out["gated_fields"].append(k_out)
    return out
