"""스토어 → 대시보드 주입 데이터 재생성.

생성물(대시보드 인라인 블록):
  var DS     = { <slug>: { <ln_key>: <계보 노드> } }   # LN() 조회 우선용 (없으면 기존 리터럴 fallback)
  var SRC    = { mcp_server, ids:{slug:entity_id}, search_query }   # 하드코딩 UUID/IDS 제거 (C4)
  var HEALTH = [ { provider, status, last_sync, detail } ]           # Governance Source Health 패널

마커 사이에 주입:  /* DS-DATA-START */ ... /* DS-DATA-END */
마커가 없으면 <script> 의 "use strict"; 다음 줄에 삽입.
index.html 과 web_deploy/index.html 둘 다 기록 (I5 해소).

기본 동작은 **비파괴**: DS 가 비면 대시보드 동작 100% 동일.
--rebuild-mccd 를 주면 최신 스토어 값으로 var MC / var CD 의 price·eps 만 갱신(옵트인).

실행:
  python -m data_sources.build_dashboard_data            # 주입
  python -m data_sources.build_dashboard_data --check    # 빌드만, 파일 미수정
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .common import store
from .common.schema import NormalizedRecord

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CFG = json.loads((HERE / "config" / "data_sources.json").read_text(encoding="utf-8"))

START = "/* DS-DATA-START */"
END = "/* DS-DATA-END */"

# Phase C §1·§8: 주입 블록/프로토타입에 secret(또는 key 포함 request URL)이 새면 즉시 중단.
_SECRET_RE = re.compile(
    r"(crtfc_key|api_key|apikey|serviceKey|access_token)\s*[:=]\s*[A-Za-z0-9._\-]{6,}"
    r"|OPENDART_API_KEY\s*[:=]\s*\S", re.I)


def _assert_no_secret(text: str, where: str = "generated block") -> None:
    m = _SECRET_RE.search(text or "")
    if m:
        raise SystemExit(f"build_dashboard_data: {where} 에 secret 패턴 감지 → 중단 "
                         f"(match ~{m.start()}). 주입/출력하지 않음.")

# Phase A: actual-data-first. ACTUAL metric 만 data-source mapping.
#   (metric, period 패턴) → 대시보드 LN 키
METRIC_TO_LNKEY = [
    (("price", None), "price"),
    (("volume", None), "volume"),
    (("market_cap", None), "mktcap"),
    (("revenue", None), "revenue"),
    (("operating_income", None), "op_income"),
    (("net_income", None), "net_income"),
    (("eps_actual", None), "eps_actual"),
    (("shares_outstanding", None), "shares"),
    (("cash", None), "cash"),
    (("debt", None), "debt"),
    (("capex", None), "capex"),
    (("inventory", None), "inventory"),
]

# DERIVED 레이어 (별도) — 대시보드가 actual 로부터 계산. is_derived + formula + input_ids 유지.
DERIVED_METRIC_TO_LNKEY = [
    (("mc_fair_value_mean", None), "fv"),
    (("mc_fair_value_p50", None), "fv_p50"),
    (("expected_return", None), "expret"),
    (("p_up", None), "pup"),
    (("fwd_pe", None), "pe"),
    (("reverse_dcf_fcff", None), "revdcf"),
    (("expectations_gap", None), "expgap"),
    (("daily_change_pct", None), "chg"),
    (("trailing_pe", None), "trailing_pe"),
    (("pb", None), "pb"),
    (("revenue_yoy", None), "revenue_yoy"),
    (("operating_margin", None), "op_margin"),
]

# 파이프라인에서 소비하지 않는 스토어(아카이브) — report/assumption
EXCLUDE_STORES = ("_report_archive",)


def _match(table, r) -> str | None:
    for (metric, period), key in table:
        if r.metric == metric and (period is None or (r.period or "").startswith(period)):
            return key
    return None


def build_ds() -> dict:
    """slug → {ln_key: node}.  node 에 layer(NORMALIZED|DERIVED) 표기.
    REPORT/ASSUMPTION(_report_archive)은 제외 → 대시보드는 기존 리터럴로 fallback(비파괴).
    같은 키 다중 소스면 Source Priority 로 preferred, 나머지는 alt_sources.
    """
    from .common.classification import priority
    from .common.store import parse_dt

    norm = store.load_all_normalized(exclude=EXCLUDE_STORES)
    derived = store.load_derived("mc_dashboard")

    buckets: dict[tuple, list] = {}
    for r in norm:
        if not r.slug:
            continue
        key = _match(METRIC_TO_LNKEY, r)
        if key:
            buckets.setdefault((r.slug, key, "NORMALIZED"), []).append(r)
    for r in derived:
        if not r.slug:
            continue
        key = _match(DERIVED_METRIC_TO_LNKEY, r)
        if key:
            buckets.setdefault((r.slug, key, "DERIVED"), []).append(r)

    # legacy MC 파생 키(estimate 의존) — Phase B 대시보드 core 기본 분석 제외
    LEGACY_KEYS = {"fv", "fv_p50", "expret", "pup", "pe"}

    ds: dict = {}
    for (slug, key, layer), rs in buckets.items():
        # 스펙 §11: priority(작을수록 우선) → 최신 filing_date → 최신 retrieved_at (실제 datetime).
        rs.sort(key=lambda r: (
            priority(r.source_type or "NEWS"),
            -parse_dt(r.filing_date).timestamp(),
            -parse_dt(r.retrieved_at).timestamp(),
        ))
        best = rs[0]
        node = best.to_ln_node()
        node["layer"] = layer
        if layer == "DERIVED":
            node["is_derived"] = True
            if best.formula:
                node["formula"] = best.formula
            if best.input_record_ids:
                node["input_record_ids"] = list(best.input_record_ids)
            if key in LEGACY_KEYS:
                node["deprecated_for_actual_dashboard"] = True
                node["core_eligible"] = False
                node["validation_status"] = node.get("validation_status") or "WARNING"
                node.setdefault("validation_notes", []).append("estimate_dependent_input")
                node["legacy"] = "estimate-dependent (forward EPS · cycle P/E)"
        node["observation_date"] = best.as_of_date
        node["retrieved_at"] = best.retrieved_at
        node["_updated"] = best.retrieved_at
        alts = [x.to_ln_node() for x in rs[1:4]]
        if alts:
            node["alt_sources"] = alts
        ds.setdefault(slug, {})[key] = node
    return ds


# ── Actual Analysis Layer (설계서 Phase B §16) ────────────────────────
ACTUAL_GROUPS = {
    "PRICE": ["price", "market_cap"],
    "INCOME": ["revenue", "operating_income", "net_income", "eps_basic", "eps_diluted", "eps_actual"],
    "BALANCE_SHEET": ["cash", "debt", "inventory", "total_assets", "total_liabilities", "equity", "shares_outstanding"],
    "CASH_FLOW": ["operating_cash_flow", "capex"],
    "DERIVED": ["revenue_yoy", "revenue_qoq", "operating_income_yoy", "net_income_yoy", "eps_yoy",
                "operating_margin", "net_margin", "fcf_margin", "debt_to_equity"],
}
ACTUAL_STORES = ("sec_edgar", "opendart", "_migrated")  # _migrated: price(bigdata)


def _period_sort(p: str | None) -> tuple:
    """FY2025 / 2026Q2 를 한 축에서 정렬. FY = 그 해 Q4 뒤."""
    if not p:
        return (0, 0.0)
    m = re.match(r"FY(\d{4})", p)
    if m:
        return (int(m.group(1)), 4.5)
    m = re.match(r"(\d{4})Q([1-4])", p)
    if m:
        return (int(m.group(1)), float(m.group(2)))
    return (0, 0.0)


def build_actual() -> dict:
    """slug → {GROUP: {metric: {latest node + history[]}}}. actual + actual-derived 만."""
    from .common.store import parse_dt
    norm = []
    for s in ACTUAL_STORES:
        norm += store.load_normalized(s)
    deriv = store.load_derived("actual_metrics")

    def latest_and_hist(recs):
        # (slug, metric) → recs. latest revision, 최근 period 우선
        out: dict[tuple, list] = {}
        for r in recs:
            if not r.slug or r.value is None:
                continue
            if r.revision_status not in (None, "latest"):
                continue
            out.setdefault((r.slug, r.metric), []).append(r)
        return out

    per_metric = latest_and_hist(norm + deriv)
    result: dict = {}
    for (slug, metric), rs in per_metric.items():
        rs.sort(key=lambda r: (_period_sort(r.period),
                               parse_dt(r.filing_date or r.retrieved_at)))
        group = next((g for g, ms in ACTUAL_GROUPS.items() if metric in ms), None)
        if not group:
            continue
        latest = rs[-1]
        node = latest.to_ln_node()
        node["layer"] = "DERIVED" if latest.is_derived else "NORMALIZED"
        node["history"] = [
            {"period": x.period, "value": x.value, "form": x.form,
             "filing_date": x.filing_date, "revision_status": x.revision_status}
            for x in rs[-10:]
        ]
        result.setdefault(slug, {}).setdefault(group, {})[metric] = node
    return result


def build_src() -> dict:
    prov = CFG["providers"]["bigdata"]
    return {
        "mcp_server": prov.get("mcp_server", ""),
        "search_query": prov.get("search_query", ""),
        "ids": {c["slug"]: c.get("bigdata_entity_id") for c in CFG["covered"] if c.get("bigdata_entity_id")},
    }


def build_health() -> list:
    h = store.get_health()
    return [{"provider": k, **v} for k, v in h.items()]


def _block() -> str:
    j = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    b = (f"{START}\n"
         f"var DS={j(build_ds())};\n"
         f"var ACTUAL={j(build_actual())};\n"
         f"var SRC={j(build_src())};\n"
         f"var HEALTH={j(build_health())};\n"
         f"{END}")
    _assert_no_secret(b, "DS/ACTUAL/SRC/HEALTH block")
    return b


def inject(html: str, block: str) -> str:
    if START in html and END in html:
        return re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: block, html, flags=re.S)
    # 마커 없음 → "use strict"; 다음에 삽입
    m = re.search(r'"use strict";\s*\n', html)
    if not m:
        raise SystemExit('"use strict"; 를 찾지 못함 — 수동 마커 삽입 필요')
    return html[:m.end()] + block + "\n" + html[m.end():]


def _script_ok(html: str) -> bool:
    """<script> 본문만 뽑아 node --check (있으면)."""
    import shutil
    import subprocess
    import tempfile

    m = re.search(r"<script>\s*(.*?)</script>\s*</body>", html, re.S)
    if not m or not shutil.which("node"):
        return True
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(m.group(1))
        tmp = f.name
    try:
        r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stderr)
        return r.returncode == 0
    finally:
        Path(tmp).unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="빌드만 하고 파일 미수정")
    ap.add_argument("--rebuild-mccd", action="store_true", help="최신 스토어 값으로 var MC/CD 갱신(옵트인)")
    ap.add_argument("--emit-block", nargs="?", const="store/dashboard_snapshot/ds_block.js",
                    metavar="PATH",
                    help="주입용 JS 블록을 파일로만 출력(index.html 미수정). 기본 store/dashboard_snapshot/ds_block.js")
    a = ap.parse_args()

    block = _block()
    ds, actual = build_ds(), build_actual()
    print(f"DS: {sum(len(v) for v in ds.values())} 노드 / {len(ds)} 종목")
    for slug, groups in actual.items():
        tot = sum(len(v) for v in groups.values())
        print(f"ACTUAL[{slug}]: {tot} metric  " +
              " ".join(f"{g}={len(v)}" for g, v in groups.items()))
    print(f"SRC.mcp_server = {build_src()['mcp_server'] or '(비어있음)'}")
    print(f"HEALTH: {len(build_health())} provider")

    if a.emit_block:
        p = Path(a.emit_block)
        outp = p if p.is_absolute() else (HERE / a.emit_block)
        outp.parent.mkdir(parents=True, exist_ok=True)
        _assert_no_secret(block, f"emit-block → {outp}")
        outp.write_text(block + "\n", encoding="utf-8")
        if _script_ok(f"<script>\n{block}\nvoid 0;</script>\n</body>"):
            print(f"블록 파일 출력(검증 통과): {outp}  · index.html 미수정")
        else:
            print(f"블록 파일 출력: {outp}  (node --check 없음/스킵)  · index.html 미수정")
        return

    if a.check:
        print("\n--check: 파일 미수정. 블록 미리보기:\n" + block[:600] + (" ..." if len(block) > 600 else ""))
        return

    targets = [ROOT / CFG["dashboard"]["html"].lstrip("./"),
               ROOT / CFG["dashboard"]["web_deploy_html"].lstrip("./")]
    for t in targets:
        t = t.resolve()
        if not t.exists():
            print(f"건너뜀(없음): {t}")
            continue
        html = t.read_text(encoding="utf-8")
        new = inject(html, block)
        if a.rebuild_mccd:
            new = _rebuild_mccd(new)
        if not _script_ok(new):
            raise SystemExit(f"node --check 실패 → {t} 미수정")
        t.write_text(new, encoding="utf-8")
        print(f"주입 완료: {t}")
    print("\n다음: 브라우저로 index.html 열어 Home/Memory/Governance 렌더 · 숫자 클릭 팝업 확인.")


def _rebuild_mccd(html: str) -> str:
    """최신 스토어의 price / eps 를 var MC / var CD 에 반영(옵트인). 구조는 유지, 값만."""
    latest = store.latest_by_metric()
    for (sok, metric, period), r in latest.items():
        if metric == "price" and r.value is not None and r.slug:
            html = re.sub(rf'("{r.slug}":\s*{{[^}}]*?"cur":\s*)[\d.]+',
                          lambda m: m.group(1) + repr(float(r.value)), html, count=1)
    return html


if __name__ == "__main__":
    main()
