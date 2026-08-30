import json, re, os
D="/sessions/hopeful-sweet-hopper/mnt/outputs/damo"
def num(x):
    x=x.strip()
    if x in("NA","","-"): return None
    x=x.replace("%","").replace(",","")
    try:
        v=float(x); return v
    except: return None
def pct(x):
    v=num(x); return None if v is None else round(v/100,4)
def rows(fn):
    out=[]
    for ln in open(os.path.join(D,fn),encoding="utf-8"):
        ln=ln.rstrip("\n")
        if not ln.strip() or "|" not in ln: continue
        parts=[p.strip() for p in ln.split("|")]
        out.append(parts)
    return out
data={}
def key(n): return re.sub(r"\s+"," ",n).strip()
# WACC: name|n|beta|Ke|E/(D+E)|std|Kd|tax|aftKd|D/(D+E)|WACC
for p in rows("wacc_raw.txt"):
    k=key(p[0]); data.setdefault(k,{"industry":k})
    data[k].update(n_firms=int(num(p[1])), beta=num(p[2]), cost_of_equity=pct(p[3]),
        equity_weight=pct(p[4]), pretax_cost_of_debt=pct(p[6]), wacc=pct(p[10]))
# PBV: name|n|PBV|ROE|EV/InvCap|ROIC
for p in rows("pbv_raw.txt"):
    k=key(p[0]); data.setdefault(k,{"industry":k})
    data[k].update(pbv=num(p[2]), roe=pct(p[3]), ev_invcap=num(p[4]), roic=pct(p[5]))
# PE: name|n|%ml|curPE|trailPE|fwdPE|mc/ni_all|mc/ni_mm|expg5|PEG
for p in rows("pe_raw.txt"):
    k=key(p[0]); data.setdefault(k,{"industry":k})
    data[k].update(pe_current=num(p[3]), pe_trailing=num(p[4]), pe_forward=num(p[5]),
        exp_growth_5y=pct(p[8]), peg=num(p[9]))
# margin/ev: name|net|op_pretax|ebitda|ev_ebitda|ev_ebit
for p in rows("marginev_raw.txt"):
    k=key(p[0]); data.setdefault(k,{"industry":k})
    data[k].update(net_margin=pct(p[1]), operating_margin_pretax=pct(p[2]),
        ebitda_margin=pct(p[3]), ev_ebitda=num(p[4]), ev_ebit=num(p[5]))
out={"source":"Aswath Damodaran / NYU Stern (pages.stern.nyu.edu/~adamodar)",
 "as_of":"2026-01","region":"US industry aggregates (USD)",
 "market":{"implied_ERP_FCFE_2025":0.0423,"tbond_rate_2025":0.0418},
 "note":"KR/비US는 통화·CRP 조정. 사이클 업종은 peak EBITDA에 EV/EBITDA 직접 곱하지 말 것.",
 "sectors":data}
json.dump(out,open("/sessions/hopeful-sweet-hopper/mnt/AI주식리서치/학습자료/damodaran_allsectors.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
print("sectors:",len(data))
# quick integrity: sectors missing any block
miss=[k for k,v in data.items() if any(f not in v for f in["beta","pbv","pe_forward","ebitda_margin"])]
print("incomplete:",miss)
# sanity prints
for s in ["Semiconductor","Bank (Money Center)","Drugs (Pharmaceutical)","Household Products","Oil/Gas (Production and Exploration)"]:
    print(s, data[s])
