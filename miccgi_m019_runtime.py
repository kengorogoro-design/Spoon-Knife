from __future__ import annotations
import csv,hashlib,io,json,math,urllib.request,itertools
from collections import defaultdict
from pathlib import Path

BASE="https://raw.githubusercontent.com/st-tech/zr-obp/master/obd"
CAMPAIGNS=("all","men","women")
OUT=Path("miccgi_m019_state")

def mean(x):return sum(x)/len(x) if x else 0.0
def var(x):
    if len(x)<2:return 0.0
    m=mean(x);return sum((z-m)**2 for z in x)/(len(x)-1)
def se_mean(x):return math.sqrt(var(x)/len(x)) if x else 999.0
def sha(b):return hashlib.sha256(b).hexdigest()

def fetch(policy,campaign):
    url=f"{BASE}/{policy}/{campaign}/{campaign}.csv"
    req=urllib.request.Request(url,headers={"User-Agent":"MICCGI-M019-NonstationaryPolicy/1.0"})
    with urllib.request.urlopen(req,timeout=40) as r:raw=r.read()
    rows=list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    out=[]
    for i,r in enumerate(rows):
        x={str(k).strip().lower():str(v).strip() for k,v in r.items() if k is not None}
        out.append({"timestamp":x["timestamp"],"row_id":i,"position":int(float(x["position"])),"reward":float(x["click"])})
    out.sort(key=lambda z:(z["timestamp"],z["row_id"]))
    return out,{"url":url,"sha256":sha(raw),"bytes":len(raw),"rows":len(rows)}

def quarters(rows):
    n=len(rows)
    return [rows[(i*n)//4:((i+1)*n)//4] for i in range(4)]

def pos_stats(rows):
    n=len(rows);out={}
    for p in (1,2,3):
        ys=[r["reward"] for r in rows if r["position"]==p]
        out[p]={"mean":mean(ys),"se":se_mean(ys),"mass":len(ys)/n,"n":len(ys)}
    return out

def truth(rr,br,ch):
    rs=pos_stats(rr);bs=pos_stats(br)
    masses={p:(rs[p]["mass"]+bs[p]["mass"])/2 for p in (1,2,3)}
    z=sum(masses.values());masses={p:v/z for p,v in masses.items()}
    v=0;vv=0
    for p in (1,2,3):
        s=rs[p] if ch[p-1]=="random" else bs[p]
        v+=masses[p]*s["mean"];vv+=(masses[p]*s["se"])**2
    return {"value":v,"se":math.sqrt(vv)}

def all_candidates(rr,br):
    return {tuple(ch):truth(rr,br,ch) for ch in itertools.product(("random","bts"),repeat=3)}

def combine_rows(*parts):
    return [x for part in parts for x in part]

def naive_select(rq,bq):
    rr=combine_rows(rq[0],rq[1]);br=combine_rows(bq[0],bq[1])
    c=all_candidates(rr,br)
    return max(c,key=lambda k:c[k]["value"]-1.96*c[k]["se"])

def adaptive_select(rq,bq):
    c2=all_candidates(rq[1],bq[1]);c3=all_candidates(rq[2],bq[2])
    scored=[]
    for k in c3:
        recent=c3[k]["value"];recent_se=c3[k]["se"];prev=c2[k]["value"]
        drift=abs(recent-prev)
        # recent evidence dominates; drift and uncertainty penalize brittle policies.
        score=recent-1.28*recent_se-0.75*drift
        # slight preference for deployed policies under near ties.
        complexity=0 if len(set(k))==1 else 1
        score-=complexity*1e-7
        scored.append((score,k,{"recent":recent,"recent_se":recent_se,"prev":prev,"drift":drift}))
    scored.sort(reverse=True)
    return scored[0][1],scored

def campaign(c):
    rr,rrc=fetch("random",c);br,brc=fetch("bts",c)
    rq=quarters(rr);bq=quarters(br)
    naive=naive_select(rq,bq);adaptive,rank=adaptive_select(rq,bq)
    test=all_candidates(rq[3],bq[3]);oracle=max(test,key=lambda k:test[k]["value"])
    nv=test[naive]["value"];av=test[adaptive]["value"];ov=test[oracle]["value"]
    return {"campaign":c,"datasets":{"random":rrc,"bts":brc},
            "naive_choice":list(naive),"adaptive_choice":list(adaptive),"oracle_choice":list(oracle),
            "q4_values":{"naive":nv,"adaptive":av,"oracle":ov},
            "naive_regret":ov-nv,"adaptive_regret":ov-av,"regret_reduction":(ov-nv)-(ov-av),
            "adaptive_top5":[{"choice":list(x[1]),"score":x[0],**x[2]} for x in rank[:5]]}

def main():
    OUT.mkdir(exist_ok=True);cs=[campaign(c) for c in CAMPAIGNS]
    better=sum(x["adaptive_regret"]<x["naive_regret"] for x in cs)
    total_naive=sum(x["naive_regret"] for x in cs);total_adapt=sum(x["adaptive_regret"] for x in cs)
    established=better>=2 and total_adapt<total_naive
    result={"admitted":established,"campaigns":cs,"improved_campaigns":better,
            "total_naive_regret":total_naive,"total_adaptive_regret":total_adapt,
            "aggregate_regret_reduction":total_naive-total_adapt,
      "claim_boundary":{"NONSTATIONARITY_AWARE_POLICY_RECOMPILATION":"ESTABLISHED_FOR_RECORDED_OBD_TEMPORAL_WINDOWS" if established else "NOT_ESTABLISHED",
        "LIVE_POLICY_DEPLOYMENT":"NOT_ESTABLISHED","REAL_PRODUCTION_INTERVENTION":"NOT_ESTABLISHED",
        "ECONOMIC_T0":"NOT_OBSERVED","VERIFIED_REALIZED_PROFIT":"NOT_PROVEN","MICCGI":"UNPROVEN"}}
    (OUT/"adjudication.json").write_text(json.dumps(result,indent=2,sort_keys=True))
    print(json.dumps(result,sort_keys=True));raise SystemExit(0 if established else 2)
if __name__=="__main__":main()
