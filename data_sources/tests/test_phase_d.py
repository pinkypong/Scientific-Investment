# -*- coding: utf-8 -*-
"""Phase D 자동화 테스트 — company-level raw cache / 재귀 redaction / no-network.

실행:
  python -m data_sources.tests.test_phase_d      # 내장 러너
  pytest data_sources/tests/test_phase_d.py      # pytest 있으면

보안 원칙: Phase C 와 동일하다. `.env` 의 API key 는 **없는지만** 검사하고 절대 출력하지
않는다. 매칭 결과는 bool 로만 단언하며, 실패 메시지에도 매칭 문자열을 넣지 않는다.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..common import cache, netguard, store
from ..common.schema import NormalizedRecord
from .. import run_sync
from .. import build_dashboard_data as bdd

DS_ROOT = store.STORE_ROOT.parent            # data_sources/
SR = store.STORE_ROOT                        # data_sources/store/
ROOT = DS_ROOT.parent                        # 프로젝트 루트
CFG = json.loads((DS_ROOT / "config" / "data_sources.json").read_text(encoding="utf-8"))

ENUM_OK = {"HEALTHY", "WARNING", "ERROR", "NOT_CONFIGURED", "SKIPPED"}


# ── helpers ─────────────────────────────────────────────────────────────
def _env_key() -> str | None:
    """.env 의 OPENDART_API_KEY 값 (없으면 None). 반환값은 절대 print 하지 않는다."""
    envp = DS_ROOT / ".env"
    if not envp.exists():
        return None
    for ln in envp.read_text(encoding="utf-8", errors="ignore").splitlines():
        ln = ln.strip()
        if ln.startswith("OPENDART_API_KEY=") and not ln.startswith("#"):
            v = ln.split("=", 1)[1].strip().strip('"').strip("'")
            return v or None
    return None


class _patch:
    """가벼운 monkeypatch (setattr 후 원복)."""

    def __init__(self, obj, name, value):
        self.obj, self.name, self.value = obj, name, value

    def __enter__(self):
        self._orig = getattr(self.obj, self.name)
        setattr(self.obj, self.name, self.value)
        return self

    def __exit__(self, *exc):
        setattr(self.obj, self.name, self._orig)
        return False


class _store_guard:
    """sync_state.json / source_health.json 스냅샷 후 복원 (테스트 idempotent)."""

    def __enter__(self):
        self._snap = {}
        for p in (store.SYNC_STATE, store.HEALTH):
            self._snap[p] = p.read_text(encoding="utf-8") if p.exists() else None
        return self

    def __exit__(self, *exc):
        for p, txt in self._snap.items():
            if txt is None:
                if p.exists():
                    p.unlink()
            else:
                p.write_text(txt, encoding="utf-8")
        return False


def _fingerprint() -> dict:
    """store 전체(파일별 sha256)의 지문. dry-run 불변 검증용."""
    out = {}
    for p in sorted(SR.rglob("*")):
        if p.is_file():
            out[p.relative_to(SR).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _cov(slug: str) -> dict:
    return next(c for c in CFG["covered"] if c["slug"] == slug)


def _boom(*_a, **_k):
    raise AssertionError("네트워크 호출이 발생했다 — cache hit 이면 나가면 안 된다")


def _sec_provider(ttl: int = 10 ** 9):
    from ..sec_edgar.adapter import SecEdgarProvider
    p = SecEdgarProvider(CFG)
    p.raw_cache_ttl = ttl
    return p


def _dart_provider(ttl: int = 10 ** 9):
    from ..opendart.adapter import OpenDartProvider
    p = OpenDartProvider(CFG)
    p.raw_cache_ttl = ttl
    return p


# ── 1. 재귀 redaction ─────────────────────────────────────────────────
def test_redact_is_fully_recursive():
    """dict / list / tuple / set 이 몇 겹으로 중첩돼도 secret 이 남지 않는다."""
    deep = {
        "lvl1": [
            {"lvl2": ({"token": "SENTINEL_A"}, ["x", {"password": "SENTINEL_B"}])},
            [[[{"authorization": "SENTINEL_C"}]]],
        ],
        "meta": {"inner": {"deeper": {"api_key": "SENTINEL_D"}}},
    }
    out = json.dumps(store.redact(deep), default=str)
    for name in ("SENTINEL_A", "SENTINEL_B", "SENTINEL_C", "SENTINEL_D"):
        assert name not in out, f"{name} 위치의 secret 이 재귀 redaction 을 통과하지 못함"
    assert out.count("[REDACTED]") == 4


def test_redact_preserves_container_types():
    out = store.redact({"t": (1, 2), "s": {1, 2}, "l": [1, 2]})
    assert isinstance(out["t"], tuple) and isinstance(out["s"], set) and isinstance(out["l"], list)


def test_redact_secret_query_param_only():
    """secret query param 만 [REDACTED], 비-secret param 은 원문 보존."""
    url = ("https://example.invalid/api/x.json"
           "?corp_code=00126380&bsns_year=2025&fs_div=CFS&token=SENTINEL_E")
    out = store.redact(url)
    assert "SENTINEL_E" not in out
    assert "token=[REDACTED]" in out
    for keep in ("corp_code=00126380", "bsns_year=2025", "fs_div=CFS"):
        assert keep in out, f"비-secret query param 이 사라짐: {keep.split('=')[0]}"


def test_redact_does_not_eat_lookalike_params():
    """monkey= / donkey= 처럼 'key' 를 포함하는 일반 파라미터는 건드리지 않는다."""
    out = store.redact("https://example.invalid/p?monkey=1&donkey=2&low_key=3")
    assert out == "https://example.invalid/p?monkey=1&donkey=2&low_key=3"


def test_redact_payload_untouched_for_business_fields():
    """원본 보존 원칙: business 필드는 무분별하게 지우지 않는다."""
    out = store.redact({"corp_code": "00126380", "result_count": 14, "value": 41456000000})
    assert out == {"corp_code": "00126380", "result_count": 14, "value": 41456000000}


# ── 2. cache key 에 secret 미포함 ────────────────────────────────────
def test_stable_key_excludes_secret_fields():
    """secret 계열 필드를 넣어도 키 계산에서 제외 → 같은 키가 나온다."""
    a = cache.stable_key("opendart", slug="samsung", corp_code="00126380")
    b = cache.stable_key("opendart", slug="samsung", corp_code="00126380",
                         crtfc_key="SENTINEL_F", api_key="SENTINEL_G")
    assert a == b, "secret 필드가 캐시 키를 바꿨다 — 키 계산에서 제외돼야 함"
    assert "SENTINEL_F" not in b and "SENTINEL_G" not in b


def test_stable_key_is_order_independent_and_deterministic():
    a = cache.stable_key("sec_edgar", slug="micron", metrics=["revenue", "cash"])
    b = cache.stable_key("sec_edgar", metrics=["revenue", "cash"], slug="micron")
    assert a == b and a == cache.stable_key("sec_edgar", slug="micron",
                                            metrics=["revenue", "cash"])


def test_provider_cache_keys_have_no_env_key():
    k = _env_key()
    keys = [_dart_provider().cache_key(_cov("samsung")),
            _sec_provider().cache_key(_cov("micron"))]
    for ck in keys:
        assert "crtfc" not in ck.lower()
        if k:
            assert k not in ck


def test_cache_files_contain_no_secret():
    """디스크에 남은 캐시 엔트리에 API key 원문이 없다."""
    k = _env_key()
    base = SR / "_cache"
    n = 0
    for f in base.rglob("*.json") if base.exists() else []:
        blob = f.read_text(encoding="utf-8", errors="ignore")
        assert "crtfc_key" not in blob
        if k:
            assert k not in blob
        n += 1
    assert n >= 0


# ── 3. company-level cache hit → 네트워크 호출 없음 ──────────────────
def test_opendart_cache_hit_makes_no_http_call():
    p = _dart_provider()
    with _patch(p, "_get", _boom):
        recs = p.collect(_cov("samsung"), no_network=True)
    assert p.last_cache_state == "hit", f"cache hit 이 아님: {p.last_cache_state}"
    assert recs, "cache hit 인데 normalized 재생성이 비었다"


def test_sec_cache_hit_makes_no_http_call():
    p = _sec_provider()
    with _patch(p, "_get_json", _boom):
        recs = p.collect(_cov("micron"), no_network=True)
    assert p.last_cache_state == "hit", f"cache hit 이 아님: {p.last_cache_state}"
    assert recs, "cache hit 인데 normalized 재생성이 비었다"


def test_cache_hit_regenerates_same_normalized_shape():
    """cache hit 로 만든 레코드가 정상 스키마 + provenance 를 갖춘다."""
    p = _sec_provider()
    with _patch(p, "_get_json", _boom):
        recs = p.collect(_cov("micron"), no_network=True)
    r = recs[0]
    assert isinstance(r, NormalizedRecord)
    assert r.provider == "sec_edgar" and r.slug == "micron"
    assert r.raw_ref and r.record_id and r.source_metric


def test_cache_miss_when_ttl_expired():
    """TTL 을 0 으로 주면 fresh 판정이 깨지고 miss 로 떨어진다(no-network 이면 blocked)."""
    p = _sec_provider(ttl=1)
    with _patch(p, "_get_json", _boom):
        recs = p.collect(_cov("micron"), no_network=True)
    assert p.last_cache_state == "blocked"
    assert recs == []


# ── 4. provider TTL skip 과 company cache hit 구분 ───────────────────
def test_ttl_skip_and_cache_hit_are_distinct():
    """provider-level TTL skip 은 collect 자체를 안 하고, cache hit 은 collect 안에서 일어난다."""
    with _store_guard():
        store.update_sync_state("sec_edgar", last_successful_sync=store._now())
        res_skip = run_sync.sync_provider("sec_edgar", since="2026-01-01", until="2026-12-31",
                                          dry_run=True, force=False, no_network=True)
        assert res_skip.get("skipped") == "ttl_fresh"
        assert "cache_hits" not in res_skip, "TTL skip 결과에 company cache 통계가 섞였다"

        res_hit = run_sync.sync_provider("sec_edgar", since="2026-01-01", until="2026-12-31",
                                         dry_run=True, force=True, no_network=True)
        assert res_hit.get("skipped") is None
        assert res_hit["cache_hits"] >= 1, res_hit
        assert res_hit["companies"] >= 1


# ── 5. no-network ────────────────────────────────────────────────────
def test_netguard_blocks_http_entrypoints():
    """가드는 규약이 아니라 강제 — 어댑터 HTTP 진입점에서 예외가 난다."""
    netguard.set_no_network(True)
    try:
        for p, call in ((_sec_provider(), lambda x: x._get_json("https://data.sec.gov/x")),
                        (_dart_provider(), lambda x: x._get("x.json", {}))):
            try:
                call(p)
                raise AssertionError("no-network 인데 호출이 통과했다")
            except netguard.NoNetworkError:
                pass
    finally:
        netguard.set_no_network(False)


def test_no_network_error_message_has_no_query():
    netguard.set_no_network(True)
    try:
        try:
            netguard.guard("opendart.fss.or.kr/api/fnlttSinglAcntAll.json")
        except netguard.NoNetworkError as e:
            assert "?" not in str(e), "no-network 예외 메시지에 query string 이 들어갔다"
    finally:
        netguard.set_no_network(False)


def test_no_network_cache_miss_is_blocked_not_fetched():
    """cache miss 인데 --no-network 면 외부 호출 없이 blocked 로 보고한다."""
    with _store_guard():
        p = _sec_provider(ttl=1)          # 강제 miss
        with _patch(p, "_get_json", _boom):
            recs = p.collect(_cov("micron"), no_network=True)
        assert recs == [] and p.last_cache_state == "blocked"


def test_no_network_flag_resets_after_run():
    with _store_guard():
        run_sync.sync_provider("sec_edgar", since="2026-01-01", until="2026-12-31",
                               dry_run=True, force=True, no_network=True)
    assert netguard.is_no_network() is False, "no-network 플래그가 런 이후에도 남아 있다"


def test_force_bypasses_cache_when_network_allowed():
    """--force 는 재수집이 목적 → 네트워크가 열려 있으면 cache 를 건너뛴다."""
    p = _sec_provider()
    called = {"n": 0}

    def _fake(*_a, **_k):
        called["n"] += 1
        raise RuntimeError("stop before real fetch")

    with _patch(p, "fetch_statements", _fake):
        try:
            p.collect(_cov("micron"), no_network=False, force=True)
        except RuntimeError:
            pass
    assert called["n"] == 1, "--force 인데 cache 로 단락됐다"
    assert p.last_cache_state == "miss"


# ── 6. dry-run + no-network = 완전 무해 ──────────────────────────────
def test_dry_run_no_network_changes_nothing():
    before = _fingerprint()
    for prov in ("sec_edgar", "opendart"):
        run_sync.sync_provider(prov, since="2026-01-01", until="2026-12-31",
                               dry_run=True, force=True, no_network=True)
    after = _fingerprint()
    changed = sorted(set(before) ^ set(after)) + \
              sorted(k for k in before.keys() & after.keys() if before[k] != after[k])
    assert not changed, f"dry-run --no-network 인데 store 파일이 변경됨: {changed[:5]}"


# ── 7. source_health cache stats ─────────────────────────────────────
def test_health_has_cache_stats_fields():
    h = store.get_health()
    assert h, "source_health.json 이 비어 있다"
    need = {"cache_hits", "cache_misses", "company_count",
            "skipped_companies", "no_network_blocked_count"}
    for prov, v in h.items():
        missing = need - set(v)
        assert not missing, f"{prov}: cache stats 누락 {sorted(missing)}"
        assert v["status"] in ENUM_OK, f"{prov}: enum 이탈 {v['status']}"


def test_health_last_error_carries_no_secret():
    k = _env_key()
    for prov, v in store.get_health().items():
        err = str(v.get("last_error") or "")
        assert "crtfc_key" not in err
        if k:
            assert k not in err


# ── 8. 산출물 secret 스캔 ────────────────────────────────────────────
def test_no_secret_in_generated_artifacts():
    """dashboard 주입 블록 / prototype / docs / README / log / health 전부."""
    k = _env_key()
    blobs = []
    for rel in ("prototypes/DS_hook_prototype.html", "README.md"):
        p = DS_ROOT / rel
        if p.exists():
            blobs.append((rel, p.read_text(encoding="utf-8", errors="ignore")))
    for p in (ROOT / "docs").rglob("*.md"):
        blobs.append((p.name, p.read_text(encoding="utf-8", errors="ignore")))
    for p in (SR / "source_health.json", SR / "sync.log", SR / "sync_state.json"):
        if p.exists():
            blobs.append((p.name, p.read_text(encoding="utf-8", errors="ignore")))
    blk = SR / "dashboard_snapshot" / "ds_block.js"
    if blk.exists():
        blobs.append((blk.name, blk.read_text(encoding="utf-8", errors="ignore")))

    hits = 0
    for name, text in blobs:
        if "crtfc_key" in text:
            hits += 1
        if k and k in text:
            hits += 1
    assert hits == 0, f"secret 패턴이 산출물 {hits}건에서 발견됨"


def test_dashboard_block_builds_and_is_clean():
    blk = bdd._block()          # 내부에서 _assert_no_secret 통과
    assert blk.startswith(bdd.START) and blk.rstrip().endswith(bdd.END)
    assert "var ACTUAL=" in blk and "var DS=" in blk


def test_main_dashboard_untouched():
    """Phase D 는 index.html 을 건드리지 않는다 (명시 승인 없음)."""
    for rel in (CFG["dashboard"]["html"], CFG["dashboard"]["web_deploy_html"]):
        p = (ROOT / rel.lstrip("./")).resolve()
        if not p.exists():
            continue
        assert "/* DS-DATA-START */" not in p.read_text(encoding="utf-8"), \
            f"{p.name} 에 주입 마커가 생겼다 — 승인 없이 수정됨"


# ── 9. Phase B/C 회귀 ────────────────────────────────────────────────
def test_phase_b_and_c_suites_still_green():
    import contextlib
    import io
    for mod in ("test_phase_b", "test_phase_c"):
        m = __import__(f"{__package__}.{mod}", fromlist=[mod])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = m._run()
        tail = "\n".join(buf.getvalue().splitlines()[-3:])
        assert ok, f"{mod} 가 깨짐:\n{tail}"


# ── 러너 ──────────────────────────────────────────────────────────────
def _run():
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    p = fl = 0
    for n, f in fns:
        try:
            f()
            p += 1
            print(f"  PASS {n}")
        except AssertionError as e:
            fl += 1
            print(f"  FAIL {n}: {e}")
        except Exception as e:  # noqa: BLE001
            fl += 1
            print(f"  ERROR {n}: {e!r}")
    print(f"\n{p} passed, {fl} failed / {len(fns)} total")
    return fl == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if _run() else 1)
