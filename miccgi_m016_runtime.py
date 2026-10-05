from __future__ import annotations
import csv, hashlib, io, json, math, urllib.request
from collections import defaultdict
from pathlib import Path

RANDOM_URL="https://raw.githubusercontent.com/st-tech/zr-obp/master/obd/random/all/all.csv"
BTS_URL="https://raw.githubusercontent.com/st-tech/zr-obp/master/obd/bts/all/all.csv"
OUT=Path("miccgi_m016_state")
EPS_GRID=(0.25,0.45,0.65)
TEMP_GRID=(0.003,0.007,0.015,0.03)
SHRINK_GRID=(8.0,25.0,80.0)

def mean(xs): return sum(xs)/len(xs) if xs else 0.0
def var(xs):
    if len(xs)<2:return 0.0
    m=mean(xs); return sum((x-m)**2 for x in xs)/(len(xs)-1)
def sha(b): return hashlib.sha256(b).hexdigest()

def fetch(url):
    last=None
    for k in range(3):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"MICCGI-M016-CrossLoggerOPE/1.0"})
            with urllib.request.urlopen(req,timeout=40) as r: raw=r.read()
            if len(raw)<4_000_000: raise RuntimeError("DATA_TOO_SMALL")
            rows=list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
            if len(rows)<9000: raise RuntimeError(f"ROW_COUNT:{len(rows)}")
            return rows,{"url":url,"sha256":sha(raw),"bytes":len(raw),"rows":len(rows),"columns":list(rows[0])}
        except Exception as e:
            last=e
    raise last

def normalize(rows):
    out=[]
    for i,r in enumerate(rows):
        x={str(k).strip().lower():str(v).strip() for k,v in r.items() if k is not None}
        def pick(*names):
            for n in names:
                if n in x:return x[n]
            raise KeyError(names)
        y={
            "row_id":i,
            "timestamp":pick("timestamp"),
            "action":int(float(pick("item_id"))),
            "position":int(float(pick("position"))),
            "reward":float(pick("click")),
            "pscore":float(pick("propensity_score","action_prob")),
        }
        if not (0<y["pscore"]<=1): raise RuntimeError("INVALID_PSCORE")
        for k,v in x.items():
            if "user_feature" in k:
                y[k]=v
            if "affinity" in k:
                try:y[k]=float(v)
                except Exception:pass
        out.append(y)
    out.sort(key=lambda r:r["timestamp"])
    return out

def split_time(rows):
    n=len(rows); a=int(n*.50); b=int(n*.70)
    return rows[:a],rows[a:b],rows[b:]

def schema(rows):
    keys=sorted({k for r in rows for k in r})
    ctx=[k for k in keys if "user_feature" in k]
    aff=[k for k in keys if "affinity" in k]
    return ctx,aff

def build_model(train,feature,shrink):
    actions=sorted({r["action"] for r in train})
    positions=sorted({r["position"] for r in train})
    global_ctr=mean([r["reward"] for r in train])
    base=defaultdict(lambda:[0.0,0])
    cell=defaultdict(lambda:[0.0,0])
    for r in train:
        b=base[(r["position"],r["action"])];b[0]+=r["reward"];b[1]+=1
        if feature:
            c=cell[(r["position"],str(r.get(feature,"")),r["action"])];c[0]+=r["reward"];c[1]+=1
    base_ctr={}
    for p in positions:
      for a in actions:
        s,n=base[(p,a)]
        base_ctr[(p,a)]=(s+20.0*global_ctr)/(n+20.0)
    def scores(row):
        p=row["position"]; val=str(row.get(feature,"")) if feature else None
        z=[]
        for a in actions:
            prior=base_ctr[(p,a)]
            if feature:
                s,n=cell[(p,val,a)]
                est=(s+shrink*prior)/(n+shrink)
            else:
                est=prior
            z.append((a,est))
        return z
    return actions,scores

def probs_from_scores(sc,temp,eps):
    mx=max(v for _,v in sc)
    ex=[math.exp(max(-50.0,min(50.0,(v-mx)/temp))) for _,v in sc]
    z=sum(ex); n=len(ex)
    return {a:(1-eps)*(e/z)+eps/n for (a,_),e in zip(sc,ex)}

def eval_policy(rows,scores_fn,temp,eps,detail=False):
    w=[];wr=[];rewards=[];diff=[]
    for r in rows:
        probs=probs_from_scores(scores_fn(r),temp,eps)
        pe=probs.get(r["action"],0.0)
        wi=pe/r["pscore"]
        w.append(wi);wr.append(wi*r["reward"]);rewards.append(r["reward"]);diff.append(wi*r["reward"]-r["reward"])
    ips=mean(wr); base=mean(rewards); sw=sum(w)
    snips=sum(wr)/sw if sw else 0.0
    ess=(sw*sw)/max(1e-12,sum(x*x for x in w))
    se=math.sqrt(var(diff)/len(diff))
    lo=(ips-base)-1.96*se;hi=(ips-base)+1.96*se
    # delta-method-ish influence for SNIPS
    infl=[wi*(ri-snips) for wi,ri in zip(w,rewards)]
    sn_se=math.sqrt(var(infl)/len(infl))/(mean(w) if mean(w)>1e-12 else 1.0)
    sn_lo=(snips-base)-1.96*sn_se;sn_hi=(snips-base)+1.96*sn_se
    out={"n":len(rows),"logging_value":base,"ips_value":ips,"snips_value":snips,
         "ips_uplift":ips-base,"snips_uplift":snips-base,
         "ips_uplift_ci95":[lo,hi],"snips_uplift_ci95":[sn_lo,sn_hi],
         "ess":ess,"ess_ratio":ess/len(rows),"mean_weight":mean(w),"max_weight":max(w),
         "p99_weight":sorted(w)[min(len(w)-1,int(.99*len(w)))],"snips_se":sn_se,"ips_diff_se":se}
    if detail: out["weight_sha256"]=sha(json.dumps([round(x,12) for x in w],separators=(",",":")).encode())
    return out

def select(train,val):
    ctx,aff=schema(train)
    features=[None]+ctx[:8]
    candidates=[]
    for feature in features:
      for shrink in SHRINK_GRID:
        actions,sfn=build_model(train,feature,shrink)
        for temp in TEMP_GRID:
          for eps in EPS_GRID:
            m=eval_policy(val,sfn,temp,eps)
            conservative=min(m["ips_uplift_ci95"][0],m["snips_uplift_ci95"][0])
            support=min(m["ess_ratio"],1.0)
            score=conservative + .15*min(m["ips_uplift"],m["snips_uplift"]) + .001*support
            candidates.append((score,feature,shrink,temp,eps,m,actions,sfn))
    candidates.sort(key=lambda x:x[0],reverse=True)
    return candidates[0],len(candidates),ctx,aff

def consistency(a,b):
    # compare SNIPS value estimates from independent behavior policies
    d=a["snips_value"]-b["snips_value"]
    se=math.sqrt(a["snips_se"]**2+b["snips_se"]**2)
    z=abs(d)/max(se,1e-12)
    return {"difference":d,"combined_se":se,"z_abs":z,"consistent_at_95pct":z<=1.96}

def main():
    OUT.mkdir(exist_ok=True)
    rr,rrcp=fetch(RANDOM_URL); br,brcp=fetch(BTS_URL)
    random_rows=normalize(rr); bts_rows=normalize(br)
    tr,va,te=split_time(random_rows)
    btr,bva,bte=split_time(bts_rows)
    best,ncand,ctx,aff=select(tr,va)
    score,feature,shrink,temp,eps,vm,actions,sfn=best
    tm=eval_policy(te,sfn,temp,eps,detail=True)
    bm=eval_policy(bte,sfn,temp,eps,detail=True)
    cons=consistency(tm,bm)
    support_ok=(tm["ess_ratio"]>=.15 and bm["ess_ratio"]>=.10 and tm["max_weight"]<=50 and bm["max_weight"]<=50)
    random_gain=(tm["ips_uplift_ci95"][0]>0 and tm["snips_uplift_ci95"][0]>0)
    established=bool(random_gain and support_ok and cons["consistent_at_95pct"])
    result={
      "admitted":established,
      "datasets":{"random":rrcp,"bts":brcp},
      "schema":{"context_features":ctx,"affinity_features":aff,"n_actions":len(actions)},
      "time_split":{"random":{"train":len(tr),"validation":len(va),"test":len(te)},
                    "bts":{"train":len(btr),"validation":len(bva),"test":len(bte)}},
      "candidate_search":{"count":ncand,"selected":{"feature":feature,"shrink":shrink,"temperature":temp,"epsilon_uniform_floor":eps,
                                                    "validation":vm}},
      "random_future_test":tm,
      "bts_future_cross_logger_test":bm,
      "cross_logger_consistency":cons,
      "support_ok":support_ok,
      "claim_boundary":{
        "CROSS_LOGGER_OFF_POLICY_EVALUATION":"ESTABLISHED_FOR_RECORDED_ZOZOTOWN_LOGS" if established else "NOT_ESTABLISHED",
        "SEQUENTIAL_POLICY_DEPLOYMENT":"NOT_ESTABLISHED",
        "LIVE_EXPERIMENT_EXECUTION":"NOT_ESTABLISHED",
        "REAL_PRODUCTION_INTERVENTION":"NOT_ESTABLISHED",
        "ECONOMIC_T0":"NOT_OBSERVED",
        "VERIFIED_REALIZED_PROFIT":"NOT_PROVEN",
        "MICCGI":"UNPROVEN"
      }
    }
    (OUT/"adjudication.json").write_text(json.dumps(result,indent=2,sort_keys=True))
    print(json.dumps(result,sort_keys=True))
    raise SystemExit(0 if established else 2)

if __name__=="__main__": main()
