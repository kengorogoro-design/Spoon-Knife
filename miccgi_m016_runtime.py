from __future__ import annotations
import csv, hashlib, io, json, math, urllib.request
from collections import defaultdict
from pathlib import Path

RANDOM_URL="https://raw.githubusercontent.com/st-tech/zr-obp/master/obd/random/all/all.csv"
BTS_URL="https://raw.githubusercontent.com/st-tech/zr-obp/master/obd/bts/all/all.csv"
OUT=Path("miccgi_m016_state")
MIX_GRID=(0.25,0.45,0.65,0.80)
AFF_GRID=(0.0,0.5,1.0,1.5,2.0)
CTR_GRID=(0.0,0.4,0.8)
SUP_GRID=(0.0,0.4,0.8,1.2)

def mean(xs): return sum(xs)/len(xs) if xs else 0.0
def var(xs):
    if len(xs)<2:return 0.0
    m=mean(xs); return sum((x-m)**2 for x in xs)/(len(xs)-1)
def sha(b): return hashlib.sha256(b).hexdigest()

def fetch(url):
    last=None
    for _ in range(3):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"MICCGI-M016B-SupportAwareOPE/1.0"})
            with urllib.request.urlopen(req,timeout=40) as r: raw=r.read()
            rows=list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
            if len(rows)<9000: raise RuntimeError(f"ROW_COUNT:{len(rows)}")
            return rows,{"url":url,"sha256":sha(raw),"bytes":len(raw),"rows":len(rows),"columns":list(rows[0])}
        except Exception as e: last=e
    raise last

def normalize(rows):
    out=[]
    for i,r in enumerate(rows):
        x={str(k).strip().lower():str(v).strip() for k,v in r.items() if k is not None}
        def pick(*names):
            for n in names:
                if n in x:return x[n]
            raise KeyError(names)
        action=int(float(pick("item_id")))
        aff=[]
        for a in range(80):
            k=f"user-item_affinity_{a}"
            try: aff.append(float(x[k]))
            except Exception: aff.append(0.0)
        out.append({
            "row_id":i,"timestamp":pick("timestamp"),"action":action,
            "position":int(float(pick("position"))),"reward":float(pick("click")),
            "pscore":float(pick("propensity_score","action_prob")),"affinity":aff,
            "user_features":[x.get(f"user_feature_{j}","") for j in range(4)]
        })
    out.sort(key=lambda r:r["timestamp"])
    if any(not (0<r["pscore"]<=1) for r in out): raise RuntimeError("INVALID_PSCORE")
    return out

def split_time(rows):
    n=len(rows);a=int(n*.50);b=int(n*.70)
    return rows[:a],rows[a:b],rows[b:]

def zvec(xs):
    m=mean(xs); s=math.sqrt(mean([(x-m)**2 for x in xs]))
    if s<1e-9:return [0.0]*len(xs)
    return [(x-m)/s for x in xs]

def build_tables(rtrain,btrain):
    actions=range(80);positions=sorted({r["position"] for r in rtrain+btrain})
    g=mean([r["reward"] for r in rtrain])
    clicks=defaultdict(float); counts=defaultdict(int)
    for r in rtrain:
        k=(r["position"],r["action"]);clicks[k]+=r["reward"];counts[k]+=1
    ctr={}
    for p in positions:
        raw=[]
        for a in actions:
            n=counts[(p,a)]; c=clicks[(p,a)]
            raw.append((c+25*g)/(n+25))
        zs=zvec(raw)
        for a,z in zip(actions,zs):ctr[(p,a)]=z
    freq=defaultdict(float)
    for p in positions:
        rc=[0.5]*80; bc=[0.5]*80
        for r in rtrain:
            if r["position"]==p:rc[r["action"]]+=1
        for r in btrain:
            if r["position"]==p:bc[r["action"]]+=1
        rs=sum(rc);bs=sum(bc)
        # geometric support consensus: avoids actions unsupported by either logger
        geom=[math.sqrt((rc[a]/rs)*(bc[a]/bs)) for a in actions]
        z=sum(geom)
        for a in actions:freq[(p,a)]=geom[a]/z
    return ctr,freq

def policy_probs(row,ctr,support,mix,waff,wctr,wsup):
    p=row["position"]; aff=zvec(row["affinity"])
    logits=[]
    for a in range(80):
        sp=max(1e-12,support[(p,a)])
        logits.append(waff*aff[a]+wctr*ctr[(p,a)]+wsup*math.log(sp*80.0+1e-12))
    mx=max(logits); ex=[math.exp(max(-40,min(40,v-mx))) for v in logits];z=sum(ex)
    reward_pi=[e/z for e in ex]
    # support-aware mixture keeps target inside both logging policies' observable region
    return [(1-mix)*support[(p,a)] + mix*reward_pi[a] for a in range(80)]

def eval_policy(rows,ctr,support,mix,waff,wctr,wsup):
    weights=[];wr=[];rewards=[];diff=[]
    for r in rows:
        pi=policy_probs(r,ctr,support,mix,waff,wctr,wsup)
        w=pi[r["action"]]/r["pscore"]
        weights.append(w);wr.append(w*r["reward"]);rewards.append(r["reward"]);diff.append(w*r["reward"]-r["reward"])
    ips=mean(wr);base=mean(rewards);mw=mean(weights);sw=sum(weights)
    snips=sum(wr)/sw if sw else 0.0
    ess=sw*sw/max(1e-12,sum(w*w for w in weights))
    se=math.sqrt(var(diff)/len(diff))
    infl=[w*(r-snips) for w,r in zip(weights,rewards)]
    snse=(math.sqrt(var(infl)/len(infl))/mw) if mw>1e-12 else 999.0
    srt=sorted(weights)
    return {"n":len(rows),"logging_value":base,"ips_value":ips,"snips_value":snips,
            "ips_uplift":ips-base,"snips_uplift":snips-base,
            "ips_uplift_ci95":[ips-base-1.96*se,ips-base+1.96*se],
            "snips_uplift_ci95":[snips-base-1.96*snse,snips-base+1.96*snse],
            "ips_diff_se":se,"snips_se":snse,"mean_weight":mw,"ess":ess,"ess_ratio":ess/len(rows),
            "max_weight":max(weights),"p99_weight":srt[min(len(srt)-1,int(.99*len(srt)))],
            "weight_sha256":sha(json.dumps([round(x,10) for x in weights],separators=(",",":")).encode())}

def consistency(a,b):
    d=a["snips_value"]-b["snips_value"];se=math.sqrt(a["snips_se"]**2+b["snips_se"]**2)
    z=abs(d)/max(se,1e-12)
    return {"difference":d,"combined_se":se,"z_abs":z,"consistent_at_95pct":z<=1.96}

def select(rtr,rva,btr,bva):
    ctr,support=build_tables(rtr,btr);cand=[]
    for mix in MIX_GRID:
      for waff in AFF_GRID:
       for wctr in CTR_GRID:
        for wsup in SUP_GRID:
          if waff==wctr==wsup==0:continue
          rm=eval_policy(rva,ctr,support,mix,waff,wctr,wsup)
          bm=eval_policy(bva,ctr,support,mix,waff,wctr,wsup)
          con=consistency(rm,bm)
          support_floor=min(rm["ess_ratio"],bm["ess_ratio"])
          tail=max(rm["max_weight"],bm["max_weight"])
          # validation utility: absolute target value across both loggers + identifiability
          low=min(rm["snips_value"]-1.96*rm["snips_se"],bm["snips_value"]-1.96*bm["snips_se"])
          gain=min(rm["ips_uplift"],rm["snips_uplift"])
          penalty=max(0.0,con["z_abs"]-1.5)*.001 + max(0.0,.12-support_floor)*.02 + max(0.0,tail-50)*.00002
          score=low + .25*gain + .0005*support_floor - penalty
          cand.append((score,mix,waff,wctr,wsup,rm,bm,con,ctr,support))
    cand.sort(key=lambda x:x[0],reverse=True)
    return cand[0],len(cand)

def main():
    OUT.mkdir(exist_ok=True)
    rr,rrcp=fetch(RANDOM_URL);br,brcp=fetch(BTS_URL)
    r=normalize(rr);b=normalize(br);rtr,rva,rte=split_time(r);btr,bva,bte=split_time(b)
    best,ncand=select(rtr,rva,btr,bva)
    score,mix,waff,wctr,wsup,rvm,bvm,vcon,ctr,support=best
    rt=eval_policy(rte,ctr,support,mix,waff,wctr,wsup)
    bt=eval_policy(bte,ctr,support,mix,waff,wctr,wsup)
    con=consistency(rt,bt)
    support_ok=rt["ess_ratio"]>=.20 and bt["ess_ratio"]>=.10 and rt["max_weight"]<=50 and bt["max_weight"]<=50
    random_gain=rt["ips_uplift_ci95"][0]>0 and rt["snips_uplift_ci95"][0]>0
    established=bool(random_gain and support_ok and con["consistent_at_95pct"])
    result={"admitted":established,"datasets":{"random":rrcp,"bts":brcp},
      "time_split":{"random":{"train":len(rtr),"validation":len(rva),"test":len(rte)},"bts":{"train":len(btr),"validation":len(bva),"test":len(bte)}},
      "candidate_search":{"count":ncand,"selected":{"mix_reward":mix,"affinity_weight":waff,"ctr_weight":wctr,"support_weight":wsup,
         "random_validation":rvm,"bts_validation":bvm,"validation_cross_logger":vcon}},
      "random_future_test":rt,"bts_future_cross_logger_test":bt,"cross_logger_consistency":con,"support_ok":support_ok,
      "claim_boundary":{"SUPPORT_AWARE_CROSS_LOGGER_OPE":"ESTABLISHED_FOR_RECORDED_ZOZOTOWN_LOGS" if established else "NOT_ESTABLISHED",
       "SEQUENTIAL_POLICY_DEPLOYMENT":"NOT_ESTABLISHED","LIVE_EXPERIMENT_EXECUTION":"NOT_ESTABLISHED",
       "REAL_PRODUCTION_INTERVENTION":"NOT_ESTABLISHED","ECONOMIC_T0":"NOT_OBSERVED",
       "VERIFIED_REALIZED_PROFIT":"NOT_PROVEN","MICCGI":"UNPROVEN"}}
    (OUT/"adjudication.json").write_text(json.dumps(result,indent=2,sort_keys=True))
    print(json.dumps(result,sort_keys=True));raise SystemExit(0 if established else 2)
if __name__=="__main__":main()
