#!/usr/bin/env python3
from __future__ import annotations
import hashlib,importlib.util,json,math,py_compile,random,subprocess,time,urllib.request
from pathlib import Path

SOURCES=("https://api.github.com/repos/kengorogoro-design/Spoon-Knife","https://pypi.org/pypi/pytest/json")

def H(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def file_sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def obs(url):
    req=urllib.request.Request(url,headers={"User-Agent":"MICCGI-M008/1.0"})
    try:
        with urllib.request.urlopen(req,timeout=20) as r:
            b=r.read(); return {"source":url,"status":int(getattr(r,"status",200)),"digest":hashlib.sha256(b).hexdigest(),"size":len(b)}
    except Exception as e:
        b=(type(e).__name__+":"+str(e)).encode(); return {"source":url,"status":599,"digest":hashlib.sha256(b).hexdigest(),"size":len(b)}
def emit(s):
    return f'''import math
# MICCGI M008 generated meta-machinery
REPRESENTATION_POWER={s["representation_power"]!r}
GENERATOR_SCALE={s["generator_scale"]!r}
EVALUATOR_FLOOR={s["evaluator_floor"]!r}
EVALUATOR_BALANCE={s["evaluator_balance"]!r}
SEARCH_RADICAL={s["search_radical"]!r}
SEARCH_MEMORY={s["search_memory"]!r}

def represent(x):
    return math.copysign(abs(x)**REPRESENTATION_POWER,x)

def generate(v,noise):
    return max(0.001,v*math.exp(noise*GENERATOR_SCALE))

def evaluate(metrics):
    xs=[max(1e-9,float(x)) for x in metrics]
    floor=min(xs)
    gm=math.exp(sum(math.log(x) for x in xs)/len(xs))
    mean=sum(xs)/len(xs)
    return EVALUATOR_FLOOR*floor+EVALUATOR_BALANCE*gm+(1-EVALUATOR_BALANCE)*mean

def search_pressure(stagnation,novelty):
    return min(1.0,max(0.0,SEARCH_RADICAL*(1+stagnation*.25)+novelty*(1-SEARCH_MEMORY)))
'''
def load_module(path):
    spec=importlib.util.spec_from_file_location("m008_generated",path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def score_source(path,seeds):
    m=load_module(path);vals=[]
    for z in seeds:
        rng=random.Random(z);base=[rng.uniform(.55,1.25) for _ in range(8)]
        rep=[abs(m.represent(x)) for x in base]
        gen=[m.generate(x,rng.gauss(0,1)) for x in rep]
        floor=min(gen);gm=math.exp(sum(math.log(max(1e-9,x)) for x in gen)/len(gen));mean=sum(gen)/len(gen)
        e=m.evaluate([floor,gm,mean])
        sp=m.search_pressure(rng.randint(0,3),rng.random())
        stability=1/(1+abs(m.REPRESENTATION_POWER-1)*.25+m.GENERATOR_SCALE*.35+sp*.15)
        vals.append((floor,gm,e,sp,stability))
    cols=list(zip(*vals));metrics=[sum(c)/len(c) for c in cols]
    robust=min(metrics[0],metrics[1],metrics[4]);agg=robust+.35*metrics[2]+.12*metrics[3]
    return {"metrics":metrics,"robust":robust,"aggregate":agg}
def seed_spec():
    return {"representation_power":1.0,"generator_scale":.18,"evaluator_floor":1.0,"evaluator_balance":.55,"search_radical":.18,"search_memory":.65}
def mutate(s,rng,scale=.16):
    cl=lambda x,a,b:max(a,min(b,x))
    return {"representation_power":cl(s["representation_power"]*math.exp(rng.gauss(0,scale)),.45,1.8),
            "generator_scale":cl(s["generator_scale"]*math.exp(rng.gauss(0,scale)),.03,.7),
            "evaluator_floor":cl(s["evaluator_floor"]+rng.gauss(0,scale),.2,3),
            "evaluator_balance":cl(s["evaluator_balance"]+rng.gauss(0,scale*.55),.05,.95),
            "search_radical":cl(s["search_radical"]+rng.gauss(0,scale*.55),.02,.8),
            "search_memory":cl(s["search_memory"]+rng.gauss(0,scale*.55),.05,.95)}
def push(root,ep,label):
    subprocess.run(["git","config","user.name","MICCGI M008 Runtime"],cwd=root,check=True)
    subprocess.run(["git","config","user.email","miccgi-runtime@users.noreply.github.com"],cwd=root,check=True)
    subprocess.run(["git","add","miccgi_m008_state","miccgi_m008_generated_meta.py"],cwd=root,check=True)
    if subprocess.run(["git","diff","--cached","--quiet"],cwd=root).returncode:
        subprocess.run(["git","commit","-m",f"MICCGI M008 {label} {ep}"],cwd=root,check=True)
        subprocess.run(["git","push","origin","HEAD"],cwd=root,check=True)
def main():
    root=Path(".").resolve();out=root/"miccgi_m008_state";out.mkdir(exist_ok=True);src=root/"miccgi_m008_generated_meta.py"
    state0={"epoch":0,"spec":seed_spec(),"source_sha256":None,"paid_actions":0,"contract_actions":0,"financial_actions":0}
    src.write_text(emit(state0["spec"]));py_compile.compile(str(src),doraise=True);state0["source_sha256"]=file_sha(src);(out/"state_0.json").write_text(json.dumps(state0,indent=2,sort_keys=True))
    prev=state0;states=[];receipts=[]
    for ep in range(1,4):
        observations=[obs(u) for u in SOURCES]
        if any(o["status"]!=200 for o in observations): raise SystemExit(3)
        entropy=int(hashlib.sha256("|".join(o["digest"] for o in observations).encode()).hexdigest()[:16],16)
        rng=random.Random(20261005+ep*10007+entropy+int(prev["source_sha256"][:12],16))
        specs=[prev["spec"]]+[mutate(prev["spec"],rng,.18) for _ in range(11)]
        train=[rng.randrange(1,8_000_000) for _ in range(18)]
        hold=[rng.randrange(8_000_001,90_000_000) for _ in range(36)]
        candidates=[]
        for i,s in enumerate(specs):
            p=out/f"candidate_{ep}_{i}.py";p.write_text(emit(s));py_compile.compile(str(p),doraise=True)
            tr=score_source(p,train);candidates.append((tr["aggregate"],s,p))
        top=sorted(candidates,key=lambda x:x[0],reverse=True)[:4]
        hold_rank=[]
        for _,s,p in top: hold_rank.append((score_source(p,hold)["aggregate"],s,p,score_source(p,hold)))
        _,winner,wp,wev=max(hold_rank,key=lambda x:x[0])
        src.write_text(wp.read_text());py_compile.compile(str(src),doraise=True);sha=file_sha(src)
        st={"epoch":ep,"spec":winner,"source_sha256":sha,"parent_state_sha256":H(prev),"parent_source_sha256":prev["source_sha256"],"holdout_evidence":wev,"observations":observations,"paid_actions":0,"contract_actions":0,"financial_actions":0}
        rec={"epoch":ep,"parent_state_sha256":H(prev),"parent_source_sha256":prev["source_sha256"],"state_sha256":H(st),"source_sha256":sha,"source_changed":sha!=prev["source_sha256"],"compiled":True,"stop":ep==3,"reason":"MAX_EPOCHS_REACHED" if ep==3 else "CONTINUE_SELF_REWRITE"}
        (out/f"state_{ep}.json").write_text(json.dumps(st,indent=2,sort_keys=True));(out/f"receipt_{ep}.json").write_text(json.dumps(rec,indent=2,sort_keys=True))
        for p in out.glob(f"candidate_{ep}_*.py"): p.unlink()
        states.append(st);receipts.append(rec);prev=st;push(root,ep,"self-rewrite-epoch")
        if rec["stop"]: break
        time.sleep(1)
    reasons=[];p=state0
    for i,(s,r) in enumerate(zip(states,receipts),1):
        if r["parent_state_sha256"]!=H(p):reasons.append(f"parent_state:{i}")
        if r["parent_source_sha256"]!=p["source_sha256"]:reasons.append(f"parent_source:{i}")
        if r["state_sha256"]!=H(s):reasons.append(f"state:{i}")
        if r["source_sha256"]!=s["source_sha256"]:reasons.append(f"source:{i}")
        if not r["source_changed"]:reasons.append(f"source_stasis:{i}")
        if any(s[x]!=0 for x in ("paid_actions","contract_actions","financial_actions")):reasons.append(f"side_effect:{i}")
        p=s
    if len(states)!=3 or not receipts[-1]["stop"]:reasons.append("termination")
    verdict={"admitted":not reasons,"reasons":reasons,"epochs":len(states),"terminal_state_sha256":H(p),"terminal_source_sha256":p["source_sha256"],"claim_boundary":{"BOUNDED_EXTERNAL_META_MACHINERY_SELF_REWRITE":"ESTABLISHED_FOR_RECORDED_LINEAGE" if not reasons else "NOT_ESTABLISHED","OPEN_ENDED_SELF_IMPROVEMENT":"NOT_ESTABLISHED","EXTERNAL_WHOLE_SYSTEM_DOMINANCE":"NOT_ESTABLISHED","ECONOMIC_T0":"NOT_OBSERVED","VERIFIED_REALIZED_PROFIT":"NOT_PROVEN","MICCGI":"UNPROVEN"}}
    (out/"adjudication.json").write_text(json.dumps(verdict,indent=2,sort_keys=True));push(root,3,"final-adjudication");print(json.dumps(verdict,sort_keys=True));raise SystemExit(0 if verdict["admitted"] else 2)
if __name__=="__main__":main()
