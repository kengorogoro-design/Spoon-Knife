from __future__ import annotations
import csv,hashlib,io,json,math,random,urllib.request
from itertools import product
from pathlib import Path

ARMS=("Mens E-Mail","Womens E-Mail")
CONTROL="No E-Mail"
OUTCOMES=("spend","conversion","visit")
FEATURES=("history_segment","zip_code","channel","newbie","mens","womens","recency_bucket")
URL="https://raw.githubusercontent.com/W-Tran/uplift-modelling/refs/heads/master/data/hillstrom/Kevin_Hillstrom_MineThatData_E-MailAnalytics_DataMiningChallenge_2008.03.20.csv"
OUT=Path("miccgi_m015_state")

def mean(x):return sum(x)/len(x) if x else 0.0
def var(x):
    if len(x)<2:return 0.0
    m=mean(x);return sum((z-m)**2 for z in x)/(len(x)-1)
def sd(x):return math.sqrt(max(0.0,var(x)))
def fetch():
    req=urllib.request.Request(URL,headers={"User-Agent":"MICCGI-M015-ActiveExperiment/1.0"})
    with urllib.request.urlopen(req,timeout=35) as r: raw=r.read()
    rows=list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    if len(rows)!=64000:raise RuntimeError(f"BAD_ROWS:{len(rows)}")
    return rows,{"url":URL,"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),"rows":len(rows)}
def prep(rows):
    out=[]
    for i,r in enumerate(rows):
        x={k.strip().lower():v.strip() for k,v in r.items()};x["row_id"]=i
        x["recency"]=float(x["recency"]);x["history"]=float(x["history"]);x["spend"]=float(x["spend"])
        for k in ("mens","womens","newbie","visit","conversion"):x[k]=int(float(x[k]))
        x["recency_bucket"]=str(min(3,int((x["recency"]-1)//3)))
        out.append(x)
    return out
def bucket(r):return int(hashlib.sha256(f'M015|{r["row_id"]}'.encode()).hexdigest()[:8],16)%10
def fval(r,f):return str(r[f])
def questions(initial):
    vals={f:sorted({fval(r,f) for r in initial}) for f in FEATURES}
    qs=[]
    for arm in ARMS:
      for outcome in OUTCOMES:
       for f in FEATURES:
        for value in vals[f]:
            sub=[r for r in initial if fval(r,f)==value and r["segment"] in (arm,CONTROL)]
            a=[r[outcome] for r in sub if r["segment"]==arm];c=[r[outcome] for r in sub if r["segment"]==CONTROL]
            if min(len(a),len(c))<80:continue
            se=math.sqrt(var(a)/len(a)+var(c)/len(c));mass=len(sub)/len(initial)
            effect=mean(a)-mean(c);width=3.92*se;score=mass*width
            qs.append({"arm":arm,"outcome":outcome,"feature":f,"value":value,"effect":effect,"se":se,"score":score,
                       "n_t":len(a),"n_c":len(c),"sd_t":sd(a),"sd_c":sd(c)})
    return sorted(qs,key=lambda q:q["score"],reverse=True)
def neyman(q,budget):
    st,sc=max(q["sd_t"],1e-9),max(q["sd_c"],1e-9);nt=round(budget*st/(st+sc));nt=max(int(.2*budget),min(int(.8*budget),nt));return nt,budget-nt
def eval_design(q,reservoir,budget,reps=250):
    pool_t=[r[q["outcome"]] for r in reservoir if r["segment"]==q["arm"] and fval(r,q["feature"])==q["value"]]
    pool_c=[r[q["outcome"]] for r in reservoir if r["segment"]==CONTROL and fval(r,q["feature"])==q["value"]]
    if min(len(pool_t),len(pool_c))<200:return None
    budget=min(budget,2*min(len(pool_t),len(pool_c))-2)
    if budget<120:return None
    nt,nc=neyman(q,budget);nu=budget//2;cu=budget-nu
    if nt>=len(pool_t) or nc>=len(pool_c) or nu>=len(pool_t) or cu>=len(pool_c):return None
    truth=mean(pool_t)-mean(pool_c);ae=[];ue=[]
    salt=int(hashlib.sha256(json.dumps(q,sort_keys=True).encode()).hexdigest()[:8],16)
    for i in range(reps):
        rng=random.Random(20261005+i*7919+salt)
        da=mean(rng.sample(pool_t,nt))-mean(rng.sample(pool_c,nc))
        du=mean(rng.sample(pool_t,nu))-mean(rng.sample(pool_c,cu))
        ae.append((da-truth)**2);ue.append((du-truth)**2)
    armse=math.sqrt(mean(ae));urmse=math.sqrt(mean(ue));impr=(urmse-armse)/max(urmse,1e-12)
    return {"budget":budget,"active_allocation":{"treatment":nt,"control":nc},"uniform_allocation":{"treatment":nu,"control":cu},
            "reservoir_truth_effect":truth,"active_rmse":armse,"uniform_rmse":urmse,"rmse_improvement":impr,
            "reservoir_counts":{"treatment":len(pool_t),"control":len(pool_c)}}
def main():
    OUT.mkdir(exist_ok=True);raw,receipt=fetch();rows=prep(raw)
    initial=[r for r in rows if bucket(r)<2];reservoir=[r for r in rows if 2<=bucket(r)<7];audit=[r for r in rows if bucket(r)>=7]
    qs=questions(initial);chosen=[];seen=set()
    for q in qs:
        sig=(q["arm"],q["outcome"],q["feature"])
        if sig in seen:continue
        ev=eval_design(q,reservoir,800)
        if ev is None:continue
        qq=dict(q);qq["replay"]=ev;chosen.append(qq);seen.add(sig)
        if len(chosen)>=5:break
    if len(chosen)<3:raise RuntimeError("INSUFFICIENT_EXPERIMENT_QUESTIONS")
    avg=mean([q["replay"]["rmse_improvement"] for q in chosen]);best=max(q["replay"]["rmse_improvement"] for q in chosen)
    audit_ok=True;audit_effects=[]
    for q in chosen:
        at=[r[q["outcome"]] for r in audit if r["segment"]==q["arm"] and fval(r,q["feature"])==q["value"]]
        ac=[r[q["outcome"]] for r in audit if r["segment"]==CONTROL and fval(r,q["feature"])==q["value"]]
        if min(len(at),len(ac))<80:audit_ok=False;continue
        eff=mean(at)-mean(ac);se=math.sqrt(var(at)/len(at)+var(ac)/len(ac))
        audit_effects.append({"question":{k:q[k] for k in ("arm","outcome","feature","value")},"effect":eff,"se":se,"ci95":[eff-1.96*se,eff+1.96*se],"n_t":len(at),"n_c":len(ac)})
    established=audit_ok and avg>0.005 and best>0.01
    result={"admitted":established,"dataset":receipt,"split":{"initial":len(initial),"replay_reservoir":len(reservoir),"audit":len(audit)},
            "selected_experiments":chosen,"average_rmse_improvement_vs_uniform":avg,"best_rmse_improvement_vs_uniform":best,
            "independent_audit_effects":audit_effects,
            "claim_boundary":{"ADAPTIVE_CAUSAL_EXPERIMENT_DESIGN":"ESTABLISHED_FOR_RECORDED_RCT_REPLAY" if established else "NOT_ESTABLISHED",
                              "LIVE_EXPERIMENT_EXECUTION":"NOT_ESTABLISHED","REAL_PRODUCTION_INTERVENTION":"NOT_ESTABLISHED",
                              "ECONOMIC_T0":"NOT_OBSERVED","VERIFIED_REALIZED_PROFIT":"NOT_PROVEN","MICCGI":"UNPROVEN"}}
    (OUT/"adjudication.json").write_text(json.dumps(result,indent=2,sort_keys=True))
    print(json.dumps(result,sort_keys=True));raise SystemExit(0 if established else 2)
if __name__=="__main__":main()
