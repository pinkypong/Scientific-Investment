# -*- coding: utf-8 -*-
"""Phase E1 자동화 테스트 — valuation 레이어(Damodaran benchmark · recipe · company context).

실행:
  python -m data_sources.tests.test_phase_e1     # 내장 러너
  pytest data_sources/tests/test_phase_e1.py     # pytest 있으면

보안 원칙: Phase C/D 와 동일하다. `.env` 값은 **없는지만** 검사하고 절대 출력하지 않는다.
매칭 결과는 bool 로만 단언하며, 실패 메시지에도 값 원문을 넣지 않는다.

범위 원칙: 이 스위트는 **읽기 전용**이다. valuation 레이어는 store/ 나 index.html 을
쓰지 않아야 하며, 그 사실 자체를 test_valuation_layer_writes_nothing 이 지킨다.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

from ..common import store
from ..valuation import context as vctx
from ..valuation import damodaran as dmd
from ..valuation import recipes as rcp

DS_ROOT = store.STORE_ROOT.parent            # data_sources/
SR = store.STORE_ROOT                        # data_sources/store/
ROOT = DS_ROOT.parent                        # 프로젝트 루트
CFG = json.loads((DS_ROOT / "config" / "data_sources.json").read_text(encoding="utf-8"))

COVERED_SLUGS = {"samsung", "skhynix", "micron", "sandisk"}
CONFIDENCE_OK = {"high", "medium", "low"}

# damodaran_allsectors.json 의 업종 수(2026-01 스냅샷). 스냅샷 갱신 시 흔들릴 수 있으므로
# 정확값이 아니라 "54개 근처"로 느슨하게 잡는다.
EXPECTED_INDUSTRY_COUNT = 54
INDUSTRY_COUNT_TOLERANCE = 6

# Benchmark.to_dict() 가 반드시 노출해야 하는 필드 키(값은 None 허용).
REQUIRED_BENCHMARK_KEYS = ("industry",) + dmd.CORE_FIELDS       # 1 + 17 = 18

# recipe 이름 — 최소한 존재해야 하는 것들.
REQUIRED_RECIPES = ("Bank", "Software", "REIT", "Energy", "Default")


# ── helpers ─────────────────────────────────────────────────────────────
def _env_values() -> list[str]:
    """.env 의 값들(8자 이상). 반환값은 절대 print 하지 않고 bool 로만 쓴다."""
    envp = DS_ROOT / ".env"
    if not envp.exists():
        return []
    out: list[str] = []
    for ln in envp.read_text(encoding="utf-8", errors="ignore").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        v = ln.split("=", 1)[1].strip().strip('"').strip("'")
        if len(v) >= 8:
            out.append(v)
    return out


def _fingerprint() -> dict:
    """store/ + index.html 2종의 파일별 sha256. 읽기 전용 검증용."""
    out = {}
    for p in sorted(SR.rglob("*")):
        if p.is_file():
            out["store/" + p.relative_to(SR).as_posix()] = \
                hashlib.sha256(p.read_bytes()).hexdigest()
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


def _ctx(slug: str) -> dict:
    return next(c for c in vctx.build_all() if c["slug"] == slug)


# ── 1. Damodaran 데이터 로드 ────────────────────────────────────────────
def test_damodaran_json_files_load():
    """두 파일 모두 로드된다 — allsectors(필수) / benchmarks(심화)."""
    a = dmd.load_allsectors(refresh=True)
    assert isinstance(a, dict) and a.get("sectors"), "allsectors 에 sectors 가 비었다"
    assert a.get("as_of"), "allsectors 에 as_of 가 없다 — 스냅샷 시점 표기는 필수"

    b = dmd.load_benchmarks(refresh=True)
    assert isinstance(b, dict) and b, "damodaran_benchmarks.json 로드 실패(빈 dict 로 degrade)"
    assert b.get("usage_rules"), "benchmarks.json 에 usage_rules 가 없다"


def test_damodaran_files_exist_at_resolved_paths():
    allsectors, benchmarks = dmd._resolve_paths()
    assert allsectors.exists(), f"allsectors 경로 없음: {allsectors}"
    assert benchmarks.exists(), f"benchmarks 경로 없음: {benchmarks}"


def test_missing_file_raises_damodaran_data_missing():
    """데이터 부재가 아니라 설정 오류 — 조용히 넘기지 않고 전용 예외를 낸다."""
    try:
        dmd._load(DS_ROOT / "__no_such_damodaran__.json", "test")
        raise AssertionError("없는 파일인데 예외가 안 났다")
    except dmd.DamodaranDataMissing:
        pass


def test_list_industries_count_and_contains_semiconductor():
    inds = dmd.list_industries()
    assert "Semiconductor" in inds, "Semiconductor 업종이 목록에 없다"
    assert abs(len(inds) - EXPECTED_INDUSTRY_COUNT) <= INDUSTRY_COUNT_TOLERANCE, \
        f"업종 수가 예상({EXPECTED_INDUSTRY_COUNT}±{INDUSTRY_COUNT_TOLERANCE})을 벗어남: {len(inds)}"
    assert inds == sorted(inds), "list_industries() 가 정렬되어 있지 않다"


# ── 2. Semiconductor benchmark ──────────────────────────────────────────
def test_semiconductor_benchmark_exists():
    bm = dmd.get_benchmark("Semiconductor")
    assert bm is not None, "Semiconductor benchmark 가 None 이다"
    assert bm.industry == "Semiconductor", f"원래 표기가 보존되지 않음: {bm.industry}"


def test_semiconductor_benchmark_core_values_present():
    """wacc / beta / ev_ebit / ev_ebitda / operating_margin_pretax 가 None 이 아님."""
    bm = dmd.get_benchmark("Semiconductor")
    for f in ("wacc", "beta", "ev_ebit", "ev_ebitda", "operating_margin_pretax"):
        v = getattr(bm, f)
        assert v is not None, f"Semiconductor.{f} 가 None"
        assert isinstance(v, (int, float)) and not isinstance(v, bool), \
            f"Semiconductor.{f} 가 수치형이 아님: {type(v).__name__}"
        assert v > 0, f"Semiconductor.{f} 가 양수가 아님: {v}"


def test_semiconductor_benchmark_has_deep_and_caveat():
    """심화 파일(benchmarks.json)이 반도체에 붙고 caveat 이 가드레일로 노출된다."""
    bm = dmd.get_benchmark("Semiconductor")
    assert bm.has_deep, "Semiconductor 에 deep(심화) 데이터가 붙지 않았다"
    assert bm.caveat, "심화 caveat 이 비었다"
    assert "caveat" not in (bm.deep or {}), "caveat 이 deep 안에 중복으로 남아 있다"
    guards = bm.guardrails()
    assert bm.caveat in guards, "caveat 이 guardrails() 에 포함되지 않았다"
    assert len(guards) >= 1 + len(dmd.usage_rules()), "usage_rules 가 guardrails 에 안 붙었다"


def test_benchmark_to_dict_has_all_required_keys():
    """to_dict() 가 요구된 18개 필드 키를 전부 갖는다(값은 None 허용)."""
    d = dmd.get_benchmark("Semiconductor").to_dict()
    missing = [k for k in REQUIRED_BENCHMARK_KEYS if k not in d]
    assert not missing, f"to_dict() 필드 누락: {missing}"
    assert len(REQUIRED_BENCHMARK_KEYS) == 18, \
        f"필수 필드 수가 18이 아님: {len(REQUIRED_BENCHMARK_KEYS)}"
    for k in ("guardrails", "has_deep", "usage_rules"):
        assert k in d, f"to_dict() 에 {k} 없음"
    json.dumps(d, ensure_ascii=False)          # 직렬화 가능해야 저장물로 쓸 수 있다


def test_get_benchmark_is_lookup_tolerant():
    """대소문자/구두점/공백에 관용적이되 원래 표기를 돌려준다."""
    for probe in ("semiconductor", "  SEMICONDUCTOR ", "Semi-conductor"):
        bm = dmd.get_benchmark(probe)
        assert bm is not None and bm.industry == "Semiconductor", f"조회 실패: {probe!r}"
    assert dmd.get_benchmark("r.e.i.t.").industry == "R.E.I.T."


def test_get_benchmark_unknown_industry_returns_none_not_raises():
    """업종 부재는 예외가 아니라 None — 호출측이 warning 으로 degrade 해야 하기 때문."""
    assert dmd.get_benchmark("Zzz Nonexistent Industry 9000") is None
    assert dmd.get_benchmark("") is None
    assert dmd.resolve_industry(None) is None


def test_benchmark_missing_field_stays_none_not_zero():
    """Missing != 0 원칙. 값이 없는 필드는 None 을 유지한다."""
    hits = 0
    for name in dmd.list_industries():
        bm = dmd.get_benchmark(name)
        for f in dmd.CORE_FIELDS:
            v = getattr(bm, f)
            assert v is None or isinstance(v, (int, float)), \
                f"{name}.{f} 타입 이상: {type(v).__name__}"
            hits += 1
    assert hits > 0


# ── 3. forward-looking 가드 ─────────────────────────────────────────────
def test_forward_looking_fields_declared_and_guarded():
    """forward 계열이 상수로 선언되고 가드레일 문구에 등장한다."""
    fl = set(dmd.FORWARD_LOOKING_FIELDS)
    assert {"pe_forward", "exp_growth_5y", "peg"} <= fl, \
        f"FORWARD_LOOKING_FIELDS 누락: {sorted({'pe_forward', 'exp_growth_5y', 'peg'} - fl)}"
    text = " ".join(dmd.get_benchmark("Semiconductor").guardrails())
    for f in ("pe_forward", "exp_growth_5y", "peg"):
        assert f in text, f"가드레일 문구에 {f} 언급이 없다"


def test_forward_fields_not_in_any_recipe_metric_list():
    """recipe 의 primary/secondary 는 actual 기준 metric 만 — forward/컨센서스 금지."""
    banned = ("forward", "consensus", "target", "exp_growth", "peg")
    for name, r in rcp.REGISTRY.items():
        for metric in tuple(r.primary) + tuple(r.secondary):
            low = metric.lower()
            for b in banned:
                assert b not in low, f"recipe {name} 의 metric 에 forward 계열이 섞임: {metric}"


def test_forward_fields_absent_from_recipe_side_of_context():
    """context 의 recipe 쪽(우리가 실제로 계산할 metric)에 forward 필드명이 없다."""
    for c in vctx.build_all():
        for key in ("recipe", "recipe_alt"):
            r = c.get(key)
            if not r:
                continue
            blob = json.dumps({k: v for k, v in r.items() if k != "note"},
                              ensure_ascii=False).lower()
            for f in ("pe_forward", "exp_growth_5y"):
                assert f not in blob, f"{c['slug']} 의 {key} 에 {f} 가 새어 들어감"


# ── 4. recipe 레지스트리 / 매핑 ─────────────────────────────────────────
def test_recipe_registry_has_required_names():
    names = set(rcp.list_recipes())
    missing = [n for n in REQUIRED_RECIPES if n not in names]
    assert not missing, f"recipe 레지스트리 누락: {missing}"
    assert "Semiconductor" in names and "Insurance" in names


def test_every_recipe_has_nonempty_primary():
    for name, r in rcp.REGISTRY.items():
        assert r.name == name, f"REGISTRY 키({name})와 recipe.name({r.name}) 불일치"
        assert r.primary, f"recipe {name} 의 primary 가 비었다"
        assert all(isinstance(m, str) and m.strip() for m in r.primary), \
            f"recipe {name} 의 primary 에 빈 metric"


def test_select_recipe_industry_pattern_mapping():
    """Damodaran 실제 업종명 → recipe 매핑 실측."""
    cases = {
        "Semiconductor": "Semiconductor",
        "Semiconductor Equip": "Semiconductor",
        "Semiconductor/Manufacturing": "Semiconductor",     # alias 표기
        "Computers/Peripherals": "Semiconductor",
        "Banks (Regional)": "Bank",
        "Bank (Money Center)": "Bank",
        "R.E.I.T.": "REIT",
        "Oil/Gas (Production and Exploration)": "Energy",
        "Oil/Gas Distribution": "Energy",
        "Software (System & Application)": "Software",
        "Software (Internet)": "Software",
        "Insurance (Life)": "Insurance",
        "Insurance (Prop/Cas.)": "Insurance",
    }
    bad = {k: rcp.select_recipe(k).name for k, v in cases.items()
           if rcp.select_recipe(k).name != v}
    assert not bad, f"업종→recipe 매핑 오류(기대 vs 실제): { {k: (cases[k], v) for k, v in bad.items()} }"


def test_unknown_industry_selects_default_recipe():
    for probe in ("Zzz Nonexistent Industry 9000", "", None, "   "):
        r, why = rcp.select_recipe_with_reason(probe)
        assert r.name == rcp.DEFAULT, f"{probe!r} → {r.name} (Default 여야 함)"
        assert why["fallback"] is True and why["matched"] is False
        assert why["pattern"] is None
    assert "low_sector_specificity" in rcp.get_recipe(rcp.DEFAULT).warnings, \
        "Default recipe 에 low_sector_specificity 경고가 없다"


def test_matched_industry_reports_pattern():
    r, why = rcp.select_recipe_with_reason("Semiconductor")
    assert r.name == "Semiconductor"
    assert why["matched"] is True and why["fallback"] is False and why["pattern"]


def test_semiconductor_alias_is_declared():
    assert "Semiconductor/Manufacturing" in rcp.REGISTRY["Semiconductor"].aliases


def test_all_damodaran_industries_resolve_to_a_recipe():
    """54개 업종 전부가 크래시 없이 recipe 를 얻는다(대부분은 Default 로 떨어져도 정상)."""
    counts: dict[str, int] = {}
    for name in dmd.list_industries():
        r = rcp.select_recipe(name)
        assert r is not None and r.primary, f"{name} 에서 recipe 가 비었다"
        counts[r.name] = counts.get(r.name, 0) + 1
    for expect in ("Semiconductor", "Bank", "REIT", "Insurance", "Software", "Energy"):
        assert counts.get(expect, 0) >= 1, \
            f"실제 Damodaran 업종 중 {expect} recipe 로 가는 것이 하나도 없다 — 패턴 테이블 점검"


def test_recipe_to_dict_is_json_serializable():
    for r in rcp.REGISTRY.values():
        d = r.to_dict()
        assert isinstance(d["primary"], list) and isinstance(d["warnings"], list)
        json.dumps(d, ensure_ascii=False)


# ── 5. company context ──────────────────────────────────────────────────
def test_all_covered_companies_build_context():
    ctxs = vctx.build_all()
    slugs = {c["slug"] for c in ctxs}
    assert len(ctxs) == 4, f"context 개수가 4가 아님: {len(ctxs)}"
    assert slugs == COVERED_SLUGS, f"slug 불일치: {sorted(slugs)}"
    for c in ctxs:
        for f in ("ticker", "name", "market", "currency", "damodaran_industry"):
            assert c.get(f), f"{c['slug']}: {f} 비었음"


def test_every_context_has_recipe_with_primary():
    for c in vctx.build_all():
        r = c.get("recipe")
        assert r and r.get("name"), f"{c['slug']}: recipe 없음"
        assert r.get("primary"), f"{c['slug']}: recipe.primary 가 비었다"
        assert all(m.strip() for m in r["primary"]), f"{c['slug']}: primary 에 빈 metric"


def test_covered_semiconductor_companies_get_semiconductor_recipe():
    for slug in ("samsung", "skhynix", "micron"):
        c = _ctx(slug)
        assert c["damodaran_industry"] == "Semiconductor", \
            f"{slug} 업종이 Semiconductor 가 아님: {c['damodaran_industry']}"
        assert c["recipe"]["name"] == "Semiconductor", \
            f"{slug} recipe 가 Semiconductor 가 아님: {c['recipe']['name']}"
        assert c["benchmark"] is not None, f"{slug}: benchmark 가 None"
        assert c["mapping_confidence"] == "high", \
            f"{slug}: 명확한 매핑인데 confidence={c['mapping_confidence']}"


def test_context_benchmark_carries_guardrails():
    c = _ctx("micron")
    assert c["benchmark"].get("guardrails"), "context benchmark 에 guardrails 가 없다"
    assert c["benchmark"]["industry"] == "Semiconductor"


def test_context_confidence_enum_and_status():
    for c in vctx.build_all():
        assert c["mapping_confidence"] in CONFIDENCE_OK, \
            f"{c['slug']}: confidence enum 이탈 {c['mapping_confidence']}"
        assert vctx.benchmark_status(c) in {"OK", "WARNING", "MISSING"}


def test_unknown_sector_falls_back_to_default_recipe_with_warning():
    """존재하지 않는 업종 → Default recipe + benchmark_missing/recipe_fallback_default 경고."""
    fake = {"slug": "__fake__", "ticker": "XXX", "name": "Fake Co",
            "market": "US", "currency": "USD",
            "damodaran_industry": "Zzz Nonexistent Industry 9000"}
    c = vctx.build_context(fake)
    assert c["benchmark"] is None, "없는 업종인데 benchmark 가 생겼다"
    assert c["recipe"]["name"] == rcp.DEFAULT, \
        f"fallback recipe 가 Default 가 아님: {c['recipe']['name']}"
    ws = c["mapping_warnings"]
    assert "benchmark_missing" in ws, f"benchmark_missing 경고 없음: {ws}"
    assert "recipe_fallback_default" in ws, f"recipe_fallback_default 경고 없음: {ws}"
    assert c["mapping_confidence"] == "low", f"confidence 가 low 가 아님: {c['mapping_confidence']}"
    assert vctx.benchmark_status(c) == "MISSING"
    assert "low_sector_specificity" in c["recipe"]["warnings"]


def test_missing_industry_field_is_warned_not_crashed():
    c = vctx.build_context({"slug": "__noind__", "ticker": "Y", "name": "N",
                            "market": "US", "currency": "USD"})
    assert "industry_not_configured" in c["mapping_warnings"]
    assert c["recipe"]["name"] == rcp.DEFAULT and c["mapping_confidence"] == "low"


def test_sandisk_has_mapping_warning_and_rationale():
    """SanDisk 는 분류 모호 종목 — 경고 코드와 명시적 근거 문장이 둘 다 있어야 한다."""
    c = _ctx("sandisk")
    ws = c["mapping_warnings"]
    assert vctx.AMBIGUOUS_MAPPING_WARNING in ws, f"모호성 경고 없음: {ws}"
    rationale = [w for w in ws if " " in w]           # 코드가 아닌 문장형 근거
    assert rationale, "SanDisk 에 명시적 rationale 문자열이 없다"
    assert any("Semiconductor" in r for r in rationale), \
        "rationale 이 alt 업종(Semiconductor)을 설명하지 않는다"
    assert c["damodaran_industry"] == "Computers/Peripherals"
    assert c["damodaran_industry_alt"] == "Semiconductor"
    assert c["benchmark_alt"] is not None, "교차검증용 alt benchmark 가 비었다"
    assert c["mapping_confidence"] == "medium", \
        f"모호 매핑인데 confidence={c['mapping_confidence']}"
    assert c["recipe_alt"] and c["recipe_alt"]["name"] == "Semiconductor"


def test_context_is_json_serializable_and_stable():
    a = json.dumps(vctx.build_all(), ensure_ascii=False, sort_keys=True)
    b = json.dumps(vctx.build_all(), ensure_ascii=False, sort_keys=True)
    assert a == b, "build_all() 이 호출마다 다른 결과를 낸다(비결정적)"


def test_pick_industry_prefers_new_alias_field():
    assert vctx.pick_industry({"damodaran_industry": "A", "sector_damodaran": "B"}) == "A"
    assert vctx.pick_industry({"sector_damodaran": "B"}) == "B"      # 하위호환
    assert vctx.pick_industry({}) is None


# ── 6. secret 비노출 ────────────────────────────────────────────────────
def test_env_values_absent_from_valuation_outputs():
    """valuation 산출물(context JSON / benchmark dict)에 .env 값이 없다."""
    vals = _env_values()
    blob = json.dumps(vctx.build_all(), ensure_ascii=False, default=str)
    blob += json.dumps([dmd.get_benchmark(n).to_dict() for n in dmd.list_industries()],
                       ensure_ascii=False, default=str)
    blob += json.dumps(dmd.market_context(), ensure_ascii=False, default=str)
    hits = sum(1 for v in vals if v in blob)
    assert hits == 0, f"valuation 산출물에서 .env 값이 {hits}건 발견됨"
    for token in ("crtfc_key", "api_key", "OPENDART_API_KEY", "SEC_EDGAR_USER_AGENT"):
        assert token not in blob, f"산출물에 secret 계열 토큰 노출: {token}"


def test_env_values_absent_from_cli_output():
    vals = _env_values()
    for mod in ("data_sources.valuation.context", "data_sources.valuation.damodaran",
                "data_sources.valuation.recipes"):
        arg = "--json" if mod.endswith("context") else "--list"
        r = _run_cli(mod, arg)
        out = (r.stdout or "") + (r.stderr or "")
        hits = sum(1 for v in vals if v in out)
        assert hits == 0, f"{mod} CLI 출력에서 .env 값이 {hits}건 발견됨"
        assert "crtfc_key" not in out


# ── 7. CLI ──────────────────────────────────────────────────────────────
def test_context_check_cli_exits_zero_and_lists_all_slugs():
    r = _run_cli("data_sources.valuation.context", "--check")
    assert r.returncode == 0, f"context --check exit={r.returncode}\n{(r.stderr or '')[-500:]}"
    out = r.stdout or ""
    missing = [s for s in sorted(COVERED_SLUGS) if s not in out]
    assert not missing, f"--check 출력에 slug 누락: {missing}"
    assert "Semiconductor" in out and "Computers/Peripherals" in out
    assert vctx.AMBIGUOUS_MAPPING_WARNING in out, "SanDisk 모호성 경고가 표에 안 보인다"


def test_valuation_package_main_matches_context_check():
    a = _run_cli("data_sources.valuation", "--check")
    b = _run_cli("data_sources.valuation.context", "--check")
    assert a.returncode == 0 and b.returncode == 0
    assert a.stdout == b.stdout, "`-m data_sources.valuation --check` 가 context --check 와 다르다"


def test_damodaran_cli_lists_industries():
    r = _run_cli("data_sources.valuation.damodaran", "--list")
    assert r.returncode == 0, (r.stderr or "")[-500:]
    assert "Semiconductor" in r.stdout and "R.E.I.T." in r.stdout


def test_recipes_cli_lists_registry():
    r = _run_cli("data_sources.valuation.recipes", "--list")
    assert r.returncode == 0, (r.stderr or "")[-500:]
    for name in REQUIRED_RECIPES:
        assert f"[{name}]" in r.stdout, f"recipes --list 에 {name} 없음"


def test_context_cli_unknown_slug_reports_nonzero():
    r = _run_cli("data_sources.valuation.context", "--slug", "__nope__")
    assert r.returncode == 1, f"없는 slug 인데 exit={r.returncode}"


# ── 8. 읽기 전용 보장 ───────────────────────────────────────────────────
def test_valuation_layer_writes_nothing():
    """valuation 은 조회 레이어다 — store/ 도 index.html 도 건드리지 않는다."""
    before = _fingerprint()
    vctx.build_all()
    _run_cli("data_sources.valuation.context", "--check")
    _run_cli("data_sources.valuation.context", "--json")
    after = _fingerprint()
    changed = sorted(set(before) ^ set(after)) + \
              sorted(k for k in before.keys() & after.keys() if before[k] != after[k])
    assert not changed, f"valuation 실행으로 파일이 변경됨: {changed[:5]}"


def test_main_dashboard_untouched():
    """Phase E1 도 index.html 을 건드리지 않는다 (명시 승인 없음)."""
    for rel in (CFG["dashboard"]["html"], CFG["dashboard"]["web_deploy_html"]):
        p = (ROOT / rel.lstrip("./")).resolve()
        if not p.exists():
            continue
        assert "/* DS-DATA-START */" not in p.read_text(encoding="utf-8"), \
            f"{p.name} 에 주입 마커가 생겼다 — 승인 없이 수정됨"


def test_two_dashboard_htmls_are_identical():
    hs = []
    for rel in (CFG["dashboard"]["html"], CFG["dashboard"]["web_deploy_html"]):
        p = (ROOT / rel.lstrip("./")).resolve()
        assert p.exists(), f"대시보드 파일 없음: {p}"
        hs.append(hashlib.sha256(p.read_bytes()).hexdigest())
    assert hs[0] == hs[1], f"index.html 두 벌의 sha256 이 다르다: {hs[0][:12]} vs {hs[1][:12]}"


# ── 9. Phase B/C/D 회귀 ─────────────────────────────────────────────────
def test_phase_b_c_d_suites_still_green():
    for mod in ("test_phase_b", "test_phase_c", "test_phase_d"):
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
