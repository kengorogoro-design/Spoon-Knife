from __future__ import annotations
import csv,hashlib,io,json,math,urllib.request
from pathlib import Path

DATA_URL="https://raw.githubusercontent.com/st-tech/zr-obp/master/obd/random/all/all.csv"
OUT=Path("miccgi_m016_state")
BETAS=(0.25,0.5,1.0,2.0,4.0,8.0)
EPSILONS=(0.02,0.05,0.10,0.20,0.35)

def H(b): return hashlib.sha256(b).hexdigest()
def mean(xs): return sum(xs)/len(xs) if xs else 0.0

def fetch():
    req=urllib.request.Request(DATA_URL,headers={"User-Agent":"MICCGI-M016B-ContextualPolicy/1.0"})
    with urllib.request.urlopen(req,timeout=35) as r: raw=r.read()
    rows=list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    if len(rows)!=10000: raise RuntimeError(f"BAD_ROW_COUNT:{len(rows)}")
    fields=list(rows[0].keys())
    aff=[f"user-item_affinity_{i}" for i in range(80)]
    reqd={"timestamp","item_id","position","click","propensity_score",*aff}
    if not reqd.issubset(fields): raise RuntimeError("BAD_SCHEMA")
    return rows,{"url":DATA_URL,"sha256":H(raw),"bytes":len(raw),"rows":len(rows),"fields":fields}

def prep(rows):
    out=[]
    for i,r in enumerate(rows):
        aff=[float(r[f"user-item_affinity_{j}"]) for j in range(80)]
        x={"row_id":i,"timestamp":str(r["timestamp"]),"item_id":int(r["item_id"]),"position":int(r["position"]),
           "click":int(float(r["click"])),"pscore":float(r["propensity_score"]),"affinity":aff,
           "user_ctx":tuple(r.get(f"user_feature_{j}","") for j in range(4))}
        if not (0<x["pscore"]<=1): raise RuntimeError("BAD_PSCORE")
        if len(aff)!=80 or not all(math.isfinite(a) for a in aff): raise RuntimeError("BAD_AFFINITY")
        out.append(x)
    out.sort(key=lambda z:(z["timestamp"],z["row_id"]))
    return out

def blocks(rows,n=5):
    m=len(rows);return [rows[(i*m)//n:((i+1)*m)//n] for i in range(n)]

def probs(r,beta,eps):
    xs=[max(-30.0,min(30.0,beta*a)) for a in r["affinity"]]
    mx=max(xs); es=[math.exp(x-mx) for x in xs]; z=sum(es)
    return [(1-eps)*e/z+eps/80.0 for e in es]

def ope(rows,beta,eps):
    ws=[]; wr=[]
    for r in rows:
        q=probs(r,beta,eps)[r["item_id"]]
        w=q/r["pscore"]
        if not math.isfinite(w) or w<0: raise RuntimeError("BAD_WEIGHT")
        ws.append(w);wr.append(w*r["click"])
    ips=mean(wr);snips=sum(wr)/sum(ws) if sum(ws)>0 else 0.0
    ess=(sum(ws)**2)/sum(w*w for w in ws)
    return {"ips":ips,"snips":snips,"ess":ess,"n":len(rows),"max_weight":max(ws),
            "mean_weight":mean(ws)}

def logging_ctr(rows): return mean([r["click"] for r in rows])

def choose(val):
    cand=[]
    for beta in BETAS:
        for eps in EPSILONS:
            ev=ope(val,beta,eps)
            disagreement=abs(ev["ips"]-ev["snips"])
            support_penalty=0 if ev["ess"]>=0.25*len(val) and ev["max_weight"]<30 else 1
            score=min(ev["ips"],ev["snips"])-0.5*disagreement-support_penalty
            cand.append((score,beta,eps,ev))
    return max(cand,key=lambda x:x[0])

def main():
    OUT.mkdir(exist_ok=True);raw,receipt=fetch();rows=prep(raw);bs=blocks(rows,5)
    lineage=[];parent="ROOT"
    for epoch in range(1,4):
        val=bs[epoch];test=bs[epoch+1]
        score,beta,eps,ve=choose(val);te=ope(test,beta,eps);base=logging_ctr(test)
        st={"epoch":epoch,"validation_rows":len(val),"test_rows":len(test),
            "policy":{"beta":beta,"epsilon":eps,"kind":"contextual_affinity_softmax"},
            "validation_ope":ve,"test_ope":te,"logging_test_ctr":base,
            "test_lift_ips":te["ips"]-base,"test_lift_snips":te["snips"]-base,
            "dataset_sha256":receipt["sha256"],"parent_state_sha256":parent,
            "paid_actions":0,"contract_actions":0,"financial_actions":0}
        sha=H(json.dumps(st,sort_keys=True,separators=(",",":")).encode());st["state_sha256"]=sha
        (OUT/f"state_{epoch}.json").write_text(json.dumps(st,indent=2,sort_keys=True));lineage.append(st);parent=sha
    supported=all(x["test_ope"]["ess"]>=0.25*x["test_rows"] and x["test_ope"]["max_weight"]<30 for x in lineage)
    positive=sum(x["test_lift_ips"]>0 and x["test_lift_snips"]>0 for x in lineage)
    avg_ips=mean([x["test_lift_ips"] for x in lineage]);avg_snips=mean([x["test_lift_snips"] for x in lineage])
    admitted=supported and positive>=2 and avg_ips>0 and avg_snips>0
    verdict={"admitted":admitted,"dataset":receipt,"epochs":3,"supported":supported,"positive_epochs":positive,
      "average_lift_ips":avg_ips,"average_lift_snips":avg_snips,
      "lineage":[{"epoch":x["epoch"],"policy":x["policy"],"logging_test_ctr":x["logging_test_ctr"],
                  "test_ope":x["test_ope"],"test_lift_ips":x["test_lift_ips"],"test_lift_snips":x["test_lift_snips"],
                  "state_sha256":x["state_sha256"],"parent_state_sha256":x["parent_state_sha256"]} for x in lineage],
      "claim_boundary":{"SEQUENTIAL_CONTEXTUAL_OFF_POLICY_UPDATE":"ESTABLISHED_FOR_RECORDED_OBD_LOG" if admitted else "NOT_ESTABLISHED",
                        "LIVE_POLICY_DEPLOYMENT":"NOT_ESTABLISHED","REAL_PRODUCTION_INTERVENTION":"NOT_ESTABLISHED",
                        "ECONOMIC_T0":"NOT_OBSERVED","VERIFIED_REALIZED_PROFIT":"NOT_PROVEN","MICCGI":"UNPROVEN"}}
    (OUT/"adjudication.json").write_text(json.dumps(verdict,indent=2,sort_keys=True))
    print(json.dumps(verdict,sort_keys=True));raise SystemExit(0 if admitted else 2)

if __name__=="__main__":main()
