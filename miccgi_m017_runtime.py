from __future__ import annotations
import csv,hashlib,io,json,math,urllib.request,itertools
from collections import defaultdict
from pathlib import Path

BASE="https://raw.githubusercontent.com/st-tech/zr-obp/master/obd"
CAMPAIGNS=("all","men","women")
OUT=Path("miccgi_m017_state")
CAP=2.0

def mean(x):return sum(x)/len(x) if x else 0.0
def var(x):
    if len(x)<2:return 0.0
    m=mean(x);return sum((z-m)**2 for z in x)/(len(x)-1)
def se_mean(x):return math.sqrt(var(x)/len(x)) if x else 999.0
def sha(b):return hashlib.sha256(b).hexdigest()

def fetch(policy,campaign):
    url=f"{BASE}/{policy}/{campaign}/{campaign}.csv"
    req=urllib.request.Request(url,headers={"User-Agent":"MICCGI-M017-PolicyComposition/1.0"})
    with urllib.request.urlopen(req,timeout=40) as r: raw=r.read()
    rows=list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    if len(rows)<9000:raise RuntimeError("BAD_ROWS")
    out=[]
    for r in rows:
        x={str(k).strip().lower():str(v).strip() for k,v in r.items() if k is not None}
        out.append({"position":int(float(x["position"])),"reward":float(x["click"]),
                    "pscore":float(x.get("propensity_score",x.get("action_prob","0")))})
    return out,{"url":url,"sha256":sha(raw),"bytes":len(raw),"rows":len(rows)}

def infer_random_target(rr):
    by=defaultdict(list)
    for r in rr:by[r["position"]].append(r["pscore"])
    t={}
    for p,xs in by.items():
        if max(xs)-min(xs)>1e-10:raise RuntimeError("RANDOM_NOT_CONSTANT")
        t[p]=mean(xs)
    return t

def pos_stats(rows):
    out={}
    n=len(rows)
    for p in (1,2,3):
        ys=[r["reward"] for r in rows if r["position"]==p]
        out[p]={"mean":mean(ys),"se":se_mean(ys),"n":len(ys),"mass":len(ys)/n}
    return out

def composite_truth(rr,br,choice):
    rs=pos_stats(rr);bs=pos_stats(br)
    # Use pooled empirical position mass to avoid privileging either logger.
    masses={p:(rs[p]["mass"]+bs[p]["mass"])/2 for p in (1,2,3)}
    z=sum(masses.values());masses={p:v/z for p,v in masses.items()}
    val=0.0;variance=0.0
    for p in (1,2,3):
        src=rs[p] if choice[p-1]=="random" else bs[p]
        val+=masses[p]*src["mean"]
        variance+=(masses[p]*src["se"])**2
    return {"value":val,"se":math.sqrt(variance),"position_mass":masses}

def ope_from_bts(br,random_target,choice):
    ws=[];wr=[]
    for r in br:
        target = r["pscore"] if choice[r["position"]-1]=="bts" else random_target[r["position"]]
        w=min(target/r["pscore"],CAP)
        ws.append(w);wr.append(w*r["reward"])
    value=sum(wr)/sum(ws)
    mw=mean(ws);infl=[w*(y-value) for w,y in zip(ws,[r["reward"] for r in br])]
    se=se_mean(infl)/mw if mw>1e-12 else 999
    ess=sum(ws)**2/sum(w*w for w in ws)
    return {"value":value,"se":se,"ess":ess,"ess_ratio":ess/len(ws),"max_weight":max(ws),"clip":CAP}

def deployed_truth(rr,br):
    return {"random":{"value":mean([r["reward"] for r in rr]),"se":se_mean([r["reward"] for r in rr])},
            "bts":{"value":mean([r["reward"] for r in br]),"se":se_mean([r["reward"] for r in br])}}

def campaign(c):
    rr,rrc=fetch("random",c);br,brc=fetch("bts",c);rt=infer_random_target(rr);dep=deployed_truth(rr,br)
    cands=[]
    for bits in itertools.product(("random","bts"),repeat=3):
        truth=composite_truth(rr,br,bits);est=ope_from_bts(br,rt,bits)
        comb=math.sqrt(truth["se"]**2+est["se"]**2);z=abs(est["value"]-truth["value"])/max(comb,1e-12)
        cands.append({"choice":list(bits),"truth":truth,"ope":est,
                      "calibration":{"difference":est["value"]-truth["value"],"combined_se":comb,"z_abs":z,"consistent_95pct":z<=1.96}})
    return {"campaign":c,"datasets":{"random":rrc,"bts":brc},"deployed":dep,"candidates":cands}

def candidate_key(x):return tuple(x["choice"])

def robust_select(train):
    keys=[candidate_key(x) for x in train[0]["candidates"] if len(set(x["choice"]))>1]
    scored=[]
    for k in keys:
        vals=[]
        for c in train:
            x=next(z for z in c["candidates"] if candidate_key(z)==k)
            vals.append(x["truth"]["value"]-1.96*x["truth"]["se"])
        scored.append((min(vals),mean(vals),k))
    scored.sort(reverse=True)
    return scored

def main():
    OUT.mkdir(exist_ok=True);cs=[campaign(c) for c in CAMPAIGNS];loo=[]
    for held in CAMPAIGNS:
        train=[x for x in cs if x["campaign"]!=held];test=next(x for x in cs if x["campaign"]==held)
        ranking=robust_select(train);floor,avg,k=ranking[0]
        cand=next(z for z in test["candidates"] if candidate_key(z)==k)
        best_deployed=max(test["deployed"].values(),key=lambda z:z["value"])
        superiority=cand["truth"]["value"]-best_deployed["value"]
        superiority_se=math.sqrt(cand["truth"]["se"]**2+best_deployed["se"]**2)
        loo.append({"held_out_campaign":held,"selected_choice":list(k),"training_robust_floor":floor,"training_avg_floor":avg,
                    "held_out":cand,"best_deployed":best_deployed,
                    "superiority_vs_best_deployed":superiority,
                    "superiority_z":superiority/max(superiority_se,1e-12),
                    "top5":[{"choice":list(q[2]),"robust_floor":q[0],"avg_floor":q[1]} for q in ranking[:5]]})
    calibrated=all(x["held_out"]["calibration"]["consistent_95pct"] and x["held_out"]["ope"]["ess_ratio"]>=0.05 for x in loo)
    positive=sum(x["superiority_vs_best_deployed"]>0 for x in loo)
    strong=sum(x["superiority_z"]>0 for x in loo)
    novel=all(len(set(x["selected_choice"]))>1 for x in loo)
    established=calibrated and novel and positive>=2
    result={"admitted":established,"campaigns":cs,"leave_one_campaign_out":loo,
            "calibrated_all":calibrated,"positive_holdouts":positive,"novel_compositions_all":novel,
      "claim_boundary":{"CROSS_CAMPAIGN_COMPOSITE_POLICY_GENESIS":"ESTABLISHED_FOR_RECORDED_OBD_CAMPAIGNS" if established else "NOT_ESTABLISHED",
        "CALIBRATED_COUNTERFACTUAL_EVALUATION_OF_NEW_POLICY":"ESTABLISHED" if calibrated else "NOT_ESTABLISHED",
        "LIVE_POLICY_DEPLOYMENT":"NOT_ESTABLISHED","REAL_PRODUCTION_INTERVENTION":"NOT_ESTABLISHED",
        "ECONOMIC_T0":"NOT_OBSERVED","VERIFIED_REALIZED_PROFIT":"NOT_PROVEN","MICCGI":"UNPROVEN"}}
    (OUT/"adjudication.json").write_text(json.dumps(result,indent=2,sort_keys=True))
    print(json.dumps(result,sort_keys=True));raise SystemExit(0 if established else 2)

if __name__=="__main__":main()
