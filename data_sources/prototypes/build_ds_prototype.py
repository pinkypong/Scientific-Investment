"""Phase D 프로토타입(자립형 HTML) 재생성.

스토어(store/normalized · derived · source_health · sync_state) → DS_hook_prototype.html.

- 데이터는 build_dashboard_data 의 정규 빌더(build_actual/build_health/build_ds)를 그대로 사용
  → 대시보드 주입 블록과 동일한 소스. 별도 계산 로직 없음.
- 보안: 직렬화 blob 에 secret 패턴(crtfc_key / api_key / OPENDART_API_KEY=…) 있으면 SystemExit.
  OpenDART original_url 은 공개 DART 뷰어(dsaf001/main.do?rcpNo=…) — API request URL 아님.
- index.html / web_deploy 는 건드리지 않음. 이 스크립트는 prototypes/DS_hook_prototype.html 만 씀.

실행:  python -m data_sources.prototypes.build_ds_prototype
"""
from __future__ import annotations

import json
from pathlib import Path

from ..common import store
from .. import build_dashboard_data as bdd

OUT = Path(__file__).resolve().parent / "DS_hook_prototype.html"

# build_ds 노드 중 estimate 의존(core_eligible=false) → Legacy 패널
LEGACY_KEYS = {"fv", "fv_p50", "expret", "pup", "pe"}


def build_legacy() -> dict:
    ds = bdd.build_ds()
    out: dict = {}
    for slug, keys in ds.items():
        for k, node in keys.items():
            if node.get("core_eligible") is False or k in LEGACY_KEYS:
                out.setdefault(slug, {})[k] = {
                    "label": node.get("label", k),
                    "value": node.get("value"),
                    "layer": node.get("layer", "DERIVED"),
                    "formula": node.get("formula"),
                    "validation_status": node.get("validation_status"),
                    "validation_notes": node.get("validation_notes", []),
                    "legacy": node.get("legacy", "estimate-dependent"),
                }
    return out


def build_sync() -> dict:
    """sync_state + health 를 운영자용으로 요약 (secret 없음)."""
    st = store.get_sync_state()
    h = store.get_health()
    rows = []
    for prov in sorted(set(st) | set(h)):
        if prov.startswith("_"):            # _migrated 등 내부 시드는 sync 대상 아님
            continue
        s = st.get(prov, {})
        hv = h.get(prov, {})
        rows.append({
            "provider": prov,
            "status": hv.get("status", "—"),
            "last_successful_sync": s.get("last_successful_sync") or hv.get("last_successful_sync"),
            "last_attempted_sync": s.get("last_attempted_sync") or hv.get("last_attempted_sync"),
            "latest_document_date": s.get("latest_document_date"),
            "last_skipped_at": s.get("last_skipped_at"),
            "last_skip_reason": s.get("last_skip_reason"),
            "blocked": s.get("blocked"),
            "detail": hv.get("detail", ""),
        })
    return {"rows": rows}


def build_cache() -> dict:
    """Phase D §1·§6: company-level raw cache 현황.

    캐시 엔트리는 payload 를 복제하지 않고 raw 파일을 가리키는 포인터라서,
    여기서 보여주는 건 '어떤 종목을 네트워크 없이 되살릴 수 있나' 다.
    secret 은 애초에 캐시 키/엔트리에 들어가지 않는다(cache.stable_key)."""
    import json as _json
    import time as _t

    cfg = _json.loads((Path(__file__).resolve().parent.parent
                       / "config" / "data_sources.json").read_text(encoding="utf-8"))
    h = store.get_health()
    rows, entries = [], []

    for prov_key, prefix in (("sec_edgar", "concepts"), ("opendart", "statements")):
        pconf = cfg["providers"].get(prov_key, {})
        ttl = int(pconf.get("raw_cache_ttl_sec") or pconf.get("update_policy_sec") or 0)
        hv = h.get(prov_key, {})
        rows.append({
            "provider": prov_key,
            "status": hv.get("status", "—"),
            "provider_ttl_sec": pconf.get("update_policy_sec"),
            "raw_cache_ttl_sec": ttl,
            "cache_hits": hv.get("cache_hits", 0),
            "cache_misses": hv.get("cache_misses", 0),
            "company_count": hv.get("company_count", 0),
            "blocked": hv.get("no_network_blocked_count", 0),
            "detail": hv.get("detail", ""),
        })
        d = store.RAW_DIR / prov_key
        if not d.exists():
            continue
        for cov in cfg["covered"]:
            slug = cov.get("slug")
            cands = sorted(d.glob(f"{prefix}_{slug}_*.json"),
                           key=lambda f: f.stat().st_mtime, reverse=True)
            if not cands:
                continue
            f = cands[0]
            age = _t.time() - f.stat().st_mtime
            entries.append({
                "provider": prov_key, "slug": slug,
                "age_sec": int(age),
                "ttl_sec": ttl,
                "fresh": bool(ttl and age <= ttl),
                "bytes": f.stat().st_size,
                "raw_ref": f"raw/{prov_key}/{f.name}",
            })
    return {"rows": rows, "entries": entries}


def build_pb() -> dict:
    return {
        "ACTUAL": bdd.build_actual(),
        "LEGACY": build_legacy(),
        "HEALTH": bdd.build_health(),
        "SYNC": build_sync(),
        "CACHE": build_cache(),
        "GENERATED_AT": store._now(),
    }


HTML = """<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Phase C · Incremental Sync & Provenance</title>
<style>
:root{color-scheme:light;--bg:#f5f7fa;--card:#fff;--ink:#161a22;--sub:#5b6472;--line:#e6e9ef;--green:#16a34a;--red:#dc2626;--amber:#d97706;--violet:#7c3aed;--slate:#475569;--blue:#2563eb}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Malgun Gothic",sans-serif;line-height:1.55;font-size:14px}
.wrap{max-width:1080px;margin:0 auto;padding:20px 16px 90px}h1{font-size:20px;margin:0 0 4px}
.meta{color:var(--sub);font-size:12px;margin-bottom:14px}
section{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:15px 17px;margin:12px 0}
h2{font-size:15px;margin:0 0 8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
h2 .k{font-size:10px;font-weight:700;color:#fff;background:var(--slate);border-radius:6px;padding:2px 8px}
h3{font-size:13px;margin:14px 0 6px;color:var(--slate)}.q{color:var(--sub);font-style:italic}
table{width:100%;border-collapse:collapse;font-size:12px;margin-top:6px}th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}th{background:#f8fafc}
select{border:1px solid var(--line);background:#fff;border-radius:8px;padding:6px 12px;font-size:12.5px;font-weight:600}
code{background:#f1f4f9;border-radius:4px;padding:1px 5px;font-size:11px}
.pill{display:inline-block;font-size:9.5px;font-weight:800;padding:2px 7px;border-radius:999px}
.pill.n{background:#dcfce7;color:#166534}.pill.d{background:#ede9fe;color:#5b21b6}.pill.b{background:#fee2e2;color:#991b1b}.pill.w{background:#fef9c3;color:#854d0e}
.pill.s{background:#dbeafe;color:#1e40af}.pill.g{background:#dcfce7;color:#166534}
.spark{font-family:ui-monospace,monospace;font-size:10.5px;color:var(--sub)}.mrow{cursor:pointer}.mrow:hover{background:#f8fafc}
.box{background:#fff;border:1px solid var(--line);border-radius:14px;max-width:560px;padding:16px 18px;box-shadow:0 12px 44px rgba(0,0,0,.14);max-height:86vh;overflow:auto}
.arow{display:flex;justify-content:space-between;gap:12px;font-size:11.5px;padding:5px 0;border-bottom:1px solid var(--line)}.arow .l{color:var(--sub);flex-shrink:0}
.ok{background:#f0fdf4;border-left:3px solid var(--green);border-radius:6px;padding:8px 12px;font-size:12px;margin:8px 0}
.bad{background:#fef2f2;border-left:3px solid var(--red);border-radius:6px;padding:8px 12px;font-size:12px;margin:8px 0}
.note{background:#eff6ff;border-left:3px solid var(--blue);border-radius:6px;padding:8px 12px;font-size:12px;margin:8px 0}
</style></head><body><div class="wrap">
<h1>Phase D — Company Cache, No-Network & Provenance</h1>
<div class="meta">actual 숫자: dashboard node → <code>record_id</code> → <code>raw_ref</code> → accession → 원문 filing URL.
SEC EDGAR + OpenDART live. 증분 동기화(TTL) · <b>company 단위 raw cache</b> · <code>--no-network</code> · append-only dedup · secret 미노출. <b>index.html 미수정.</b>
<span id="gen" class="q"></span></div>

<section><h2><span class="k">§14</span>Incremental Sync / TTL · 운영 상태</h2>
<div class="q" style="font-size:11.5px">provider별 <code>update_policy_sec</code> 안이면 <span class="pill s">SKIPPED</span> (ttl_fresh) — 외부 호출 없음, 실패 아님. <code>--force</code> 로 우회.</div>
<div id="sync"></div></section>

<section><h2><span class="k">§D1</span>Company-level Raw Cache</h2>
<div class="q" style="font-size:11.5px">provider TTL 은 <b>얼마나 자주 시도하나</b>, raw cache TTL 은 <b>받아둔 스냅샷을 얼마나 오래 믿나</b>.
종목별 raw 가 신선하면 API 재호출 없이 normalized 를 다시 만든다. <code>--force</code> 는 둘 다 우회한다.</div>
<div id="cache"></div>
<h3>종목별 스냅샷</h3><div id="centries"></div>
<div class="note"><code>--dry-run</code> = 외부 <b>저장</b> 없음 · <code>--no-network</code> = 외부 <b>호출</b> 없음.
둘을 같이 주면 완전 무해 점검 모드. cache miss 인데 no-network 면 API 를 때리지 않고
<span class="pill s">blocked</span> 로 보고한다(netguard 로 강제).</div></section>

<section><h2><span class="k">§16</span>Actual Analysis Layer</h2>
<div><select id="co"></select> <span class="q">행 클릭 = 전체 provenance 체인(§8·§17)</span></div>
<div id="layer"></div></section>

<section><h2><span class="k">§12·§15</span>Legacy / estimate-dependent (core_eligible=false)</h2>
<div class="q" style="font-size:11.5px">MC 파생 — forward EPS · cycle P/E 의존. 삭제 안 함, actual core 에서 제외 표시.</div>
<div id="legacy"></div></section>

<section><h2><span class="k">§13</span>Provider Health</h2><div id="health"></div></section>
</div>
<script>
var PB=__PB__;
var ACTUAL=PB.ACTUAL,LEGACY=PB.LEGACY,HEALTH=PB.HEALTH,SYNC=PB.SYNC,CACHE=PB.CACHE||{};
var GORD=["PRICE","INCOME","BALANCE_SHEET","CASH_FLOW","DERIVED"];
document.getElementById("gen").textContent=" · generated "+(PB.GENERATED_AT||"");
function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];});}
function fv(m,v){if(v==null||v==="—")return "—";if(/margin|_yoy|_qoq|debt_to_equity/.test(m))return (v>=0?"+":"")+(v*100).toFixed(1)+"%";
 if(/eps|price/.test(m))return Number(v).toLocaleString();var a=Math.abs(v);
 if(a>=1e12)return (v/1e12).toFixed(2)+"조";if(a>=1e9)return (v/1e9).toFixed(2)+"B";if(a>=1e6)return (v/1e6).toFixed(1)+"M";return Number(v).toLocaleString();}
function hstr(h){return (h==null||h==="")?"—":esc(h);}
function statusPill(s){var c={HEALTHY:"g",WARNING:"w",ERROR:"b",NOT_CONFIGURED:"b",SKIPPED:"s"}[s]||"w";return '<span class="pill '+c+'">'+esc(s||"—")+'</span>';}
function dur(s){if(s==null)return "—";var a=Math.abs(s);
 if(a<60)return Math.round(a)+"초";if(a<3600)return Math.round(a/60)+"분";
 if(a<86400)return (a/3600).toFixed(1)+"시간";return (a/86400).toFixed(1)+"일";}
function kb(n){return n>=1048576?(n/1048576).toFixed(1)+" MB":Math.round(n/1024)+" KB";}
function renderCache(){var el=document.getElementById("cache"),rows=(CACHE.rows)||[];
 if(!rows.length){el.innerHTML='<div class="q">cache 정보 없음.</div>';}
 else{el.innerHTML='<table><thead><tr><th>provider</th><th>status</th><th>provider TTL</th><th>raw cache TTL</th>'
  +'<th>hits</th><th>misses</th><th>blocked</th><th>companies</th></tr></thead><tbody>'
  +rows.map(function(r){return '<tr><td>'+esc(r.provider)+'</td><td>'+statusPill(r.status)+'</td>'
   +'<td>'+dur(r.provider_ttl_sec)+'</td><td>'+dur(r.raw_cache_ttl_sec)+'</td>'
   +'<td><b>'+(r.cache_hits||0)+'</b></td><td>'+(r.cache_misses||0)+'</td>'
   +'<td>'+((r.blocked||0)?'<span class="pill s">'+r.blocked+'</span>':"0")+'</td>'
   +'<td>'+(r.company_count||0)+'</td></tr>';}).join("")+'</tbody></table>';}
 var es=(CACHE.entries)||[],e2=document.getElementById("centries");
 if(!es.length){e2.innerHTML='<div class="q">저장된 raw 스냅샷 없음.</div>';return;}
 e2.innerHTML='<table><thead><tr><th>provider</th><th>slug</th><th>나이</th><th>TTL</th>'
  +'<th>네트워크 없이 복원</th><th>크기</th><th>raw_ref</th></tr></thead><tbody>'
  +es.map(function(x){return '<tr><td>'+esc(x.provider)+'</td><td><b>'+esc(x.slug)+'</b></td>'
   +'<td>'+dur(x.age_sec)+'</td><td>'+dur(x.ttl_sec)+'</td>'
   +'<td>'+(x.fresh?'<span class="pill g">가능 (cache hit)</span>':'<span class="pill w">만료 — 재수집 필요</span>')+'</td>'
   +'<td class="q">'+kb(x.bytes)+'</td><td class="q">'+esc(x.raw_ref)+'</td></tr>';}).join("")
  +'</tbody></table>';}
function renderSync(){var el=document.getElementById("sync"),rows=(SYNC&&SYNC.rows)||[];
 if(!rows.length){el.innerHTML='<div class="q">sync_state 비어있음.</div>';return;}
 el.innerHTML='<table><thead><tr><th>provider</th><th>status</th><th>last success</th><th>last attempted</th><th>latest doc</th><th>last skip</th><th>blocked</th></tr></thead><tbody>'
 +rows.map(function(r){return '<tr><td>'+esc(r.provider)+'</td><td>'+statusPill(r.status)+'</td>'
  +'<td class="q">'+hstr(r.last_successful_sync)+'</td><td class="q">'+hstr(r.last_attempted_sync)+'</td>'
  +'<td class="q">'+hstr(r.latest_document_date)+'</td>'
  +'<td class="q">'+(r.last_skipped_at?hstr(r.last_skipped_at)+' <span class="pill s">'+esc(r.last_skip_reason||"skip")+'</span>':"—")+'</td>'
  +'<td class="q">'+(r.blocked?'<span class="pill b">'+esc(r.blocked)+'</span>':"—")+'</td></tr>';}).join("")
 +'</tbody></table>';}
function tbl(co,g,ms){var rows=Object.keys(ms).map(function(m){var n=ms[m];
 var sp=(n.history||[]).map(function(x){return esc(x.period)+":"+fv(m,x.value);}).join("  ");
 var vs=n.validation_status&&n.validation_status!=="VALID"?' <span class="pill w">'+esc(n.validation_status)+'</span>':'';
 var lp=n.layer==="DERIVED"?'<span class="pill d">D</span>':'<span class="pill n">N</span>';
 return '<tr class="mrow" data-co="'+co+'" data-g="'+g+'" data-m="'+esc(m)+'"><td>'+esc(m)+' '+lp+vs+'</td>'
  +'<td style="text-align:right;font-weight:700">'+fv(m,n.value)+'</td><td>'+esc(n.period||"")+' <span class="q">'+esc(n.form||"")+'</span></td>'
  +'<td class="spark">'+sp+'</td></tr>';}).join("");
 return '<h3>'+g.replace(/_/g," ")+'</h3><table><thead><tr><th>metric</th><th style="text-align:right">latest</th><th>period</th><th>history</th></tr></thead><tbody>'+rows+'</tbody></table>';}
function renderLayer(){var co=document.getElementById("co").value,b=document.getElementById("layer"),g=ACTUAL[co]||{};
 if(!g.INCOME&&!g.BALANCE_SHEET){b.innerHTML='<div class="bad">'+esc(co)+': 실제 공시 재무 없음.</div>'+(g.PRICE?tbl(co,"PRICE",g.PRICE):"");}
 else{b.innerHTML=GORD.filter(function(x){return g[x];}).map(function(x){return tbl(co,x,g[x]);}).join("");}
 b.querySelectorAll(".mrow").forEach(function(tr){tr.onclick=function(){prov(tr.dataset.co,tr.dataset.g,tr.dataset.m);};});}
function prov(co,g,m){var n=ACTUAL[co][g][m],ov=document.getElementById("ov");
 var chain=['<b>Provenance chain</b>','dashboard: '+esc(co)+' / '+esc(g)+' / '+esc(m),
  '  ↳ record_id: '+esc(n.record_id||"—"),'  ↳ raw_ref: '+esc(n.raw_ref||"—"),
  '  ↳ accession: '+esc(n.accession||"—"),'  ↳ URL: '+(n.url?'<a target="_blank" rel="noopener" href="'+esc(n.url)+'">filing</a>':"—")].join("\\n");
 var rows=[["Layer",n.layer],["Provider",n.source],["Source type",n.layer==="DERIVED"?"DERIVED":(n.source_type||"PRIMARY_OFFICIAL")],
  ["Metric",m],["Original 계정/XBRL tag",n.source_metric||"(derived)"],["Value",fv(m,n.value)+"  ("+(n.value!=null&&n.value!=="—"?Number(n.value).toLocaleString():"")+")"],
  ["Unit / Currency",n.currency||""],["Period",n.period||""],["Form",n.form||"—"],["fs_div",n.fs_div||"—"],
  ["Filing date",n.filing_date||"—"],["Available date",n.available_date||"—"],["Retrieved at",n.retrieved_at||"—"],
  ["Validation",(n.validation_status||"—")+(n.validation_notes&&n.validation_notes.length?" · "+n.validation_notes.join("; "):"")],
  ["Record ID",n.record_id||"—"]];
 if(n.formula)rows.push(["Formula",n.formula]);
 if(n.input_record_ids)rows.push(["Input record ids",(n.input_record_ids||[]).join(", ")]);
 if(n.core_eligible===false)rows.push(["core_eligible","false — estimate-dependent"]);
 ov.innerHTML='<div class="box"><pre style="white-space:pre-wrap;font-size:11px;background:#f8fafc;padding:8px;border-radius:6px">'+chain+'</pre>'
  +rows.map(function(r){return '<div class="arow"><span class="l">'+esc(r[0])+'</span><span style="text-align:right">'+(r[0]==="Formula"||r[0].indexOf("record id")>=0?esc(r[1]):r[1])+'</span></div>';}).join("")
  +'<div style="margin-top:10px;text-align:right"><button id="x">닫기</button></div></div>';
 ov.style.display="flex";document.getElementById("x").onclick=function(){ov.style.display="none";};}
function renderLegacy(){var el=document.getElementById("legacy"),rows="";
 Object.keys(LEGACY).forEach(function(co){Object.keys(LEGACY[co]).forEach(function(k){var n=LEGACY[co][k];
  rows+='<tr><td>'+esc(co)+'</td><td>'+esc(n.label||k)+'</td><td>'+fv(k,n.value)+'</td><td><span class="pill b">core_eligible=false</span></td><td class="q">'+esc((n.validation_notes||[]).join("; ")||n.legacy||"")+'</td></tr>';});});
 el.innerHTML=rows?'<table><thead><tr><th>slug</th><th>metric</th><th>value</th><th>flag</th><th>note</th></tr></thead><tbody>'+rows+'</tbody></table>':'<div class="q">estimate 의존 파생 없음.</div>';}
function renderHealth(){var el=document.getElementById("health");
 el.innerHTML='<table><thead><tr><th>provider</th><th>status</th><th>fetched</th><th>new</th><th>dupes</th><th>warns</th><th>resp ms</th><th>last attempted</th><th>last error</th></tr></thead><tbody>'
 +HEALTH.map(function(r){return '<tr><td>'+esc(r.provider)+'</td><td>'+statusPill(r.status)+'</td><td>'+(r.records_fetched||0)+'</td><td>'+((r.new_records!=null?r.new_records:r.records_added)||0)+'</td><td>'+(r.duplicates||0)+'</td><td>'+(r.validation_warnings||0)+'</td><td>'+hstr(r.response_ms!=null?r.response_ms:r.response_time_ms)+'</td><td class="q">'+esc(r.last_attempted_sync||r.last_sync||"")+'</td><td class="q">'+esc(r.last_error||"")+'</td></tr>';}).join("")+'</tbody></table>';}
var sel=document.getElementById("co");
Object.keys(ACTUAL).forEach(function(s){var o=document.createElement("option");o.value=s;o.textContent=s+" ("+(ACTUAL[s].INCOME?(s==="samsung"||s==="skhynix"?"OpenDART":"SEC"):"price only")+")";sel.appendChild(o);});
sel.onchange=renderLayer;
var ov=document.createElement("div");ov.id="ov";ov.style.cssText="display:none;position:fixed;inset:0;background:rgba(0,0,0,.35);align-items:center;justify-content:center;padding:20px;z-index:50";
ov.onclick=function(e){if(e.target===ov)ov.style.display="none";};document.body.appendChild(ov);
renderCache();renderSync();renderLayer();renderLegacy();renderHealth();
</script></body></html>
"""


def main() -> None:
    pb = build_pb()
    blob = json.dumps(pb, ensure_ascii=False, separators=(",", ":"))
    bdd._assert_no_secret(blob, "DS_hook_prototype PB blob")
    # 방어: OpenDART API request URL(crtfc_key 포함 가능) 이 혹시라도 노드에 들어오면 차단
    if "opendart.fss.or.kr/api" in blob or "crtfc_key" in blob:
        raise SystemExit("prototype: OpenDART API URL/crtfc_key 감지 → 중단")
    html = HTML.replace("__PB__", blob)
    OUT.write_text(html, encoding="utf-8")
    n_actual = sum(len(ms) for gr in pb["ACTUAL"].values() for ms in gr.values())
    print(f"wrote {OUT}  ({len(html):,} bytes)")
    print(f"  ACTUAL: {len(pb['ACTUAL'])} slug / {n_actual} metric")
    print(f"  LEGACY: {sum(len(v) for v in pb['LEGACY'].values())} metric")
    print(f"  HEALTH: {len(pb['HEALTH'])} provider   SYNC: {len(pb['SYNC']['rows'])} provider")
    print("  secret scan: PASS   index.html: 미수정")


if __name__ == "__main__":
    main()
