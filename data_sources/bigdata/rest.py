"""Bigdata.com REST **Quote** 클라이언트 (Phase E2 시장 데이터 SSOT).

이전 어댑터(`bigdata/adapter.py`)는 브라우저 MCP 전용이었다. 이 모듈은 서버/CI 에서
공식 REST 를 직접 부른다:

  POST https://api.bigdata.com/v1/quote/query
      body   {"identifier": {"type": "rp_entity_id", "value": "<rp_entity_id>"}}
      header X-API-KEY: <env BIGDATA_API_KEY>

Gate 검증 결과(2026-09-01, CONDITIONAL PASS)가 이 구현의 계약이다:
  · 응답 = {results:[1건], errors:[], metadata:{}}
  · 결과 객체에 price·market_cap·change·change_percentage·volume·currency·exchange·
    timestamp(+open/previous_close/day_high/low/year_high/low/price_avg_50/200) 존재
  · shares_outstanding 은 **없음** → null (market_cap/price 역산 금지)
  · timestamp 에 timezone 표기가 없다 → **원문 문자열 그대로** as_of_date 로 쓰고
    모든 레코드에 `timezone_unspecified` 경고를 단다 (사용자 결정 D1=a).

원칙:
  · 재시도 없음 · 병렬 없음 · 기업당 정확히 1회.
  · 키 값을 로그·예외·출력에 절대 노출하지 않는다(_scrub).
  · 이 모듈은 store 를 쓰지 않는다. 수집(스냅샷 적재)은 별도 workflow PR 에서.
  · `--no-network` 이면 HTTP 진입점에서 netguard 가 막는다.

CLI:
  python -m data_sources.bigdata.rest --check              # 라이브 4종목 + quota (유료 크레딧 소비, 저장 안 함)
  python -m data_sources.bigdata.rest --from-json resp.json --slug micron   # 오프라인 파싱(무해)
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..common import netguard
from ..common.classification import NumberType, SourceClass
from ..common.normalization import canon_currency, parse_num
from ..common.schema import NormalizedRecord, now_iso

HERE = Path(__file__).resolve().parent
DS_ROOT = HERE.parent
CFG_PATH = DS_ROOT / "config" / "data_sources.json"

SOURCE = "bigdata.com"
QUOTE_ENDPOINT = "https://api.bigdata.com/v1/quote/query"
QUOTA_ENDPOINT = "https://api.bigdata.com/v1/subscription/quotas"
API_KEY_ENV = "BIGDATA_API_KEY"
TIMEOUT_SEC = 25

TZ_UNSPECIFIED = "timezone_unspecified"

# 결과 객체에서 뽑을 필드 → (canonical metric, unit 종류)
#   unit 종류: "ccy"=종목 통화 · "pct"=% · "shares"=주식수 · "ratio"
QUOTE_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("price", "price", "ccy"),
    ("market_cap", "market_cap", "ccy"),
    ("change", "change", "ccy"),
    ("change_percentage", "change_percentage", "pct"),
    ("volume", "volume", "shares"),
    ("open", "open", "ccy"),
    ("previous_close", "previous_close", "ccy"),
    ("day_high", "day_high", "ccy"),
    ("day_low", "day_low", "ccy"),
    ("year_high", "year_high", "ccy"),
    ("year_low", "year_low", "ccy"),
    ("price_avg_50", "price_avg_50", "ccy"),
    ("price_avg_200", "price_avg_200", "ccy"),
)
TS_KEYS = ("timestamp", "as_of", "price_timestamp", "quote_time")


# ── 자격증명 ─────────────────────────────────────────────────────────────
def _load_dotenv() -> None:
    """data_sources/.env 를 os.environ 에 주입(이미 있으면 유지). CI 는 Secret 이 우선."""
    env = DS_ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _api_key() -> str:
    _load_dotenv()
    return os.environ.get(API_KEY_ENV, "")


def _scrub(text: Any, key: str) -> str:
    """로그/예외 문자열에서 API 키·bd_ 토큰 제거. 절대 노출 금지."""
    s = str(text)
    if key:
        s = s.replace(key, f"<{API_KEY_ENV}>")
    # 방어: bd_ 로 시작하는 토큰도 가린다
    import re as _re
    return _re.sub(r"\bbd_[A-Za-z0-9_]+", "<KEYLIKE>", s)


class BigdataQuoteError(RuntimeError):
    """HTTP/전송 오류. 메시지에 인증 헤더·응답 원문을 넣지 않는다."""


# ── config ──────────────────────────────────────────────────────────────
def load_covered(cfg: dict | None = None) -> list[dict]:
    if cfg is None:
        cfg = json.loads(CFG_PATH.read_text(encoding="utf-8"))
    return list(cfg.get("covered") or [])


def _market_of(entry: dict) -> str | None:
    return entry.get("market")


# ── 저수준 HTTP (재시도 없음) ───────────────────────────────────────────
def _post_json(url: str, body: dict, key: str) -> tuple[int | None, Any, str | None]:
    netguard.guard("bigdata quote")
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    req.add_header("X-API-KEY", key)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
            return resp.status, payload, None
    except urllib.error.HTTPError as e:            # 4xx/5xx — 재호출 안 함
        return e.code, None, f"HTTPError {e.code}"
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        return None, None, type(e).__name__


def _get_json(url: str, key: str) -> tuple[int | None, Any, str | None]:
    netguard.guard("bigdata quota")
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "application/json")
    req.add_header("X-API-KEY", key)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", "replace")), None
    except urllib.error.HTTPError as e:
        return e.code, None, f"HTTPError {e.code}"
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        return None, None, type(e).__name__


def _pick(dd: Any, *names: str) -> Any:
    """중첩 dict/list 에서 이름(대소문자 무시) 첫 히트."""
    if isinstance(dd, dict):
        low = {k.lower(): k for k in dd}
        for n in names:
            if n.lower() in low:
                return dd[low[n.lower()]]
        for v in dd.values():
            r = _pick(v, *names)
            if r is not None:
                return r
    elif isinstance(dd, list):
        for v in dd:
            r = _pick(v, *names)
            if r is not None:
                return r
    return None


def _result_row(payload: dict) -> tuple[Any, int]:
    """(결과 객체, results 건수)."""
    res = _pick(payload, "results")
    if isinstance(res, list):
        return (res[0] if res else None), len(res)
    if isinstance(res, dict):
        return res, 1
    return None, 0


def _tz_tag(ts: Any) -> str | None:
    """timestamp 문자열의 timezone 표기 유무. 값은 변환하지 않는다."""
    if not isinstance(ts, str) or not ts:
        return None
    import re as _re
    if _re.search(r"(Z|[+\-]\d{2}:?\d{2})$", ts):
        return "explicit_offset"
    return TZ_UNSPECIFIED


# ── 파싱 + 검증 (순수 함수, 네트워크 없음) ─────────────────────────────
@dataclass
class QuoteResult:
    slug: str | None
    entity_id: str
    http_status: int | None
    n_results: int
    errors_present: bool
    fields: dict = field(default_factory=dict)     # canonical metric -> float|None
    name: str | None = None
    target_identifier_id: str | None = None
    exchange: str | None = None
    currency: str | None = None
    timestamp_raw: Any = None                       # 원문 그대로 (as_of_date 후보)
    timestamp_tz: str | None = None                 # None | "explicit_offset" | "timezone_unspecified"
    retrieved_at: str = ""
    checks: list[tuple[str, bool]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(v for _, v in self.checks)

    @property
    def verdict(self) -> str:
        names = {n: v for n, v in self.checks}
        if not names.get("target_id_match", True) or not names.get("name_matches_company", True):
            return "MATCH_ERROR"
        if not self.ok:
            return "FAIL"
        if self.timestamp_tz == TZ_UNSPECIFIED:
            return "CONDITIONAL"      # 데이터는 유효, timezone 미상
        return "PASS"


def parse_quote(payload: dict, *, slug: str | None, entity_id: str,
                expected: dict | None = None, http_status: int | None = 200,
                retrieved_at: str | None = None) -> QuoteResult:
    """Quote 응답 payload → QuoteResult. expected = {target_identifier_id, currency, name_hints[]}."""
    exp = expected or {}
    row, n = _result_row(payload)
    row = row if isinstance(row, dict) else {}
    errs = _pick(payload, "errors")
    qr = QuoteResult(
        slug=slug, entity_id=entity_id, http_status=http_status, n_results=n,
        errors_present=bool(errs),
        retrieved_at=retrieved_at or now_iso(),
    )
    qr.name = _pick(row, "name", "company_name", "entity_name")
    qr.target_identifier_id = _pick(row, "target_identifier_id", "identifier_id", "ticker", "symbol")
    qr.exchange = _pick(row, "exchange", "exchange_name", "mic")
    qr.currency = canon_currency(_pick(row, "currency", "currency_code", "price_currency")) \
        or _pick(row, "currency", "currency_code", "price_currency")
    ts = None
    for k in TS_KEYS:
        ts = row.get(k) if isinstance(row, dict) else None
        if ts is not None:
            break
    qr.timestamp_raw = ts
    qr.timestamp_tz = _tz_tag(ts)

    for src_key, metric, _unit in QUOTE_FIELDS:
        qr.fields[metric] = parse_num(row.get(src_key)) if isinstance(row, dict) else None

    price = qr.fields.get("price")
    mcap = qr.fields.get("market_cap")
    name_hints = [h.lower() for h in (exp.get("name_hints") or [])]
    qr.checks = [
        ("http_200", http_status == 200),
        ("results_is_one", n == 1),
        ("entity_id_echo", str(_pick(row, "rp_entity_id", "entity_id") or "").upper() == entity_id.upper()),
        ("target_id_match", (exp.get("target_identifier_id") is None)
         or str(qr.target_identifier_id) == str(exp.get("target_identifier_id"))),
        ("name_matches_company", (not name_hints) or bool(qr.name)
         and any(h in str(qr.name).lower() for h in name_hints)),
        ("currency_match", (exp.get("currency") is None)
         or str(qr.currency).upper() == str(exp.get("currency")).upper()),
        ("price_positive", isinstance(price, (int, float)) and price > 0),
        ("market_cap_positive", isinstance(mcap, (int, float)) and mcap > 0),
        ("timestamp_present", ts is not None),
    ]

    # 경고 노트 — timezone 은 D1=a 결정에 따라 값이 있어도 **항상** 단다.
    if qr.timestamp_tz == TZ_UNSPECIFIED:
        qr.notes.append(TZ_UNSPECIFIED)
    elif ts is None:
        qr.notes.append("price_as_of_missing")
    for cn, cv in qr.checks:
        if not cv:
            qr.notes.append(f"check_failed:{cn}")
    if qr.errors_present:
        qr.notes.append("response_errors_present")
    return qr


def to_records(qr: QuoteResult, *, market: str | None = None) -> list[NormalizedRecord]:
    """QuoteResult → NormalizedRecord[] (metric 당 1건). store 에 쓰지는 않는다.

    as_of_date = timestamp 원문 문자열 그대로(변환 금지). retrieved_at 은 분리 보존.
    모든 레코드에 timezone_unspecified 경고를 남긴다(D1=a).
    """
    ccy = qr.currency
    recs: list[NormalizedRecord] = []
    base_notes = list(qr.notes)
    for src_key, metric, unit_kind in QUOTE_FIELDS:
        val = qr.fields.get(metric)
        unit = {"ccy": ccy, "pct": "%", "shares": "shares", "ratio": "ratio"}[unit_kind]
        status = "VALID"
        if not qr.ok:
            status = "WARNING"
        if qr.verdict == "MATCH_ERROR" or (metric in ("price", "market_cap") and not (
                isinstance(val, (int, float)) and val > 0)):
            status = "WARNING" if qr.verdict != "MATCH_ERROR" else "ERROR"
        recs.append(NormalizedRecord(
            source=SOURCE, provider="bigdata",
            source_type=SourceClass.MARKET_DATA, number_type=NumberType.FACT,
            document_type="market",
            ticker=qr.target_identifier_id, slug=qr.slug, company_name=qr.name,
            market=market, currency=ccy,
            metric=metric, value=val, unit=unit,
            source_metric=src_key,
            raw_value=qr.timestamp_raw if metric == "price" else None,
            as_of_date=qr.timestamp_raw,             # ← 원문 문자열 그대로 (timezone 변환 안 함)
            available_date=None,                     # 시장 이용가능 시점 불명 → 임의값 금지
            retrieved_at=qr.retrieved_at,
            original_url="https://bigdata.com",
            confidence=("High" if qr.ok else "Low"),
            verification=("Cross-Checked" if qr.ok else "Unverified"),
            validation_status=status,
            validation_notes=base_notes,
            missing=([] if qr.timestamp_raw is not None else ["price_as_of_missing"]),
        ))
    return recs


# ── 클라이언트 ─────────────────────────────────────────────────────────
class BigdataQuoteClient:
    """Quote REST 클라이언트. 재시도·병렬 없음."""

    def __init__(self, config: dict | None = None) -> None:
        self.config = config
        self.covered = load_covered(config)
        self._key = _api_key()

    @property
    def has_key(self) -> bool:
        return bool(self._key.strip())

    def _expected(self, slug: str) -> dict:
        e = next((c for c in self.covered if c.get("slug") == slug), {})
        hints = []
        nm = (e.get("name") or "").strip()
        # 영문 힌트만 사용(회사명 매칭용). 한글명은 응답과 안 맞음.
        EN = {"samsung": ["Samsung"], "skhynix": ["hynix"], "micron": ["Micron"],
              "sandisk": ["Sandisk", "SanDisk"]}
        hints = EN.get(slug, [nm] if nm.isascii() else [])
        return {
            "target_identifier_id": {"samsung": "005930.KS", "skhynix": "000660.KS",
                                     "micron": "MU", "sandisk": "SNDK"}.get(slug),
            "currency": e.get("currency"),
            "name_hints": hints,
            "entity_id": e.get("bigdata_entity_id"),
            "market": e.get("market"),
        }

    def fetch_quote(self, slug: str) -> QuoteResult:
        """기업 1곳 → QuoteResult. HTTP 1회, 재시도 없음."""
        if not self.has_key:
            raise BigdataQuoteError(f"{API_KEY_ENV} 없음 — data_sources/.env 또는 환경변수 설정 필요")
        exp = self._expected(slug)
        eid = exp["entity_id"]
        if not eid:
            raise BigdataQuoteError(f"covered 에 {slug} 의 bigdata_entity_id 없음 — 추측 금지")
        body = {"identifier": {"type": "rp_entity_id", "value": eid}}
        st, payload, err = _post_json(QUOTE_ENDPOINT, body, self._key)
        rt = now_iso()
        if err or payload is None:
            qr = QuoteResult(slug=slug, entity_id=eid, http_status=st, n_results=0,
                             errors_present=True, retrieved_at=rt)
            qr.checks = [("http_200", st == 200)]
            qr.notes = [f"transport_error:{_scrub(err, self._key)}"]
            return qr
        return parse_quote(payload, slug=slug, entity_id=eid, expected=exp,
                           http_status=st, retrieved_at=rt)

    def fetch_quota(self) -> dict:
        """usage/quota 조회 1회. 실패 시 {'error': ...}."""
        if not self.has_key:
            return {"error": f"{API_KEY_ENV} 없음"}
        st, payload, err = _get_json(QUOTA_ENDPOINT, self._key)
        if err or payload is None:
            return {"http": st, "error": _scrub(err, self._key)}
        return {
            "http": st,
            "subscription_type": _pick(payload, "subscription_type", "plan", "tier"),
            "limit": _pick(payload, "limit", "credit_limit", "quota", "total"),
            "used": _pick(payload, "used", "total_used", "consumed", "usage"),
            "remaining": _pick(payload, "remaining", "remaining_credits", "available"),
            "errors_present": bool(_pick(payload, "errors")),
            "unit": "credits" if _pick(payload, "subscription_type", "plan") == "credits" else None,
        }


# ── CLI ────────────────────────────────────────────────────────────────
_SLUGS = ("samsung", "skhynix", "micron", "sandisk")


def _print_result(qr: QuoteResult) -> None:
    f = qr.fields
    print(f"\n[{qr.slug}] {qr.verdict}   http={qr.http_status} results={qr.n_results}")
    print(f"  name={qr.name}  target_id={qr.target_identifier_id}  exchange={qr.exchange}  currency={qr.currency}")
    print(f"  price={f.get('price')}  market_cap={f.get('market_cap')}  "
          f"change={f.get('change')}  change_%={f.get('change_percentage')}  volume={f.get('volume')}")
    print(f"  quote_timestamp(raw)={qr.timestamp_raw!r}  tz={qr.timestamp_tz}")
    print(f"  retrieved_at={qr.retrieved_at}")
    print(f"  checks: " + ", ".join(f"{n}={'OK' if v else 'FAIL'}" for n, v in qr.checks))
    if qr.notes:
        print(f"  notes: {qr.notes}")


def _cmd_check() -> int:
    print("⚠  --check 는 라이브 REST 호출입니다 (유료 크레딧 소비). 저장은 하지 않습니다.")
    cli = BigdataQuoteClient()
    if not cli.has_key:
        print(f"BLOCKED: {API_KEY_ENV} 없음 (data_sources/.env 또는 환경변수)")
        return 1
    qb = cli.fetch_quota()
    print(f"\n=== quota BEFORE === {qb}")
    results = []
    for slug in _SLUGS:
        try:
            qr = cli.fetch_quote(slug)          # 기업당 1회, 재시도 없음
        except BigdataQuoteError as e:
            print(f"\n[{slug}] BLOCKED: {_scrub(e, '')}")
            continue
        results.append(qr)
        _print_result(qr)
    qa = cli.fetch_quota()
    print(f"\n=== quota AFTER === {qa}")
    for k in ("limit", "used", "remaining"):
        b, a = qb.get(k), qa.get(k)
        try:
            d = a - b
        except TypeError:
            d = "n/a"
        print(f"  {k}: {b} -> {a}  diff={d}")
    bad = [r.slug for r in results if r.verdict in ("FAIL", "MATCH_ERROR")]
    cond = [r.slug for r in results if r.verdict == "CONDITIONAL"]
    print(f"\n판정: {'FAIL ' + str(bad) if bad else ('CONDITIONAL ' + str(cond) if cond else 'PASS')}")
    print("(모든 레코드에 timezone_unspecified 경고가 붙습니다 — D1=a)")
    return 1 if bad else 0


def _cmd_from_json(path: str, slug: str | None) -> int:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cli = BigdataQuoteClient()
    exp = cli._expected(slug) if slug else {}
    qr = parse_quote(payload, slug=slug, entity_id=str(exp.get("entity_id") or ""),
                     expected=exp, http_status=200)
    _print_result(qr)
    recs = to_records(qr, market=exp.get("market"))
    print(f"\n→ NormalizedRecord {len(recs)}건 생성 (store 미기록)")
    print(f"  as_of_date(첫 레코드) = {recs[0].as_of_date!r}  (timestamp 원문 그대로)")
    print(f"  validation_notes = {recs[0].validation_notes}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Bigdata REST Quote 클라이언트 (Phase E2)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true",
                   help="라이브 4종목 + quota 조회 (유료, 저장 안 함)")
    g.add_argument("--from-json", metavar="PATH", help="저장된 Quote 응답 JSON 파싱(무해)")
    ap.add_argument("--slug", choices=_SLUGS, help="--from-json 과 함께 기대값 검증")
    a = ap.parse_args(argv)
    if a.check:
        return _cmd_check()
    return _cmd_from_json(a.from_json, a.slug)


if __name__ == "__main__":
    raise SystemExit(main())
