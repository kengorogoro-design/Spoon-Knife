#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,math,random,subprocess,time,urllib.request
from pathlib import Path

SOURCES=("https://api.github.com/repos/kengorogoro-design/Spoon-Knife","https://pypi.org/pypi/pytest/json")
UNARY=("abs","neg","tanh","sigmoid","sqrt","log")
BINARY=("add","sub","mul","div","min","max","mean")

def J(x): return json.dumps(x,sort_keys=True,separators=(",",":"))
def H(x):
    b=x if isinstance(x,(bytes,bytearray)) else J(x).encode()
    return hashlib.sha256(b).hexdigest()
def V(n): return ["v",n]
def C(x): return ["c",float(x)]
def U(op,x): return ["u",op,x]
def B(op,x,y): return ["b",op,x,y]
def sd(a,b): return a/(b if abs(b)>1e-9 else (1e-9 if b>=0 else -1e-9))
def sg(x): x=max(-30.0,min(30.0,x)); return 1/(1+math.exp(-x))

def ev(e,a,b):
    t=e[0]
    if t=="v": return float(a if e[1]=="a" else b)
    if t=="c": return float(e[1])
    if t=="u":
        x=ev(e[2],a,b);op=e[1]
        if op=="abs":z=abs(x)
        elif op=="neg":z=-x
        elif op=="tanh":z=math.tanh(x)
        elif op=="sigmoid":z=sg(x)
        elif op=="sqrt":z=math.sqrt(abs(x))
        elif op=="log":z=math.log1p(abs(x))
        else: raise ValueError(op)
    else:
        x,y=ev(e[2],a,b),ev(e[3],a,b);op=e[1]
        if op=="add":z=x+y
        elif op=="sub":z=x-y
        elif op=="mul":z=x*y
        elif op=="div":z=sd(x,y)
        elif op=="min":z=min(x,y)
        elif op=="max":z=max(x,y)
        elif op=="mean":z=(x+y)/2
        else: raise ValueError(op)
    if not math.isfinite(z): raise ValueError("nonfinite")
    return max(-1e9,min(1e9,float(z)))

def src(e):
    t=e[0]
    if t=="v": return e[1]
    if t=="c": return repr(float(e[1]))
    if t=="u":
        x=src(e[2]);op=e[1]
        return {"abs":f"abs({x})","neg":f"(-({x}))","tanh":f"math.tanh({x})","sigmoid":f"sg({x})",
                "sqrt":f"math.sqrt(abs({x}))","log":f"math.log1p(abs({x}))"}[op]
    x,y=src(e[2]),src(e[3]);op=e[1]
    return {"add":f"(({x})+({y}))","sub":f"(({x})-({y}))","mul":f"(({x})*({y}))","div":f"sd({x},{y})",
            "min":f"min({x},{y})","max":f"max({x},{y})","mean":f"(({x}+{y})/2)"}[op]

def rand_expr(rng,d):
    if d<=0 or rng.random()<.22:
        return V(rng.choice(("a","b"))) if rng.random()<.72 else C(rng.uniform(-1.3,1.3))
    if rng.random()<.42:
        return U(rng.choice(UNARY),rand_expr(rng,d-1))
    return B(rng.choice(BINARY),rand_expr(rng,d-1),rand_expr(rng,d-1))

def probes(seed,n=150):
    rng=random.Random(seed);xs=[(float(a),float(b)) for a in (-4,-2,-1,-.2,0,.2,1,2,4) for b in (-3,-1,-.1,0,.1,1,3)]
    while len(xs)<n: xs.append((rng.uniform(-5,5),rng.uniform(-5,5)))
    return xs[:n]

def behavior(e,data): return [round(ev(e,a,b),9) for a,b in data]
def ndist(x,y):
    den=sum(abs(v) for v in x)/len(x)+sum(abs(v) for v in y)/len(y)+.5
    return min(4.0,(sum(abs(a-b) for a,b in zip(x,y))/len(x))/den)

def challenge_metrics(e,registry,archive,data):
    try: vals=behavior(e,data)
    except Exception: return None
    m=sum(vals)/len(vals);var=sum((x-m)**2 for x in vals)/len(vals)
    if var<1e-6:return None
    bases=[p["expr"] for p in registry]
    if not bases:
        bases=[B("add",V("a"),V("b")),B("sub",V("a"),V("b")),B("mul",V("a"),V("b")),B("mean",V("a"),V("b")),U("abs",V("a")),U("tanh",V("b"))]
    gap=min(ndist(vals,behavior(x,data)) for x in bases)
    nov=min((ndist(vals,behavior(c["expr"],data)) for c in archive),default=1.0)
    return {"gap":gap,"novelty":nov,"variance":min(4.0,var),"behavior_sha256":H(vals)}

def seed_evaluators():
    return [
      {"id":"EV-GAP","w":[.48,.22,.22,.08]},
      {"id":"EV-NOVEL","w":[.25,.48,.19,.08]},
      {"id":"EV-LEARN","w":[.30,.20,.43,.07]},
      {"id":"EV-BAL","w":[.32,.32,.28,.08]},
    ]

def escore(e,c):
    gap,nov,var=c["gap"],c["novelty"],c["variance"];learn=max(0.0,1-abs(gap-.45)/.45);w=e["w"]
    return w[0]*gap+w[1]*nov+w[2]*learn+w[3]*min(1,var)

def choose_challenge(reg,archive,evals,seed,epoch,budget=220):
    rng=random.Random(seed+epoch*100003);data=probes(seed+epoch*7919);pool=[];seen=set()
    for i in range(budget):
        e=rand_expr(rng,rng.randint(2,5));sem=H(e)
        if sem in seen:continue
        seen.add(sem);m=challenge_metrics(e,reg,archive,data)
        if not m or m["gap"]<.06 or m["novelty"]<.015:continue
        c={"id":"ch_"+sem[:12],"expr":e,"semantic_sha256":sem,**m,"source_epoch":epoch}
        ss=sorted((escore(v,c) for v in evals),reverse=True);score=.7*(sum(ss)/len(ss))+.3*min(ss)
        pool.append((score,c))
    if not pool: raise RuntimeError("NO_ENDOGENOUS_CHALLENGE")
    pool.sort(key=lambda z:z[0],reverse=True)
    return pool[0][1]

def primitive_source(p):
    name=p["name"];return "\n".join([
      "import math",
      "def sd(a,b): return a/(b if abs(b)>1e-9 else (1e-9 if b>=0 else -1e-9))",
      "def sg(x): x=max(-30.0,min(30.0,x)); return 1/(1+math.exp(-x))",
      f"def {name}(a,b):",
      f"    return float({src(p['expr'])})",""
    ])

def absorb(ch,registry):
    sem=H(ch["expr"]);name="spi_"+sem[:12];p={"name":name,"expr":ch["expr"],"semantic_sha256":sem,
      "behavior_sha256":ch["behavior_sha256"],"challenge_sha256":ch["semantic_sha256"],"source":None}
    p["source"]=primitive_source(p);compile(p["source"],f"<{name}>","exec")
    if any(x["behavior_sha256"]==p["behavior_sha256"] for x in registry):raise RuntimeError("BEHAVIOR_DUPLICATE")
    return p

def evolve_evaluators(evs,winner,seed,epoch):
    rng=random.Random(seed+epoch*33013);ranked=sorted(evs,key=lambda x:escore(x,winner),reverse=True);elite=ranked[:2];out=[dict(x) for x in elite]
    while len(out)<len(evs):
        p=rng.choice(elite);w=[max(.03,x*math.exp(rng.gauss(0,.12))) for x in p["w"]];s=sum(w);w=[x/s for x in w]
        out.append({"id":f"EV{epoch}-{len(out)}","w":w,"parent":p["id"]})
    return out

def active_source(reg):
    parts=["import math","def sd(a,b): return a/(b if abs(b)>1e-9 else (1e-9 if b>=0 else -1e-9))","def sg(x): x=max(-30.0,min(30.0,x)); return 1/(1+math.exp(-x))"]
    for p in reg: parts.append(p["source"])
    parts.append(f"def active_controller(a,b): return {reg[-1]['name']}(a,b)")
    return "\n\n".join(parts)+"\n"

def fetch(url):
    req=urllib.request.Request(url,headers={"User-Agent":"MICCGI-M011/1.0"})
    try:
        with urllib.request.urlopen(req,timeout=20) as r:
            b=r.read();return {"source":url,"status":int(getattr(r,"status",200)),"digest":hashlib.sha256(b).hexdigest(),"size":len(b)}
    except Exception as e:
        b=(type(e).__name__+":"+str(e)).encode();return {"source":url,"status":599,"digest":hashlib.sha256(b).hexdigest(),"size":len(b)}

def push(root,ep,label):
    subprocess.run(["git","config","user.name","MICCGI M011 Runtime"],cwd=root,check=True);subprocess.run(["git","config","user.email","miccgi-runtime@users.noreply.github.com"],cwd=root,check=True)
    subprocess.run(["git","add","miccgi_m011_state","miccgi_m011_active_semantics.py"],cwd=root,check=True)
    if subprocess.run(["git","diff","--cached","--quiet"],cwd=root).returncode:
        subprocess.run(["git","commit","-m",f"MICCGI M011 {label} {ep}"],cwd=root,check=True);subprocess.run(["git","push","origin","HEAD"],cwd=root,check=True)

def main():
    root=Path(".").resolve();out=root/"miccgi_m011_state";out.mkdir(exist_ok=True);active=root/"miccgi_m011_active_semantics.py"
    reg=[];archive=[];evals=seed_evaluators();parent=None;states=[];receipts=[]
    for ep in range(1,4):
        observations=[fetch(u) for u in SOURCES]
        if any(x["status"]!=200 for x in observations):raise RuntimeError("OBSERVATION_FAILURE")
        entropy=int(hashlib.sha256("|".join(x["digest"] for x in observations).encode()).hexdigest()[:16],16);seed=20261005+entropy
        ch=choose_challenge(reg,archive,evals,seed,ep);p=absorb(ch,reg);reg=reg+[p];archive=archive+[ch];evals=evolve_evaluators(evals,ch,seed,ep)
        asrc=active_source(reg);compile(asrc,f"<m011_active_{ep}>","exec");active.write_text(asrc)
        st={"epoch":ep,"parent_state_sha256":parent,"registry":reg,"registry_sha256":H(reg),"challenge_archive":archive,"challenge_archive_sha256":H(archive),
            "evaluators":evals,"evaluator_sha256":H(evals),"selected_challenge":ch,"new_primitive":p,"active_source_sha256":H(asrc.encode()),
            "observations":observations,"paid_actions":0,"contract_actions":0,"financial_actions":0}
        sh=H(st);rc={"epoch":ep,"state_sha256":sh,"registry_sha256":st["registry_sha256"],"challenge_sha256":ch["semantic_sha256"],
                     "evaluator_sha256":st["evaluator_sha256"],"primitive_name":p["name"],"compiled":True,"active_use_verified":p["name"] in asrc,
                     "stop":ep==3,"reason":"MAX_EPOCHS_REACHED" if ep==3 else "CONTINUE_SEMANTIC_COEVOLUTION"}
        (out/f"state_{ep}.json").write_text(json.dumps(st,indent=2,sort_keys=True));(out/f"receipt_{ep}.json").write_text(json.dumps(rc,indent=2,sort_keys=True))
        states.append(st);receipts.append(rc);parent=sh;push(root,ep,"semantic-epoch")
        if rc["stop"]:break
        time.sleep(1)
    reasons=[];prev=None;prev_reg=[];prev_archive=[]
    for i,(s,r) in enumerate(zip(states,receipts),1):
        if r["state_sha256"]!=H(s):reasons.append(f"state:{i}")
        if s["parent_state_sha256"]!=prev:reasons.append(f"parent:{i}")
        if s["registry"][:len(prev_reg)]!=prev_reg:reasons.append(f"registry:{i}")
        if s["challenge_archive"][:len(prev_archive)]!=prev_archive:reasons.append(f"archive:{i}")
        if not r["compiled"] or not r["active_use_verified"]:reasons.append(f"execution:{i}")
        if any(s[x]!=0 for x in ("paid_actions","contract_actions","financial_actions")):reasons.append(f"side_effect:{i}")
        prev=r["state_sha256"];prev_reg=s["registry"];prev_archive=s["challenge_archive"]
    if len({s["selected_challenge"]["behavior_sha256"] for s in states})!=3:reasons.append("challenge_behavior_stasis")
    if len({s["evaluator_sha256"] for s in states})<2:reasons.append("evaluator_stasis")
    if len(states)!=3 or not receipts[-1]["stop"]:reasons.append("termination")
    v={"admitted":not reasons,"reasons":reasons,"epochs":len(states),"terminal_state_sha256":prev,
       "terminal_registry_sha256":states[-1]["registry_sha256"],"terminal_registry_size":len(states[-1]["registry"]),
       "terminal_evaluator_sha256":states[-1]["evaluator_sha256"],"challenge_archive_size":len(states[-1]["challenge_archive"]),
       "claim_boundary":{"BOUNDED_EXTERNAL_ENDOGENOUS_SEMANTIC_COEVOLUTION":"ESTABLISHED_FOR_RECORDED_LINEAGE" if not reasons else "NOT_ESTABLISHED",
         "HUMAN_FIXED_TARGET_LIST_REQUIRED":"FALSE_FOR_RECORDED_LINEAGE","EXTERNAL_SEMANTIC_UTILITY":"NOT_ESTABLISHED",
         "FUNDAMENTALLY_NEW_PRIMITIVE_SEMANTICS":"NOT_ESTABLISHED","ECONOMIC_T0":"NOT_OBSERVED",
         "VERIFIED_REALIZED_PROFIT":"NOT_PROVEN","MICCGI":"UNPROVEN"}}
    (out/"adjudication.json").write_text(json.dumps(v,indent=2,sort_keys=True));push(root,3,"final-adjudication");print(json.dumps(v,sort_keys=True));raise SystemExit(0 if v["admitted"] else 2)
if __name__=="__main__":main()
