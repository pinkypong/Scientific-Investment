# -*- coding: utf-8 -*-
"""Phase C 자동화 테스트 — 증분 동기화 / TTL / 캐시 / 보안 강화 / 대시보드 주입 준비.

실행:
  python -m data_sources.tests.test_phase_c      # 내장 러너
  pytest data_sources/tests/test_phase_c.py      # pytest 있으면

보안 원칙: 이 테스트는 .env 의 OPENDART_API_KEY 를 **읽어서 '없는지'만 검사**하고
절대 출력하지 않는다. 매칭 결과도 bool 로만 단언한다.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..common import store
from ..common.schema import NormalizedRecord
from .. import run_sync
from .. import build_dashboard_data as bdd

DS_ROOT = store.STORE_ROOT.parent            # data_sources/
SR = store.STORE_ROOT                        # data_sources/store/


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


def _rec(**kw) -> NormalizedRecord:
    base = dict(source="t", provider="opendart", metric="revenue", value=1.0,
                slug="samsung", period="FY1900", source_type="PRIMARY_OFFICIAL",
                original_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=x",
                accession="acc-phasec-unit",
                raw_ref="raw/opendart/unit.json#revenue|ifrs")
    base.update(kw)
    return NormalizedRecord(**base)


class _store_guard:
    """sync_state.json / source_health.json 을 스냅샷 후 복원 (테스트 idempotent)."""

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


def _counts() -> dict:
    n = {"_raw": sum(1 for _ in (SR / "raw").rglob("*.json"))}
    for sub in ("normalized", "derived"):
        for f in (SR / sub).glob("*.jsonl"):
            n[f"{sub}/{f.name}"] = sum(1 for _ in f.open(encoding="utf-8"))
    return n


ENUM_OK = {"HEALTHY", "WARNING", "ERROR", "NOT_CONFIGURED", "SKIPPED"}


# ── 1. 보안: .env key 가 산출물에 노출되지 않음 ──────────────────────────
def test_env_key_absent_from_all_artifacts():
    k = _env_key()
    if not k:
        print("SKIP test_env_key_absent_from_all_artifacts (.env 에 OPENDART_API_KEY 없음)")
        return
    blobs = []
    for p in (SR / "source_health.json", SR / "sync_state.json", SR / "sync.log"):
        if p.exists():
            blobs.append(p.read_text(encoding="utf-8", errors="ignore"))
    for p in (SR / "raw").rglob("*"):
        if p.is_file():
            blobs.append(p.read_text(encoding="utf-8", errors="ignore"))
    for p in DS_ROOT.rglob("README.md"):
        blobs.append(p.read_text(encoding="utf-8", errors="ignore"))
    proto = DS_ROOT / "prototypes" / "DS_hook_prototype.html"
    if proto.exists():
        blobs.append(proto.read_text(encoding="utf-8", errors="ignore"))
    blob = "\n".join(blobs)
    assert k not in blob, "API key 원문이 health/log/raw/README/prototype 에 노출됨"
    assert ("crtfc_key=" + k) not in blob, "crtfc_key=<key> 형태로 노출됨"


# ── 2. OpenDART raw metadata 보안 ──────────────────────────────────────
def test_opendart_raw_meta_has_no_crtfc_key():
    files = list((SR / "raw" / "opendart").glob("*.json"))
    if not files:
        print("SKIP test_opendart_raw_meta_has_no_crtfc_key (raw/opendart 비어있음)")
        return
    k = _env_key()
    allowed = {"endpoint", "ticker", "corp_code", "fs_div", "years_back", "reprt_codes",
               "http_status", "result_count", "retrieved_at", "content_hash", "provider",
               "request_url", "params"}
    for p in files:
        doc = json.loads(p.read_text(encoding="utf-8"))
        meta = doc.get("_meta", {})
        s = json.dumps(meta, ensure_ascii=False)
        assert "crtfc_key" not in s, f"{p.name}: _meta 에 crtfc_key"
        if k:
            assert k not in s, f"{p.name}: _meta 에 API key 원문"
        assert set(meta) <= allowed, f"{p.name}: 예상 밖 _meta 키 {set(meta) - allowed}"


def test_redact_meta_strips_secrets():
    dummy_key = "ABC123" + "def456"
    m = store._redact_meta({
        "endpoint": "example.invalid/api/x",
        "request_url": f"https://example.invalid/api/x.json?corp_code=1&crtfc_key={dummy_key}&bsns_year=2026",
        "crtfc_key": dummy_key,
        "params": {"crtfc_key": dummy_key, "corp_code": "00126380"},
        "reprt_codes": ["11011", "11014"],
    })
    s = json.dumps(m, ensure_ascii=False)
    assert dummy_key not in s, "redact 실패 — secret 잔존"
    assert "[REDACTED]" in s
    assert m["endpoint"] == "example.invalid/api/x"      # 비-secret 보존
    assert m["reprt_codes"] == ["11011", "11014"]


def test_save_raw_json_redacts_request_url_on_disk():
    """저장 경로(_DRY_RUN=False)에서도 _meta 의 crtfc_key 포함 URL 이 [REDACTED] 로 기록돼야 함."""
    p = SR / "raw" / "opendart" / "unit_redact_test.json"
    try:
        store.set_dry_run(False)
        store.save_raw_json(
            "opendart", "unit_redact_test", {"status": "000"},
            meta={"endpoint": "x",
                  "request_url": "https://example.invalid/api/x.json?crtfc_key=LEAKME999&y=1",
                  "crtfc_key": "LEAKME999"})
        s = json.dumps(json.loads(p.read_text(encoding="utf-8"))["_meta"], ensure_ascii=False)
        assert "LEAKME999" not in s, "raw _meta 에 secret 잔존"
        assert "[REDACTED]" in s
    finally:
        if p.exists():
            p.unlink()


def store_dry():
    class _c:
        def __enter__(self_):
            store.set_dry_run(True)

        def __exit__(self_, *a):
            store.set_dry_run(False)
            return False
    return _c()


# ── 3. --dry-run 은 파일을 늘리지 않는다 ───────────────────────────────
def test_dry_run_store_writes_are_noop():
    before = _counts()
    with store_dry():
        ref, chash = store.save_raw_json("opendart", "dryrun_should_not_exist",
                                         {"a": 1}, meta={"endpoint": "x"})
        n_new = store.append_normalized("opendart", [_rec(period="FY1899")])
        store.append_derived("actual_metrics", [_rec(is_derived=True, formula="a/b",
                             input_record_ids=["r1"], period="FY1899",
                             metric="revenue_yoy")])
        store.update_sync_state("opendart", last_successful_sync="2000-01-01T00:00:00+00:00")
        store.record_health("opendart", status="HEALTHY", detail="dryrun")
        store.log("opendart", "dryrun_event", {})
    after = _counts()
    assert before == after, f"dry-run 이 파일을 변경함: {before} → {after}"
    assert not (SR / "raw" / "opendart" / "dryrun_should_not_exist.json").exists()
    assert isinstance(n_new, int)          # 리포트용 '신규 건수'는 그대로 계산


def test_dry_run_sync_provider_no_growth():
    if not _env_key():
        print("SKIP test_dry_run_sync_provider_no_growth (키 없음 — NOT_CONFIGURED 경로)")
        return
    import data_sources.opendart.adapter as A

    def fake_collect(self, cov, **kw):
        return [NormalizedRecord(source="OpenDART", provider="opendart", metric="revenue",
                                 value=123.0, slug=cov.get("slug"), period="FY1901",
                                 source_type="PRIMARY_OFFICIAL", accession="dryrun-acc",
                                 original_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=x",
                                 raw_ref="raw/opendart/x.json#revenue|ifrs")]

    before = _counts()
    with _store_guard(), _patch(A.OpenDartProvider, "collect", fake_collect):
        res = run_sync.sync_provider("opendart", since="2026-06-01", until="2026-08-28",
                                     dry_run=True, force=True)
    after = _counts()
    assert res.get("dry_run") is True, res
    assert before == after, f"--dry-run sync 가 파일을 늘림: {before} → {after}"


# ── 4. TTL: fresh 면 외부 호출 없이 skip ───────────────────────────────
def test_ttl_fresh_skips_without_network():
    import data_sources.opendart.adapter as A
    hits = {"n": 0}

    def boom_fetch(self, **kw):
        hits["n"] += 1
        raise AssertionError("네트워크 호출됨 — TTL skip 이 안 먹음")

    def boom_collect(self, cov, **kw):
        hits["n"] += 1
        raise AssertionError("collect 호출됨 — TTL skip 이 안 먹음")

    with _store_guard(), \
         _patch(A.OpenDartProvider, "fetch_statements", boom_fetch), \
         _patch(A.OpenDartProvider, "collect", boom_collect):
        store.update_sync_state("opendart", last_successful_sync=store._now())  # 방금 성공
        res = run_sync.sync_provider("opendart", since="2026-06-01",
                                     until="2026-08-28", force=False)
    assert res.get("skipped") == "ttl_fresh", res
    assert hits["n"] == 0, "TTL fresh 인데 외부 호출이 일어남"
    assert "age_sec" in res and "ttl_sec" in res


def test_force_ignores_ttl():
    if not _env_key():
        print("SKIP test_force_ignores_ttl (키 없음)")
        return
    import data_sources.opendart.adapter as A
    hits = {"n": 0}

    def fake_collect(self, cov, **kw):
        hits["n"] += 1
        return []

    with _store_guard(), _patch(A.OpenDartProvider, "collect", fake_collect):
        store.update_sync_state("opendart", last_successful_sync=store._now())  # fresh
        res = run_sync.sync_provider("opendart", since="2026-06-01",
                                     until="2026-08-28", force=True)
    assert res.get("skipped") != "ttl_fresh", f"--force 인데 skip 됨: {res}"
    assert hits["n"] >= 1, "--force 인데 collect 가 안 불림"


def test_ttl_skip_is_not_a_failure():
    with _store_guard():
        store.update_sync_state("opendart", last_successful_sync=store._now())
        prev_ok = store.get_health().get("opendart", {}).get("last_successful_sync")
        run_sync.sync_provider("opendart", since="x", until="y", force=False)
        h = store.get_health().get("opendart", {})
    assert (h.get("status") or "").upper() in ENUM_OK
    if (h.get("status") or "").upper() == "SKIPPED":
        assert not h.get("last_error"), "SKIPPED 인데 last_error 세팅됨"
        # skip 은 성공시각을 앞당기지 않는다
        if prev_ok:
            assert h.get("last_successful_sync") == prev_ok


# ── 5. append-only dedup (중복 sync 가 카운트를 늘리지 않음) ────────────
def test_duplicate_append_is_deduped():
    existing = store.load_normalized("opendart")
    if not existing:
        print("SKIP test_duplicate_append_is_deduped (opendart store 비어있음)")
        return
    r = existing[0]
    cnt0 = len(store.load_normalized("opendart"))
    assert store.append_normalized("opendart", [r]) == 0, "이미 있는 레코드가 신규로 잡힘"
    assert store.append_normalized("opendart", [r, r]) == 0
    assert len(store.load_normalized("opendart")) == cnt0, "중복 append 로 normalized 가 늘어남"


# ── 6. source_health enum ─────────────────────────────────────────────
def test_source_health_status_enum():
    h = store.get_health()
    if not h:
        print("SKIP test_source_health_status_enum (health 비어있음)")
        return
    for prov, v in h.items():
        assert (v.get("status") or "").upper() in ENUM_OK, (prov, v.get("status"))
        for f in ("records_fetched", "new_records", "duplicates",
                  "validation_warnings", "response_ms"):
            assert f in v, f"{prov}: source_health 에 {f} 없음"


# ── 7. 대시보드 주입 블록: secret 미포함 + key 포함 request URL 미포함 ──
def test_generated_block_has_no_secret():
    import re
    blk = bdd._block()                         # _assert_no_secret 내장 (secret 있으면 SystemExit)
    assert "crtfc_key" not in blk
    k = _env_key()
    if k:
        assert k not in blk
    # secret 성 query param 이 붙은 URL 이 없어야 함 (공개 rcpNo= 등은 허용)
    assert not re.search(r"[?&](crtfc_key|api_key|apikey|serviceKey|token)=", blk, re.I)
    for tok in ("var DS=", "var ACTUAL=", "var SRC=", "var HEALTH="):
        assert tok in blk


def test_emit_block_writes_file_only(tmp_path=None):
    out = SR / "dashboard_snapshot" / "ds_block.js"
    dash = DS_ROOT.parent / "반도체_메모리_대시보드" / "index.html"
    before_html = dash.read_text(encoding="utf-8") if dash.exists() else None
    import sys
    argv = sys.argv
    sys.argv = ["build_dashboard_data", "--emit-block"]
    try:
        bdd.main()
    finally:
        sys.argv = argv
    assert out.exists(), "emit-block 파일이 생성되지 않음"
    txt = out.read_text(encoding="utf-8")
    assert txt.startswith("/* DS-DATA-START */") and "/* DS-DATA-END */" in txt
    assert "crtfc_key" not in txt
    if before_html is not None:
        assert dash.read_text(encoding="utf-8") == before_html, "index.html 이 수정됨 — 금지"
        assert "/* DS-DATA-START */" not in before_html


# ── 8. 프로토타입 HTML 보안 ───────────────────────────────────────────
def test_prototype_html_has_no_secret():
    proto = DS_ROOT / "prototypes" / "DS_hook_prototype.html"
    if not proto.exists():
        print("SKIP test_prototype_html_has_no_secret")
        return
    import re
    html = proto.read_text(encoding="utf-8", errors="ignore")
    assert "crtfc_key" not in html
    k = _env_key()
    if k:
        assert k not in html
    assert not re.search(r"opendart\.fss\.or\.kr/api/[^\s\"']*\?", html), \
        "prototype 에 OpenDART API request URL(query) 이 통째로 노출됨"


# ── 9. Phase B 회귀 (전부 통과 유지) ──────────────────────────────────
def test_phase_b_suite_still_green():
    from . import test_phase_b as tb
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ok = tb._run()
    tail = "\n".join(buf.getvalue().splitlines()[-3:])
    assert ok, f"Phase B 테스트가 깨짐:\n{tail}"


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
