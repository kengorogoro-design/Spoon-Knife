from __future__ import annotations
import csv, hashlib, io, json, math, urllib.request
from itertools import combinations
from pathlib import Path

ARMS=("No E-Mail","Mens E-Mail","Womens E-Mail")
OUTCOMES=("visit","conversion","spend")
FEATURES=("history_segment","zip_code","channel","newbie","mens","womens","recency_bucket")
URLS=(
"https://raw.githubusercontent.com/W-Tran/uplift-modelling/refs/heads/master/data/hillstrom/Kevin_Hillstrom_MineThatData_E-MailAnalytics_DataMiningChallenge_2008.03.20.csv",
"https://raw.githubusercontent.com/Olesiewitch/Predictive_Analytics/master/Kevin_Hillstrom_MineThatData_E-MailAnalytics_DataMiningChallenge_2008.03.20.csv",
)
OUT=Path("miccgi_m014_state")

def H(b): return hashlib.sha256(b).hexdigest()

def fetch():
    last=None
    for url in URLS:
        for _ in range(3):
            try:
                req=urllib.request.Request(url,headers={"User-Agent":"MICCGI-M014-RCT/1.0"})
                with urllib.request.urlopen(req,timeout=30) as r: raw=r.read()
                if len(raw)<3_000_000: raise RuntimeError("DATA_TOO_SMALL")
                rows=list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
                if len(rows)!=64000: raise RuntimeError(f"ROW_COUNT:{len(rows)}")
                return rows,{"url":url,"sha256":H(raw),"bytes":len(raw),"rows":len(rows)}
            except Exception as e: last=e
    raise last

def prep(rows):
    out=[]
    for i,r in enumerate(rows):
        x={k.strip().lower():v.strip() for k,v in r.items()}
        x["row_id"]=i
        x["recency"]=float(x["recency"]); x["history"]=float(x["history"])
        for k in ("mens","womens","newbie","visit","conversion"): x[k]=int(float(x[k]))
        x["spend"]=float(x["spend"])
        x["recency_bucket"]=str(min(3,int((x["recency"]-1)//3)))
        if x["segment"] not in ARMS: raise RuntimeError("BAD_ARM:"+x["segment"])
        out.append(x)
    return out

def split(rows):
    tr=[]; va=[]; te=[]
    for r in rows:
        b=int(hashlib.sha256(f'M014|{r["row_id"]}'.encode()).hexdigest()[:8],16)%10
        (tr if b<6 else va if b<8 else te).append(r)
    return tr,va,te

def mean(xs): return sum(xs)/len(xs) if xs else 0.0
def var(xs):
    if len(xs)<2:return 0.0
    m=mean(xs); return sum((x-m)**2 for x in xs)/(len(xs)-1)

def arm_means(rows,outcome):
    return {a:mean([r[outcome] for r in rows if r["segment"]==a]) for a in ARMS}

def arm_effect(rows,outcome,arm,control="No E-Mail"):
    a=[r[outcome] for r in rows if r["segment"]==arm]; c=[r[outcome] for r in rows if r["segment"]==control]
    d=mean(a)-mean(c); se=math.sqrt(var(a)/len(a)+var(c)/len(c))
    return d,se,d-1.96*se,d+1.96*se,len(a),len(c)

def smd(a,b):
    den=math.sqrt(max(1e-12,(var(a)+var(b))/2))
    return abs(mean(a)-mean(b))/den

def balance(rows):
    numeric=("recency","history","mens","womens","newbie")
    mx=0.0; detail={}
    for f in numeric:
        for a,b in combinations(ARMS,2):
            z=smd([r[f] for r in rows if r["segment"]==a],[r[f] for r in rows if r["segment"]==b])
            detail[f"{f}|{a}|{b}"]=z; mx=max(mx,z)
    props={a:sum(r["segment"]==a for r in rows)/len(rows) for a in ARMS}
    return mx,detail,props

def fval(r,f): return str(r[f])
def kfun(r,fs): return tuple(fval(r,f) for f in fs)

def fit_policy(train,outcome,fs,prior):
    gm=arm_means(train,outcome); default=max(ARMS,key=lambda a:gm[a]); stats={}
    for r in train:
        k=kfun(r,fs); a=r["segment"]; y=r[outcome]
        d=stats.setdefault(k,{z:[0.0,0] for z in ARMS}); d[a][0]+=y; d[a][1]+=1
    table={}
    for k,d in stats.items():
        est={a:(d[a][0]+prior*gm[a])/(d[a][1]+prior) for a in ARMS}
        table[k]=max(ARMS,key=lambda a:est[a])
    return {"features":fs,"prior":prior,"table":table,"default":default,"global_means":gm}

def action(policy,r):
    return policy["table"].get(kfun(r,policy["features"]),policy["default"])

def ips_diff(rows,outcome,policy,baseline):
    diffs=[]; pv=[]; bv=[]
    for r in rows:
        y=float(r[outcome]); a=r["segment"]; pa=action(policy,r)
        pterm=3*y if a==pa else 0.0
        bterm=3*y if a==baseline else 0.0
        pv.append(pterm); bv.append(bterm); diffs.append(pterm-bterm)
    d=mean(diffs); se=math.sqrt(var(diffs)/len(diffs))
    return mean(pv),mean(bv),d,se,d-1.96*se,d+1.96*se

def main():
    OUT.mkdir(exist_ok=True)
    raw,receipt=fetch(); rows=prep(raw); tr,va,te=split(rows)
    mx,bdetail,props=balance(rows)
    if mx>=0.10 or any(not (0.30<p<0.37) for p in props.values()):
        raise RuntimeError("RANDOMIZATION_BALANCE_FAILED")
    feature_sets=[(f,) for f in FEATURES]+list(combinations(FEATURES,2))
    candidates=[]
    for outcome in OUTCOMES:
        baseline=max(ARMS,key=lambda a:arm_means(tr,outcome)[a])
        for fs in feature_sets:
            for prior in (30.0,100.0,300.0):
                pol=fit_policy(tr,outcome,fs,prior)
                pv,bv,d,se,lo,hi=ips_diff(va,outcome,pol,baseline)
                score=lo/(abs(bv)+1e-9)
                candidates.append((score,d,lo,outcome,baseline,fs,prior,pol,pv,bv,se,hi))
    candidates.sort(key=lambda x:(x[0],x[1]),reverse=True)
    _,vd,vlo,outcome,baseline,fs,prior,pol,vpv,vbv,vse,vhi=candidates[0]
    tpv,tbv,td,tse,tlo,thi=ips_diff(te,outcome,pol,baseline)
    effects={}
    for o in OUTCOMES:
        effects[o]={}
        for arm in ARMS[1:]:
            d,se,lo,hi,na,nc=arm_effect(te,o,arm)
            effects[o][arm]={"effect":d,"se":se,"ci95":[lo,hi],"n_treat":na,"n_control":nc}
    causal=any(v["ci95"][0]>0 or v["ci95"][1]<0 for x in effects.values() for v in x.values())
    personalized=(vd>0 and vlo>0 and td>0 and tlo>0)
    result={
      "admitted":causal,
      "dataset":receipt,"rows":len(rows),"split":{"train":len(tr),"validation":len(va),"test":len(te)},
      "randomization":{"arm_proportions":props,"max_numeric_smd":mx,"numeric_smd":bdetail},
      "selected_policy":{"outcome":outcome,"features":list(fs),"prior":prior,"baseline_arm":baseline,
        "validation":{"policy_value":vpv,"baseline_value":vbv,"difference":vd,"se":vse,"ci95":[vlo,vhi]},
        "test":{"policy_value":tpv,"baseline_value":tbv,"difference":td,"se":tse,"ci95":[tlo,thi]},
        "distinct_actions":sorted(set(pol["table"].values())|{pol["default"]}),"groups":len(pol["table"])},
      "test_randomized_effects":effects,
      "claim_boundary":{"RANDOMIZED_CAUSAL_EFFECT_ESTIMATION":"ESTABLISHED_FOR_RECORDED_HILLSTROM_RCT" if causal else "NOT_ESTABLISHED",
        "PERSONALIZED_CAUSAL_POLICY":"ESTABLISHED_FOR_RECORDED_HILLSTROM_HOLDOUT" if personalized else "NOT_ESTABLISHED",
        "REAL_PRODUCTION_INTERVENTION":"NOT_ESTABLISHED","ECONOMIC_T0":"NOT_OBSERVED","VERIFIED_REALIZED_PROFIT":"NOT_PROVEN","MICCGI":"UNPROVEN"}
    }
    (OUT/"adjudication.json").write_text(json.dumps(result,indent=2,sort_keys=True))
    print(json.dumps(result,sort_keys=True))
    raise SystemExit(0 if causal else 2)

if __name__=="__main__":main()
