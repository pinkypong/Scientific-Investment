"""OpenDART 어댑터 — 한국 기업 실제 공시 재무 (PRIMARY_OFFICIAL).

인증: OPENDART_API_KEY (환경변수 / data_sources/.env). 없으면 BLOCKED (구현은 완료).
연결(CFS) 우선, 없으면 별도(OFS) fallback + notes 표기.

CLI:
  python -m data_sources.opendart.adapter --slug samsung
  python -m data_sources.opendart.adapter --all
  python -m data_sources.opendart.adapter --resolve-corp 005930 000660   (키 필요)
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from ..common.classification import NumberType, SourceClass
from ..common.provider import FundamentalProvider, register
from ..common.retry import RateLimiter, retry_with_backoff
from ..common.schema import NormalizedRecord, now_iso
from ..common import cache, netguard, store
from . import parser as P
from .schema import BASE, FILING_URL, STATUS_MSG

SOURCE = "OpenDART"
HERE = Path(__file__).resolve().parent
CFG_PATH = HERE.parent / "config" / "data_sources.json"


def _load_dotenv() -> None:
    env = HERE.parent / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


class BlockedNoKey(RuntimeError):
    pass


def _scrub(text: str, key: str) -> str:
    """로그/예외 문자열에서 API 키와 crtfc_key 쿼리값 제거 (절대 노출 금지)."""
    s = str(text)
    if key:
        s = s.replace(key, "<OPENDART_API_KEY>")
    import re as _re
    return _re.sub(r"crtfc_key=[^&\s'\"]+", "crtfc_key=<redacted>", s)


@register("opendart")
class OpenDartProvider(FundamentalProvider):
    source_label = SOURCE
    supports_incremental = True

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        _load_dotenv()
        c = (config or {}).get("providers", {}).get("opendart", {}) if config else {}
        self.base = c.get("base_url", BASE)
        self.key = os.environ.get(c.get("api_key_env", "OPENDART_API_KEY"), "")
        self.fs_div = c.get("fs_div", "CFS")
        self.delay = RateLimiter(c.get("request_delay_sec", 0.6))
        self.years_back = c.get("years_back", 4)
        self.reprt_codes = c.get("reprt_codes", ["11011", "11014", "11012", "11013"])
        # Phase D §1: company-level raw cache TTL (없으면 provider TTL 재사용)
        self.raw_cache_ttl = int(c.get("raw_cache_ttl_sec")
                                 or c.get("update_policy_sec") or 86400)
        self.last_cache_state = None      # "hit" | "miss" | "blocked"
        self.last_cache_age = None

    @property
    def available(self) -> bool:
        return bool(self.key)

    @retry_with_backoff(retries=3, base_delay=1.0)
    def _get(self, path: str, params: dict) -> dict:
        # Phase D §3: no-network 이면 여기서 즉시 중단(수신 URL·쿼리 미노출).
        netguard.guard(f"opendart.fss.or.kr/api/{path}")
        self.delay.wait()
        q = urllib.parse.urlencode({**params, "crtfc_key": self.key})
        url = f"{self.base}/{path}?{q}"
        req = urllib.request.Request(url, headers={"User-Agent": "AI-stock-research"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())

    # ── FundamentalProvider ──────────────────────────────────────────
    def fetch_statements(self, *, entity_id: str, statement: str = "all") -> dict:
        """entity_id = corp_code. 연도×보고서 매트릭스로 fnlttSinglAcntAll 수집."""
        if not self.available:
            raise BlockedNoKey("OPENDART_API_KEY 없음 — .env 또는 환경변수 설정 필요")
        import datetime
        this_year = datetime.date.today().year
        results = []
        for y in range(this_year, this_year - self.years_back, -1):
            for rc in self.reprt_codes:
                for fsd in ([self.fs_div, "OFS"] if self.fs_div == "CFS" else [self.fs_div]):
                    try:
                        payload = self._get("fnlttSinglAcntAll.json", {
                            "corp_code": entity_id, "bsns_year": str(y),
                            "reprt_code": rc, "fs_div": fsd})
                    except Exception as e:  # noqa: BLE001
                        store.log("opendart", "http_error", {"corp": entity_id, "y": y,
                                  "rc": rc, "e": _scrub(repr(e), self.key)})
                        continue
                    st = payload.get("status")
                    if st == "000":
                        results.append({"payload": payload, "bsns_year": str(y),
                                        "reprt_code": rc, "fs_div": fsd})
                        break   # 이 (연도,보고서) 는 CFS 성공 → OFS 스킵
                    elif st in ("010", "011", "020"):
                        raise BlockedNoKey(f"OpenDART {st}: {STATUS_MSG.get(st, st)}")
                    # "013" 데이터없음 → 다음 fs_div/보고서
        return {"corp_code": entity_id, "results": results}

    def normalize(self, raw: dict) -> list[NormalizedRecord]:
        cov = raw["covered_row"]
        raw_ref = raw.get("raw_ref")
        recs: list[NormalizedRecord] = []
        for blk in raw["fetched"]["results"]:
            facts = P.parse_acnt_all(blk["payload"], bsns_year=blk["bsns_year"],
                                     reprt_code=blk["reprt_code"], fs_div=blk["fs_div"])
            for f in facts:
                notes = []
                if f["fs_div"] == "OFS":
                    notes.append("연결(CFS) 데이터 없음 → 별도(OFS) fallback")
                if f["cumulative"]:
                    notes.append("반기 누적치")
                recs.append(NormalizedRecord(
                    source=SOURCE, provider="opendart",
                    source_type=SourceClass.PRIMARY_OFFICIAL,
                    number_type=NumberType.FACT, document_type="filing",
                    ticker=cov.get("ticker"), slug=cov.get("slug"),
                    company_name=cov.get("name"), market="KR", currency=f["currency"],
                    metric=f["metric"], source_metric=f["source_metric"],
                    value=f["value"], unit=f["unit"], raw_value=f["raw_value"],
                    period=f["period"], original_period=f["original_period"],
                    fiscal_year=f["fiscal_year"], fiscal_period=f["fiscal_period"],
                    form=f["form"], fs_div=f["fs_div"], accession=f["rcept_no"],
                    filing_date=f["filing_date"], available_date=f["filing_date"],
                    revision_status="latest",
                    as_of_date=f["period_end"], retrieved_at=now_iso(),
                    original_url=FILING_URL.format(rcept_no=f["rcept_no"]),
                    raw_ref=(f"{raw_ref}#{f['period']}|{f['metric']}|{f['source_metric']}"
                             if raw_ref else None),
                    confidence="High", verification="Verified",
                    missing=notes))
        return recs

    # ── Phase D §1: company-level raw cache ─────────────────
    CACHE_NS = "raw_opendart"

    def cache_key(self, covered_row: dict) -> str:
        """provider + company + 요청 파라미터 + 기준날짜.
        API key 는 stable_key 가 secret 필드를 제거하므로 애초에 들어갈 수 없다."""
        return cache.stable_key(
            "opendart",
            slug=covered_row.get("slug"),
            ticker=covered_row.get("ticker"),
            corp_code=covered_row.get("dart_corp_code"),
            years_back=self.years_back,
            reprt_codes=sorted(self.reprt_codes),
            fs_div=self.fs_div,
            as_of=now_iso()[:10],
        )

    def _from_cache(self, covered_row: dict):
        """fresh cache 가 가리키는 raw 문서를 복원 → (fetched, raw_ref, age).
        포인터는 있는데 raw 파일이 없으면 miss 로 강등."""
        e = cache.get_entry(self.CACHE_NS, self.cache_key(covered_row), self.raw_cache_ttl)
        doc, raw_ref, age = None, None, None
        if e:
            raw_ref = (e.get("value") or {}).get("raw_ref")
            doc, age = store.load_raw_json(raw_ref), e.get("age_sec")
        if not doc or not doc.get("data"):
            # 엔트리가 없거나 가리키던 raw 가 사라짐 → append-only raw 에서 승격 시도
            fb = cache.raw_fallback("opendart", "statements",
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
        return doc["data"], raw_ref, age

    def collect(self, covered_row: dict, *, no_network: bool = False,
                force: bool = False) -> list[NormalizedRecord]:
        corp = covered_row.get("dart_corp_code")
        if not corp:
            store.log("opendart", "no_corp_code", {"slug": covered_row.get("slug")})
            self.last_cache_state = "skip"
            return []

        # --force 는 재수집이 목적이므로 cache 를 건너뛴다.
        # 단 --no-network 면 네트워크가 막혀 있어 cache 가 유일한 경로다.
        use_cache = (not force) or no_network
        hit = self._from_cache(covered_row) if use_cache else None
        if hit:
            fetched, raw_ref, age = hit
            self.last_cache_state, self.last_cache_age = "hit", age
            store.log("opendart", "cache_hit", {"slug": covered_row.get("slug"),
                                                "raw_ref": raw_ref, "age_sec": int(age or 0)})
            return self.normalize({"covered_row": covered_row, "fetched": fetched,
                                   "raw_ref": raw_ref})

        if no_network:
            self.last_cache_state = "blocked"
            store.log("opendart", "no_network_cache_miss", {"slug": covered_row.get("slug")})
            return []

        self.last_cache_state = "miss"
        fetched = self.fetch_statements(entity_id=corp)
        raw_ref, chash = store.save_raw_json(
            "opendart", f"statements_{covered_row['slug']}_{now_iso()[:10]}", fetched,
            meta={
                "endpoint": "opendart.fss.or.kr/api/fnlttSinglAcntAll.json",
                "ticker": covered_row.get("ticker"),
                "corp_code": corp,
                "fs_div": self.fs_div,
                "years_back": self.years_back,
                "reprt_codes": self.reprt_codes,
                "http_status": 200,
                "result_count": len(fetched.get("results", [])),
            })
        store.log("opendart", "raw_saved", {"raw_ref": raw_ref, "sha256": chash[:16]})
        # 포인터만 캐시한다 — payload 를 복제하지 않아 append-only raw 가 유일 원본으로 남는다.
        cache.put(self.CACHE_NS, self.cache_key(covered_row),
                  {"raw_ref": raw_ref, "content_hash": chash, "retrieved_at": now_iso()})
        return self.normalize({"covered_row": covered_row, "fetched": fetched, "raw_ref": raw_ref})

    # ── corp_code 조회 ───────────────────────────────────────────────
    def resolve_corp(self, stock_codes: list[str]) -> dict:
        if not self.available:
            raise BlockedNoKey("키 필요")
        import io
        import xml.etree.ElementTree as ET
        import zipfile
        q = urllib.parse.urlencode({"crtfc_key": self.key})
        with urllib.request.urlopen(f"{self.base}/corpCode.xml?{q}", timeout=30) as r:
            zf = zipfile.ZipFile(io.BytesIO(r.read()))
        root = ET.fromstring(zf.read(zf.namelist()[0]))
        by_stock = {}
        for el in root.iter("list"):
            sc = (el.findtext("stock_code") or "").strip()
            if sc:
                by_stock[sc] = {"corp_code": el.findtext("corp_code"),
                                "corp_name": el.findtext("corp_name")}
        return {sc: by_stock.get(sc) for sc in stock_codes}


def _cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--resolve-corp", nargs="+")
    a = ap.parse_args()
    cfg = json.loads(CFG_PATH.read_text(encoding="utf-8"))
    prov = OpenDartProvider(cfg)

    if not prov.available:
        print("BLOCKED — OPENDART_API_KEY 없음.")
        print("  1) https://opendart.fss.or.kr 가입 → 인증키 발급(무료)")
        print("  2) data_sources/.env 에  OPENDART_API_KEY=발급키  추가  (data_sources/.env.example 참고)")
        print("  3) 재실행:  python -m data_sources.opendart.adapter --all")
        return

    if a.resolve_corp:
        for sc, v in prov.resolve_corp(a.resolve_corp).items():
            print(f"  {sc} -> {v}")
        return

    rows = [c for c in cfg["covered"] if c.get("market") == "KR"
            and (a.all or c.get("slug") == a.slug)]
    total = 0
    for cov in rows:
        try:
            recs = prov.collect(cov)
        except BlockedNoKey as e:
            print(f"{cov['slug']}: BLOCKED — {e}")
            continue
        n = store.append_normalized("opendart", recs)
        total += n
        by_m = {}
        for r in recs:
            by_m.setdefault(r.metric, set()).add(r.period)
        print(f"{cov['slug']}: {len(recs)} 레코드, 신규 {n}")
        for m, pers in sorted(by_m.items()):
            print(f"   {m:20} {sorted(pers)}")
    print(f"\n총 신규 {total} → data_sources/store/normalized/opendart.jsonl")


if __name__ == "__main__":
    _cli()
