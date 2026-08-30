"""동기화 오케스트레이터 (Phase C: 증분 동기화 + TTL + 운영 안정성).

provider 별로:  [TTL skip 판정] → collect → validate_batch → store.append_normalized → record_health
증분 판단:  config.providers.<p>.update_policy_sec (TTL) + sync_state.last_successful_sync.
  · TTL 안이고 --force 아니면  →  {"skipped": "ttl_fresh"} + source_health.status=SKIPPED (실패 아님).
  · --force        : TTL 무시하고 강제 동기화.
  · --dry-run      : 외부 **저장** 없음(raw/normalized/derived/sync_state/health/log 미기록). store.set_dry_run 로 강제.
                     네트워크는 막지 않는다 — TTL 이 만료되고 --force 면 실제 API 호출이 나간다.
  · --no-network   : 외부 **호출** 없음(Phase D §3). provider TTL skip 또는 company-level cache hit 만 허용하고,
                     cache miss 는 API 를 때리지 않고 blocked 로 보고한다(netguard 로 강제).
  · --dry-run --no-network : 완전 무해 점검 모드 — 아무것도 읽으러 나가지 않고 아무것도 쓰지 않는다.
  · --force-derived: 신규 actual 레코드가 없어도 actual derived 재계산.

실행:
  python -m data_sources.run_sync --provider opendart
  python -m data_sources.run_sync --provider opendart --dry-run
  python -m data_sources.run_sync --provider opendart --force
  python -m data_sources.run_sync --all --dry-run
"""
from __future__ import annotations

import argparse
import json
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from .common import netguard, store
from .common.provider import available, get_provider
from .common.validation import summarize, validate_batch

# @register 데코레이터 실행을 위해 어댑터 패키지를 로드
from . import bigdata as _bigdata  # noqa: F401,E402
from . import hankyung_consensus as _hc  # noqa: F401,E402
from . import hankyung_global as _hg  # noqa: F401,E402
from . import sec_edgar as _sec  # noqa: F401,E402
from . import opendart as _dart  # noqa: F401,E402

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / "config" / "data_sources.json").read_text(encoding="utf-8"))


def _covered(market: str | None = None):
    rows = CFG["covered"]
    return [r for r in rows if market is None or r.get("market") == market]


def _ttl_skip(key: str, pconf: dict, *, force: bool) -> dict | None:
    """update_policy_sec(TTL) 안이고 --force 아니면 skip dict, 아니면 None.

    TTL 은 config.providers.<key>.update_policy_sec (초). 없거나 0 이면 스로틀 없음.
    판단 근거: sync_state.<key>.last_successful_sync (실제 datetime 비교, 문자열 길이 아님)."""
    ttl = int(pconf.get("update_policy_sec") or 0)
    if force or ttl <= 0:
        return None
    st = store.get_sync_state().get(key, {})
    last_ok = st.get("last_successful_sync")
    if not last_ok:
        return None
    age = (datetime.now(timezone.utc) - store.parse_dt(last_ok)).total_seconds()
    if age >= ttl:
        return None
    store.record_health(
        key, status="SKIPPED",
        detail=f"ttl_fresh: age={int(age)}s < update_policy_sec={ttl}s (외부 호출 안 함)",
        request_count=0, succeeded=True)
    store.update_sync_state(key, last_skipped_at=store._now(), last_skip_reason="ttl_fresh")
    store.log(key, "sync_skipped", {"reason": "ttl_fresh", "age_sec": int(age), "ttl_sec": ttl})
    return {"provider": key, "skipped": "ttl_fresh",
            "age_sec": int(age), "ttl_sec": ttl, "last_successful_sync": last_ok}


def sync_provider(key: str, *, since: str, until: str,
                  dry_run: bool = False, force: bool = False,
                  no_network: bool = False) -> dict:
    pconf = CFG["providers"].get(key, {})
    if not pconf.get("enabled", False):
        return {"provider": key, "skipped": "disabled"}
    store.set_dry_run(dry_run)
    netguard.set_no_network(no_network)
    try:
        skip = _ttl_skip(key, pconf, force=force)
        if skip:
            return skip
        return _do_sync(key, pconf, since=since, until=until,
                        dry_run=dry_run, no_network=no_network, force=force)
    finally:
        store.set_dry_run(False)
        netguard.set_no_network(False)


def _do_sync(key: str, pconf: dict, *, since: str, until: str, dry_run: bool = False,
             no_network: bool = False, force: bool = False) -> dict:
    prov = get_provider(key, CFG)
    t0 = time.time()
    all_recs, failures, reqs = [], 0, 0
    # Phase D §1·§6: company 단위 cache 판정을 provider TTL skip 과 구분해 집계한다.
    cstat = {"hit": 0, "miss": 0, "blocked": 0, "skip": 0}
    companies = 0

    try:
        if key == "hankyung_consensus":
            for cov in _covered("KR"):
                reqs += 1
                try:
                    all_recs += prov.collect(cov, since, until, pconf.get("max_per_ticker", 15))
                except Exception:  # noqa: BLE001
                    failures += 1
                    store.log(key, "collect_error", {"slug": cov["slug"], "tb": traceback.format_exc()})
        elif key == "hankyung_global":
            for cov in _covered("US"):
                reqs += 1
                try:
                    all_recs += prov.collect(cov)
                except Exception:  # noqa: BLE001
                    failures += 1
                    store.log(key, "collect_error", {"slug": cov["slug"], "tb": traceback.format_exc()})
        elif key == "sec_edgar":
            for cov in _covered("US"):
                if not cov.get("sec_cik"):
                    continue
                companies += 1
                try:
                    all_recs += prov.collect(cov, no_network=no_network, force=force)
                    st = getattr(prov, "last_cache_state", None)
                    if st in cstat:
                        cstat[st] += 1
                    if st == "miss":
                        reqs += 1
                except Exception:  # noqa: BLE001
                    failures += 1
                    reqs += 1
                    store.log(key, "collect_error", {"slug": cov["slug"], "tb": traceback.format_exc()})
        elif key == "opendart":
            # 자격증명은 **fetch 할 때만** 필요하다. --no-network 는 정의상 API 를 부르지 않고
            # company cache(=append-only raw)만 읽으므로, 키가 없어도 normalized 재생성이 된다.
            # (클론 직후 raw 만 있는 환경에서 키 없이 복구하는 경로 — cache miss 면 아래 blocked 처리)
            if not no_network and not getattr(prov, "available", False):
                store.record_health(
                    key, status="NOT_CONFIGURED",
                    detail="OPENDART_API_KEY 미설정 — data_sources/.env 필요 (구현 완료, 호출 불가)",
                    request_count=0, succeeded=False,
                    last_error="missing OPENDART_API_KEY")
                store.update_sync_state(key, last_attempted_sync=store._now(),
                                        blocked="OPENDART_API_KEY")
                return {"provider": key, "status": "NOT_CONFIGURED",
                        "blocked": "OPENDART_API_KEY 없음 (.env)"}
            for cov in _covered("KR"):
                if not cov.get("dart_corp_code"):
                    continue
                companies += 1
                try:
                    all_recs += prov.collect(cov, no_network=no_network, force=force)
                    st = getattr(prov, "last_cache_state", None)
                    if st in cstat:
                        cstat[st] += 1
                    if st == "miss":
                        reqs += 1
                except Exception as e:  # noqa: BLE001
                    failures += 1
                    reqs += 1
                    from .opendart.adapter import _scrub
                    store.log(key, "collect_error", {"slug": cov["slug"],
                              "e": _scrub(repr(e), getattr(prov, "key", ""))})
        elif key == "bigdata":
            print("  bigdata: 브라우저(window.cowork)에서 호출 → save_snapshot 사용. run_sync 대상 아님.")
            return {"provider": key, "skipped": "browser-side (use bigdata.adapter save_snapshot)"}
        else:
            return {"provider": key, "skipped": "no sync handler"}

        prev = {(r.slug or r.ticker, r.metric, r.period): r.value
                for r in store.load_normalized(key)}
        all_recs = validate_batch(all_recs, prev)
        stats = summarize(all_recs)
        # store.set_dry_run 이 켜져 있으면 append_normalized 는 '기록 없이 신규 건수만' 반환
        new_n = store.append_normalized(key, all_recs)
        dupes = len(all_recs) - new_n
        warns = stats.get("WARNING", 0) + stats.get("ERROR", 0)

        status = "HEALTHY" if failures == 0 else ("WARNING" if failures < max(reqs, 1) else "ERROR")
        if warns and status == "HEALTHY":
            status = "WARNING"
        # Phase D §6: no-network cache miss 는 실패가 아니라 '이번엔 못 받아왔다'.
        #   전부 blocked → SKIPPED(안 돌았음) / 일부만 blocked → WARNING(부분 수집)
        blocked = cstat["blocked"]
        if blocked and status in ("HEALTHY", "WARNING"):
            status = "SKIPPED" if not all_recs else "WARNING"
        resp_ms = int((time.time() - t0) * 1000)
        # dry-run 이면 아래 두 호출은 store 레벨에서 no-op (외부 저장 없음)
        detail = f"{stats}"
        if companies:
            detail += (" | cache hit=%d miss=%d blocked=%d of %d companies"
                       % (cstat["hit"], cstat["miss"], blocked, companies))
        ok = (failures == 0 and blocked == 0)
        store.record_health(key, status=status, detail=detail,
                            request_count=reqs, failures=failures,
                            records_fetched=len(all_recs), new_records=new_n,
                            duplicates=dupes, validation_warnings=warns,
                            cache_hits=cstat["hit"], cache_misses=cstat["miss"],
                            company_count=companies,
                            skipped_companies=cstat["skip"] + blocked,
                            no_network_blocked_count=blocked,
                            response_ms=resp_ms, succeeded=ok,
                            last_error=("no_network_cache_miss" if blocked else None))
        if ok:
            store.update_sync_state(key, last_successful_sync=store._now(),
                                    last_attempted_sync=store._now(),
                                    latest_document_date=until, blocked=None)
        else:
            store.update_sync_state(
                key, last_attempted_sync=store._now(),
                last_skipped_at=store._now() if blocked else None,
                last_skip_reason="no_network_cache_miss" if blocked else None)
        return {"provider": key, "collected": len(all_recs), "new": new_n,
                "duplicates": dupes, "failures": failures, "validation": stats,
                "cache_hits": cstat["hit"], "cache_misses": cstat["miss"],
                "no_network_blocked": blocked, "companies": companies,
                "ms": resp_ms, "dry_run": dry_run, "no_network": no_network}
    except Exception as e:  # noqa: BLE001
        msg = repr(e)
        if key == "opendart":
            try:
                from .opendart.adapter import _scrub
                msg = _scrub(msg, getattr(prov, "key", ""))
            except Exception:  # noqa: BLE001
                pass
        store.record_health(key, status="ERROR", detail=msg,
                            succeeded=False, last_error=msg)
        store.log(key, "sync_fatal", {"tb": _scrub_tb(key, prov, traceback.format_exc())})
        return {"provider": key, "error": msg}


def _scrub_tb(key, prov, tb: str) -> str:
    if key != "opendart":
        return tb
    try:
        from .opendart.adapter import _scrub
        return _scrub(tb, getattr(prov, "key", ""))
    except Exception:  # noqa: BLE001
        return tb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=available())
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--since", default="2026-06-01")
    ap.add_argument("--until", default=time.strftime("%Y-%m-%d"))
    ap.add_argument("--dry-run", action="store_true", help="외부 저장 없음 (raw/normalized/derived/state/health/log 미기록)")
    ap.add_argument("--force", action="store_true", help="update_policy_sec(TTL) 무시하고 강제 동기화")
    ap.add_argument("--no-network", action="store_true",
                    help="외부 호출 없음. TTL skip / company cache hit 만 허용, cache miss 는 blocked")
    ap.add_argument("--force-derived", action="store_true", help="신규 actual 레코드가 없어도 actual derived 재계산")
    a = ap.parse_args()

    keys = available() if a.all else ([a.provider] if a.provider else [])
    if not keys:
        ap.error("--provider <key> 또는 --all 필요. 등록: " + ", ".join(available()))
    ran_actual = False
    for k in keys:
        print(f"▶ {k}")
        res = sync_provider(k, since=a.since, until=a.until,
                            dry_run=a.dry_run, force=a.force,
                            no_network=a.no_network)
        print("  ", res)
        if k in ("sec_edgar", "opendart") and res.get("new"):
            ran_actual = True
    # 파생 재계산: 신규 actual 이 있었거나(--force-derived 시 무조건). dry-run 은 append no-op.
    if (ran_actual or a.force_derived) and not a.dry_run:
        from .common import derive
        from .common.validation import validate_record
        recs = derive.compute()
        for r in recs:                       # 스펙 §8: 파생 완전성 검증
            st, notes = validate_record(r)
            r.validation_status, r.validation_notes = st, notes
        bad = [r for r in recs if r.validation_status == "ERROR"]
        n = store.append_derived("actual_metrics", recs)
        why = "신규 actual" if ran_actual else "--force-derived"
        print(f"▶ derive(actual)  [{why}]  계산 {len(recs)}  신규 {n}  검증ERROR {len(bad)}")
    elif a.force_derived and a.dry_run:
        print("▶ derive(actual)  --dry-run: 재계산 스킵(외부 저장 없음)")
    if not a.dry_run:
        print("\n다음: python -m data_sources.build_dashboard_data --check")


if __name__ == "__main__":
    main()
