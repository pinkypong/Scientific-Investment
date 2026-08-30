"""Append-only snapshot store — 이 프로젝트의 "Database" (스펙 §17, §5).

- 원본을 덮어쓰지 않는다. 갱신 = 새 스냅샷 행 추가.
- RAW → NORMALIZED → DERIVED 를 분리 보관.
- sync_state.json (스펙 §10) · source_health.json (스펙 §19) · sync.log (스펙 §18).

레이아웃:
  data_sources/store/
    normalized/<provider>.jsonl      # NormalizedRecord append-only
    derived/<name>.jsonl
    raw/<provider>/<key>.{json,html,pdf}
    sync_state.json
    source_health.json
    sync.log
"""
from __future__ import annotations

import hashlib
import json
import re as _re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .schema import NormalizedRecord, dumps

STORE_ROOT = Path(__file__).resolve().parent.parent / "store"
NORM_DIR = STORE_ROOT / "normalized"
DERIVED_DIR = STORE_ROOT / "derived"
ARCHIVE_DIR = STORE_ROOT / "archive"          # 스펙 §12: report/forward/legacy 격리
RAW_DIR = STORE_ROOT / "raw"
SYNC_STATE = STORE_ROOT / "sync_state.json"
HEALTH = STORE_ROOT / "source_health.json"
LOG = STORE_ROOT / "sync.log"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── dry-run 가드 (Phase C §3: --dry-run 은 외부 저장을 하지 않는다) ─────
_DRY_RUN = False


def set_dry_run(value: bool) -> None:
    """True 이면 이 모듈의 모든 쓰기(save_raw*, append_*, sync_state, health, log)가 no-op.
    append_* 는 '기록 없이' 신규 건수만 계산해 반환하므로 dry-run 리포트는 그대로 나온다."""
    global _DRY_RUN
    _DRY_RUN = bool(value)


def is_dry_run() -> bool:
    return _DRY_RUN


# ── secret 방어 (Phase C §1·§2 → Phase D §4: 완전 재귀) ────────────
# 필드명이 이 집합에 들면 값을 통째로 [REDACTED]. 단독 "key" 는 일반 business 필드일
# 수 있어 제외 — query string 의 `key=` 만 _SECRET_QS_RE 로 처리한다.
_SECRET_META_KEYS = {"crtfc_key", "api_key", "apikey", "servicekey", "token",
                     "access_token", "authorization", "auth", "secret", "password"}
# query string 의 secret 파라미터만. 앞에 단어문자가 붙은 경우(monkey=1)는 제외.
_SECRET_QS_RE = _re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(crtfc_key|api_key|apikey|serviceKey|access_token|token|authorization|secret|password|key)"
    r"=[^&\s\"']+", _re.I)

_REDACTED = "[REDACTED]"


def is_secret_key(name) -> bool:
    """필드명이 secret 계열인가. cache.stable_key 도 이 판정을 재사용한다."""
    return str(name).lower() in _SECRET_META_KEYS


def _redact_qs(text):
    """query string 형태의 secret 파라미터 값만 [REDACTED] 로.
    비-secret 파라미터(corp_code, bsns_year …)는 그대로 보존한다."""
    if not isinstance(text, str):
        return text
    return _SECRET_QS_RE.sub(lambda m: f"{m.group(1)}={_REDACTED}", text)


def redact(value, *, _key=None, _depth: int = 0):
    """임의 깊이의 dict / list / tuple / set 을 재귀로 훑어 secret 을 제거한다.

    · 필드명이 secret 계열이면 값을 통째로 [REDACTED]
    · 문자열은 query string 의 secret 파라미터만 치환 (나머지 보존)
    · 컴퍼진 타입은 종류를 유지(tuple→tuple, set→set)
    payload 본문을 무분별하게 가공하지 않도록, 호출측은 _meta / log / health /
    cache entry 처럼 '원본 보존 의무가 없는' 값에만 쓴다."""
    if _depth > 20:                      # 순환/이상 깊이 방어
        return value
    if _key is not None and is_secret_key(_key):
        return _REDACTED
    if isinstance(value, dict):
        return {k: redact(v, _key=k, _depth=_depth + 1) for k, v in value.items()}
    if isinstance(value, tuple):
        return tuple(redact(v, _depth=_depth + 1) for v in value)
    if isinstance(value, set):
        return {redact(v, _depth=_depth + 1) for v in value}
    if isinstance(value, list):
        return [redact(v, _depth=_depth + 1) for v in value]
    if isinstance(value, str):
        return _redact_qs(value)
    return value


def _redact_meta(meta: dict) -> dict:
    """raw _meta 를 저장하기 전에 secret 키/URL 쿼리값을 제거한다(완전 재귀)."""
    return redact(dict(meta or {}))


def parse_dt(s: str | None):
    """ISO 문자열 → datetime (비교용). 실패/None → epoch. 스펙 §11: 문자열 길이 비교 금지."""
    if not s:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            return datetime.fromisoformat(s[:10]).replace(tzinfo=timezone.utc)
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)


def ensure() -> None:
    for d in (NORM_DIR, DERIVED_DIR, ARCHIVE_DIR, RAW_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ── RAW 보존 ───────────────────────────────────────────────────────────
def save_raw(provider: str, key: str, content: bytes | str, ext: str) -> str:
    if _DRY_RUN:
        return f"raw/{provider}/{key}.{ext}"
    ensure()
    d = RAW_DIR / provider
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{key}.{ext}"
    if isinstance(content, bytes):
        p.write_bytes(content)
    else:
        p.write_text(content, encoding="utf-8")
    return str(p.relative_to(STORE_ROOT))


def save_raw_json(provider: str, key: str, payload, *, meta: dict) -> tuple[str, str]:
    """스펙 §3: 실제 원본 payload + 요청 metadata 보존.
    파일 구조: {"_meta": {provider,endpoint,request_url,ticker,cik,retrieved_at,http_status,content_hash}, "data": <원본>}
    반환: (raw 상대경로, content_hash)
    """
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    chash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    meta = _redact_meta({**meta, "retrieved_at": meta.get("retrieved_at") or _now(),
                         "content_hash": chash, "provider": provider})
    if _DRY_RUN:
        return f"raw/{provider}/{key}.json", chash
    doc = json.dumps({"_meta": meta, "data": payload}, ensure_ascii=False, indent=1)
    rel = save_raw(provider, key, doc, "json")
    return rel, chash


def load_raw_json(rel_path: str) -> dict | None:
    """save_raw_json 이 남긴 raw 문서를 다시 읽는다 (Phase D §1: cache hit 시 재사용).

    rel_path 는 `raw/<provider>/<key>.json` 또는 `…#fragment` 형태(raw_ref) 둘 다 허용.
    반환: {"_meta":…, "data":…}  · 없거나 깨졌으면 None."""
    if not rel_path:
        return None
    rel = str(rel_path).split("#", 1)[0]
    p = STORE_ROOT / rel
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


# ── NORMALIZED append ─────────────────────────────────────────────────
def append_normalized(provider: str, records: Iterable[NormalizedRecord]) -> int:
    records = list(records)
    if not records:
        return 0
    existing = load_dedup_keys(provider)          # append-only dedup (Phase C §3)
    fresh = [r for r in records if r.dedup_key() not in existing]
    dupes = len(records) - len(fresh)
    if _DRY_RUN:                                   # 기록 없이 신규 건수만
        return len(fresh)
    ensure()
    if fresh:
        with (NORM_DIR / f"{provider}.jsonl").open("a", encoding="utf-8") as f:
            f.write(dumps(fresh) + "\n")
    log(provider, "append_normalized", {"new": len(fresh), "duplicates": dupes})
    return len(fresh)


def load_normalized(provider: str) -> list[NormalizedRecord]:
    p = NORM_DIR / f"{provider}.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(NormalizedRecord.from_json(json.loads(line)))
    return out


def load_all_normalized(exclude: tuple[str, ...] = ()) -> list[NormalizedRecord]:
    """normalized/*.jsonl 전체. exclude 에 든 파일 stem 은 건너뜀 (예: '_report_archive')."""
    out: list[NormalizedRecord] = []
    if NORM_DIR.exists():
        for p in sorted(NORM_DIR.glob("*.jsonl")):
            if p.stem in exclude:
                continue
            out.extend(load_normalized(p.stem))
    return out


def load_dedup_keys(provider: str) -> set[str]:
    return {r.dedup_key() for r in load_normalized(provider)}


def _recency_key(r: NormalizedRecord) -> tuple:
    """스펙 §11: 실제 datetime 비교. amended filing 우선(filing_date), 그다음 retrieved_at."""
    return (parse_dt(r.filing_date), parse_dt(r.retrieved_at))


def latest_by_metric(provider: str | None = None):
    """(slug|ticker, metric, period) → 최신 filing/retrieved 레코드. 이력 보존, 조회 편의만."""
    recs = load_normalized(provider) if provider else load_all_normalized()
    best: dict[tuple, NormalizedRecord] = {}
    for r in recs:
        key = (r.slug or r.ticker, r.metric, r.period)
        cur = best.get(key)
        if cur is None or _recency_key(r) >= _recency_key(cur):
            best[key] = r
    return best


# ── ARCHIVE (스펙 §12: report/forward/legacy 격리) ────────────────────
def append_archive(name: str, records: Iterable[NormalizedRecord]) -> int:
    ensure()
    records = list(records)
    if not records:
        return 0
    p = ARCHIVE_DIR / f"{name}.jsonl"
    existing = set()
    if p.exists():
        for ln in p.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                existing.add(NormalizedRecord.from_json(json.loads(ln)).dedup_key())
    fresh = [r for r in records if r.dedup_key() not in existing]
    if _DRY_RUN:
        return len(fresh)
    if fresh:
        with p.open("a", encoding="utf-8") as f:
            f.write(dumps(fresh) + "\n")
    log(name, "append_archive", {"new": len(fresh), "duplicates": len(records) - len(fresh)})
    return len(fresh)


def load_archive(name: str) -> list[NormalizedRecord]:
    p = ARCHIVE_DIR / f"{name}.jsonl"
    if not p.exists():
        return []
    return [NormalizedRecord.from_json(json.loads(ln))
            for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def history(slug_or_ticker: str, metric: str, period: str | None = None) -> list[NormalizedRecord]:
    """스펙 §5·§7: revision / time-series 조회."""
    out = []
    for r in load_all_normalized():
        if (r.slug == slug_or_ticker or r.ticker == slug_or_ticker) and r.metric == metric:
            if period is None or r.period == period:
                out.append(r)
    out.sort(key=lambda r: (r.as_of_date or r.published_at or r.retrieved_at or ""))
    return out


# ── DERIVED append ────────────────────────────────────────────────────
def append_derived(name: str, records: Iterable[NormalizedRecord]) -> int:
    ensure()
    records = list(records)
    if not records:
        return 0
    existing = load_derived_keys(name)
    fresh = [r for r in records if r.dedup_key() not in existing]
    if _DRY_RUN:
        return len(fresh)
    if fresh:
        with (DERIVED_DIR / f"{name}.jsonl").open("a", encoding="utf-8") as f:
            f.write(dumps(fresh) + "\n")
    log(name, "append_derived", {"new": len(fresh), "duplicates": len(records) - len(fresh)})
    return len(fresh)


def load_derived(name: str) -> list[NormalizedRecord]:
    p = DERIVED_DIR / f"{name}.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(NormalizedRecord.from_json(json.loads(line)))
    return out


def load_derived_keys(name: str) -> set[str]:
    return {r.dedup_key() for r in load_derived(name)}


# ── sync_state (스펙 §10) ─────────────────────────────────────────────
def get_sync_state() -> dict:
    if SYNC_STATE.exists():
        try:
            return json.loads(SYNC_STATE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def update_sync_state(provider: str, **fields) -> None:
    if _DRY_RUN:
        return
    ensure()
    st = get_sync_state()
    node = st.get(provider, {})
    node.update(fields)
    node["last_run_at"] = _now()
    st[provider] = node
    SYNC_STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


# ── source_health (스펙 §19) ─────────────────────────────────────────
def record_health(provider: str, *, status: str, detail: str = "",
                  request_count: int = 0, failures: int = 0,
                  new_records: int = 0, response_ms: int | None = None,
                  records_fetched: int = 0, records_updated: int = 0,
                  duplicates: int = 0, validation_warnings: int = 0,
                  cache_hits: int = 0, cache_misses: int = 0,
                  company_count: int = 0, skipped_companies: int = 0,
                  no_network_blocked_count: int = 0,
                  last_error: str | None = None, succeeded: bool | None = None) -> None:
    """Phase C §5. status ∈ {HEALTHY, WARNING, ERROR, NOT_CONFIGURED, SKIPPED}.
    SKIPPED(=TTL fresh)는 실패로 간주하지 않으며 last_successful_sync 를 갱신하지 않는다."""
    if _DRY_RUN:
        return
    ensure()
    data = get_health()
    prev = data.get(provider, {})
    now = _now()
    su = (status or "").upper()
    ok = succeeded if succeeded is not None else (su in ("HEALTHY", "WARNING", "SKIPPED"))
    # SKIPPED 은 '정상이지만 이번엔 안 돌았다' → 이전 성공시각을 그대로 보존
    last_ok = prev.get("last_successful_sync") if su == "SKIPPED" else (
        now if ok else prev.get("last_successful_sync"))
    data[provider] = {
        "provider": provider,
        "status": status,
        "detail": detail,
        "last_attempted_sync": now,
        "last_successful_sync": last_ok,
        "last_error": (redact(last_error) if last_error and not ok else None),
        "last_sync": now,  # 하위호환
        "request_count": request_count,
        "failures": failures,
        "records_fetched": records_fetched,
        "records_added": new_records,
        "new_records": new_records,  # 하위호환
        "records_updated": records_updated,
        "duplicates": duplicates,
        "validation_warnings": validation_warnings,
        "response_time_ms": response_ms,
        "response_ms": response_ms,  # 하위호환
        # Phase D §6: company-level cache 통계. status enum 은 그대로 두고 stats 로만 표현.
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "company_count": company_count,
        "skipped_companies": skipped_companies,
        "no_network_blocked_count": no_network_blocked_count,
    }
    HEALTH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def get_health() -> dict:
    if HEALTH.exists():
        try:
            return json.loads(HEALTH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


# ── log (스펙 §18) ───────────────────────────────────────────────────
def log(provider: str, event: str, payload: dict | None = None) -> None:
    if _DRY_RUN:
        return
    ensure()
    line = json.dumps(
        {"ts": _now(), "provider": provider, "event": event,
         "payload": redact(payload or {})},          # Phase D §4: 로그에도 secret 미포함
        ensure_ascii=False,
    )
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
