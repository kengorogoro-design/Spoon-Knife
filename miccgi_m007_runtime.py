#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,math,random,subprocess,time,urllib.request
from pathlib import Path

AXES=("cognition","foresight","causal_intervention","research","technology","execution","economics","distribution","organization","recovery")
SOURCES=("https://api.github.com/repos/kengorogoro-design/Spoon-Knife","https://pypi.org/pypi/pytest/json")

def H(x):
    return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def norm(v):
    s=sum(max(.001,float(x)) for x in v); return [max(.001,float(x))/s for x in v]
def obs(url):
    req=urllib.request.Request(url,headers={"User-Agent":"MICCGI-M007/1.0"})
    try:
        with urllib.request.urlopen(req,timeout=20) as r:
            b=r.read(); return {"source":url,"status":int(getattr(r,"status",200)),"digest":hashlib.sha256(b).hexdigest(),"size":len(b)}
    except Exception as e:
        b=(type(e).__name__+":"+str(e)).encode(); return {"source":url,"status":599,"digest":hashlib.sha256(b).hexdigest(),"size":len(b)}
def init(seed=20261005,npop=12,nworld=8,neval=5,nsearch=5):
    rng=random.Random(seed)
    c=[{"id":f"C{i}","g":[rng.uniform(.35,.75) for _ in AXES]} for i in range(npop)]
    w=[{"id":f"W{i}","s":[rng.uniform(.15,.75) for _ in AXES]} for i in range(nworld)]
    e=[{"id":f"E{i}","w":norm([rng.uniform(.5,1.8) for _ in AXES]),"floor":rng.uniform(.8,1.8)} for i in range(neval)]
    p=[{"id":f"S{i}","rate":rng.uniform(.25,.7),"scale":rng.uniform(.08,.35),"radical":rng.uniform(.05,.35)} for i in range(nsearch)]
    return {"epoch":0,"seed":seed,"serial":1000,"candidates":c,"worlds":w,"evaluators":e,"search":p,"history":[],"paid_actions":0,"contract_actions":0,"financial_actions":0}
def perf(c,w):
    xs=[max(0.001,g*(1-.55*s)) for g,s in zip(c["g"],w["s"])]
    return min(xs),sum(math.log(x) for x in xs)/len(xs)
def score(c,worlds,e):
    per=[perf(c,w) for w in worlds]
    floor=min(x[0] for x in per); gm=sum(x[1] for x in per)/len(per)
    weighted=sum(a*b for a,b in zip(c["g"],e["w"]))
    return e["floor"]*floor+gm+weighted
def mutate_vec(v,rng,scale,radical):
    out=list(v)
    if rng.random()<radical:
        k=rng.randrange(len(out)); out[k]=rng.uniform(.2,1.2)
    for i in range(len(out)):
        if rng.random()<.45: out[i]=max(.03,min(1.5,out[i]*math.exp(rng.gauss(0,scale))))
    return out
def evolve(prev, observations, max_epochs=3):
    ep=prev["epoch"]+1; parent=H(prev)
    if any(o["status"]!=200 for o in observations):
        st=dict(prev);st["epoch"]=ep;st["parent"]=parent;st["observations"]=observations;st["transition"]="PRESERVE"
        return st,{"epoch":ep,"parent":parent,"state":H(st),"stop":ep>=max_epochs,"reason":"OBSERVATION_FAILURE"}
    entropy=int(hashlib.sha256("|".join(o["digest"] for o in observations).encode()).hexdigest()[:16],16)
    rng=random.Random(prev["seed"]+ep*10007+entropy)
    C=[dict(x,id=x["id"],g=list(x["g"])) for x in prev["candidates"]]
    W=[dict(x,id=x["id"],s=list(x["s"])) for x in prev["worlds"]]
    E=[dict(x,id=x["id"],w=list(x["w"])) for x in prev["evaluators"]]
    S=[dict(x) for x in prev["search"]];serial=prev["serial"]
    consensus={c["id"]:sum(score(c,W,e) for e in E)/len(E) for c in C}
    ranked=sorted(C,key=lambda c:consensus[c["id"]],reverse=True); leader=ranked[0]
    world_disc=[]
    for w in W:
        vals=[perf(c,w)[0] for c in C]; world_disc.append((max(vals)-min(vals)+sum(w["s"])/len(w["s"]),w))
    hard=[x[1] for x in sorted(world_disc,key=lambda z:z[0],reverse=True)[:max(3,len(W)//2)]]
    gains={}
    for sp in S:
        samples=[]
        for _ in range(3):
            p=rng.choice(ranked[:4]); child={"id":"tmp","g":mutate_vec(p["g"],rng,sp["scale"],sp["radical"])}
            samples.append(sum(score(child,W,e) for e in E)/len(E)-consensus[p["id"]])
        gains[sp["id"]]=sum(samples)/len(samples)
    bests=max(S,key=lambda s:gains[s["id"]])
    nextC=ranked[:3]
    while len(nextC)<len(C):
        p=rng.choice(ranked[:6]); serial+=1
        nextC.append({"id":f"C{serial}","g":mutate_vec(p["g"],rng,bests["scale"],bests["radical"])})
    nextW=hard[:]
    while len(nextW)<len(W):
        p=rng.choice(hard);serial+=1
        nextW.append({"id":f"W{serial}","s":mutate_vec(p["s"],rng,.18,.2)})
    eranked=sorted(E,key=lambda e:score(leader,W,e),reverse=True);nextE=eranked[:2]
    while len(nextE)<len(E):
        p=rng.choice(eranked[:3]);serial+=1
        nextE.append({"id":f"E{serial}","w":norm(mutate_vec(p["w"],rng,.12,.1)),"floor":max(.2,min(3,p["floor"]+rng.gauss(0,.12)))})
    sranked=sorted(S,key=lambda s:gains[s["id"]],reverse=True);nextS=sranked[:2]
    while len(nextS)<len(S):
        p=rng.choice(sranked[:3]);serial+=1
        nextS.append({"id":f"S{serial}","rate":max(.1,min(.85,p["rate"]+rng.gauss(0,.05))),"scale":max(.03,min(.6,p["scale"]+rng.gauss(0,.04))),"radical":max(.01,min(.6,p["radical"]+rng.gauss(0,.04)))})
    hist=list(prev["history"])+[{"epoch":ep,"leader":leader["id"],"leader_score":consensus[leader["id"]],"best_search":bests["id"],"observation_digests":[o["digest"] for o in observations]}]
    st={"epoch":ep,"seed":prev["seed"],"serial":serial,"candidates":nextC,"worlds":nextW,"evaluators":nextE,"search":nextS,"history":hist,"parent":parent,"observations":observations,"paid_actions":0,"contract_actions":0,"financial_actions":0}
    rec={"epoch":ep,"parent":parent,"state":H(st),"leader":leader["id"],"fingerprints":{"candidates":H(nextC),"worlds":H(nextW),"evaluators":H(nextE),"search":H(nextS)},"stop":ep>=max_epochs,"reason":"MAX_EPOCHS_REACHED" if ep>=max_epochs else "CONTINUE_METAGENESIS"}
    return st,rec
def verify(s0,states,recs,max_epochs):
    reasons=[];prev=s0;changed={k:False for k in ("candidates","worlds","evaluators","search")}
    for i,(s,r) in enumerate(zip(states,recs),1):
        if s["epoch"]!=i or r["epoch"]!=i:reasons.append(f"epoch:{i}")
        if r["parent"]!=H(prev):reasons.append(f"parent:{i}")
        if r["state"]!=H(s):reasons.append(f"state:{i}")
        for k in changed:
            if H(s[k])!=H(prev[k]):changed[k]=True
        if any(s[x]!=0 for x in ("paid_actions","contract_actions","financial_actions")):reasons.append(f"side_effect:{i}")
        prev=s
    if len(states)!=max_epochs:reasons.append("count")
    if not recs or not recs[-1]["stop"]:reasons.append("stop")
    if not all(changed.values()):reasons.append("population_stasis")
    return {"admitted":not reasons,"reasons":reasons,"epochs":len(states),"changed":changed,"terminal_state_sha256":H(prev),"claim_boundary":{"INDEPENDENT_EXTERNAL_METAGENESIS":"ESTABLISHED_FOR_BOUNDED_LINEAGE" if not reasons else "NOT_ESTABLISHED","OPEN_ENDED_SELF_IMPROVEMENT":"NOT_ESTABLISHED","EXTERNAL_WHOLE_SYSTEM_DOMINANCE":"NOT_ESTABLISHED","ECONOMIC_T0":"NOT_OBSERVED","VERIFIED_REALIZED_PROFIT":"NOT_PROVEN","MICCGI":"UNPROVEN"}}
def push(root,ep,label):
    subprocess.run(["git","config","user.name","MICCGI M007 Runtime"],cwd=root,check=True);subprocess.run(["git","config","user.email","miccgi-runtime@users.noreply.github.com"],cwd=root,check=True)
    subprocess.run(["git","add","miccgi_m007_state"],cwd=root,check=True)
    if subprocess.run(["git","diff","--cached","--quiet"],cwd=root).returncode:
        subprocess.run(["git","commit","-m",f"MICCGI M007 {label} {ep}"],cwd=root,check=True);subprocess.run(["git","push","origin","HEAD"],cwd=root,check=True)
def main():
    root=Path(".").resolve();out=root/"miccgi_m007_state";out.mkdir(exist_ok=True);s0=init();(out/"state_0.json").write_text(json.dumps(s0,indent=2,sort_keys=True))
    prev=s0;states=[];recs=[]
    for ep in range(1,4):
        o=[obs(u) for u in SOURCES];st,rc=evolve(prev,o,3);(out/f"state_{ep}.json").write_text(json.dumps(st,indent=2,sort_keys=True));(out/f"receipt_{ep}.json").write_text(json.dumps(rc,indent=2,sort_keys=True));states.append(st);recs.append(rc);prev=st;push(root,ep,"metagenesis-epoch")
        if rc["stop"]:break
        time.sleep(1)
    v=verify(s0,states,recs,3);(out/"adjudication.json").write_text(json.dumps(v,indent=2,sort_keys=True));push(root,3,"final-adjudication");print(json.dumps(v,sort_keys=True));raise SystemExit(0 if v["admitted"] else 2)
if __name__=="__main__":main()
