# -*- coding: utf-8 -*-
"""Phase E2 자동화 테스트 — Bigdata REST Quote 클라이언트(`bigdata/rest.py`).

실행:
  python -m data_sources.tests.test_phase_e2     # 내장 러너
  pytest data_sources/tests/test_phase_e2.py     # pytest 있으면

원칙:
  · **오프라인**. 라이브 REST 를 부르지 않는다 — 인라인 fixture 로 파서/정규화/검증만 본다.
  · `.env` 값은 **없는지만** 검사하고 절대 print 하지 않는다.
  · 이 스위트는 store/ · index.html 을 건드리지 않는다.
  · 사용자 결정 D1=a: Quote timestamp 는 원문 문자열 그대로 as_of_date 로 쓰고
    모든 레코드에 timezone_unspecified 경고를 단다 — 그 성질을 여기서 고정한다.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from ..common import netguard, store
from ..bigdata import rest

DS_ROOT = store.STORE_ROOT.parent
SR = store.STORE_ROOT
ROOT = DS_ROOT.parent
CFG = json.loads((DS_ROOT / "config" / "data_sources.json").read_text(encoding="utf-8"))

FORWARD_METRICS = {
    "pe_forward", "eps_forward", "eps_fwd", "pe_fwd", "ebitda_fwd", "peg",
    "exp_growth_5y", "target_price", "target_price_upside", "rating", "eps",
}


# ── fixtures ────────────────────────────────────────────────────────────
def _row(**over):
    r = {
        "rp_entity_id": "49BBBC",
        "target_identifier_id": "MU",
        "name": "Micron Technology, Inc.",
        "price": 955.53,
        "market_cap": 1079165913761,
        "change": -3.2,
        "change_percentage": -0.334,
        "volume": 10315438,
        "exchange": "NASDAQ",
        "currency": "USD",
        "timestamp": "2026-09-01T15:27:23",
        "open": 958.0, "previous_close": 958.73,
        "day_high": 961.1, "day_low": 949.4,
        "year_high": 1200.0, "year_low": 410.2,
        "price_avg_50": 900.1, "price_avg_200": 720.5,
    }
    r.update(over)
    return r


def _payload(**over):
    return {"results": [_row(**over)], "errors": [], "metadata": {}}


def _parse(slug="micron", **over):
    exp = rest.BigdataQuoteClient(CFG)._expected(slug)
    return rest.parse_quote(_payload(**over), slug=slug, entity_id=exp["entity_id"],
                            expected=exp, http_status=200)


def _env_values() -> list[str]:
    envp = DS_ROOT / ".env"
    if not envp.exists():
        return []
    out = []
    for ln in envp.read_text(encoding="utf-8", errors="ignore").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            v = ln.split("=", 1)[1].strip().strip('"').strip("'")
            if len(v) >= 8:
                out.append(v)
    return out


def _fingerprint() -> dict:
    out = {}
    for p in sorted(SR.rglob("*")):
        if p.is_file():
            out["store/" + p.relative_to(SR).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    for rel in (CFG["dashboard"]["html"], CFG["dashboard"]["web_deploy_html"]):
        p = (ROOT / rel.lstrip("./")).resolve()
        if p.exists():
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", *args], cwd=str(ROOT), env=env,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120)


# ── 1. 파싱 / 정규화 ───────────────────────────────────────────────────
def test_parse_quote_extracts_core_fields():
    qr = _parse()
    assert qr.n_results == 1 and not qr.errors_present
    assert qr.fields["price"] == 955.53
    assert qr.fields["market_cap"] == 1079165913761
    assert qr.currency == "USD" and qr.exchange == "NASDAQ"
    assert qr.target_identifier_id == "MU"
    for extra in ("open", "previous_close", "day_high", "year_low", "price_avg_200"):
        assert qr.fields[extra] is not None, f"{extra} 누락"


def test_quote_timestamp_preserved_verbatim_no_tz_conversion():
    qr = _parse()
    assert qr.timestamp_raw == "2026-09-01T15:27:23"
    assert qr.timestamp_tz == rest.TZ_UNSPECIFIED
    recs = rest.to_records(qr, market="US")
    for r in recs:
        assert r.as_of_date == "2026-09-01T15:27:23", "as_of_date 가 원문과 다르다(변환됨)"
        assert r.retrieved_at and r.retrieved_at != r.as_of_date, "retrieved_at 과 as_of_date 가 분리돼야 한다"


def test_all_records_carry_timezone_unspecified_note():
    recs = rest.to_records(_parse(), market="US")
    assert recs, "레코드가 비었다"
    for r in recs:
        assert rest.TZ_UNSPECIFIED in r.validation_notes, f"{r.metric}: timezone_unspecified 경고 누락"


def test_explicit_offset_timestamp_not_warned():
    qr = _parse(timestamp="2026-09-01T15:27:23+00:00")
    assert qr.timestamp_tz == "explicit_offset"
    recs = rest.to_records(qr, market="US")
    assert all(rest.TZ_UNSPECIFIED not in r.validation_notes for r in recs)


# ── 2. shares / forward 금지 ───────────────────────────────────────────
def test_shares_outstanding_never_produced():
    recs = rest.to_records(_parse(market_cap=1e12, price=1000.0), market="US")
    metrics = {r.metric for r in recs}
    assert "shares_outstanding" not in metrics
    assert "book_value" not in metrics


def test_no_forward_or_consensus_metrics():
    recs = rest.to_records(_parse(), market="US")
    metrics = {r.metric for r in recs}
    assert not (metrics & FORWARD_METRICS), f"forward/consensus metric 유입: {metrics & FORWARD_METRICS}"


def test_records_are_market_data_fact():
    for r in rest.to_records(_parse(), market="US"):
        assert r.source_type == "MARKET_DATA"
        assert r.number_type == "FACT"
        assert r.provider == "bigdata"
        assert r.original_url == "https://bigdata.com"


# ── 3. 검증 규칙 ───────────────────────────────────────────────────────
def test_currency_mismatch_flagged():
    qr = _parse("samsung", currency="USD", rp_entity_id="B811D5",
                target_identifier_id="005930.KS", name="Samsung Electronics Co., Ltd.")
    d = {n: v for n, v in qr.checks}
    assert d["currency_match"] is False
    assert qr.verdict in ("FAIL", "MATCH_ERROR")


def test_match_error_on_wrong_company_name():
    qr = _parse(name="Tesla, Inc.", target_identifier_id="MU")
    assert qr.verdict == "MATCH_ERROR"


def test_target_id_mismatch_is_match_error():
    qr = _parse(target_identifier_id="AAPL")
    assert qr.verdict == "MATCH_ERROR"


def test_missing_timestamp_fails_and_price_as_of_null():
    row = _row()
    row.pop("timestamp")
    qr = rest.parse_quote({"results": [row], "errors": [], "metadata": {}},
                          slug="micron", entity_id="49BBBC",
                          expected=rest.BigdataQuoteClient(CFG)._expected("micron"))
    d = {n: v for n, v in qr.checks}
    assert d["timestamp_present"] is False
    assert qr.verdict == "FAIL"
    recs = rest.to_records(qr, market="US")
    assert all(r.as_of_date is None for r in recs)
    assert all("price_as_of_missing" in r.missing for r in recs)


def test_results_not_one_flagged():
    qr = rest.parse_quote({"results": [], "errors": [], "metadata": {}},
                          slug="micron", entity_id="49BBBC",
                          expected=rest.BigdataQuoteClient(CFG)._expected("micron"))
    d = {n: v for n, v in qr.checks}
    assert d["results_is_one"] is False


def test_non_positive_price_and_mcap_flagged():
    qr = _parse(price=0, market_cap=-5)
    d = {n: v for n, v in qr.checks}
    assert d["price_positive"] is False and d["market_cap_positive"] is False
    recs = rest.to_records(qr, market="US")
    pr = next(r for r in recs if r.metric == "price")
    assert pr.validation_status in ("WARNING", "ERROR")
    assert pr.value == 0            # 0 을 None 으로 바꾸지 않고, 상태로만 표시


def test_response_errors_present_noted():
    qr = rest.parse_quote({"results": [_row()], "errors": [{"code": "X"}], "metadata": {}},
                          slug="micron", entity_id="49BBBC",
                          expected=rest.BigdataQuoteClient(CFG)._expected("micron"))
    assert qr.errors_present and "response_errors_present" in qr.notes


def test_happy_path_verdict_is_conditional_due_to_tz():
    """모든 검증 통과 + timestamp 에 tz 없음 → CONDITIONAL (데이터는 유효)."""
    assert _parse().verdict == "CONDITIONAL"
    assert _parse(timestamp="2026-09-01T06:30:00Z").verdict == "PASS"


# ── 4. 보안 / 읽기 전용 ───────────────────────────────────────────────
def test_rest_module_source_has_no_key_material():
    src = (DS_ROOT / "bigdata" / "rest.py").read_text(encoding="utf-8")
    import re
    assert not re.search(r"\bbd_[A-Za-z0-9]{6,}", src), "rest.py 에 키 비슷한 토큰"
    for v in _env_values():
        assert v not in src, "rest.py 에 .env 값이 하드코딩됨"


def test_records_json_has_no_env_values():
    recs = rest.to_records(_parse(), market="US")
    blob = json.dumps([r.to_json() for r in recs], ensure_ascii=False, default=str)
    for v in _env_values():
        assert v not in blob, ".env 값이 레코드 산출물에 노출됨"
    for tok in ("BIGDATA_API_KEY", "X-API-KEY", "x-api-key"):
        assert tok not in blob


def test_no_network_blocks_live_fetch():
    """--no-network 이면 HTTP 진입점에서 netguard 가 막는다(라이브 호출 없음 증명)."""
    netguard.set_no_network(True)
    try:
        cli = rest.BigdataQuoteClient(CFG)
        if not cli.has_key:
            # 키가 없으면 has_key 게이트에서 먼저 막힘 — 그래도 네트워크는 안 나감
            try:
                cli.fetch_quote("micron")
            except rest.BigdataQuoteError:
                return
        try:
            cli.fetch_quote("micron")
            assert False, "no-network 인데 fetch 가 통과함"
        except netguard.NoNetworkError:
            pass
    finally:
        netguard.set_no_network(False)


def test_from_json_cli_is_offline_and_writes_nothing():
    before = _fingerprint()
    fx = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    try:
        json.dump(_payload(), fx)
        fx.close()
        netguard.set_no_network(True)          # CLI 가 네트워크를 안 쓰는지도 같이 본다
        try:
            r = _run_cli("data_sources.bigdata.rest", "--from-json", fx.name, "--slug", "micron")
        finally:
            netguard.set_no_network(False)
        assert r.returncode == 0, f"--from-json exit={r.returncode}\n{(r.stderr or '')[-400:]}"
        assert "2026-09-01T15:27:23" in r.stdout
        assert rest.TZ_UNSPECIFIED in r.stdout
        for v in _env_values():
            assert v not in (r.stdout + r.stderr)
    finally:
        os.unlink(fx.name)
    assert _fingerprint() == before, "--from-json 실행으로 store/index.html 이 변경됨"


def test_check_cli_requires_a_mode():
    r = _run_cli("data_sources.bigdata.rest")
    assert r.returncode != 0            # --check 또는 --from-json 필수


def test_main_dashboard_untouched():
    for rel in (CFG["dashboard"]["html"], CFG["dashboard"]["web_deploy_html"]):
        p = (ROOT / rel.lstrip("./")).resolve()
        if p.exists():
            assert "/* DS-DATA-START */" not in p.read_text(encoding="utf-8")


def test_two_dashboard_htmls_are_identical():
    hs = []
    for rel in (CFG["dashboard"]["html"], CFG["dashboard"]["web_deploy_html"]):
        p = (ROOT / rel.lstrip("./")).resolve()
        assert p.exists()
        hs.append(hashlib.sha256(p.read_bytes()).hexdigest())
    assert hs[0] == hs[1]


# ── 5. 회귀 ────────────────────────────────────────────────────────────
def test_phase_b_c_d_e1_suites_still_green():
    for mod in ("test_phase_b", "test_phase_c", "test_phase_d", "test_phase_e1"):
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
    sys.exit(0 if _run() else 1)
