from __future__ import annotations
import csv,hashlib,io,json,math,urllib.request
from collections import defaultdict
from pathlib import Path

RANDOM_URL="https://raw.githubusercontent.com/st-tech/zr-obp/master/obd/random/all/all.csv"
BTS_URL="https://raw.githubusercontent.com/st-tech/zr-obp/master/obd/bts/all/all.csv"
OUT=Path("miccgi_m016_state")
TOPK=(3,5,8,12,20,30,40)
CTR_W=(0.0,0.5,1.0,2.0)
FREQ_W=(0.5,1.0,2.0)
Q_W=(0.5,1.0,2.0)

def mean(x):return sum(x)/len(x) if x else 0.0
def var(x):
    if len(x)<2:return 0.0
    m=mean(x);return sum((z-m)**2 for z in x)/(len(x)-1)
def sha(b):return hashlib.sha256(b).hexdigest()
def quantile(xs,q):
    if not xs:return 0.0
    s=sorted(xs);i=min(len(s)-1,max(0,int(q*(len(s)-1))))
    return s[i]

def fetch(url):
    req=urllib.request.Request(url,headers={"User-Agent":"MICCGI-M016C-CertifiedSupport/1.0"})
    with urllib.request.urlopen(req,timeout=40) as r:raw=r.read()
    rows=list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    if len(rows)<9000:raise RuntimeError("BAD_ROWS")
    return rows,{"url":url,"sha256":sha(raw),"bytes":len(raw),"rows":len(rows),"columns":list(rows[0])}

def norm(rows):
    out=[]
    for i,r in enumerate(rows):
        x={str(k).strip().lower():str(v).strip() for k,v in r.items() if k is not None}
        out.append({"row_id":i,"timestamp":x["timestamp"],"action":int(float(x["item_id"])),"position":int(float(x["position"])),
                    "reward":float(x["click"]),"pscore":float(x.get("propensity_score",x.get("action_prob","0")))})
    out.sort(key=lambda r:r["timestamp"])
    if any(not(0<r["pscore"]<=1) for r in out):raise RuntimeError("BAD_PSCORE")
    return out

def split(rows):
    n=len(rows);a=int(.5*n);b=int(.7*n);return rows[:a],rows[a:b],rows[b:]

def zmap(d,keys):
    xs=[d[k] for k in keys];m=mean(xs);s=math.sqrt(mean([(x-m)**2 for x in xs]))
    return {k:((d[k]-m)/s if s>1e-12 else 0.0) for k in keys}

def train_stats(rtr,btr):
    positions=sorted({r["position"] for r in rtr+btr}); actions=range(80)
    rg=mean([r["reward"] for r in rtr])
    rc=defaultdict(int);rr=defaultdict(float);bf=defaultdict(int);bp=defaultdict(list)
    for r in rtr:
        k=(r["position"],r["action"]);rc[k]+=1;rr[k]+=r["reward"]
    for r in btr:
        k=(r["position"],r["action"]);bf[k]+=1;bp[k].append(r["pscore"])
    ctr={};freq={};q10={};diag={}
    for p in positions:
        tot=sum(bf[(p,a)] for a in actions)+80
        for a in actions:
            k=(p,a);n=rc[k];ctr[k]=(rr[k]+25*rg)/(n+25)
            freq[k]=(bf[k]+1)/tot
            q10[k]=quantile(bp[k],.10) if bp[k] else 0.0
            diag[f"{p}:{a}"]={"bts_count":bf[k],"bts_pscore_q10":q10[k],"bts_pscore_median":quantile(bp[k],.5) if bp[k] else 0.0,
                              "random_ctr":ctr[k]}
    return positions,ctr,freq,q10,diag

def build_policy(positions,ctr,freq,q10,k, wc,wf,wq):
    probs={}
    for p in positions:
        keys=[(p,a) for a in range(80)]
        zc=zmap(ctr,keys)
        # rank by certified support first: frequency * lower propensity
        ranked=sorted(range(80),key=lambda a:(q10[(p,a)]*freq[(p,a)],freq[(p,a)]),reverse=True)
        safe=ranked[:k]
        raw={}
        for a in safe:
            sp=max(q10[(p,a)],1e-12);fr=max(freq[(p,a)],1e-12)
            raw[a]=math.exp(max(-40,min(40,wc*zc[(p,a)]+wf*math.log(fr*80)+wq*math.log(sp*80))))
        z=sum(raw.values())
        if z<=0:continue
        for a in range(80):probs[(p,a)]=raw.get(a,0.0)/z
    return probs

def evalp(rows,probs):
    w=[];wr=[];rwd=[];d=[]
    for r in rows:
        pi=probs.get((r["position"],r["action"]),0.0);wi=pi/r["pscore"]
        w.append(wi);wr.append(wi*r["reward"]);rwd.append(r["reward"]);d.append(wi*r["reward"]-r["reward"])
    ips=mean(wr);base=mean(rwd);sw=sum(w);mw=mean(w);sn=sum(wr)/sw if sw else 0.0
    ess=sw*sw/max(1e-12,sum(x*x for x in w));se=math.sqrt(var(d)/len(d))
    infl=[wi*(ri-sn) for wi,ri in zip(w,rwd)];snse=math.sqrt(var(infl)/len(infl))/mw if mw>1e-12 else 999
    sws=sorted(w)
    return {"n":len(rows),"logging_value":base,"ips_value":ips,"snips_value":sn,"ips_uplift":ips-base,"snips_uplift":sn-base,
            "ips_uplift_ci95":[ips-base-1.96*se,ips-base+1.96*se],"snips_uplift_ci95":[sn-base-1.96*snse,sn-base+1.96*snse],
            "ips_diff_se":se,"snips_se":snse,"mean_weight":mw,"ess":ess,"ess_ratio":ess/len(rows),"max_weight":max(w),
            "p99_weight":sws[min(len(sws)-1,int(.99*len(sws)))],"zero_weight_fraction":sum(x==0 for x in w)/len(w)}

def cons(a,b):
    d=a["snips_value"]-b["snips_value"];se=math.sqrt(a["snips_se"]**2+b["snips_se"]**2);z=abs(d)/max(se,1e-12)
    return {"difference":d,"combined_se":se,"z_abs":z,"consistent_at_95pct":z<=1.96}

def main():
    OUT.mkdir(exist_ok=True);rr,rrcp=fetch(RANDOM_URL);br,brcp=fetch(BTS_URL)
    r=norm(rr);b=norm(br);rtr,rva,rte=split(r);btr,bva,bte=split(b)
    positions,ctr,freq,q10,diag=train_stats(rtr,btr);cand=[]
    for k in TOPK:
      for wc in CTR_W:
       for wf in FREQ_W:
        for wq in Q_W:
            pi=build_policy(positions,ctr,freq,q10,k,wc,wf,wq)
            rm=evalp(rva,pi);bm=evalp(bva,pi);cc=cons(rm,bm)
            support=min(rm["ess_ratio"],bm["ess_ratio"]);tail=max(rm["max_weight"],bm["max_weight"])
            if support<.10 or tail>60:continue
            low=min(rm["snips_value"]-1.96*rm["snips_se"],bm["snips_value"]-1.96*bm["snips_se"])
            score=low+.35*min(rm["ips_uplift"],rm["snips_uplift"])+.001*support-.0005*cc["z_abs"]
            cand.append((score,k,wc,wf,wq,rm,bm,cc,pi))
    if not cand:
        result={"admitted":False,"datasets":{"random":rrcp,"bts":brcp},"reason":"NO_POLICY_SURVIVED_VALIDATION_SUPPORT_CERTIFICATE",
                "support_diagnostics":diag,"claim_boundary":{"CERTIFIED_SUPPORT_CROSS_LOGGER_OPE":"NOT_ESTABLISHED","MICCGI":"UNPROVEN",
                "ECONOMIC_T0":"NOT_OBSERVED","VERIFIED_REALIZED_PROFIT":"NOT_PROVEN"}}
        (OUT/"adjudication.json").write_text(json.dumps(result,indent=2,sort_keys=True));print(json.dumps(result,sort_keys=True));raise SystemExit(2)
    cand.sort(key=lambda x:x[0],reverse=True);best=cand[0]
    score,k,wc,wf,wq,rvm,bvm,vcc,pi=best;rt=evalp(rte,pi);bt=evalp(bte,pi);cc=cons(rt,bt)
    support_ok=min(rt["ess_ratio"],bt["ess_ratio"])>=.10 and max(rt["max_weight"],bt["max_weight"])<=60
    gain=rt["ips_uplift_ci95"][0]>0 and rt["snips_uplift_ci95"][0]>0
    established=bool(gain and support_ok and cc["consistent_at_95pct"])
    result={"admitted":established,"datasets":{"random":rrcp,"bts":brcp},"validation_survivors":len(cand),
      "selected_policy":{"top_k":k,"ctr_weight":wc,"bts_frequency_weight":wf,"bts_q10_propensity_weight":wq,
                         "random_validation":rvm,"bts_validation":bvm,"validation_cross_logger":vcc},
      "random_future_test":rt,"bts_future_cross_logger_test":bt,"cross_logger_consistency":cc,"support_ok":support_ok,
      "support_diagnostics_sha256":sha(json.dumps(diag,sort_keys=True).encode()),
      "claim_boundary":{"CERTIFIED_SUPPORT_CROSS_LOGGER_OPE":"ESTABLISHED_FOR_RECORDED_ZOZOTOWN_LOGS" if established else "NOT_ESTABLISHED",
       "SEQUENTIAL_POLICY_DEPLOYMENT":"NOT_ESTABLISHED","REAL_PRODUCTION_INTERVENTION":"NOT_ESTABLISHED",
       "ECONOMIC_T0":"NOT_OBSERVED","VERIFIED_REALIZED_PROFIT":"NOT_PROVEN","MICCGI":"UNPROVEN"}}
    (OUT/"adjudication.json").write_text(json.dumps(result,indent=2,sort_keys=True));print(json.dumps(result,sort_keys=True));raise SystemExit(0 if established else 2)
if __name__=="__main__":main()
