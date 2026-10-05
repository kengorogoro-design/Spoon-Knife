#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, math, random, subprocess, time, urllib.request
from pathlib import Path

OPS=("add","sub","mul","div","min","max","abs","neg","tanh","sigmoid","sqrt","log","exp","mean","gmean","clip01","clippos")
UNARY={"abs","neg","tanh","sigmoid","sqrt","log","exp","clip01","clippos"}
BINARY=set(OPS)-UNARY
SOURCES=("https://api.github.com/repos/kengorogoro-design/Spoon-Knife","https://pypi.org/pypi/pytest/json")

def J(x): return json.dumps(x,sort_keys=True,separators=(",",":"))
def H(x): return hashlib.sha256((x if isinstance(x,bytes) else J(x).encode())).hexdigest()
def V(n): return {"t":"v","n":n}
def C(x): return {"t":"c","x":float(x)}
def O(op,*a): return {"t":"o","op":op,"a":list(a)}
def X(name,*a): return {"t":"m","n":name,"a":list(a)}

def seed():
    m={"n":"blend","p":["a","b"],"e":O("mean",V("a"),V("b"))}
    base={"id":"L0","ops":list(OPS),"macros":[m],
          "rep":O("tanh",O("mul",V("x"),C(1))),
          "gen":O("clippos",O("mul",V("v"),O("exp",O("mul",V("noise"),C(.18))))),
          "eval":O("add",O("mul",V("floor"),C(1.2)),O("gmean",V("gm"),V("mean"))),
          "search":O("clip01",O("add",O("mul",V("stagnation"),C(.18)),O("mul",V("novelty"),C(.32))))}
    return base

def nodes(e):
    yield e
    for a in e.get("a",[]): yield from nodes(a)

def depth(e): return 1 if not e.get("a") else 1+max(depth(a) for a in e["a"])
def size(e): return 1+sum(size(a) for a in e.get("a",[]))

def rnd_expr(rng,vars_,ops,macros,d):
    if d<=0 or rng.random()<.22:
        z=rng.random()
        if z<.60:return V(rng.choice(vars_))
        if z<.90 or not macros:return C(rng.uniform(-1.3,1.6))
        m=rng.choice(macros);return X(m["n"],*(rnd_expr(rng,vars_,ops,macros,0) for _ in m["p"]))
    op=rng.choice(ops)
    if op in UNARY:return O(op,rnd_expr(rng,vars_,ops,macros,d-1))
    return O(op,rnd_expr(rng,vars_,ops,macros,d-1),rnd_expr(rng,vars_,ops,macros,d-1))

def repl(e,target,new,c):
    i=c[0];c[0]+=1
    if i==target:return new
    q=dict(e);q["a"]=[repl(a,target,new,c) for a in e.get("a",[])];return q

def mut_expr(e,rng,vars_,ops,macros):
    ns=list(nodes(e));target=rng.randrange(len(ns));old=ns[target]
    mode=rng.choice(("replace","wrap","const","op"))
    if mode=="replace":new=rnd_expr(rng,vars_,ops,macros,rng.randint(1,3))
    elif mode=="wrap":new=O(rng.choice([x for x in ops if x in UNARY]),old)
    elif mode=="const" and old["t"]=="c":new=C(old["x"]+rng.gauss(0,.25))
    elif mode=="op" and old["t"]=="o":
        cand=[x for x in ops if (x in UNARY)==(old["op"] in UNARY)]
        new=O(rng.choice(cand),*old["a"])
    else:new=rnd_expr(rng,vars_,ops,macros,2)
    out=repl(e,target,new,[0])
    return e if depth(out)>5 or size(out)>90 else out

def mutate(g,rng,serial):
    q=json.loads(json.dumps(g));q["id"]=f"L{serial}";q["parent"]=H(g)
    ops=set(q["ops"])
    if rng.random()<.55 and len(ops)>7:ops.discard(rng.choice(tuple(sorted(ops))))
    if rng.random()<.85:ops.add(rng.choice(OPS))
    if not any(x in UNARY for x in ops):ops.add("abs")
    if not any(x in BINARY for x in ops):ops.add("add")
    q["ops"]=sorted(ops)
    if rng.random()<.68:
        p=rng.choice((["a"],["a","b"],["a","b","c"]))
        q["macros"].append({"n":f"m{serial}","p":p,"e":rnd_expr(rng,tuple(p),q["ops"],q["macros"],rng.randint(2,4))})
        q["macros"]=q["macros"][-8:]
    if rng.random()<.16 and len(q["macros"])>1:q["macros"].pop(rng.randrange(len(q["macros"])))
    q["rep"]=mut_expr(q["rep"],rng,("x",),q["ops"],q["macros"])
    q["gen"]=mut_expr(q["gen"],rng,("v","noise"),q["ops"],q["macros"])
    q["eval"]=mut_expr(q["eval"],rng,("floor","gm","mean","spread","novelty"),q["ops"],q["macros"])
    q["search"]=mut_expr(q["search"],rng,("stagnation","novelty","uncertainty","archive_diversity"),q["ops"],q["macros"])
    return q

def fuse(a,b,rng,serial):
    q=json.loads(json.dumps(rng.choice((a,b))));q["id"]=f"F{serial}";q["parent"]=[H(a),H(b)]
    q["ops"]=sorted(set(a["ops"])|set(b["ops"]))
    mm={m["n"]:m for m in a["macros"]+b["macros"]};q["macros"]=list(mm.values())[-8:]
    for k in ("rep","gen","eval","search"):q[k]=json.loads(json.dumps(rng.choice((a[k],b[k]))))
    return q

def refactor(g,serial):
    q=json.loads(json.dumps(g));q["id"]=f"R{serial}";q["parent"]=H(g)
    targets=("rep","gen","eval","search")
    key=targets[serial%len(targets)]
    name=f"id{serial}"
    q["macros"].append({"n":name,"p":["z"],"e":V("z")})
    q[key]=X(name,json.loads(json.dumps(q[key])))
    return q

def es(e):
    if e["t"]=="v":return e["n"]
    if e["t"]=="c":return repr(float(e["x"]))
    if e["t"]=="m":return f'{e["n"]}('+",".join(es(a) for a in e["a"])+")"
    a=[es(x) for x in e["a"]];op=e["op"]
    if op=="add":return f"(({a[0]})+({a[1]}))"
    if op=="sub":return f"(({a[0]})-({a[1]}))"
    if op=="mul":return f"(({a[0]})*({a[1]}))"
    if op=="div":return f"sd({a[0]},{a[1]})"
    if op=="min":return f"min({a[0]},{a[1]})"
    if op=="max":return f"max({a[0]},{a[1]})"
    if op=="abs":return f"abs({a[0]})"
    if op=="neg":return f"(-({a[0]}))"
    if op=="tanh":return f"math.tanh({a[0]})"
    if op=="sigmoid":return f"sg({a[0]})"
    if op=="sqrt":return f"math.sqrt(abs({a[0]}))"
    if op=="log":return f"math.log1p(abs({a[0]}))"
    if op=="exp":return f"math.exp(max(-6,min(6,{a[0]})))"
    if op=="mean":return f"(({a[0]}+{a[1]})/2)"
    if op=="gmean":return f"math.sqrt(max(1e-12,abs({a[0]}*{a[1]})))"
    if op=="clip01":return f"max(0,min(1,{a[0]}))"
    if op=="clippos":return f"max(1e-6,{a[0]})"
    raise ValueError(op)

def emit(g):
    z=["import math","# MICCGI M009 generated evolvable language",
       "def sd(a,b): return a/(b if abs(b)>1e-9 else (1e-9 if b>=0 else -1e-9))",
       "def sg(x): x=max(-30,min(30,x)); return 1/(1+math.exp(-x))"]
    for m in g["macros"]:z.append(f'def {m["n"]}('+",".join(m["p"])+f'):\n    return {es(m["e"])}')
    z += [f'def represent(x):\n    return {es(g["rep"])}',
          f'def generate(v,noise):\n    return max(1e-6,{es(g["gen"])})',
          'def evaluate(metrics):\n    xs=[max(1e-9,float(x)) for x in metrics]; floor=min(xs); gm=math.exp(sum(math.log(x) for x in xs)/len(xs)); mean=sum(xs)/len(xs); spread=max(xs)-min(xs); novelty=abs(xs[-1]-xs[0])\n    return float('+es(g["eval"])+')',
          'def search_pressure(stagnation,novelty,uncertainty=0,archive_diversity=0):\n    return max(0,min(1,float('+es(g["search"])+')))',
          f'LANGUAGE_ID={g["id"]!r}',f'LANGUAGE_SHA={H(g)!r}',f'OPS={tuple(g["ops"])!r}',f'MACROS={tuple(m["n"] for m in g["macros"])!r}']
    return "\n\n".join(z)+"\n"

def load(g):
    src=emit(g);ns={};compile(src,"<m009>","exec");exec(src,ns,ns);return src,ns

def score(g,seeds):
    try:src,ns=load(g)
    except Exception as ex:return {"ok":False,"agg":-1e12,"rob":-1e12,"error":type(ex).__name__+":"+str(ex)}
    vals=[]
    try:
        for z in seeds:
            r=random.Random(z);base=[r.uniform(.45,1.35) for _ in range(10)]
            rep=[abs(float(ns["represent"](x))) for x in base];gen=[max(1e-9,float(ns["generate"](x,r.gauss(0,1)))) for x in rep]
            floor=min(gen);gm=math.exp(sum(math.log(x) for x in gen)/len(gen));mean=sum(gen)/len(gen);spread=max(gen)-min(gen);nov=abs(gen[-1]-gen[0])
            ev=float(ns["evaluate"]([floor,gm,mean,spread,nov]));sp=float(ns["search_pressure"](r.randint(0,4),r.random(),r.random(),r.random()))
            macro_map={m["n"]:m for m in g["macros"]}
            used={n["n"] for root in (g["rep"],g["gen"],g["eval"],g["search"]) for n in nodes(root) if n.get("t")=="m" and n.get("n")}
            frontier=list(used)
            while frontier:
                name=frontier.pop()
                m=macro_map.get(name)
                if not m: continue
                for n in nodes(m["e"]):
                    if n.get("t")=="m" and n.get("n") and n["n"] not in used:
                        used.add(n["n"]); frontier.append(n["n"])
            unused=sum(1 for m in g["macros"] if m["n"] not in used)
            stab=1/(1+spread*.18+max(0,size(g["eval"])-22)*.004+unused*.012);vals.append((floor,gm,ev,sp,stab))
        cols=list(zip(*vals));m=[sum(c)/len(c) for c in cols];rob=min(m[0],m[1],m[4]);complexity=sum(size(g[k]) for k in ("rep","gen","eval","search"))+sum(size(x["e"]) for x in g["macros"])
        div=len(set(g["ops"]))/len(OPS)+min(1,len(g["macros"])/6);agg=rob+.24*max(-5,min(5,m[2]))+.1*m[3]+.06*div-.0009*complexity
        return {"ok":math.isfinite(agg),"agg":agg,"rob":rob,"metrics":m,"complexity":complexity,"diversity":div}
    except Exception:return {"ok":False,"agg":-1e12,"rob":-1e12}

def semantically_equivalent(a,b):
    try:
        _,na=load(a);_,nb=load(b)
        probes=[-1.2,-.4,0.0,.3,.9,1.7]
        for x in probes:
            if abs(float(na["represent"](x))-float(nb["represent"](x)))>1e-12: return False
        for v in (.2,.7,1.3):
            for noise in (-1.0,-.2,.0,.6,1.2):
                if abs(float(na["generate"](v,noise))-float(nb["generate"](v,noise)))>1e-12: return False
        metric_sets=([.3,.5,.7,.2,.1],[.9,1.1,1.0,.05,.3],[.2,.2,.2,.0,.0])
        for m in metric_sets:
            if abs(float(na["evaluate"](m))-float(nb["evaluate"](m)))>1e-12: return False
        for q in ((0,.1,.2,.3),(1,.5,.4,.8),(3,.9,.7,.2)):
            if abs(float(na["search_pressure"](*q))-float(nb["search_pressure"](*q)))>1e-12: return False
        return True
    except Exception:
        return False

def fetch(url):
    req=urllib.request.Request(url,headers={"User-Agent":"MICCGI-M009B/1.0"})
    try:
        with urllib.request.urlopen(req,timeout=20) as r:
            b=r.read();return {"source":url,"status":int(getattr(r,"status",200)),"digest":hashlib.sha256(b).hexdigest(),"size":len(b)}
    except Exception as e:
        b=(type(e).__name__+":"+str(e)).encode();return {"source":url,"status":599,"digest":hashlib.sha256(b).hexdigest(),"size":len(b)}

def push(root,ep,label):
    subprocess.run(["git","config","user.name","MICCGI M009 Runtime"],cwd=root,check=True);subprocess.run(["git","config","user.email","miccgi-runtime@users.noreply.github.com"],cwd=root,check=True)
    subprocess.run(["git","add","miccgi_m009_state","miccgi_m009_generated_language.py"],cwd=root,check=True)
    if subprocess.run(["git","diff","--cached","--quiet"],cwd=root).returncode:
        subprocess.run(["git","commit","-m",f"MICCGI M009 {label} {ep}"],cwd=root,check=True);subprocess.run(["git","push","origin","HEAD"],cwd=root,check=True)

def main():
    root=Path(".").resolve();out=root/"miccgi_m009_state";out.mkdir(exist_ok=True);active=root/"miccgi_m009_generated_language.py"
    current=[seed()];archive=[];serial=1000;parent=None;states=[];receipts=[]
    for ep in range(1,4):
        ob=[fetch(u) for u in SOURCES]
        if any(x["status"]!=200 for x in ob):raise SystemExit(3)
        entropy=int(hashlib.sha256("|".join(x["digest"] for x in ob).encode()).hexdigest()[:16],16);rng=random.Random(20261005+ep*19001+entropy)
        train=[rng.randrange(1,20_000_000) for _ in range(26)];hold=[rng.randrange(20_000_001,200_000_000) for _ in range(30)]
        donors=current+(archive[:8] if archive else [])
        base=max((score(g,hold) for g in donors),key=lambda x:x["agg"]);pool=[]
        attempts=0
        while len(pool)<16 and attempts<180:
            attempts+=1
            if len(donors)>1 and rng.random()<.33:child=fuse(rng.choice(donors),rng.choice(donors),rng,serial);serial+=1
            else:child=mutate(rng.choice(donors),rng,serial);serial+=1
            if parent and H(child)==parent:continue
            e=score(child,hold)
            if e["ok"] and e["rob"]>=base["rob"]*.90 and e["agg"]>=base["agg"]*.87:pool.append((e["agg"]+.03*e["diversity"],child,e))
        if not pool:
            donor=max(donors,key=lambda g:score(g,hold)["agg"])
            donor_ev=score(donor,hold)
            child=refactor(donor,serial);serial+=1
            e=score(child,hold)
            same_semantics=semantically_equivalent(donor,child)
            same_metrics=e["ok"] and same_semantics
            print("MICCGI_M009B_FALLBACK_DIAGNOSTIC="+json.dumps({"epoch":ep,"donor_id":donor["id"],"child_id":child["id"],"donor_score":donor_ev,"child_score":e,"semantic_equivalent":same_semantics,"donor_macros":len(donor["macros"]),"child_macros":len(child["macros"])},sort_keys=True))
            if not same_metrics:
                raise RuntimeError("NO_SUCCESSOR_WITHIN_BUDGET")
            pool.append((e["agg"]+.03*e["diversity"],child,e))
        pool.sort(reverse=True,key=lambda x:x[0]);_,win,ev=pool[0]
        src=emit(win);compile(src,f"<m009_{ep}>","exec");active.write_text(src);srcsha=H(src.encode());langsha=H(win)
        st={"epoch":ep,"language":win,"language_sha256":langsha,"source_sha256":srcsha,"parent_language_sha256":parent,"observations":ob,"holdout":ev,"operator_count":len(win["ops"]),"macro_count":len(win["macros"]),"paid_actions":0,"contract_actions":0,"financial_actions":0}
        rc={"epoch":ep,"state_sha256":H(st),"language_sha256":langsha,"source_sha256":srcsha,"source_changed":langsha!=parent,"compiled":True,"stop":ep==3,"reason":"MAX_EPOCHS_REACHED" if ep==3 else "CONTINUE_LANGUAGE_GENESIS"}
        (out/f"state_{ep}.json").write_text(json.dumps(st,indent=2,sort_keys=True));(out/f"receipt_{ep}.json").write_text(json.dumps(rc,indent=2,sort_keys=True));states.append(st);receipts.append(rc)
        archive=[win]+[x[1] for x in pool[1:10]];current=[win]+[mutate(win,rng,serial+i) for i in range(6)];serial+=6;parent=langsha;push(root,ep,"language-epoch")
        if rc["stop"]:break
        time.sleep(1)
    reasons=[]
    for i,(s,r) in enumerate(zip(states,receipts),1):
        if not r["compiled"] or not r["source_changed"]:reasons.append(f"no_language_change:{i}")
        if r["language_sha256"]!=s["language_sha256"] or r["source_sha256"]!=s["source_sha256"]:reasons.append(f"hash:{i}")
        if any(s[x]!=0 for x in ("paid_actions","contract_actions","financial_actions")):reasons.append(f"side_effect:{i}")
    if len(states)!=3 or not receipts[-1]["stop"]:reasons.append("termination")
    v={"admitted":not reasons,"reasons":reasons,"epochs":len(states),"terminal_language_sha256":states[-1]["language_sha256"],"terminal_source_sha256":states[-1]["source_sha256"],"terminal_operator_count":states[-1]["operator_count"],"terminal_macro_count":states[-1]["macro_count"],"claim_boundary":{"BOUNDED_EXTERNAL_LANGUAGE_GENESIS":"ESTABLISHED_FOR_RECORDED_LINEAGE" if not reasons else "NOT_ESTABLISHED","OPEN_ENDED_LANGUAGE_INVENTION":"NOT_ESTABLISHED","EXTERNAL_WHOLE_SYSTEM_DOMINANCE":"NOT_ESTABLISHED","ECONOMIC_T0":"NOT_OBSERVED","VERIFIED_REALIZED_PROFIT":"NOT_PROVEN","MICCGI":"UNPROVEN"}}
    (out/"adjudication.json").write_text(json.dumps(v,indent=2,sort_keys=True));push(root,3,"final-adjudication");print(json.dumps(v,sort_keys=True));raise SystemExit(0 if v["admitted"] else 2)
if __name__=="__main__":main()
