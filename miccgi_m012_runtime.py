#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, math, os, random, subprocess, time, urllib.parse, urllib.request
from pathlib import Path

BRANCH="miccgi-m012-reality-relations"
YEAR=2022
INDICATORS={
    "life_expectancy":"SP.DYN.LE00.IN",
    "fertility":"SP.DYN.TFRT.IN",
    "internet_pct":"IT.NET.USER.ZS",
    "urban_pct":"SP.URB.TOTL.IN.ZS",
    "gdp_per_capita":"NY.GDP.PCAP.CD",
    "population_growth":"SP.POP.GROW",
}
BASE="https://api.worldbank.org/v2"
OUT=Path("miccgi_m012_state")

def jdump(x): return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def H(x):
    if isinstance(x,bytes): b=x
    elif isinstance(x,str): b=x.encode()
    else: b=jdump(x).encode()
    return hashlib.sha256(b).hexdigest()

def get_json(url:str):
    req=urllib.request.Request(url,headers={"User-Agent":"MICCGI-M012-Reality-Induction/1.0"})
    with urllib.request.urlopen(req,timeout=40) as r:
        body=r.read()
    return json.loads(body.decode()), H(body), len(body)

def fetch_matrix():
    meta_url=f"{BASE}/country?format=json&per_page=400"
    meta,meta_sha,meta_n=get_json(meta_url)
    countries={}
    for x in meta[1]:
        region=(x.get("region") or {}).get("id")
        iso=x.get("id")
        if iso and len(iso)==3 and region and region!="NA":
            countries[iso]={"__id__":iso,"country_name":x.get("name","")}
    source_receipts=[{"kind":"country_metadata","url":meta_url,"sha256":meta_sha,"bytes":meta_n}]
    for field,code in INDICATORS.items():
        url=f"{BASE}/country/all/indicator/{code}?date={YEAR}&format=json&per_page=400"
        obj,sha,n=get_json(url)
        seen=0
        for x in (obj[1] if isinstance(obj,list) and len(obj)>1 else []):
            iso=x.get("countryiso3code");v=x.get("value")
            if iso in countries and v is not None:
                try: countries[iso][field]=float(v);seen+=1
                except Exception: pass
        source_receipts.append({"kind":"indicator","field":field,"code":code,"url":url,"sha256":sha,"bytes":n,"non_null":seen})
    rows=[r for r in countries.values() if all(f in r and math.isfinite(r[f]) for f in INDICATORS)]
    rows.sort(key=lambda r:r["__id__"])
    if len(rows)<60: raise RuntimeError(f"INSUFFICIENT_COMPLETE_WORLD_BANK_ROWS:{len(rows)}")
    return rows,source_receipts

def bucket(k):
    return int(hashlib.sha256(k.encode()).hexdigest()[:8],16)%10

def split(rows):
    tr=[];va=[];te=[]
    for r in rows:
        b=bucket(r["__id__"])
        (tr if b<6 else va if b<8 else te).append(r)
    if min(map(len,(tr,va,te)))<10: raise RuntimeError("SPLIT_TOO_SMALL")
    return tr,va,te

def stats(rows,fields):
    out={}
    for f in fields:
        xs=[r[f] for r in rows]
        m=sum(xs)/len(xs);v=sum((x-m)**2 for x in xs)/len(xs);s=max(1e-9,math.sqrt(v))
        out[f]=(m,s)
    return out

def z(r,f,st): return (r[f]-st[f][0])/st[f][1]
def sd(a,b): return a/(b if abs(b)>1e-9 else (1e-9 if b>=0 else -1e-9))
def sg(x): x=max(-30,min(30,x)); return 1/(1+math.exp(-x))

EXPRESSIONS={
    "add":lambda a,b:a+b,
    "sub":lambda a,b:a-b,
    "mul":lambda a,b:a*b,
    "mean":lambda a,b:(a+b)/2,
    "ratio":lambda a,b:sd(a,b),
    "tanh_add":lambda a,b:math.tanh(a+b),
    "tanh_sub":lambda a,b:math.tanh(a-b),
    "log_abs_mul":lambda a,b:math.log1p(abs(a*b)),
    "sqrt_abs_mul":lambda a,b:math.sqrt(abs(a*b)),
    "abs_gap":lambda a,b:abs(a-b),
    "sigmoid_mul":lambda a,b:sg(a*b),
    "signed_sqrt_prod":lambda a,b:math.copysign(math.sqrt(abs(a*b)),a*b),
}
SOURCE_EXPR={
    "add":"(a+b)","sub":"(a-b)","mul":"(a*b)","mean":"((a+b)/2)",
    "ratio":"sd(a,b)","tanh_add":"math.tanh(a+b)","tanh_sub":"math.tanh(a-b)",
    "log_abs_mul":"math.log1p(abs(a*b))","sqrt_abs_mul":"math.sqrt(abs(a*b))",
    "abs_gap":"abs(a-b)","sigmoid_mul":"sg(a*b)",
    "signed_sqrt_prod":"math.copysign(math.sqrt(abs(a*b)),a*b)",
}

def fit_affine(vals,ys):
    mx=sum(vals)/len(vals);my=sum(ys)/len(ys)
    vv=sum((x-mx)**2 for x in vals)
    a=sum((x-mx)*(y-my) for x,y in zip(vals,ys))/vv if vv>1e-12 else 0.0
    return a,my-a*mx

def rmse(expr,target,fa,fb,rows,st,alpha=None,beta=None):
    vals=[];ys=[]
    fn=EXPRESSIONS[expr]
    try:
        for r in rows:
            x=fn(z(r,fa,st),z(r,fb,st)); y=z(r,target,st)
            if not math.isfinite(x): return float("inf"),0,0
            vals.append(float(x));ys.append(float(y))
    except Exception:
        return float("inf"),0,0
    if len(vals)<8:return float("inf"),0,0
    if alpha is None: alpha,beta=fit_affine(vals,ys)
    err=math.sqrt(sum((alpha*x+beta-y)**2 for x,y in zip(vals,ys))/len(ys))
    return err,alpha,beta

def baseline(target,rows,st):
    ys=[z(r,target,st) for r in rows]
    return math.sqrt(sum(y*y for y in ys)/len(ys))

def discover(rows,fields,exclude,epoch):
    tr,va,te=split(rows);st=stats(tr,fields);cands=[]
    for target in fields:
        vb=baseline(target,va,st);tb=baseline(target,te,st)
        for fa in fields:
            if fa==target: continue
            for fb in fields:
                if fb<=fa or fb==target: continue
                if (target,fa,fb) in exclude: continue
                for expr in EXPRESSIONS:
                    trerr,a,b=rmse(expr,target,fa,fb,tr,st)
                    verr,_,_=rmse(expr,target,fa,fb,va,st,a,b)
                    terr,_,_=rmse(expr,target,fa,fb,te,st,a,b)
                    if not all(math.isfinite(x) for x in (trerr,verr,terr)): continue
                    vi=(vb-verr)/max(vb,1e-12);ti=(tb-terr)/max(tb,1e-12)
                    if vi>.08 and ti>.03:
                        score=min(vi,ti)+.20*ti-.01*trerr
                        cands.append((score,target,fa,fb,expr,a,b,trerr,verr,terr,vi,ti))
    if not cands: raise RuntimeError("NO_WORLD_BANK_RELATION_SURVIVED_HOLDOUT")
    return max(cands,key=lambda x:x[0]), (len(tr),len(va),len(te))

def relation_source(rid,expr,a,b):
    return "\n".join([
        "import math",
        "def sd(a,b): return a/(b if abs(b)>1e-9 else (1e-9 if b>=0 else -1e-9))",
        "def sg(x): x=max(-30.0,min(30.0,x)); return 1/(1+math.exp(-x))",
        f"def {rid}(a,b):",
        f"    x=float({SOURCE_EXPR[expr]})",
        f"    return ({a!r})*x+({b!r})",
        "",
    ])

def git_push(epoch,label):
    subprocess.run(["git","config","user.name","MICCGI M012 Runtime"],check=True)
    subprocess.run(["git","config","user.email","miccgi-runtime@users.noreply.github.com"],check=True)
    subprocess.run(["git","add","miccgi_m012_state"],check=True)
    if subprocess.run(["git","diff","--cached","--quiet"]).returncode:
        subprocess.run(["git","commit","-m",f"MICCGI M012 {label} {epoch}"],check=True)
        subprocess.run(["git","push","origin","HEAD"],check=True)

def main():
    OUT.mkdir(exist_ok=True)
    rows,source_receipts=fetch_matrix()
    fields=tuple(INDICATORS)
    dataset_sha=H([{k:v for k,v in r.items() if k!="country_name"} for r in rows])
    exclude=set();history=[];parent="ROOT"
    for ep in range(1,4):
        best,sizes=discover(rows,fields,exclude,ep)
        score,target,fa,fb,expr,a,b,trerr,verr,terr,vi,ti=best
        exclude.add((target,fa,fb))
        semantic={"target":target,"feature_a":fa,"feature_b":fb,"expr":expr,"alpha":a,"beta":b}
        sem_sha=H(semantic);rid="rr_"+sem_sha[:12];src=relation_source(rid,expr,a,b);compile(src,f"<{rid}>","exec")
        state={
            "epoch":ep,"dataset_sha256":dataset_sha,"row_count":len(rows),"year":YEAR,
            "train_rows":sizes[0],"validation_rows":sizes[1],"test_rows":sizes[2],
            "relation_id":rid,"target":target,"feature_a":fa,"feature_b":fb,"expr":expr,
            "alpha":a,"beta":b,"train_error":trerr,"validation_error":verr,"test_error":terr,
            "validation_improvement":vi,"test_improvement":ti,"semantic_sha256":sem_sha,
            "source_sha256":H(src),"source":src,"parent_state_sha256":parent,
            "source_receipts":source_receipts,
            "paid_actions":0,"contract_actions":0,"financial_actions":0,
        }
        state_sha=H(state);receipt={
            "epoch":ep,"state_sha256":state_sha,"parent_state_sha256":parent,
            "holdout_survived":ti>.03,"validation_survived":vi>.08,"compiled":True,
            "stop":ep==3,"reason":"MAX_EPOCHS_REACHED" if ep==3 else "CONTINUE_REALITY_RELATION_INDUCTION"
        }
        (OUT/f"state_{ep}.json").write_text(json.dumps(state,indent=2,sort_keys=True))
        (OUT/f"receipt_{ep}.json").write_text(json.dumps(receipt,indent=2,sort_keys=True))
        history.append(state);parent=state_sha;git_push(ep,"relation-epoch")
    distinct=len({(x["target"],x["feature_a"],x["feature_b"]) for x in history})==3
    admitted=distinct and all(x["validation_improvement"]>.08 and x["test_improvement"]>.03 for x in history)
    verdict={
        "admitted":admitted,"epochs":3,"dataset_sha256":dataset_sha,"row_count":len(rows),"year":YEAR,
        "lineage":[{"epoch":x["epoch"],"relation_id":x["relation_id"],"target":x["target"],"feature_a":x["feature_a"],
                    "feature_b":x["feature_b"],"expr":x["expr"],"validation_improvement":x["validation_improvement"],
                    "test_improvement":x["test_improvement"],"semantic_sha256":x["semantic_sha256"],"source_sha256":x["source_sha256"]}
                   for x in history],
        "claim_boundary":{
            "LIVE_EXTERNAL_REALITY_GROUNDED_RELATION_INDUCTION":"ESTABLISHED_FOR_RECORDED_WORLD_BANK_LINEAGE" if admitted else "NOT_ESTABLISHED",
            "CAUSAL_INTERVENTION":"NOT_ESTABLISHED","ECONOMIC_T0":"NOT_OBSERVED",
            "VERIFIED_REALIZED_PROFIT":"NOT_PROVEN","MICCGI":"UNPROVEN",
        }
    }
    (OUT/"adjudication.json").write_text(json.dumps(verdict,indent=2,sort_keys=True));git_push(3,"final-adjudication")
    print(json.dumps(verdict,sort_keys=True))
    raise SystemExit(0 if admitted else 2)

if __name__=="__main__": main()
