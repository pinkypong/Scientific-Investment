"""일회성: 현재 대시보드 인라인 리터럴(var MC / var CD) + data/*.json 스냅샷
→ append-only 스토어에 '역사적 스냅샷'으로 시드.

- 출처를 아는 값은 그 source_type 으로, 모르면 UNVERIFIED.
- 기존 대시보드는 변하지 않는다(읽기만). 재실행해도 dedup 으로 중복 안 쌓임.

실행:  python -m data_sources.migrate_inline_to_store
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .common.classification import MetricClass, NumberType, SourceClass, metric_class
from .common.schema import NormalizedRecord
from .common import store

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((Path(__file__).resolve().parent / "config" / "data_sources.json").read_text(encoding="utf-8"))
DASH = ROOT / "반도체_메모리_대시보드" / "index.html"
AS_OF = "2026-08-21"   # README_핸드오프 기준 스냅샷 일자


def _extract_object(js: str, varname: str) -> dict | None:
    m = re.search(rf"var\s+{varname}\s*=\s*", js)
    if not m:
        return None
    i = js.index("{", m.end())
    depth, j, instr, esc = 0, i, False, False
    while j < len(js):
        ch = js[j]
        if instr:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                instr = False
        else:
            if ch == '"':
                instr = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(js[i:j + 1])
        j += 1
    return None


def _cov(slug: str) -> dict:
    return next((c for c in CFG["covered"] if c["slug"] == slug), {"slug": slug})


def migrate_mc(mc: dict) -> list[NormalizedRecord]:
    recs = []
    for slug, m in mc.items():
        cov = _cov(slug)
        base = dict(slug=slug, ticker=cov.get("ticker"), company_name=m.get("name"),
                    market=cov.get("market"), currency=cov.get("currency"),
                    as_of_date=AS_OF, retrieved_at=AS_OF + "T00:00:00+00:00")
        # 현재가 = FACT (Bigdata)
        if m.get("cur") is not None:
            recs.append(NormalizedRecord(
                source="bigdata.com", provider="bigdata", source_type=SourceClass.MARKET_DATA,
                number_type=NumberType.FACT, metric="price", value=m["cur"],
                unit=cov.get("currency"), period=AS_OF, verification="Cross-Checked",
                confidence="High", original_url="https://bigdata.com",
                raw_value="migrated from index.html var MC", **base))
        # 사이클 P/E 중앙값 = ASSUMPTION
        if m.get("fv_pe_mid") is not None:
            recs.append(NormalizedRecord(
                source="analyst_judgment", provider="analytics_engine",
                source_type=SourceClass.DERIVED, number_type=NumberType.ASSUMPTION,
                metric="cycle_pe_mid", value=m["fv_pe_mid"], unit="x", period="forward",
                confidence="Medium", verification="Weak Evidence",
                why=['"메모리 피크 = 저멀티플" 원칙(주관)'],
                missing=["P/E DISTRIBUTION NOT VALIDATED"], **base))
        # MC 산출물 = MODEL (파생)
        for metric, val, nt in (("mc_fair_value_mean", m.get("ev"), NumberType.MODEL),
                                ("mc_fair_value_p50", (m.get("pct") or {}).get("50"), NumberType.MODEL),
                                ("expected_return", m.get("exp_ret"), NumberType.MODEL),
                                ("p_up", m.get("p_up"), NumberType.MODEL),
                                ("fwd_pe", m.get("cur_pe"), NumberType.MODEL)):
            if val is not None:
                recs.append(NormalizedRecord(
                    source="derived", provider="analytics_engine", source_type=SourceClass.DERIVED,
                    number_type=nt, metric=metric, value=val, is_derived=True,
                    formula="Monte Carlo 20,000 sims; FV = Fwd EPS × Cycle P/E",
                    unit=cov.get("currency") if "value" in metric or "fair" in metric else None,
                    period="forward", confidence="Medium", **base))
    return recs


def migrate_cd(cd: dict) -> list[NormalizedRecord]:
    recs = []
    fin = cd.get("fin", {})
    for slug, f in fin.items():
        cov = _cov(slug)
        base = dict(slug=slug, ticker=cov.get("ticker"), company_name=f.get("name"),
                    market=cov.get("market"), currency=cov.get("currency"),
                    as_of_date=AS_OF, retrieved_at=AS_OF + "T00:00:00+00:00",
                    source="bigdata.com", provider="bigdata",
                    source_type=SourceClass.MARKET_DATA, number_type=NumberType.CONSENSUS,
                    verification="Estimated", confidence="Low",
                    original_url="https://bigdata.com")
        for i, yr in enumerate(("FY2026", "FY2027", "FY2028")):
            v = (f.get("eps") or [None, None, None])[i]
            if v is not None:
                recs.append(NormalizedRecord(metric="eps", value=v, unit=cov.get("currency"),
                                             period=yr, why=["migrated from index.html var CD.fin"],
                                             missing=["개별 broker EPS 미추출 — Bigdata 집계치"], **base))
        if f.get("tp"):
            tpsrc = {"samsung": "삼성증권", "skhynix": "삼성증권", "sandisk": "한화투자증권"}.get(slug, "—")
            recs.append(NormalizedRecord(metric="target_price", value=f["tp"], unit=cov.get("currency"),
                                         period="as_reported", broker=tpsrc,
                                         why=["단일 하우스 · 컨센서스 TP 집계 아님"],
                                         **{k: v for k, v in base.items() if k != "source_type"},
                                         source_type=SourceClass.SECONDARY_PROFESSIONAL))
        # 과낙관 체크 산문 = 계보 노드(값 없음)
        o = f.get("opt") or {}
        if o:
            recs.append(NormalizedRecord(
                metric="optimism_check", value=o.get("verdict"),
                report_title=o.get("report"), why=[o.get("claim", ""), o.get("check", ""), o.get("effect", "")],
                number_type=NumberType.MODEL,
                **{k: v for k, v in base.items() if k not in ("number_type",)}))
    return recs


def migrate_json_snapshots() -> list[NormalizedRecord]:
    """data/*.json 스냅샷도 raw 로 보존."""
    out = []
    ddir = ROOT / "반도체_메모리_대시보드" / "data"
    for name in ("mc.json", "cdata.json", "samsung_dcf.json"):
        p = ddir / name
        if p.exists():
            store.save_raw("dashboard_snapshot", f"{name}_{AS_OF}", p.read_text(encoding="utf-8"), "json")
    return out


def main():
    js = DASH.read_text(encoding="utf-8")
    mc = _extract_object(js, "MC")
    cd = _extract_object(js, "CD")
    if mc is None or cd is None:
        raise SystemExit("index.html 에서 var MC / var CD 를 찾지 못함")
    recs = migrate_mc(mc) + migrate_cd(cd)
    migrate_json_snapshots()

    # ── Phase A: metric layer 로 분리 ────────────────────────────────
    actual, derived, archive = [], [], []
    for r in recs:
        mc_ = metric_class(r.metric)
        if mc_ == MetricClass.ACTUAL:
            actual.append(r)
        elif mc_ == MetricClass.DERIVED:
            r.is_derived = True
            derived.append(r)
        else:  # REPORT / ASSUMPTION / META
            r.missing = (r.missing or []) + [
                f"[{mc_}] Phase A 에서 파이프라인 제외 — 아카이브 보존(삭제 아님)"]
            r.deprecated_for_actual_dashboard = True
            archive.append(r)

    n_a = store.append_normalized("_migrated", actual)
    n_d = store.append_derived("mc_dashboard", derived)
    n_r = store.append_archive("report", archive)   # 스펙 §12: store/archive/report.jsonl
    store.update_sync_state("_migrated", latest_data_date=AS_OF,
                            actual=len(actual), derived=len(derived), archived=len(archive))

    print(f"인라인 리터럴에서 {len(recs)} 레코드 추출:")
    print(f"  ACTUAL   → normalized/_migrated.jsonl     신규 {n_a}  ({_names(actual)})")
    print(f"  DERIVED  → derived/mc_dashboard.jsonl     신규 {n_d}  ({_names(derived)})")
    print(f"  ARCHIVE  → archive/report.jsonl           신규 {n_r}  ({_names(archive)})   ← 파이프라인 제외")
    print("\n제외(아카이브)된 report/assumption 데이터 — 삭제되지 않음, 대시보드 리터럴도 그대로:")
    for name, cnt in _by_metric(archive).items():
        print(f"    - {name}  ×{cnt}")
    print("\n기존 대시보드 index.html 은 변경되지 않음(읽기 전용). "
          "다음: python -m data_sources.build_dashboard_data --check")


def _names(recs):
    return ", ".join(sorted({r.metric or "(doc)" for r in recs})) or "-"


def _by_metric(recs):
    out = {}
    for r in recs:
        k = r.metric or "(doc)"
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items()))


if __name__ == "__main__":
    main()
