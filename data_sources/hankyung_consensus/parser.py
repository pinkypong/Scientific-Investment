"""한경 컨센서스 파서 — 목록 HTML 행 파싱 · PDF 텍스트에서 숫자 추출.

임의 숫자 금지: 못 뽑으면 None + extraction_confidence 낮춤.
"""
from __future__ import annotations

import re
from datetime import datetime

from ..common.normalization import parse_num
from .schema import REPORT_TYPE_MAP, SELECTORS


def _first(el, css: str):
    for sel in css.split(","):
        found = el.select_one(sel.strip())
        if found:
            return found
    return None


def parse_list_html(html: str, base_url: str) -> list[dict]:
    """목록 페이지 HTML → [{date, category, document_type, title, url, analyst, broker, report_idx, pdf_url}]."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    rows = []
    for sel in SELECTORS["row"].split(","):
        rows = soup.select(sel.strip())
        if rows:
            break

    out = []
    for tr in rows:
        title_a = _first(tr, SELECTORS["title_link"])
        if not title_a:
            continue
        pdf_a = _first(tr, SELECTORS["pdf_link"])
        date_el = _first(tr, SELECTORS["date"])
        cat_el = _first(tr, SELECTORS["category"])
        author_el = _first(tr, SELECTORS["author"])
        broker_el = _first(tr, SELECTORS["broker"])

        href = (pdf_a or title_a).get("href", "")
        m = re.search(r"report_idx=(\d+)", href)
        report_idx = m.group(1) if m else None
        cat = (cat_el.get_text(strip=True) if cat_el else "") or ""

        out.append({
            "date": _norm_date(date_el.get_text(strip=True) if date_el else ""),
            "category": cat,
            "document_type": REPORT_TYPE_MAP.get(cat, "company"),
            "title": title_a.get_text(strip=True),
            "url": _abs(base_url, title_a.get("href", "")),
            "analyst": (author_el.get_text(strip=True) if author_el else None),
            "broker": (broker_el.get_text(strip=True) if broker_el else None),
            "report_idx": report_idx,
            "pdf_url": _abs(base_url, f"/analysis/downpdf?report_idx={report_idx}") if report_idx else None,
        })
    return out


def _abs(base: str, href: str) -> str:
    if not href:
        return base
    if href.startswith("http"):
        return href
    return base.rstrip("/") + "/" + href.lstrip("/")


def _norm_date(s: str) -> str | None:
    s = (s or "").strip().replace(".", "-").replace("/", "-")
    for fmt in ("%Y-%m-%d", "%y-%m-%d", "%Y-%m-%d "):
        try:
            return datetime.strptime(s[:10], fmt.strip()).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# ── PDF 본문에서 숫자 추출 ────────────────────────────────────────────
_TP_PAT = re.compile(r"목표주가[^\d]{0,12}([\d,]{3,})")
_PREV_TP_PAT = re.compile(r"(?:직전|기존)\s*목표주가[^\d]{0,12}([\d,]{3,})")
_RATING_PAT = re.compile(r"투자의견[^가-힣A-Za-z]{0,6}(매수|매도|보유|중립|Buy|Hold|Sell|Outperform|Overweight|Underweight)", re.I)
_PRICE_PAT = re.compile(r"현재주가[^\d]{0,12}([\d,]{3,})")
# 연도별 추정표 라인: "2027E 매출 123,456 영업이익 12,345 순이익 9,999 EPS 4,321"
_EST_LINE = re.compile(r"(20\d{2})\s*[EFP]?")


def extract_from_pdf(path: str, max_pages: int = 3) -> dict:
    """pymupdf 로 앞 페이지 텍스트 → {target_price, prev_target, rating, price_at_report,
    key_points[], estimates{}, extraction_confidence}."""
    try:
        import fitz  # pymupdf
    except ImportError:
        return {"extraction_confidence": "none", "key_points": [],
                "estimates": {}, "notes": ["pymupdf 미설치"]}

    try:
        doc = fitz.open(path)
    except Exception as e:  # noqa: BLE001
        return {"extraction_confidence": "none", "key_points": [],
                "estimates": {}, "notes": [f"open 실패: {e}"]}

    text = "\n".join(doc[i].get_text("text") for i in range(min(max_pages, doc.page_count)))
    doc.close()

    tp = _TP_PAT.search(text)
    prev = _PREV_TP_PAT.search(text)
    rating = _RATING_PAT.search(text)
    price = _PRICE_PAT.search(text)

    # 핵심 문장: 목표주가/투자의견/전망 포함 문장 3~5개
    sentences = re.split(r"(?<=[.。])\s+|\n", text)
    kw = ("목표주가", "투자의견", "전망", "예상", "실적", "가이던스", "상향", "하향")
    key_points = [s.strip() for s in sentences if 8 < len(s.strip()) < 180 and any(k in s for k in kw)][:5]

    got = sum(x is not None for x in (tp, rating))
    conf = "mid" if got == 2 else ("low" if got == 1 else "none")

    return {
        "target_price": parse_num(tp.group(1)) if tp else None,
        "prev_target": parse_num(prev.group(1)) if prev else None,
        "rating": rating.group(1) if rating else None,
        "price_at_report": parse_num(price.group(1)) if price else None,
        "key_points": key_points,
        "estimates": {},                # 표는 대개 이미지 → 세션에서 Claude 가 직접 판독
        "extraction_confidence": conf,
        "notes": [] if conf != "none" else ["텍스트 레이어에서 목표주가/투자의견 미검출 — 이미지 표일 수 있음"],
    }
