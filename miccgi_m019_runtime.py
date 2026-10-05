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

def controller_select(prev_rr,prev_br,recent_rr,recent_br,params):
    w,k,z=params
    p=all_candidates(prev_rr,prev_br);r=all_candidates(recent_rr,recent_br)
    scored=[]
    for key in r:
        score=w*r[key]["value"]+(1-w)*p[key]["value"]-k*abs(r[key]["value"]-p[key]["value"])-z*r[key]["se"]
        scored.append((score,key))
    scored.sort(reverse=True)
    return scored[0][1]

def calibrate_controller(campaign_quarters):
    grid=[]
    for w in (0.5,0.7,0.85,1.0):
      for k in (0.0,0.25,0.5,1.0,1.5):
       for z in (0.0,0.64,1.0,1.28,1.96):
        regrets=[]
        for rq,bq in campaign_quarters:
            sel=controller_select(rq[0],bq[0],rq[1],bq[1],(w,k,z))
            q3=all_candidates(rq[2],bq[2]);oracle=max(q3,key=lambda x:q3[x]["value"])
            regrets.append(q3[oracle]["value"]-q3[sel]["value"])
        grid.append((sum(regrets),max(regrets),w,k,z))
    grid.sort()
    best=grid[0]
    return (best[2],best[3],best[4]),grid[:10]

def load_campaign(c):
    rr,rrc=fetch("random",c);br,brc=fetch("bts",c)
    return quarters(rr),quarters(br),rrc,brc

def evaluate_campaign(c,rq,bq,rrc,brc,params):
    naive=naive_select(rq,bq)
    adaptive=controller_select(rq[1],bq[1],rq[2],bq[2],params)
    test=all_candidates(rq[3],bq[3]);oracle=max(test,key=lambda x:test[x]["value"])
    nv=test[naive]["value"];av=test[adaptive]["value"];ov=test[oracle]["value"]
    return {"campaign":c,"datasets":{"random":rrc,"bts":brc},"naive_choice":list(naive),"adaptive_choice":list(adaptive),
            "oracle_choice":list(oracle),"q4_values":{"naive":nv,"adaptive":av,"oracle":ov},
            "naive_regret":ov-nv,"adaptive_regret":ov-av,"regret_reduction":nv-av+ov-ov}

def main():
    OUT.mkdir(exist_ok=True)
    loaded={c:load_campaign(c) for c in CAMPAIGNS}
    params,top=calibrate_controller([(loaded[c][0],loaded[c][1]) for c in CAMPAIGNS])
    cs=[evaluate_campaign(c,*loaded[c],params) for c in CAMPAIGNS]
    for x in cs:
        x["regret_reduction"]=x["naive_regret"]-x["adaptive_regret"]
    better=sum(x["adaptive_regret"]<x["naive_regret"] for x in cs)
    total_naive=sum(x["naive_regret"] for x in cs);total_adapt=sum(x["adaptive_regret"] for x in cs)
    established=better>=2 and total_adapt<total_naive
    result={"admitted":established,"controller":{"recent_weight":params[0],"drift_penalty":params[1],"uncertainty_penalty":params[2]},
            "controller_calibration_top10":[{"historical_total_regret":a,"historical_max_regret":b,"recent_weight":w,"drift_penalty":k,"uncertainty_penalty":z} for a,b,w,k,z in top],
            "campaigns":cs,"improved_campaigns":better,"total_naive_regret":total_naive,"total_adaptive_regret":total_adapt,
            "aggregate_regret_reduction":total_naive-total_adapt,
      "claim_boundary":{"META_CALIBRATED_NONSTATIONARITY_CONTROLLER":"ESTABLISHED_FOR_RECORDED_OBD_Q4_HOLDOUT" if established else "NOT_ESTABLISHED",
        "LIVE_POLICY_DEPLOYMENT":"NOT_ESTABLISHED","REAL_PRODUCTION_INTERVENTION":"NOT_ESTABLISHED",
        "ECONOMIC_T0":"NOT_OBSERVED","VERIFIED_REALIZED_PROFIT":"NOT_PROVEN","MICCGI":"UNPROVEN"}}
    (OUT/"adjudication.json").write_text(json.dumps(result,indent=2,sort_keys=True))
    print(json.dumps(result,sort_keys=True));raise SystemExit(0 if established else 2)

if __name__=="__main__":main()
