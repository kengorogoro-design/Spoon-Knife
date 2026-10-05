from __future__ import annotations
import csv,hashlib,io,json,math,urllib.request,itertools
from collections import defaultdict
from pathlib import Path

BASE="https://raw.githubusercontent.com/st-tech/zr-obp/master/obd"
CAMPAIGNS=("all","men","women")
OUT=Path("miccgi_m018_state")
CAP=2.0

def mean(x):return sum(x)/len(x) if x else 0.0
def var(x):
    if len(x)<2:return 0.0
    m=mean(x);return sum((z-m)**2 for z in x)/(len(x)-1)
def se_mean(x):return math.sqrt(var(x)/len(x)) if x else 999.0
def sha(b):return hashlib.sha256(b).hexdigest()

def fetch(policy,campaign):
    url=f"{BASE}/{policy}/{campaign}/{campaign}.csv"
    req=urllib.request.Request(url,headers={"User-Agent":"MICCGI-M018-EnvPolicy/1.0"})
    with urllib.request.urlopen(req,timeout=40) as r:raw=r.read()
    rows=list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    if len(rows)<9000:raise RuntimeError("BAD_ROWS")
    out=[]
    for i,r in enumerate(rows):
        x={str(k).strip().lower():str(v).strip() for k,v in r.items() if k is not None}
        out.append({"timestamp":x["timestamp"],"row_id":i,"position":int(float(x["position"])),"reward":float(x["click"]),
                    "pscore":float(x.get("propensity_score",x.get("action_prob","0")))})
    out.sort(key=lambda z:(z["timestamp"],z["row_id"]))
    return out,{"url":url,"sha256":sha(raw),"bytes":len(raw),"rows":len(rows)}

def split(rows):
    k=len(rows)//2
    return rows[:k],rows[k:]

def infer_random_target(rr):
    by=defaultdict(list)
    for r in rr:by[r["position"]].append(r["pscore"])
    t={}
    for p,xs in by.items():
        if max(xs)-min(xs)>1e-10:raise RuntimeError("RANDOM_NOT_CONSTANT")
        t[p]=mean(xs)
    return t

def pos_stats(rows):
    out={};n=len(rows)
    for p in (1,2,3):
        ys=[r["reward"] for r in rows if r["position"]==p]
        out[p]={"mean":mean(ys),"se":se_mean(ys),"n":len(ys),"mass":len(ys)/n}
    return out

def truth(rr,br,choice):
    rs=pos_stats(rr);bs=pos_stats(br)
    masses={p:(rs[p]["mass"]+bs[p]["mass"])/2 for p in (1,2,3)}
    z=sum(masses.values());masses={p:v/z for p,v in masses.items()}
    val=0;vv=0
    for p in (1,2,3):
        s=rs[p] if choice[p-1]=="random" else bs[p]
        val+=masses[p]*s["mean"];vv+=(masses[p]*s["se"])**2
    return {"value":val,"se":math.sqrt(vv),"position_mass":masses}

def deployed(rr,br):
    return {"random":{"value":mean([r["reward"] for r in rr]),"se":se_mean([r["reward"] for r in rr])},
            "bts":{"value":mean([r["reward"] for r in br]),"se":se_mean([r["reward"] for r in br])}}

def ope(br,rt,choice):
    ws=[];ys=[]
    for r in br:
        target=r["pscore"] if choice[r["position"]-1]=="bts" else rt[r["position"]]
        w=min(target/r["pscore"],CAP)
        ws.append(w);ys.append(r["reward"])
    wr=[w*y for w,y in zip(ws,ys)]
    v=sum(wr)/sum(ws);mw=mean(ws);infl=[w*(y-v) for w,y in zip(ws,ys)]
    se=se_mean(infl)/mw;ess=sum(ws)**2/sum(w*w for w in ws)
    return {"value":v,"se":se,"ess":ess,"ess_ratio":ess/len(ws),"max_weight":max(ws),"clip":CAP}

def choose(rr,br):
    scored=[]
    for ch in itertools.product(("random","bts"),repeat=3):
        if len(set(ch))==1:continue
        t=truth(rr,br,ch);floor=t["value"]-1.96*t["se"]
        scored.append((floor,t["value"],ch,t))
    scored.sort(reverse=True)
    return scored[0],scored

def campaign(c):
    rr,rrc=fetch("random",c);br,brc=fetch("bts",c)
    rr_tr,rr_te=split(rr);br_tr,br_te=split(br)
    (floor,val,ch,tr_truth),ranking=choose(rr_tr,br_tr)
    te_truth=truth(rr_te,br_te,ch);dep=deployed(rr_te,br_te);best=max(dep.values(),key=lambda z:z["value"])
    rt=infer_random_target(rr_te);est=ope(br_te,rt,ch)
    comb=math.sqrt(est["se"]**2+te_truth["se"]**2);z=abs(est["value"]-te_truth["value"])/max(comb,1e-12)
    sup=te_truth["value"]-best["value"];supse=math.sqrt(te_truth["se"]**2+best["se"]**2)
    return {"campaign":c,"datasets":{"random":rrc,"bts":brc},"selected_choice":list(ch),
            "train_truth":tr_truth,"train_robust_floor":floor,
            "test_truth":te_truth,"test_ope":est,"test_calibration":{"difference":est["value"]-te_truth["value"],
            "combined_se":comb,"z_abs":z,"consistent_95pct":z<=1.96},
            "test_deployed":dep,"superiority_vs_best_deployed":sup,"superiority_z":sup/max(supse,1e-12),
            "top5":[{"choice":list(x[2]),"floor":x[0],"value":x[1]} for x in ranking[:5]]}

def main():
    OUT.mkdir(exist_ok=True);cs=[campaign(c) for c in CAMPAIGNS]
    calibrated=all(x["test_calibration"]["consistent_95pct"] and x["test_ope"]["ess_ratio"]>=.05 for x in cs)
    positive=sum(x["superiority_vs_best_deployed"]>0 for x in cs)
    established=calibrated and positive>=2
    result={"admitted":established,"campaigns":cs,"calibrated_all":calibrated,"positive_holdouts":positive,
      "claim_boundary":{"ENVIRONMENT_CONDITIONED_POLICY_COMPILATION":"ESTABLISHED_FOR_RECORDED_OBD_TEMPORAL_HOLDOUTS" if established else "NOT_ESTABLISHED",
        "CALIBRATED_COUNTERFACTUAL_EVALUATION":"ESTABLISHED" if calibrated else "NOT_ESTABLISHED",
        "LIVE_POLICY_DEPLOYMENT":"NOT_ESTABLISHED","REAL_PRODUCTION_INTERVENTION":"NOT_ESTABLISHED",
        "ECONOMIC_T0":"NOT_OBSERVED","VERIFIED_REALIZED_PROFIT":"NOT_PROVEN","MICCGI":"UNPROVEN"}}
    (OUT/"adjudication.json").write_text(json.dumps(result,indent=2,sort_keys=True))
    print(json.dumps(result,sort_keys=True));raise SystemExit(0 if established else 2)
if __name__=="__main__":main()
