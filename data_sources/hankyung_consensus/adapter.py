"""한경 컨센서스 어댑터 — 국내 증권사 리서치 리포트 (PDF + 메타).

requests + BeautifulSoup(lxml). robots.txt 존중, rate-limit, 종목당 상한.
로그인 필요 시 cookie_file (Netscape) 을 세션에 로드. 로그인 절차 자체는 자동화하지 않음.

CLI:
  python -m data_sources.hankyung_consensus.adapter --ticker 005930 --name 삼성전자 \
         --since 2026-06-01 --until 2026-08-27 --max 10 [--dump-html]
"""
from __future__ import annotations

import argparse
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

from ..common.classification import NumberType, SourceClass
from ..common.normalization import market_of_ticker
from ..common.provider import ResearchReportProvider, register
from ..common.retry import RateLimiter, retry_with_backoff
from ..common.schema import NormalizedRecord, now_iso
from ..common import store
from . import parser as P
from .schema import SKIN_TYPE

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/125.0 Safari/537.36 personal-research/1.0")
SOURCE = "한경 컨센서스"


@register("hankyung_consensus")
class HankyungConsensusProvider(ResearchReportProvider):
    source_label = SOURCE
    supports_incremental = True

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        c = (config or {}).get("providers", {}).get("hankyung_consensus", {}) if config else {}
        self.base = c.get("base_url", "https://consensus.hankyung.com")
        self.list_path = c.get("list_path", "/analysis/list")
        self.delay = RateLimiter(c.get("request_delay_sec", 1.5))
        self.max_per_ticker = c.get("max_per_ticker", 15)
        self.cookie_file = c.get("cookie_file") or ""
        self._session = None

    # ── 세션 ──────────────────────────────────────────────────────────
    @property
    def session(self):
        if self._session is None:
            import requests
            s = requests.Session()
            s.headers["User-Agent"] = USER_AGENT
            if self.cookie_file and Path(self.cookie_file).exists():
                from http.cookiejar import MozillaCookieJar
                jar = MozillaCookieJar(self.cookie_file)
                jar.load(ignore_discard=True, ignore_expires=True)
                s.cookies = jar
            self._session = s
        return self._session

    def _robots_ok(self, url: str) -> bool:
        parts = urlparse(url)
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(f"{parts.scheme}://{parts.netloc}/robots.txt")
        try:
            rp.read()
            return rp.can_fetch(USER_AGENT, url)
        except Exception:
            return True

    # ── ResearchReportProvider ───────────────────────────────────────
    @retry_with_backoff(retries=3, base_delay=1.0)
    def _get(self, url: str, **kw):
        self.delay.wait()
        r = self.session.get(url, timeout=20, **kw)
        r.raise_for_status()
        return r

    def list_reports(self, *, ticker: str, name: str | None,
                     since: str, until: str, limit: int | None = None) -> list[dict]:
        limit = limit or self.max_per_ticker
        rows: list[dict] = []
        for page in range(1, 11):
            url = (f"{self.base}{self.list_path}?sdate={since}&edate={until}"
                   f"&now_page={page}&pagenum=50&search_text={name or ticker}")
            if not self._robots_ok(url):
                store.log("hankyung_consensus", "robots_block", {"url": url})
                break
            html = self._get(url).text
            if getattr(self, "_dump", False):
                store.save_raw("hankyung_consensus", f"list_{ticker}_p{page}", html, "html")
            page_rows = P.parse_list_html(html, self.base)
            if not page_rows:
                break
            for r in page_rows:
                if name and name not in (r["title"] or "") and (r.get("broker") or ""):
                    pass  # 목록엔 종목명이 제목에만 있을 수 있음 → 느슨하게 유지
                rows.append(r)
            if len(rows) >= limit:
                break
        return rows[:limit]

    def fetch_report(self, report_ref: dict) -> dict:
        pdf_url = report_ref.get("pdf_url")
        if not pdf_url or not self._robots_ok(pdf_url):
            return {"pdf_path": None, "raw_ref": None,
                    "meta": {"notes": ["pdf_url 없음 또는 robots 차단"], "extraction_confidence": "none"}}
        try:
            content = self._get(pdf_url).content
        except Exception as e:  # noqa: BLE001
            return {"pdf_path": None, "raw_ref": None,
                    "meta": {"notes": [f"다운로드 실패: {e}"], "extraction_confidence": "none"}}
        idx = report_ref.get("report_idx") or "x"
        raw_ref = store.save_raw("hankyung_consensus", f"pdf_{idx}", content, "pdf")
        abspath = str((store.STORE_ROOT / raw_ref))
        meta = P.extract_from_pdf(abspath)
        return {"pdf_path": raw_ref, "raw_ref": raw_ref, "meta": meta}

    # ── normalize ────────────────────────────────────────────────────
    def normalize(self, raw: dict) -> list[NormalizedRecord]:
        """raw = {covered_row, list_row, fetched}. 리포트 1건 → 레코드 여러 개(목표주가·투자의견·추정치)."""
        cov = raw["covered_row"]
        lr = raw["list_row"]
        fx = raw.get("fetched", {}) or {}
        meta = fx.get("meta", {}) or {}
        common = dict(
            source=SOURCE, provider="hankyung_consensus",
            source_type=SourceClass.SECONDARY_PROFESSIONAL,
            document_type=lr.get("document_type"),
            ticker=cov.get("ticker"), slug=cov.get("slug"),
            company_name=cov.get("name"), market=cov.get("market") or market_of_ticker(cov.get("ticker")),
            currency=cov.get("currency"),
            published_at=lr.get("date"), as_of_date=lr.get("date"),
            report_id=lr.get("report_idx"), report_title=lr.get("title"),
            analyst=lr.get("analyst"), broker=lr.get("broker"),
            original_url=lr.get("url"), pdf_url=lr.get("pdf_url"),
            pdf_path=fx.get("pdf_path"), raw_ref=fx.get("raw_ref"),
            confidence={"mid": "Medium", "low": "Low", "none": "Low"}.get(
                meta.get("extraction_confidence", "none"), "Low"),
            verification="Estimated",
            why=meta.get("key_points", []),
            missing=meta.get("notes", []),
        )
        recs: list[NormalizedRecord] = []

        tp = meta.get("target_price")
        recs.append(NormalizedRecord(metric="target_price", value=tp,
                                     unit=cov.get("currency"), period="as_reported",
                                     number_type=NumberType.CONSENSUS,
                                     raw_value=meta.get("target_price"), **common))
        if meta.get("prev_target") is not None:
            recs.append(NormalizedRecord(metric="prev_target_price", value=meta["prev_target"],
                                        unit=cov.get("currency"), period="as_reported",
                                        number_type=NumberType.CONSENSUS, **common))
        if meta.get("rating"):
            recs.append(NormalizedRecord(metric="rating", value=meta["rating"],
                                        period="as_reported",
                                        number_type=NumberType.CONSENSUS, **common))
        for yr, e in (meta.get("estimates") or {}).items():
            for k, val in e.items():
                recs.append(NormalizedRecord(metric=k, value=val, unit=cov.get("currency"),
                                            period=f"FY{yr}", number_type=NumberType.CONSENSUS,
                                            **common))
        # 리포트 자체를 문서 레코드로도 남김(값 없음, 계보/뉴스탭용)
        recs.append(NormalizedRecord(metric=None, value=lr.get("title"),
                                     number_type=NumberType.CONSENSUS,
                                     document_type=lr.get("document_type"), **common))
        return recs

    # ── 오케스트레이션 ──────────────────────────────────────────────
    def collect(self, covered_row: dict, since: str, until: str,
                limit: int | None = None) -> list[NormalizedRecord]:
        out: list[NormalizedRecord] = []
        rows = self.list_reports(ticker=covered_row["ticker"], name=covered_row.get("name"),
                                 since=since, until=until, limit=limit)
        for lr in rows:
            fetched = self.fetch_report(lr) if lr.get("pdf_url") else {}
            out.extend(self.normalize({"covered_row": covered_row, "list_row": lr, "fetched": fetched}))
        return out


def _cli():
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--name")
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", required=True)
    ap.add_argument("--max", type=int, default=10)
    ap.add_argument("--dump-html", action="store_true")
    a = ap.parse_args()

    cfg_path = Path(__file__).resolve().parent.parent / "config" / "data_sources.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    prov = HankyungConsensusProvider(cfg)
    prov._dump = a.dump_html
    covered = {"ticker": a.ticker, "name": a.name, "slug": a.name or a.ticker,
               "market": market_of_ticker(a.ticker), "currency": "KRW"}
    recs = prov.collect(covered, a.since, a.until, a.max)
    n = store.append_normalized("hankyung_consensus", recs)
    print(f"수집 {len(recs)} 레코드, 신규 {n} 저장. raw → data_sources/store/raw/hankyung_consensus/")


if __name__ == "__main__":
    _cli()
