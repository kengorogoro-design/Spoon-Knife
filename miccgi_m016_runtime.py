from __future__ import annotations
import csv, hashlib, io, json, math, urllib.request
from collections import defaultdict
from pathlib import Path

DATA_URL="https://raw.githubusercontent.com/st-tech/zr-obp/master/obd/random/all/all.csv"
OUT=Path("miccgi_m016_state")
EPSILONS=(0.05,0.10,0.20,0.35)
ALPHAS=(2.0,5.0,10.0,20.0)

def mean(xs): return sum(xs)/len(xs) if xs else 0.0
def H(b): return hashlib.sha256(b).hexdigest()

def fetch():
    req=urllib.request.Request(DATA_URL,headers={"User-Agent":"MICCGI-M016-SequentialPolicy/1.0"})
    with urllib.request.urlopen(req,timeout=35) as r: raw=r.read()
    rows=list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    if len(rows)!=10000: raise RuntimeError(f"BAD_ROW_COUNT:{len(rows)}")
    fields=list(rows[0].keys())
    required={"timestamp","item_id","position","click","propensity_score"}
    if not required.issubset(fields): raise RuntimeError("BAD_SCHEMA:"+repr(fields))
    return rows,{"url":DATA_URL,"sha256":H(raw),"bytes":len(raw),"rows":len(rows),"fields":fields}

def prep(rows):
    out=[]
    for i,r in enumerate(rows):
        x=dict(r)
        x["row_id"]=i
        x["item_id"]=int(x["item_id"])
        x["position"]=int(x["position"])
        x["click"]=int(float(x["click"]))
        x["action_prob"]=float(x["propensity_score"])
        if not (0 < x["action_prob"] <= 1): raise RuntimeError("BAD_PSCORE")
        x["timestamp"]=str(x["timestamp"])
        # Keep user context only as anonymized strings; no identity inference.
        dyn=[k for k in r if k not in {"timestamp","item_id","position","click","propensity_score"}]
        x["context_key"]="|".join(str(r[k]) for k in dyn[:2]) if dyn else "GLOBAL"
        out.append(x)
    out.sort(key=lambda z:(z["timestamp"],z["row_id"]))
    return out

def blocks(rows,n=5):
    m=len(rows); return [rows[(i*m)//n:((i+1)*m)//n] for i in range(n)]

def fit_policy(hist,eps,alpha,contextual):
    by=defaultdict(lambda:defaultdict(lambda:[0.0,0]))
    actions_by_pos=defaultdict(set)
    for r in hist:
        key=(r["position"],r["context_key"] if contextual else "GLOBAL")
        by[key][r["item_id"]][0]+=r["click"]; by[key][r["item_id"]][1]+=1
        actions_by_pos[r["position"]].add(r["item_id"])
    global_ctr=mean([r["click"] for r in hist])
    tables={}
    for key,d in by.items():
        pos=key[0]; acts=sorted(actions_by_pos[pos])
        score={}
        for a in acts:
            s,n=d[a]
            score[a]=(s+alpha*global_ctr)/(n+alpha)
        z=sum(math.exp(8.0*score[a]) for a in acts)
        q={a:(1-eps)*(math.exp(8.0*score[a])/z)+eps/len(acts) for a in acts}
        tables[key]=q
    return {"eps":eps,"alpha":alpha,"contextual":contextual,"tables":tables,"actions_by_pos":{k:sorted(v) for k,v in actions_by_pos.items()}}

def qprob(pol,r):
    key=(r["position"],r["context_key"] if pol["contextual"] else "GLOBAL")
    acts=pol["actions_by_pos"].get(r["position"],[])
    if not acts:return 0.0
    tab=pol["tables"].get(key)
    if tab is None:return 1.0/len(acts)
    return tab.get(r["item_id"], pol["eps"]/len(acts))

def ope(rows,pol):
    ips=[]; weighted_click=[]; weights=[]
    for r in rows:
        q=qprob(pol,r); w=q/r["action_prob"]
        if not math.isfinite(w) or w<0: raise RuntimeError("BAD_WEIGHT")
        weights.append(w); weighted_click.append(w*r["click"]); ips.append(w*r["click"])
    ips_v=mean(ips)
    snips=sum(weighted_click)/sum(weights) if sum(weights)>0 else 0.0
    ess=(sum(weights)**2)/sum(w*w for w in weights) if weights else 0.0
    return {"ips":ips_v,"snips":snips,"ess":ess,"n":len(rows),"max_weight":max(weights) if weights else 0.0}

def logging_value(rows): return mean([r["click"] for r in rows])

def choose(hist,val):
    cands=[]
    for contextual in (False,True):
        for eps in EPSILONS:
            for alpha in ALPHAS:
                pol=fit_policy(hist,eps,alpha,contextual)
                ev=ope(val,pol)
                # conservative score penalizes low ESS and IPS/SNIPS disagreement
                disagreement=abs(ev["ips"]-ev["snips"])
                score=min(ev["ips"],ev["snips"])-0.5*disagreement
                if ev["ess"] < 0.20*len(val): score-=1.0
                cands.append((score,pol,ev))
    return max(cands,key=lambda z:z[0])

def main():
    OUT.mkdir(exist_ok=True)
    raw,receipt=fetch(); rows=prep(raw); bs=blocks(rows,5)
    lineage=[]; hist=list(bs[0]); parent="ROOT"
    for epoch in range(1,4):
        val=bs[epoch]
        test=bs[epoch+1]
        score,pol,val_ev=choose(hist,val)
        test_ev=ope(test,pol)
        base=logging_value(test)
        state={
            "epoch":epoch,"history_rows":len(hist),"validation_rows":len(val),"test_rows":len(test),
            "policy":{"epsilon":pol["eps"],"alpha":pol["alpha"],"contextual":pol["contextual"]},
            "validation_ope":val_ev,"test_ope":test_ev,"logging_test_ctr":base,
            "test_lift_ips":test_ev["ips"]-base,"test_lift_snips":test_ev["snips"]-base,
            "parent_state_sha256":parent,"dataset_sha256":receipt["sha256"],
            "paid_actions":0,"contract_actions":0,"financial_actions":0
        }
        state_sha=H(json.dumps(state,sort_keys=True,separators=(",",":")).encode())
        state["state_sha256"]=state_sha
        (OUT/f"state_{epoch}.json").write_text(json.dumps(state,indent=2,sort_keys=True))
        lineage.append(state); parent=state_sha
        hist.extend(val)
    # Need all sequential epochs to have adequate support; at least 2/3 must beat logging on both IPS and SNIPS.
    supported=all(x["test_ope"]["ess"]>=0.20*x["test_rows"] and x["test_ope"]["max_weight"]<50 for x in lineage)
    positive=sum(x["test_lift_ips"]>0 and x["test_lift_snips"]>0 for x in lineage)
    admitted=supported and positive>=2
    verdict={
      "admitted":admitted,"dataset":receipt,"epochs":3,
      "lineage":[{"epoch":x["epoch"],"policy":x["policy"],"logging_test_ctr":x["logging_test_ctr"],
                  "test_ope":x["test_ope"],"test_lift_ips":x["test_lift_ips"],"test_lift_snips":x["test_lift_snips"],
                  "state_sha256":x["state_sha256"],"parent_state_sha256":x["parent_state_sha256"]} for x in lineage],
      "claim_boundary":{"SEQUENTIAL_OFF_POLICY_POLICY_UPDATE":"ESTABLISHED_FOR_RECORDED_OBD_LOG" if admitted else "NOT_ESTABLISHED",
                        "LIVE_POLICY_DEPLOYMENT":"NOT_ESTABLISHED","REAL_PRODUCTION_INTERVENTION":"NOT_ESTABLISHED",
                        "ECONOMIC_T0":"NOT_OBSERVED","VERIFIED_REALIZED_PROFIT":"NOT_PROVEN","MICCGI":"UNPROVEN"}
    }
    (OUT/"adjudication.json").write_text(json.dumps(verdict,indent=2,sort_keys=True))
    print(json.dumps(verdict,sort_keys=True))
    raise SystemExit(0 if admitted else 2)
if __name__=="__main__": main()
