# -*- coding: utf-8 -*-
"""Phase B 자동화 테스트 (스펙 §15).

실행:
  python -m data_sources.tests.test_phase_b          # 내장 러너
  pytest data_sources/tests/test_phase_b.py          # pytest 있으면

fixture 테스트(합성 레코드)와 live-store 테스트(실제 sync 결과 읽기)를 구분한다.
live 테스트는 store 에 sec_edgar 레코드가 있을 때만 의미 있음 → 없으면 SKIP.
"""
from __future__ import annotations

import json
from datetime import timezone

from ..common import store
from ..common.classification import priority
from ..common.schema import NormalizedRecord
from ..common.store import parse_dt
from ..common.validation import validate_record

SEC = "PRIMARY_OFFICIAL"


def _rec(**kw) -> NormalizedRecord:
    base = dict(source="t", provider="t", metric="revenue", value=1.0,
                slug="x", period="FY2025", source_type=SEC,
                original_url="https://sec.gov/x-index.htm", accession="acc-1",
                raw_ref="raw/sec_edgar/x.json#revenue|Revenues")
    base.update(kw)
    return NormalizedRecord(**base)


# ── fixture ──────────────────────────────────────────────────────────────
def test_schema_roundtrip():
    r = _rec(filing_date="2026-01-02", available_date="2026-01-02")
    d = r.to_json()
    r2 = NormalizedRecord.from_json(json.loads(json.dumps(d)))
    assert r2.dedup_key() == r.dedup_key()
    assert r2.available_date == "2026-01-02"
    assert r2.raw_ref == r.raw_ref


def test_dedup_idempotency():
    a = _rec(record_id="rec_a")
    b = _rec(record_id="rec_b")   # record_id 만 다름 → 같은 논리적 fact
    assert a.dedup_key() == b.dedup_key()
    c = _rec(accession="acc-2")   # amended filing → 다른 fact
    assert c.dedup_key() != a.dedup_key()


def test_provider_priority_official_over_bigdata():
    assert priority("PRIMARY_OFFICIAL") < priority("MARKET_DATA")
    assert priority("PRIMARY_OFFICIAL") < priority("SECONDARY_PROFESSIONAL")
    assert priority("SECONDARY_PROFESSIONAL") < priority("AI_DERIVED") or \
           priority("PRIMARY_OFFICIAL") < priority("AI_DERIVED")


def test_latest_filing_selected_by_datetime_not_strlen():
    old = _rec(accession="a-old", filing_date="2024-10-01",
               retrieved_at="2026-01-01T00:00:00Z")            # 짧은 형식
    new = _rec(accession="a-new", filing_date="2025-10-01",
               retrieved_at="2026-01-01T00:00:00.123456+00:00")  # 긴 형식(문자열 길이 함정)
    chosen = sorted([old, new], key=lambda r: (
        priority(r.source_type or "NEWS"),
        -parse_dt(r.filing_date).timestamp(),
        -parse_dt(r.retrieved_at).timestamp(),
    ))[0]
    assert chosen is new, "최신 filing_date 가 선택돼야 함 (문자열 길이 아님)"


def test_parse_dt_orders_mixed_formats():
    assert parse_dt("2026-01-01T00:00:00Z") < parse_dt("2026-06-01T00:00:00+00:00")
    assert parse_dt(None) < parse_dt("2000-01-01")


def test_validation_null_negative_derived():
    assert validate_record(_rec(value=None))[0] == "INSUFFICIENT_DATA"
    assert validate_record(_rec(value=float("nan")))[0] == "ERROR"
    assert validate_record(_rec(metric="revenue", value=-5.0))[0] == "ERROR"
    # derived 인데 formula 없음 → ERROR
    bad = _rec(is_derived=True, formula=None, input_record_ids=[])
    assert validate_record(bad)[0] == "ERROR"
    good = _rec(is_derived=True, formula="a/b-1", input_record_ids=["rec_1", "rec_2"],
                source_type="DERIVED")
    assert validate_record(good)[0] == "VALID"


def test_validation_missing_provenance():
    r = _rec(original_url=None, accession=None)
    st, notes = validate_record(r)
    assert st == "WARNING" and any("provenance" in n for n in notes)
    r2 = _rec(raw_ref=None)
    st2, notes2 = validate_record(r2)
    assert st2 == "WARNING" and any("raw_ref" in n for n in notes2)


def test_extreme_change_is_warning_not_deleted():
    st, notes = validate_record(_rec(value=100.0), prev_value=1.0)
    assert st == "WARNING" and any("극단" in n for n in notes)


# ── live store ───────────────────────────────────────────────────────────
def _sec_recs():
    return store.load_normalized("sec_edgar")


def _dart_recs():
    return store.load_normalized("opendart")


def test_live_sec_records_exist():
    recs = _sec_recs()
    if not recs:
        print("SKIP test_live_sec_records_exist (sec_edgar 스토어 비어있음)")
        return
    assert len(recs) > 100
    slugs = {r.slug for r in recs}
    assert {"micron", "sandisk"} <= slugs


def test_live_provenance_complete():
    recs = _sec_recs()
    if not recs:
        print("SKIP test_live_provenance_complete"); return
    for r in recs[:500]:
        assert r.original_url and "-index.htm" in r.original_url, r.original_url
        assert r.accession, r.record_id
        assert r.raw_ref and "raw" in r.raw_ref and "#" in r.raw_ref
        assert r.filing_date and r.available_date == r.filing_date
        # raw 파일 실존 + 스텁 아님
        raw_path = store.STORE_ROOT / r.raw_ref.split("#")[0]
        assert raw_path.exists(), raw_path
    raw_path = store.STORE_ROOT / recs[0].raw_ref.split("#")[0]
    doc = json.loads(raw_path.read_text(encoding="utf-8"))
    assert "_meta" in doc and doc["_meta"].get("content_hash")
    assert doc["data"] and "..." not in json.dumps(doc["data"])[:200]


def test_live_opendart_records_exist():
    recs = _dart_recs()
    assert recs, "opendart store empty - samsung/skhynix actual filings required"
    assert len(recs) > 20
    slugs = {r.slug for r in recs}
    assert {"samsung", "skhynix"} <= slugs
    for slug in ("samsung", "skhynix"):
        assert len({r.metric for r in recs if r.slug == slug}) >= 6, slug


def test_live_opendart_provenance_complete():
    recs = _dart_recs()
    assert recs, "opendart store empty"
    for r in recs[:200]:
        assert r.original_url and "dart.fss.or.kr" in r.original_url, r.original_url
        assert r.accession, r.record_id
        assert r.raw_ref and "raw" in r.raw_ref and "#" in r.raw_ref
        assert r.filing_date and r.available_date == r.filing_date
        assert r.as_of_date and r.as_of_date != r.retrieved_at[:10]
        raw_path = store.STORE_ROOT / r.raw_ref.split("#")[0]
        assert raw_path.exists(), raw_path
    raw_path = store.STORE_ROOT / recs[0].raw_ref.split("#")[0]
    doc = json.loads(raw_path.read_text(encoding="utf-8"))
    assert "_meta" in doc and doc["_meta"].get("content_hash")
    assert doc["data"] and doc["data"].get("results")


def test_live_derived_has_formula_and_inputs():
    d = store.load_derived("actual_metrics")
    if not d:
        print("SKIP test_live_derived_has_formula_and_inputs"); return
    for r in d:
        assert r.is_derived and r.formula and r.input_record_ids
        assert r.calculated_at


def test_live_forward_report_excluded_from_ds_core():
    """target_price / forward eps / optimism_check 는 actual DS core 에 없어야 함."""
    from ..build_dashboard_data import build_ds, build_actual
    ds, actual = build_ds(), build_actual()
    banned = {"tp", "eps27", "eps28", "eps26", "optcheck", "cyclepe"}
    for slug, node in ds.items():
        assert not (banned & set(node)), f"{slug}: {banned & set(node)}"
    # legacy 파생은 있어도 core_eligible=False
    for slug, node in ds.items():
        for k in ("fv", "expret", "pup", "pe"):
            if k in node:
                assert node[k].get("core_eligible") is False
    # ACTUAL 레이어엔 estimate metric 없음
    for slug, groups in actual.items():
        flat = {m for g in groups.values() for m in g}
        assert not ({"eps", "target_price", "fwd_pe"} & flat)


def test_live_archive_excluded_from_normalized_load():
    alln = store.load_all_normalized()
    assert not any(r.metric == "target_price" for r in alln), \
        "target_price 가 normalized load 에 새어들어옴 (archive 격리 실패)"
    arch = store.load_archive("report")
    if arch:
        assert any(r.metric in ("target_price", "optimism_check", "eps") for r in arch)


def test_live_build_check_runs():
    from ..build_dashboard_data import _block
    b = _block()
    assert b.startswith("/* DS-DATA-START */") and b.rstrip().endswith("/* DS-DATA-END */")
    for tok in ("var DS=", "var ACTUAL=", "var HEALTH=", "var SRC="):
        assert tok in b


def test_live_health_not_empty_and_enum():
    h = store.get_health()
    if not h:
        print("SKIP test_live_health_not_empty_and_enum"); return
    ok = {"HEALTHY", "WARNING", "ERROR", "NOT_CONFIGURED", "SKIPPED",
          "Healthy", "Warning", "Error"}  # Phase C: SKIPPED(TTL fresh) 추가
    for prov, v in h.items():
        assert v.get("status") in ok, (prov, v.get("status"))
        assert "last_attempted_sync" in v or "last_sync" in v


def test_live_dashboard_html_untouched():
    p = store.STORE_ROOT.parent.parent / "반도체_메모리_대시보드" / "index.html"
    if p.exists():
        assert "/* DS-DATA-START */" not in p.read_text(encoding="utf-8"), \
            "index.html 에 DS 블록이 주입됨 — Phase B 는 index.html 미수정이어야 함"


# ── 러너 ────────────────────────────────────────────────────────────────
def _run():
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    p = fl = 0
    for n, f in fns:
        try:
            f(); p += 1; print(f"  PASS {n}")
        except AssertionError as e:
            fl += 1; print(f"  FAIL {n}: {e}")
        except Exception as e:  # noqa: BLE001
            fl += 1; print(f"  ERROR {n}: {e!r}")
    print(f"\n{p} passed, {fl} failed / {len(fns)} total")
    return fl == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if _run() else 1)
