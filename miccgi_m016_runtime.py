from __future__ import annotations
import csv,hashlib,io,json,math,urllib.request
from collections import defaultdict
from pathlib import Path

BASE="https://raw.githubusercontent.com/st-tech/zr-obp/master/obd"
CAMPAIGNS=("all","men","women")
OUT=Path("miccgi_m016_state")

def mean(x):return sum(x)/len(x) if x else 0.0
def var(x):
    if len(x)<2:return 0.0
    m=mean(x);return sum((z-m)**2 for z in x)/(len(x)-1)
def sha(b):return hashlib.sha256(b).hexdigest()

def fetch(policy,campaign):
    url=f"{BASE}/{policy}/{campaign}/{campaign}.csv"
    req=urllib.request.Request(url,headers={"User-Agent":"MICCGI-M016D-OPECalibration/1.0"})
    with urllib.request.urlopen(req,timeout=40) as r:raw=r.read()
    rows=list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    if len(rows)<9000:raise RuntimeError(f"BAD_ROWS:{policy}:{campaign}:{len(rows)}")
    out=[]
    for i,r in enumerate(rows):
        x={str(k).strip().lower():str(v).strip() for k,v in r.items() if k is not None}
        out.append({"timestamp":x["timestamp"],"position":int(float(x["position"])),"action":int(float(x["item_id"])),
                    "reward":float(x["click"]),"pscore":float(x.get("propensity_score",x.get("action_prob","0")))})
    out.sort(key=lambda r:r["timestamp"])
    return out,{"url":url,"sha256":sha(raw),"bytes":len(raw),"rows":len(rows),"columns":list(rows[0])}

def se_mean(xs):return math.sqrt(var(xs)/len(xs)) if xs else 999.0

def infer_random_policy(random_rows):
    by=defaultdict(list)
    for r in random_rows:by[r["position"]].append(r["pscore"])
    probs={};diag={}
    for p,xs in by.items():
        m=mean(xs);s=math.sqrt(var(xs));mn=min(xs);mx=max(xs)
        diag[str(p)]={"mean":m,"sd":s,"min":mn,"max":mx,"n":len(xs)}
        # random behavior must be effectively context/action invariant at a position
        if s>1e-10 or mx-mn>1e-10:raise RuntimeError(f"RANDOM_POLICY_NOT_CONSTANT_AT_POSITION:{p}:{mn}:{mx}")
        probs[p]=m
    return probs,diag

def ope(rows,target_by_position):
    w=[];wr=[];rwd=[]
    for r in rows:
        pi=target_by_position[r["position"]];wi=pi/r["pscore"]
        w.append(wi);wr.append(wi*r["reward"]);rwd.append(r["reward"])
    ips=mean(wr);sw=sum(w);mw=mean(w);sn=sum(wr)/sw if sw else 0.0
    ips_se=se_mean(wr)
    infl=[wi*(ri-sn) for wi,ri in zip(w,rwd)]
    sn_se=se_mean(infl)/mw if mw>1e-12 else 999
    ess=sw*sw/max(1e-12,sum(x*x for x in w));srt=sorted(w)
    return {"ips":ips,"ips_se":ips_se,"snips":sn,"snips_se":sn_se,"mean_weight":mw,
            "ess":ess,"ess_ratio":ess/len(rows),"max_weight":max(w),"p99_weight":srt[min(len(srt)-1,int(.99*len(srt)))],
            "weight_sha256":sha(json.dumps([round(x,12) for x in w],separators=(",",":")).encode())}

def zcmp(est,se,gt,gtse):
    d=est-gt;s=math.sqrt(se*se+gtse*gtse);z=abs(d)/max(s,1e-12)
    return {"difference":d,"combined_se":s,"z_abs":z,"consistent_95pct":z<=1.96}

def eval_campaign(c):
    rr,rrc=fetch("random",c);br,brc=fetch("bts",c)
    target,pdiag=infer_random_policy(rr)
    gt=mean([r["reward"] for r in rr]);gtse=se_mean([r["reward"] for r in rr])
    full=ope(br,target);mid=len(br)//2;early=ope(br[:mid],target);late=ope(br[mid:],target)
    comp={"ips":zcmp(full["ips"],full["ips_se"],gt,gtse),"snips":zcmp(full["snips"],full["snips_se"],gt,gtse),
          "early_snips":zcmp(early["snips"],early["snips_se"],gt,gtse),"late_snips":zcmp(late["snips"],late["snips_se"],gt,gtse)}
    stable=(comp["snips"]["consistent_95pct"] and comp["ips"]["z_abs"]<=2.58 and
            min(full["ess_ratio"],early["ess_ratio"],late["ess_ratio"])>0.01)
    return {"campaign":c,"datasets":{"random":rrc,"bts":brc},"random_policy_propensity_by_position":target,
            "random_policy_diagnostic":pdiag,"random_onpolicy_ground_truth":{"value":gt,"se":gtse},
            "bts_log_ope_full":full,"bts_log_ope_early":early,"bts_log_ope_late":late,
            "calibration":comp,"campaign_calibrated":stable}

def main():
    OUT.mkdir(exist_ok=True);res=[eval_campaign(c) for c in CAMPAIGNS]
    calibrated=sum(x["campaign_calibrated"] for x in res)
    snips_all=all(x["calibration"]["snips"]["consistent_95pct"] for x in res)
    established=calibrated==3 and snips_all
    result={"admitted":established,"campaigns":res,"calibrated_campaigns":calibrated,
      "claim_boundary":{"COUNTERFACTUAL_OPE_CALIBRATION":"ESTABLISHED_ON_THREE_ZOZOTOWN_CAMPAIGNS" if established else "NOT_ESTABLISHED",
        "LEARNED_POLICY_SUPERIORITY":"NOT_ESTABLISHED","SEQUENTIAL_POLICY_DEPLOYMENT":"NOT_ESTABLISHED",
        "REAL_PRODUCTION_INTERVENTION":"NOT_ESTABLISHED","ECONOMIC_T0":"NOT_OBSERVED",
        "VERIFIED_REALIZED_PROFIT":"NOT_PROVEN","MICCGI":"UNPROVEN"}}
    (OUT/"adjudication.json").write_text(json.dumps(result,indent=2,sort_keys=True))
    print(json.dumps(result,sort_keys=True));raise SystemExit(0 if established else 2)
if __name__=="__main__":main()
