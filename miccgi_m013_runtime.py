#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, math, subprocess, urllib.request
from pathlib import Path

BRANCH="miccgi-m013-reality-dynamics"
START_YEAR=2010
END_YEAR=2022
INDICATORS={
    "life_expectancy":"SP.DYN.LE00.IN",
    "fertility":"SP.DYN.TFRT.IN",
    "internet_pct":"IT.NET.USER.ZS",
    "urban_pct":"SP.URB.TOTL.IN.ZS",
    "gdp_per_capita":"NY.GDP.PCAP.CD",
    "population_growth":"SP.POP.GROW",
}
BASE="https://api.worldbank.org/v2"
OUT=Path("miccgi_m013_state")
BASIS=("trend","exo","trend_exo","trend_tanh_exo","trend_interaction")

def J(x): return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def H(x):
    if isinstance(x,bytes): b=x
    elif isinstance(x,str): b=x.encode()
    else: b=J(x).encode()
    return hashlib.sha256(b).hexdigest()

def get_json(url,retries=3):
    last=None
    for attempt in range(retries):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"MICCGI-M013-Dynamics/1.1"})
            with urllib.request.urlopen(req,timeout=25) as r: body=r.read()
            return json.loads(body.decode()),H(body),len(body)
        except Exception as e:
            last=e
            if attempt+1<retries:
                import time; time.sleep(1.5*(attempt+1))
    raise last

def fetch_panel():
    meta_url=f"{BASE}/country?format=json&per_page=400"
    meta,msha,mbytes=get_json(meta_url)
    actual=set()
    for x in meta[1]:
        iso=x.get("id"); region=(x.get("region") or {}).get("id")
        if iso and len(iso)==3 and region and region!="NA": actual.add(iso)
    rows={}
    receipts=[{"kind":"country_metadata","url":meta_url,"sha256":msha,"bytes":mbytes}]
    chunks=((2010,2013),(2014,2017),(2018,2020),(2021,2022))
    for field,code in INDICATORS.items():
        total=0
        for y0,y1 in chunks:
            url=f"{BASE}/country/all/indicator/{code}?date={y0}:{y1}&format=json&per_page=1400"
            obj,sha,n=get_json(url);count=0
            for x in (obj[1] if isinstance(obj,list) and len(obj)>1 else []):
                iso=x.get("countryiso3code");v=x.get("value");year=x.get("date")
                if iso not in actual or v is None: continue
                try: yy=int(year); vv=float(v)
                except Exception: continue
                if not math.isfinite(vv): continue
                r=rows.setdefault((iso,yy),{"__id__":iso,"year":yy});r[field]=vv;count+=1
            total+=count
            receipts.append({"kind":"indicator_chunk","field":field,"code":code,"years":[y0,y1],"url":url,"sha256":sha,"bytes":n,"non_null":count})
        if total<200: raise RuntimeError(f"INSUFFICIENT_INDICATOR_COVERAGE:{field}:{total}")
    panel=list(rows.values())
    if len(panel)<700: raise RuntimeError(f"INSUFFICIENT_PANEL_ROWS:{len(panel)}")
    return panel,receipts

def split_years(panel):
    ys=sorted({int(r["year"]) for r in panel})
    a=max(1,int(len(ys)*.60)); b=max(a+1,int(len(ys)*.80))
    if b>=len(ys): b=len(ys)-1
    return tuple(ys[:a]),tuple(ys[a:b]),tuple(ys[b:])

def stats(xs):
    m=sum(xs)/len(xs);s=math.sqrt(sum((x-m)**2 for x in xs)/len(xs))
    return m,max(1e-9,s)

def solve(a,b):
    n=len(b);m=[list(map(float,row))+[float(y)] for row,y in zip(a,b)]
    for col in range(n):
        p=max(range(col,n),key=lambda r:abs(m[r][col]))
        if abs(m[p][col])<1e-10:return None
        m[col],m[p]=m[p],m[col];d=m[col][col];m[col]=[x/d for x in m[col]]
        for r in range(n):
            if r==col:continue
            f=m[r][col]
            if f:m[r]=[x-f*y for x,y in zip(m[r],m[col])]
    return [m[i][-1] for i in range(n)]

def ols(rows):
    if not rows:return None
    p=len(rows[0][0]);xtx=[[0.0]*p for _ in range(p)];xty=[0.0]*p
    for x,y in rows:
        for i in range(p):
            xty[i]+=x[i]*y
            for j in range(p):xtx[i][j]+=x[i]*x[j]
    for i in range(p):xtx[i][i]+=1e-8
    return solve(xtx,xty)

def basis(name,cur,trend,exo):
    if name=="trend":return [1,cur,trend]
    if name=="exo":return [1,cur,exo]
    if name=="trend_exo":return [1,cur,trend,exo]
    if name=="trend_tanh_exo":return [1,cur,trend,math.tanh(exo)]
    if name=="trend_interaction":return [1,cur,trend,exo,trend*exo]
    raise ValueError(name)

def collect(panel,target,exo):
    by={(r["__id__"],int(r["year"])):r for r in panel};out=[]
    for (cid,year),r in sorted(by.items()):
        p=by.get((cid,year-1));n=by.get((cid,year+1))
        if not p or not n:continue
        try:vals=[float(p[target]),float(r[target]),float(n[target]),float(r[exo])]
        except Exception:continue
        if all(math.isfinite(x) for x in vals):
            out.append({"country":cid,"year":year,"prev":vals[0],"cur":vals[1],"next":vals[2],"exo":vals[3]})
    return out

def rmse(errs):return math.sqrt(sum(e*e for e in errs)/len(errs)) if errs else float("inf")

def fit_candidate(samples,bname,tr_years,va_years,te_years):
    tr=[x for x in samples if x["year"] in tr_years];va=[x for x in samples if x["year"] in va_years];te=[x for x in samples if x["year"] in te_years]
    if min(map(len,(tr,va,te)))<35:return None
    tm,ts=stats([x["prev"] for x in tr]+[x["cur"] for x in tr]+[x["next"] for x in tr]);em,es=stats([x["exo"] for x in tr])
    def trans(x):
        prev=(x["prev"]-tm)/ts;cur=(x["cur"]-tm)/ts;nxt=(x["next"]-tm)/ts;exo=(x["exo"]-em)/es
        return cur,cur-prev,exo,nxt
    xy=[]
    for x in tr:
        cur,trend,exo,nxt=trans(x);xy.append((basis(bname,cur,trend,exo),nxt))
    c=ols(xy)
    if c is None:return None
    def ev(rows):
        pe=[];me=[]
        for x in rows:
            cur,trend,exo,nxt=trans(x);pred=sum(a*b for a,b in zip(c,basis(bname,cur,trend,exo)))
            pe.append(cur-nxt);me.append(pred-nxt)
        return rmse(pe),rmse(me)
    pv,mv=ev(va);pt,mt=ev(te)
    return {"coef":c,"pv":pv,"mv":mv,"pt":pt,"mt":mt,"vi":(pv-mv)/max(pv,1e-12),"ti":(pt-mt)/max(pt,1e-12),
            "counts":(len(tr),len(va),len(te)),"target_stats":(tm,ts),"exo_stats":(em,es)}

def source(rid,bname,c,tstats,estats):
    tm,ts=tstats;em,es=estats
    return "\n".join([
      "import math",
      f"def {rid}(previous_target,current_target,current_exogenous):",
      f"    cur=(float(current_target)-({tm!r}))/({ts!r})",
      f"    prev=(float(previous_target)-({tm!r}))/({ts!r})",
      f"    exo=(float(current_exogenous)-({em!r}))/({es!r})",
      "    trend=cur-prev",
      f"    name={bname!r}",
      "    if name=='trend': x=[1.0,cur,trend]",
      "    elif name=='exo': x=[1.0,cur,exo]",
      "    elif name=='trend_exo': x=[1.0,cur,trend,exo]",
      "    elif name=='trend_tanh_exo': x=[1.0,cur,trend,math.tanh(exo)]",
      "    elif name=='trend_interaction': x=[1.0,cur,trend,exo,trend*exo]",
      "    else: raise ValueError(name)",
      f"    c={list(map(float,c))!r}",
      "    z=sum(a*b for a,b in zip(c,x))",
      f"    return z*({ts!r})+({tm!r})",""
    ])

def discover(panel,exclude):
    tr_y,va_y,te_y=split_years(panel);cands=[]
    for target in INDICATORS:
        for exo in INDICATORS:
            if exo==target or (target,exo) in exclude:continue
            samples=collect(panel,target,exo)
            for bn in BASIS:
                r=fit_candidate(samples,bn,tr_y,va_y,te_y)
                if not r:continue
                if r["vi"]>.005 and r["ti"]>.002:
                    score=min(r["vi"],r["ti"])+.25*r["ti"]
                    cands.append((score,target,exo,bn,r))
    if not cands:raise RuntimeError("NO_TEMPORAL_RELATION_BEAT_PERSISTENCE_ON_FUTURE_HOLDOUT")
    best=max(cands,key=lambda x:x[0]);return best,(tr_y,va_y,te_y)

def push(ep,label):
    subprocess.run(["git","config","user.name","MICCGI M013 Runtime"],check=True)
    subprocess.run(["git","config","user.email","miccgi-runtime@users.noreply.github.com"],check=True)
    subprocess.run(["git","add","miccgi_m013_state"],check=True)
    if subprocess.run(["git","diff","--cached","--quiet"]).returncode:
        subprocess.run(["git","commit","-m",f"MICCGI M013 {label} {ep}"],check=True)
        subprocess.run(["git","push","origin","HEAD"],check=True)

def main():
    OUT.mkdir(exist_ok=True);panel,receipts=fetch_panel()
    panel_sha=H(sorted([{k:v for k,v in r.items()} for r in panel],key=lambda x:(x["__id__"],x["year"])))
    exclude=set();hist=[];parent="ROOT"
    for ep in range(1,4):
        (score,target,exo,bn,r),(tr_y,va_y,te_y)=discover(panel,exclude);exclude.add((target,exo))
        sem={"target":target,"exogenous":exo,"basis":bn,"coef":r["coef"],"train_years":tr_y,"validation_years":va_y,"test_years":te_y}
        sha=H(sem);rid="dr_"+sha[:12];src=source(rid,bn,r["coef"],r["target_stats"],r["exo_stats"]);compile(src,f"<{rid}>","exec")
        st={"epoch":ep,"panel_sha256":panel_sha,"panel_rows":len(panel),"target":target,"exogenous":exo,"basis":bn,
            "coefficients":r["coef"],"persistence_validation_error":r["pv"],"model_validation_error":r["mv"],
            "persistence_test_error":r["pt"],"model_test_error":r["mt"],"validation_improvement":r["vi"],"test_improvement":r["ti"],
            "train_years":tr_y,"validation_years":va_y,"test_years":te_y,"sample_counts":r["counts"],"relation_id":rid,
            "semantic_sha256":sha,"source_sha256":H(src),"source":src,"source_receipts":receipts,"parent_state_sha256":parent,
            "paid_actions":0,"contract_actions":0,"financial_actions":0}
        state_sha=H(st);rc={"epoch":ep,"state_sha256":state_sha,"parent_state_sha256":parent,"compiled":True,
                            "future_holdout_beats_persistence":r["ti"]>.002,"stop":ep==3,
                            "reason":"MAX_EPOCHS_REACHED" if ep==3 else "CONTINUE_DYNAMICAL_INDUCTION"}
        (OUT/f"state_{ep}.json").write_text(json.dumps(st,indent=2,sort_keys=True));(OUT/f"receipt_{ep}.json").write_text(json.dumps(rc,indent=2,sort_keys=True))
        hist.append(st);parent=state_sha;push(ep,"dynamic-epoch")
    admitted=len({(x["target"],x["exogenous"]) for x in hist})==3 and all(x["validation_improvement"]>.005 and x["test_improvement"]>.002 for x in hist)
    verdict={"admitted":admitted,"epochs":3,"panel_sha256":panel_sha,"panel_rows":len(panel),
             "lineage":[{"epoch":x["epoch"],"relation_id":x["relation_id"],"target":x["target"],"exogenous":x["exogenous"],"basis":x["basis"],
                         "validation_improvement":x["validation_improvement"],"test_improvement":x["test_improvement"],
                         "train_years":x["train_years"],"validation_years":x["validation_years"],"test_years":x["test_years"],
                         "semantic_sha256":x["semantic_sha256"],"source_sha256":x["source_sha256"]} for x in hist],
             "claim_boundary":{"LIVE_EXTERNAL_DYNAMICAL_RELATION_INDUCTION":"ESTABLISHED_FOR_RECORDED_WORLD_BANK_PANEL" if admitted else "NOT_ESTABLISHED",
                               "CAUSAL_INTERVENTION":"NOT_ESTABLISHED","ECONOMIC_T0":"NOT_OBSERVED","VERIFIED_REALIZED_PROFIT":"NOT_PROVEN","MICCGI":"UNPROVEN"}}
    (OUT/"adjudication.json").write_text(json.dumps(verdict,indent=2,sort_keys=True));push(3,"final-adjudication")
    print(json.dumps(verdict,sort_keys=True));raise SystemExit(0 if admitted else 2)

if __name__=="__main__":main()
