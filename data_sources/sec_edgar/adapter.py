"""SEC EDGAR 어댑터 — 미국 기업 실제 공시 재무 (PRIMARY_OFFICIAL).

인증 불필요. SEC 정책상 User-Agent 헤더(이름+이메일) 필수 → config.providers.sec_edgar.user_agent
또는 환경변수 SEC_EDGAR_USER_AGENT. rate-limit 준수(≤ ~10 req/s, 여기선 보수적으로).

CLI:
  python -m data_sources.sec_edgar.adapter --slug micron
  python -m data_sources.sec_edgar.adapter --all
  python -m data_sources.sec_edgar.adapter --resolve-cik MU SNDK
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path

from ..common.classification import NumberType, SourceClass
from ..common.provider import FundamentalProvider, register
from ..common.retry import RateLimiter, retry_with_backoff
from ..common.schema import NormalizedRecord, now_iso
from ..common.xbrl_map import METRIC_KIND, SEC_TAGS
from ..common import cache, netguard, store
from . import parser as P
from .schema import BASE, TICKERS_URL, filing_index_url

SOURCE = "SEC EDGAR"
HERE = Path(__file__).resolve().parent
CFG_PATH = HERE.parent / "config" / "data_sources.json"


@register("sec_edgar")
class SecEdgarProvider(FundamentalProvider):
    source_label = SOURCE
    supports_incremental = True

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        c = (config or {}).get("providers", {}).get("sec_edgar", {}) if config else {}
        self.user_agent = (os.environ.get("SEC_EDGAR_USER_AGENT")
                           or c.get("user_agent")
                           or "AI-stock-research (contact: set SEC_EDGAR_USER_AGENT)")
        self.delay = RateLimiter(c.get("request_delay_sec", 0.4))
        self.metrics = c.get("metrics") or list(SEC_TAGS.keys())
        self.covered = (config or {}).get("covered", []) if config else []
        # Phase D §1: company-level raw cache TTL (없으면 provider TTL 재사용)
        self.raw_cache_ttl = int(c.get("raw_cache_ttl_sec")
                                 or c.get("update_policy_sec") or 86400)
        self.last_cache_state = None      # "hit" | "miss" | "blocked"
        self.last_cache_age = None

    # ── HTTP ─────────────────────────────────────────────────────────
    @retry_with_backoff(retries=3, base_delay=1.0)
    def _get_json(self, url: str) -> dict:
        # Phase D §3: no-network 이면 여기서 즉시 중단(URL 전문 미노출).
        netguard.guard("data.sec.gov/api/xbrl/companyconcept")
        self.delay.wait()
        req = urllib.request.Request(url, headers={
            "User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate",
        })
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                import gzip
                raw = gzip.decompress(raw)
            return json.loads(raw)

    # ── CIK 조회 ─────────────────────────────────────────────────────
    def resolve_cik(self, tickers: list[str]) -> dict:
        data = self._get_json(TICKERS_URL)
        by_t = {v["ticker"].upper(): v for v in data.values()}
        out = {}
        for t in tickers:
            v = by_t.get(t.upper())
            out[t] = {"cik": f"{v['cik_str']:010d}", "title": v["title"]} if v else None
        return out

    # ── FundamentalProvider ──────────────────────────────────────────
    def fetch_statements(self, *, entity_id: str, statement: str = "all") -> dict:
        """entity_id = CIK(10자리). metric → concept json 묶음 + 요청 URL 목록 반환."""
        cik = str(entity_id).zfill(10)
        bundle, urls = {}, {}
        for metric in self.metrics:
            for tag in SEC_TAGS.get(metric, []):
                url = f"{BASE}/companyconcept/CIK{cik}/us-gaap/{tag}.json"
                try:
                    bundle[(metric, tag)] = self._get_json(url)
                    urls[f"{metric}|{tag}"] = url
                    break  # 첫 히트 태그만
                except Exception:  # noqa: BLE001
                    continue
        return {"cik": cik, "concepts": bundle, "request_urls": urls}

    def normalize(self, raw: dict) -> list[NormalizedRecord]:
        cov = raw["covered_row"]
        cik = int(raw["fetched"]["cik"])
        raw_ref = raw.get("raw_ref")
        recs: list[NormalizedRecord] = []
        for (metric, tag), cjson in raw["fetched"]["concepts"].items():
            unit_kind = METRIC_KIND.get(metric, ("USD", "flow"))[0]
            for f in P.facts_for_metric(cjson, metric, tag):
                notes = []
                if f.get("restatement_note"):
                    notes.append("restated: " + f["restatement_note"])
                recs.append(NormalizedRecord(
                    source=SOURCE, provider="sec_edgar",
                    source_type=SourceClass.PRIMARY_OFFICIAL,
                    number_type=NumberType.FACT,
                    document_type="filing",
                    ticker=cov.get("ticker"), slug=cov.get("slug"),
                    company_name=cov.get("name"), market="US", currency="USD",
                    metric=metric, source_metric=tag,
                    value=f["value"], unit=unit_kind, raw_value=f["value"],
                    period=f["period"], original_period=f["original_period"],
                    fiscal_year=f["fiscal_year"], fiscal_period=f["fiscal_period"],
                    form=f["form"], filing_date=f["filing_date"], accession=f["accession"],
                    fs_div="CFS",
                    revision_status=f.get("revision_status"),
                    as_of_date=f["end"], available_date=f["filing_date"],
                    retrieved_at=now_iso(),
                    original_url=filing_index_url(cik, f["accession"]),
                    raw_ref=(f"{raw_ref}#{metric}|{tag}" if raw_ref else None),
                    confidence="High", verification="Verified",
                    missing=notes,
                ))
        return recs

    # ── Phase D §1: company-level raw cache ─────────────────
    CACHE_NS = "raw_sec_edgar"

    def cache_key(self, covered_row: dict) -> str:
        """provider + company + metric 목록 + 기준날짜. SEC 는 자격증명이 없지만
        키 생성은 OpenDART 와 동일한 stable_key 를 쓴다(secret 필드 자동 제거)."""
        return cache.stable_key(
            "sec_edgar",
            slug=covered_row.get("slug"),
            ticker=covered_row.get("ticker"),
            cik=str(covered_row.get("sec_cik") or "").zfill(10),
            metrics=sorted(self.metrics),
            as_of=now_iso()[:10],
        )

    def _from_cache(self, covered_row: dict):
        """fresh cache 포인터 → raw 문서 복원 → (fetched, raw_ref, age).
        raw 는 {"metric|tag": concept_json} 형태로 저장돼 있으므로 tuple 키로 되돌린다."""
        e = cache.get_entry(self.CACHE_NS, self.cache_key(covered_row), self.raw_cache_ttl)
        doc, raw_ref, age = None, None, None
        if e:
            raw_ref = (e.get("value") or {}).get("raw_ref")
            doc, age = store.load_raw_json(raw_ref), e.get("age_sec")
        if not doc or not doc.get("data"):
            # 엔트리가 없거나 가리키던 raw 가 사라짐 → append-only raw 에서 승격 시도
            fb = cache.raw_fallback("sec_edgar", "concepts",
                                    covered_row.get("slug") or "", self.raw_cache_ttl)
            if not fb:
                return None
            doc, raw_ref, age = fb
            import time as _t
            cache.put(self.CACHE_NS, self.cache_key(covered_row),
                      {"raw_ref": raw_ref,
                       "content_hash": (doc.get("_meta") or {}).get("content_hash"),
                       "retrieved_at": (doc.get("_meta") or {}).get("retrieved_at")},
                      stored_at=_t.time() - (age or 0))   # 원본 수집 시각 유지
        meta = doc.get("_meta", {})
        concepts = {}
        for k, v in doc["data"].items():
            metric, _, tag = str(k).partition("|")
            if tag:
                concepts[(metric, tag)] = v
        if not concepts:
            return None
        fetched = {"cik": meta.get("cik") or str(covered_row.get("sec_cik") or "").zfill(10),
                   "concepts": concepts,
                   "request_urls": meta.get("request_urls", {})}
        return fetched, raw_ref, age

    def collect(self, covered_row: dict, *, no_network: bool = False,
                force: bool = False) -> list[NormalizedRecord]:
        cik = covered_row.get("sec_cik")
        if not cik:
            store.log("sec_edgar", "no_cik", {"slug": covered_row.get("slug")})
            self.last_cache_state = "skip"
            return []

        # --force 는 재수집이 목적이므로 cache 를 건너뛴다.
        # 단 --no-network 면 네트워크가 막혀 있어 cache 가 유일한 경로다.
        use_cache = (not force) or no_network
        hit = self._from_cache(covered_row) if use_cache else None
        if hit:
            fetched, raw_ref, age = hit
            self.last_cache_state, self.last_cache_age = "hit", age
            store.log("sec_edgar", "cache_hit", {"slug": covered_row.get("slug"),
                                                 "raw_ref": raw_ref, "age_sec": int(age or 0)})
            recs = self.normalize({"covered_row": covered_row, "fetched": fetched,
                                   "raw_ref": raw_ref})
            return self._validate(recs)

        if no_network:
            self.last_cache_state = "blocked"
            store.log("sec_edgar", "no_network_cache_miss", {"slug": covered_row.get("slug")})
            return []

        self.last_cache_state = "miss"
        fetched = self.fetch_statements(entity_id=cik)
        # 스펙 §3: 실제 원본 payload + 요청 metadata 보존
        real = {f"{m}|{t}": cjson for (m, t), cjson in fetched["concepts"].items()}
        raw_ref, chash = store.save_raw_json(
            "sec_edgar", f"concepts_{covered_row['slug']}_{now_iso()[:10]}", real,
            meta={
                "endpoint": "data.sec.gov/api/xbrl/companyconcept",
                "request_urls": fetched.get("request_urls", {}),
                "ticker": covered_row.get("ticker"), "cik": str(cik).zfill(10),
                "http_status": 200, "concept_count": len(real),
                "user_agent": self.user_agent,
            })
        store.log("sec_edgar", "raw_saved", {"raw_ref": raw_ref, "sha256": chash[:16]})
        cache.put(self.CACHE_NS, self.cache_key(covered_row),
                  {"raw_ref": raw_ref, "content_hash": chash, "retrieved_at": now_iso()})
        recs = self.normalize({"covered_row": covered_row, "fetched": fetched, "raw_ref": raw_ref})
        return self._validate(recs)

    def _validate(self, recs: list[NormalizedRecord]) -> list[NormalizedRecord]:
        """연속 period 간 극단 변화(§19) + restatement 차이 flag. 삭제하지 않고 표시만."""
        from ..common.validation import VALID, WARNING, validate_record
        # metric 별 latest 시계열
        series: dict[str, list[NormalizedRecord]] = {}
        for r in recs:
            if r.revision_status in (None, "latest") and r.period:
                series.setdefault(r.metric, []).append(r)
        for m, lst in series.items():
            lst.sort(key=lambda r: r.period)
        prev_by_key = {}
        for m, lst in series.items():
            for i, r in enumerate(lst):
                prev_by_key[(r.slug, r.metric, r.period)] = lst[i - 1].value if i else None
        for r in recs:
            st, notes = validate_record(
                r, prev_value=prev_by_key.get((r.slug, r.metric, r.period)))
            r.validation_status = st
            r.validation_notes = notes + list(r.missing or [])
        return recs


def _cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--resolve-cik", nargs="+")
    ap.add_argument("--rebuild", action="store_true",
                    help="sec_edgar.jsonl 초기화 후 재수집 (raw_ref/available_date 반영; SEC facts 결정적)")
    a = ap.parse_args()
    cfg = json.loads(CFG_PATH.read_text(encoding="utf-8"))
    prov = SecEdgarProvider(cfg)

    if a.resolve_cik:
        for t, v in prov.resolve_cik(a.resolve_cik).items():
            print(f"  {t} -> {v}")
        return

    rows = [c for c in cfg["covered"] if c.get("market") == "US"
            and (a.all or c.get("slug") == a.slug)]
    if not rows:
        print("대상 없음 (US 종목 + --slug/--all)"); return
    if a.rebuild:
        fp = store.NORM_DIR / "sec_edgar.jsonl"
        if fp.exists():
            bak = fp.with_suffix(".jsonl.bak")
            fp.replace(bak)
            print(f"기존 {fp.name} → {bak.name} 백업 후 재수집")
    total = 0
    for cov in rows:
        recs = prov.collect(cov)
        n = store.append_normalized("sec_edgar", recs)
        total += n
        by_m = {}
        for r in recs:
            by_m.setdefault(r.metric, set()).add(r.period or "?")
        print(f"{cov['slug']}: {len(recs)} 레코드, 신규 {n}")
        for m, pers in sorted(by_m.items()):
            ps = sorted(p for p in pers if p)
            print(f"   {m:20} periods={len(ps)}  {ps[-3:]}{' ...' if len(ps) > 3 else ''}")
    print(f"\n총 신규 {total} → data_sources/store/normalized/sec_edgar.jsonl")


if __name__ == "__main__":
    _cli()
