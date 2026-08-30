"""Bigdata.com 어댑터 — 가격 · 컨센서스 집계 · 뉴스/리포트 피드 (MARKET_DATA).

이 프로젝트에서 Bigdata 는 **브라우저에서** window.cowork.callMcpTool 로 호출된다
(index.html refreshQuotes/loadNews). 서버측에서 임의로 MCP 를 부르지 않는다.

이 어댑터의 역할(Phase 1–2):
  1) MCP tool 이름을 config 의 mcp_server + entity_id 로 조립 (하드코딩 UUID 제거, C4)
  2) tearsheet/search 응답 → NormalizedRecord (normalize)
  3) save_snapshot(): 브라우저/세션에서 받은 응답을 append-only 스토어에 적재 → 이력 축적 (C3)

CLI:
  python -m data_sources.bigdata.adapter --snapshot path/to/tearsheet.json --slug samsung
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..common.classification import NumberType, SourceClass
from ..common.provider import MarketDataProvider, register
from ..common.schema import NormalizedRecord, now_iso
from ..common import store
from . import parser as P

SOURCE = "bigdata.com"


@register("bigdata")
class BigdataProvider(MarketDataProvider):
    source_label = SOURCE
    supports_incremental = True

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        c = (config or {}).get("providers", {}).get("bigdata", {}) if config else {}
        self.mcp_server = c.get("mcp_server", "")
        self.search_query = c.get("search_query", "")
        self.covered = (config or {}).get("covered", []) if config else []

    # ── MCP tool 이름 조립 (브라우저 SRC.mcp_server 로도 주입됨) ──────
    def tool(self, name: str) -> str:
        prefix = self.mcp_server.rstrip("_")
        return f"{prefix}__{name}" if prefix else name

    def call_args_tearsheet(self, entity_id: str, sections=None) -> dict:
        return {"tool": self.tool("bigdata_company_tearsheet"),
                "args": {"rp_entity_id": entity_id, "company_type": "Public",
                         "sections": sections or ["company_overview", "price_performance"]}}

    def call_args_search(self, since: str, until: str, doc_type: str) -> dict:
        return {"tool": self.tool("bigdata_search"),
                "args": {"request": {"search_mode": "fast", "query": {
                    "text": self.search_query, "max_chunks": 20,
                    "filters": {"document_type": {"mode": "INCLUDE", "values": [doc_type]},
                                "timestamp": {"start": since, "end": until}}}}}}

    # MarketDataProvider 계약 — 서버측 직접 호출 안 함
    def fetch_quote(self, *, entity_id: str) -> dict:
        raise NotImplementedError(
            "Bigdata 는 브라우저(window.cowork.callMcpTool)에서 호출. "
            "call_args_tearsheet() 로 인자만 조립하고, 받은 응답을 save_snapshot() 으로 적재하세요.")

    def fetch_consensus(self, *, entity_id: str) -> dict:
        raise NotImplementedError("fetch_quote 참고")

    # ── normalize ────────────────────────────────────────────────────
    def normalize(self, raw: dict) -> list[NormalizedRecord]:
        """raw = {covered_row, tearsheet: <parsed dict from P.parse_tearsheet>, as_of}."""
        cov = raw["covered_row"]
        ts = raw["tearsheet"]
        as_of = raw.get("as_of") or now_iso()[:10]
        common = dict(
            source=SOURCE, provider="bigdata",
            source_type=SourceClass.MARKET_DATA,
            document_type="market",
            ticker=cov.get("ticker"), slug=cov.get("slug"),
            company_name=cov.get("name"), market=cov.get("market"),
            currency=cov.get("currency"),
            as_of_date=as_of, retrieved_at=now_iso(),
            original_url="https://bigdata.com",
            confidence="High", verification="Cross-Checked",
        )
        recs: list[NormalizedRecord] = []
        if ts.get("price") is not None:
            recs.append(NormalizedRecord(metric="price", value=ts["price"],
                                         unit=cov.get("currency"), period=as_of,
                                         number_type=NumberType.FACT, **common))
        if ts.get("market_cap") is not None:
            recs.append(NormalizedRecord(metric="market_cap", value=ts["market_cap"],
                                         unit=cov.get("currency"), period=as_of,
                                         number_type=NumberType.FACT, **common))
        for name, val in (ts.get("consensus") or {}).items():
            recs.append(NormalizedRecord(metric=name, value=val, unit=cov.get("currency"),
                                         period="forward",
                                         number_type=NumberType.CONSENSUS,
                                         confidence="Medium",
                                         **{k: v for k, v in common.items() if k != "confidence"}))
        return recs

    # ── 스냅샷 적재 (이력 축적) ─────────────────────────────────────
    def save_snapshot(self, slug: str, tearsheet_json: dict, as_of: str | None = None) -> int:
        cov = next((c for c in self.covered if c.get("slug") == slug), {"slug": slug})
        parsed = P.parse_tearsheet(tearsheet_json)
        recs = self.normalize({"covered_row": cov, "tearsheet": parsed, "as_of": as_of})
        raw_ref = store.save_raw("bigdata", f"tearsheet_{slug}_{(as_of or now_iso()[:10])}",
                                 json.dumps(tearsheet_json, ensure_ascii=False), "json")
        for r in recs:
            r.raw_ref = raw_ref
        return store.append_normalized("bigdata", recs)

    def save_feed_snapshot(self, results: list[dict], as_of: str | None = None) -> int:
        as_of = as_of or now_iso()[:10]
        items = P.parse_search_results(results)
        raw_ref = store.save_raw("bigdata", f"feed_{as_of}",
                                 json.dumps(results, ensure_ascii=False), "json")
        recs = []
        for it in items:
            recs.append(NormalizedRecord(
                source=SOURCE, provider="bigdata",
                source_type=SourceClass.NEWS if it["kind"] == "news" else SourceClass.SECONDARY_PROFESSIONAL,
                number_type=NumberType.UNVERIFIED,
                document_type="news" if it["kind"] == "news" else "report",
                report_title=it["headline"], original_url=it["url"],
                broker=it["source"], published_at=it["timestamp"], as_of_date=it["timestamp"] or as_of,
                why=[it["body"][:280]] if it["body"] else [], raw_ref=raw_ref,
                confidence="Low", verification="Unverified"))
        return store.append_normalized("bigdata", recs)


def _cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True, help="tearsheet JSON 파일 경로")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--as-of")
    a = ap.parse_args()
    cfg = json.loads((Path(__file__).resolve().parent.parent / "config" / "data_sources.json").read_text(encoding="utf-8"))
    prov = BigdataProvider(cfg)
    blob = json.loads(Path(a.snapshot).read_text(encoding="utf-8"))
    n = prov.save_snapshot(a.slug, blob, a.as_of)
    print(f"{a.slug}: 신규 {n} 레코드 적재 (이력 보존).")


if __name__ == "__main__":
    _cli()
