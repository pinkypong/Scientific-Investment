"""한경 글로벌마켓 어댑터 — 해외(미국) 종목 예상실적 컨센서스 수치 + 관련 뉴스.

Playwright(Chromium headless). 세션: storage_state 또는 user_data_dir (사용자가 로그인해 둔 상태).
없으면 비로그인 진행 + 게이트 필드는 gated_fields 에 기록(값은 None, 지어내지 않음).
로그인 절차(아이디/비번 입력) 자체는 자동화하지 않는다.

CLI:
  python -m data_sources.hankyung_global.adapter --ticker MU [--storage-state state.json] [--dump-html]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..common.classification import NumberType, SourceClass
from ..common.provider import NewsProvider, register
from ..common.retry import RateLimiter
from ..common.schema import NormalizedRecord, now_iso
from ..common import store
from . import parser as P
from .schema import GATED, SELECTORS

SOURCE = "한경 글로벌마켓"


@register("hankyung_global")
class HankyungGlobalProvider(NewsProvider):
    source_label = SOURCE
    supports_incremental = True

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        c = (config or {}).get("providers", {}).get("hankyung_global", {}) if config else {}
        self.base = c.get("base_url", "https://www.hankyung.com/globalmarket/equities")
        self.delay = RateLimiter(c.get("request_delay_sec", 2.0))
        self.storage_state = c.get("storage_state") or ""
        self.user_data_dir = c.get("user_data_dir") or ""
        self._dump = False

    # ── Playwright ───────────────────────────────────────────────────
    def _page_context(self):
        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        if self.user_data_dir:
            ctx = pw.chromium.launch_persistent_context(self.user_data_dir, headless=True)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            return pw, ctx, page
        browser = pw.chromium.launch(headless=True)
        kw = {}
        if self.storage_state and Path(self.storage_state).exists():
            kw["storage_state"] = self.storage_state
        ctx = browser.new_context(**kw)
        return pw, ctx, ctx.new_page()

    def fetch_estimates(self, ticker: str, exchange: str = "americas") -> dict:
        url = f"{self.base}/{exchange}/{ticker.lower()}"
        xhr_blobs: list[dict] = []
        result = {"source_url": url, "fetched_at": now_iso(), "by_year": {},
                  "target_price": None, "rating": None, "per": None,
                  "gated_fields": list(GATED), "notes": []}
        try:
            pw, ctx, page = self._page_context()
        except Exception as e:  # noqa: BLE001
            result["notes"].append(f"Playwright 불가: {e} (pip install playwright && playwright install chromium)")
            return result

        try:
            def _on_response(resp):
                try:
                    ct = resp.headers.get("content-type", "")
                    if "json" in ct and ("estimate" in resp.url.lower() or "consensus" in resp.url.lower()):
                        xhr_blobs.append({"url": resp.url, "json": resp.json()})
                except Exception:
                    pass

            page.on("response", _on_response)
            self.delay.wait()
            page.goto(url, wait_until="networkidle", timeout=30000)

            # 예상실적 탭 클릭 시도
            for sel in SELECTORS["tab_estimates"].split(","):
                try:
                    page.click(sel.strip(), timeout=2500)
                    page.wait_for_timeout(1500)
                    break
                except Exception:
                    continue

            html = page.content()
            if self._dump:
                store.save_raw("hankyung_global", f"page_{ticker}", html, "html")
            for i, b in enumerate(xhr_blobs):
                store.save_raw("hankyung_global", f"xhr_{ticker}_{i}", json.dumps(b, ensure_ascii=False), "json")

            parsed = P.parse_estimates_json(xhr_blobs[0]["json"]) if xhr_blobs else P.parse_estimates_html(html)
            result.update({k: parsed[k] for k in ("by_year", "target_price", "rating", "per")})
            result["gated_fields"] = parsed.get("gated_fields", [])
            result["notes"] += parsed.get("notes", [])
        except Exception as e:  # noqa: BLE001
            result["notes"].append(f"추출 실패: {e}")
        finally:
            try:
                ctx.close()
                pw.stop()
            except Exception:
                pass
        return result

    # NewsProvider 계약(예상실적 중심이라 search 는 최소 구현)
    def search(self, *, query: str, since: str, until: str, limit: int) -> list[dict]:
        return []

    # ── normalize ────────────────────────────────────────────────────
    def normalize(self, raw: dict) -> list[NormalizedRecord]:
        cov = raw["covered_row"]
        est = raw["estimates"]
        common = dict(
            source=SOURCE, provider="hankyung_global",
            source_type=SourceClass.SECONDARY_PROFESSIONAL,  # 수치 섹션 override
            document_type="estimate",
            ticker=cov.get("ticker"), slug=cov.get("slug"),
            company_name=cov.get("name"), market=cov.get("market") or "US",
            currency=cov.get("currency") or "USD",
            original_url=est.get("source_url"),
            as_of_date=(est.get("fetched_at") or now_iso())[:10],
            retrieved_at=est.get("fetched_at") or now_iso(),
            broker="한경 글로벌마켓(컨센서스 집계)",
            confidence="Medium",
            verification="Estimated",
            missing=est.get("notes", []),
        )
        recs: list[NormalizedRecord] = []
        for period, metrics in (est.get("by_year") or {}).items():
            for metric, val in metrics.items():
                recs.append(NormalizedRecord(
                    metric=metric, value=val, unit=cov.get("currency") or "USD",
                    period=period, number_type=NumberType.CONSENSUS, **common))
        for name in ("target_price", "per"):
            if est.get(name) is not None:
                recs.append(NormalizedRecord(metric=name, value=est[name],
                                             unit=cov.get("currency") or "USD",
                                             period="as_reported",
                                             number_type=NumberType.CONSENSUS, **common))
        if est.get("rating"):
            recs.append(NormalizedRecord(metric="rating", value=est["rating"],
                                         period="as_reported",
                                         number_type=NumberType.CONSENSUS, **common))
        for g in est.get("gated_fields", []):
            recs.append(NormalizedRecord(metric=g, value=None, period="as_reported",
                                         number_type=NumberType.INSUFFICIENT,
                                         missing=[f"{g}: 로그인 게이트 — 미수집(0 아님)"],
                                         **{k: v for k, v in common.items() if k != "missing"}))
        return recs

    def collect(self, covered_row: dict) -> list[NormalizedRecord]:
        est = self.fetch_estimates(covered_row["ticker"])
        return self.normalize({"covered_row": covered_row, "estimates": est})


def _cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--name")
    ap.add_argument("--storage-state")
    ap.add_argument("--dump-html", action="store_true")
    a = ap.parse_args()

    cfg_path = Path(__file__).resolve().parent.parent / "config" / "data_sources.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    if a.storage_state:
        cfg["providers"]["hankyung_global"]["storage_state"] = a.storage_state
    prov = HankyungGlobalProvider(cfg)
    prov._dump = a.dump_html
    covered = {"ticker": a.ticker, "name": a.name or a.ticker, "slug": a.name or a.ticker,
               "market": "US", "currency": "USD"}
    recs = prov.collect(covered)
    n = store.append_normalized("hankyung_global", recs)
    print(f"수집 {len(recs)} 레코드, 신규 {n} 저장.")
    for r in recs:
        print(f"  {r.metric or '(doc)'}={r.value} [{r.period}] {r.validation_status or ''} {r.missing or ''}")


if __name__ == "__main__":
    _cli()
