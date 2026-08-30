"""File-based TTL cache (스펙 §12, Phase D §1). Redis 도입하지 않음 — 현재 stack 으로 가장 단순하게.

정책 (config/data_sources.json 의 cache_ttl_sec 로 조정):
  market  : short      (기본 300s)
  reports : long        (기본 7d)
  static  : very_long   (기본 30d)
  raw_<provider> : company-level raw cache (TTL = providers.<p>.raw_cache_ttl_sec 또는 update_policy_sec)

Phase D:
- `stable_key()` — provider + company + 요청 파라미터로 결정적 캐시 키 생성.
  secret 계열 필드는 **키 계산 전에 제거**되므로 API key 가 키·파일명·파일 내용에 남지 않는다.
- 엔트리는 payload 를 복제하지 않고 `raw_ref`(append-only raw 파일 상대경로)를 가리키는
  포인터로 쓰는 것을 권장 — 원본 1벌 유지(§불변 규칙: 원본 덮어쓰기 금지).
- `store.is_dry_run()` 이면 `put()` 은 no-op (dry-run 은 어떤 외부 저장도 하지 않는다).
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from . import store

_ROOT = Path(__file__).resolve().parent.parent / "store" / "_cache"

DEFAULT_TTL = {"market": 300, "reports": 7 * 86400, "static": 30 * 86400}


def _key_path(namespace: str, key: str) -> Path:
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    return _ROOT / namespace / f"{h}.json"


# ── Phase D §1: 결정적 캐시 키 ─────────────────────────────────────────
def _strip_secrets(obj: Any) -> Any:
    """캐시 키 계산 전에 secret 계열 필드를 제거한다(재귀).

    store 의 secret 판정을 그대로 재사용하므로 판정 기준이 한 곳에만 존재한다."""
    if isinstance(obj, dict):
        return {k: _strip_secrets(v) for k, v in sorted(obj.items())
                if not store.is_secret_key(k)}
    if isinstance(obj, (list, tuple)):
        return [_strip_secrets(x) for x in obj]
    if isinstance(obj, set):
        return sorted(_strip_secrets(x) for x in obj)
    return obj


def stable_key(provider: str, **parts: Any) -> str:
    """provider + 요청 파라미터 → 결정적 키.  예:
        stable_key("opendart", slug="samsung", corp_code="00126380",
                   years_back=4, reprt_codes=[...], fs_div="CFS", as_of="2026-08-28")

    · dict/list 순서에 무관(sort_keys) → 같은 요청이면 항상 같은 키.
    · secret 계열 필드(api key 등)는 제거 후 해시 → 키에 자격증명이 섞이지 않는다.
    · 반환 문자열 자체가 파일명 해시의 입력이자 엔트리의 `key` 필드로 기록된다."""
    canon = json.dumps({"provider": provider, "parts": _strip_secrets(parts)},
                       ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{provider}:{hashlib.sha256(canon.encode('utf-8')).hexdigest()[:32]}"


# ── get / put ─────────────────────────────────────────────────────────
def get_entry(namespace: str, key: str, ttl_sec: int | None = None) -> dict | None:
    """만료 여부까지 판단해 엔트리 전체를 반환. 신선하지 않으면 None.
    반환: {"value":…, "stored_at":float, "age_sec":float, "ttl_sec":int}"""
    p = _key_path(namespace, key)
    if not p.exists():
        return None
    ttl = ttl_sec if ttl_sec is not None else DEFAULT_TTL.get(namespace, 300)
    try:
        blob = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    stored = float(blob.get("_stored_at", 0))
    age = time.time() - stored
    if ttl and age > ttl:
        return None
    return {"value": blob.get("value"), "stored_at": stored,
            "age_sec": age, "ttl_sec": ttl}


def get(namespace: str, key: str, ttl_sec: int | None = None) -> Any | None:
    e = get_entry(namespace, key, ttl_sec)
    return e["value"] if e else None


def put(namespace: str, key: str, value: Any, *, stored_at: float | None = None) -> bool:
    """dry-run 이면 기록하지 않고 False. 기록했으면 True.

    `stored_at` 은 **데이터를 실제로 받아온 시각**(epoch). 기존 raw 를 캐시로 승격할 때
    반드시 원본의 시각을 넘겨야 한다 — 지금 시각으로 쓰면 오래된 스냅샷의 TTL 시계가
    리셋돼서 영원히 신선해 보이는 버그가 된다.
    `value` 는 secret 을 담지 않아야 한다(raw_ref 포인터 권장) — 방어적으로 한 번 더 redact."""
    if store.is_dry_run():
        return False
    p = _key_path(namespace, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"_stored_at": float(stored_at if stored_at is not None else time.time()),
                    "key": key, "value": store.redact(value)}, ensure_ascii=False),
        encoding="utf-8",
    )
    return True


def raw_fallback(provider: str, prefix: str, slug: str, ttl_sec: int):
    """캐시 엔트리가 없을 때 append-only raw 에서 신선한 스냅샷을 찾아 승격한다.

    캐시 디렉터리를 지웠거나 Phase D 이전에 수집한 raw 만 있는 경우에도
    company-level cache 가 동작하도록 하는 경로다. 판단 근거는 raw 파일의 mtime.
    반환: (doc, raw_ref, age_sec) 또는 None.  doc = {"_meta":…, "data":…}
    """
    import time as _t
    d = store.RAW_DIR / provider
    if not d.exists():
        return None
    cands = sorted(d.glob(f"{prefix}_{slug}_*.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for f in cands:
        age = _t.time() - f.stat().st_mtime
        if ttl_sec and age > ttl_sec:
            continue
        rel = f.relative_to(store.STORE_ROOT).as_posix()
        doc = store.load_raw_json(rel)
        if doc and doc.get("data"):
            return doc, rel, age
    return None


def clear(namespace: str | None = None) -> int:
    base = _ROOT / namespace if namespace else _ROOT
    n = 0
    if base.exists():
        for f in base.rglob("*.json"):
            f.unlink()
            n += 1
    return n
