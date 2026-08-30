"""Bigdata.com 응답 파서 — tearsheet JSON → 값 dict, search results → 뉴스/리포트 dict."""
from __future__ import annotations

from ..common.normalization import parse_num
from .schema import CONSENSUS_PATHS, MARKETCAP_PATHS, PRICE_PATHS, REPORT_SIGNALS


def _dig(d: dict, path: tuple):
    cur = d
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def _first_path(d: dict, paths: list[tuple]):
    for p in paths:
        v = _dig(d, p)
        if v is not None:
            return v
    return None


def parse_tearsheet(blob: dict) -> dict:
    """tearsheet JSON(structuredContent 또는 content[0].text 파싱 후) → {price, market_cap, consensus{...}}."""
    out = {"price": parse_num(_first_path(blob, PRICE_PATHS)),
           "market_cap": parse_num(_first_path(blob, MARKETCAP_PATHS)),
           "consensus": {}}
    for name, paths in CONSENSUS_PATHS.items():
        v = _first_path(blob, paths)
        if v is not None:
            out["consensus"][name] = parse_num(v)
    return out


def classify_feed_item(item: dict) -> str:
    """뉴스 vs 리포트. index.html loadNews 의 content-based 분류 취지."""
    text = " ".join(str(item.get(k, "")) for k in ("headline", "title", "summary"))
    if item.get("chunks"):
        text += " " + " ".join(c if isinstance(c, str) else c.get("text", "") for c in item["chunks"])
    return "report" if any(sig in text for sig in REPORT_SIGNALS) else "news"


def parse_search_results(results: list[dict]) -> list[dict]:
    out = []
    for r in results or []:
        out.append({
            "headline": r.get("headline") or r.get("title"),
            "url": r.get("url"),
            "source": (r.get("source") or {}).get("name") if isinstance(r.get("source"), dict) else r.get("source"),
            "timestamp": (r.get("timestamp") or "")[:10],
            "kind": classify_feed_item(r),
            "body": r.get("summary") or " ".join(
                c if isinstance(c, str) else c.get("text", "") for c in (r.get("chunks") or [])),
        })
    return out
