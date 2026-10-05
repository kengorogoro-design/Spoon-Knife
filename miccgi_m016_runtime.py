from __future__ import annotations
import csv,hashlib,io,json,math,urllib.request
from collections import defaultdict
from pathlib import Path

BASE="https://raw.githubusercontent.com/st-tech/zr-obp/master/obd"
CAMPAIGNS=("all","men","women")
CAPS=(2.0,5.0,10.0,20.0,50.0,100.0)
OUT=Path("miccgi_m016_state")

def mean(x):return sum(x)/len(x) if x else 0.0
def var(x):
    if len(x)<2:return 0.0
    m=mean(x);return sum((z-m)**2 for z in x)/(len(x)-1)
def se_mean(x):return math.sqrt(var(x)/len(x)) if x else 999.0
def sha(b):return hashlib.sha256(b).hexdigest()

def fetch(policy,campaign):
    url=f"{BASE}/{policy}/{campaign}/{campaign}.csv"
    req=urllib.request.Request(url,headers={"User-Agent":"MICCGI-M016E-MetaCalibratedOPE/1.0"})
    with urllib.request.urlopen(req,timeout=40) as r:raw=r.read()
    rows=list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    if len(rows)<9000:raise RuntimeError("BAD_ROWS")
    out=[]
    for r in rows:
        x={str(k).strip().lower():str(v).strip() for k,v in r.items() if k is not None}
        out.append({"position":int(float(x["position"])),"reward":float(x["click"]),
                    "pscore":float(x.get("propensity_score",x.get("action_prob","0")))})
    return out,{"url":url,"sha256":sha(raw),"bytes":len(raw),"rows":len(rows)}

def infer_target(rr):
    by=defaultdict(list)
    for r in rr:by[r["position"]].append(r["pscore"])
    target={};diag={}
    for p,xs in by.items():
        m=mean(xs);mn=min(xs);mx=max(xs);s=math.sqrt(var(xs))
        if mx-mn>1e-10:raise RuntimeError(f"RANDOM_NOT_CONSTANT:{p}")
        target[p]=m;diag[str(p)]={"mean":m,"sd":s,"min":mn,"max":mx,"n":len(xs)}
    return target,diag

def estimate(br,target,kind,cap=None):
    w=[target[r["position"]]/r["pscore"] for r in br]
    if cap is not None:w=[min(x,cap) for x in w]
    rewards=[r["reward"] for r in br];wr=[a*b for a,b in zip(w,rewards)]
    if kind=="ips":
        value=mean(wr);se=se_mean(wr)
    elif kind=="snips":
        mw=mean(w);value=sum(wr)/sum(w)
        infl=[a*(b-value) for a,b in zip(w,rewards)]
        se=se_mean(infl)/mw if mw>1e-12 else 999
    else:raise ValueError(kind)
    sw=sum(w);ess=sw*sw/max(1e-12,sum(x*x for x in w));srt=sorted(w)
    return {"value":value,"se":se,"ess":ess,"ess_ratio":ess/len(w),"mean_weight":mean(w),
            "max_weight":max(w),"p99_weight":srt[min(len(srt)-1,int(.99*len(srt)))],
            "clip":cap,"kind":kind}

def zcmp(est,gt,gtse):
    se=math.sqrt(est["se"]**2+gtse**2);d=est["value"]-gt;z=abs(d)/max(se,1e-12)
    return {"difference":d,"combined_se":se,"z_abs":z,"consistent_95pct":z<=1.96}

def campaign(c):
    rr,rrc=fetch("random",c);br,brc=fetch("bts",c);target,diag=infer_target(rr)
    gt=mean([r["reward"] for r in rr]);gtse=se_mean([r["reward"] for r in rr])
    ests={}
    for kind in ("ips","snips"):
        key=kind;ests[key]=estimate(br,target,kind,None)
        for cap in CAPS:ests[f"{kind}_clip_{int(cap)}"]=estimate(br,target,kind,cap)
    cal={k:zcmp(v,gt,gtse) for k,v in ests.items()}
    return {"campaign":c,"datasets":{"random":rrc,"bts":brc},"target":target,"random_policy_diagnostic":diag,
            "ground_truth":{"value":gt,"se":gtse},"estimators":ests,"calibration":cal}

def estimator_rank(train_campaigns):
    names=sorted(train_campaigns[0]["estimators"])
    scored=[]
    for name in names:
        zs=[x["calibration"][name]["z_abs"] for x in train_campaigns]
        # robust calibration loss; tiny preference for less clipping / SNIPS when tied
        est=train_campaigns[0]["estimators"][name]
        cap=est["clip"];complexity=(0.00001*(0 if cap is None else 1/max(cap,1e-9)))
        preference=0.000001*(0 if est["kind"]=="snips" else 1)
        loss=sum(math.log1p(z*z) for z in zs)+complexity+preference
        scored.append((loss,name,zs))
    scored.sort()
    return scored

def main():
    OUT.mkdir(exist_ok=True);cs=[campaign(c) for c in CAMPAIGNS];loo=[]
    for held in CAMPAIGNS:
        train=[x for x in cs if x["campaign"]!=held];test=next(x for x in cs if x["campaign"]==held)
        ranking=estimator_rank(train);loss,name,train_z=ranking[0]
        est=test["estimators"][name];cal=test["calibration"][name]
        loo.append({"held_out_campaign":held,"selected_estimator":name,"selection_loss":loss,
                    "training_campaign_z":train_z,"held_out_estimate":est,"held_out_calibration":cal,
                    "top5":[{"estimator":n,"loss":l,"training_z":z} for l,n,z in ranking[:5]]})
    passes=sum(x["held_out_calibration"]["consistent_95pct"] for x in loo)
    support_ok=all(x["held_out_estimate"]["ess_ratio"]>=.01 for x in loo)
    established=passes==3 and support_ok
    result={"admitted":established,"campaigns":cs,"leave_one_campaign_out":loo,
            "held_out_passes":passes,"support_ok":support_ok,
      "claim_boundary":{"META_CALIBRATED_COUNTERFACTUAL_EVALUATOR":"ESTABLISHED_ON_THREE_ZOZOTOWN_CAMPAIGNS" if established else "NOT_ESTABLISHED",
        "LEARNED_POLICY_SUPERIORITY":"NOT_ESTABLISHED","SEQUENTIAL_POLICY_DEPLOYMENT":"NOT_ESTABLISHED",
        "REAL_PRODUCTION_INTERVENTION":"NOT_ESTABLISHED","ECONOMIC_T0":"NOT_OBSERVED",
        "VERIFIED_REALIZED_PROFIT":"NOT_PROVEN","MICCGI":"UNPROVEN"}}
    (OUT/"adjudication.json").write_text(json.dumps(result,indent=2,sort_keys=True))
    print(json.dumps(result,sort_keys=True));raise SystemExit(0 if established else 2)
if __name__=="__main__":main()
