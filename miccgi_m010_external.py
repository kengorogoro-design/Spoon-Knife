#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,math,subprocess,time,urllib.request
from pathlib import Path

SOURCES=("https://api.github.com/repos/kengorogoro-design/Spoon-Knife","https://pypi.org/pypi/pytest/json")
UNARY=("abs","tanh","sigmoid","sqrt","log")
BINARY=("add","sub","mul","mean","min","max","div")
PROBES=(-100.0,-10.0,-2.0,-1.0,-.1,-1e-9,0.0,1e-9,.1,1.0,2.0,10.0,100.0)

def J(x): return json.dumps(x,sort_keys=True,separators=(",",":"))
def H(x): return hashlib.sha256((x if isinstance(x,bytes) else J(x).encode())).hexdigest()
def V(n): return ["v",n]
def U(op,a): return ["u",op,a]
def B(op,a,b): return ["b",op,a,b]
def size(e): return 1 if e[0]=="v" else 1+sum(size(x) for x in e[2:])

def sd(a,b): return a/(b if abs(b)>1e-9 else (1e-9 if b>=0 else -1e-9))
def sg(x): x=max(-30.0,min(30.0,x)); return 1.0/(1.0+math.exp(-x))
def ev(e,a,b):
    if e[0]=="v": return a if e[1]=="a" else b
    if e[0]=="u":
        x=ev(e[2],a,b);op=e[1]
        if op=="abs":v=abs(x)
        elif op=="tanh":v=math.tanh(x)
        elif op=="sigmoid":v=sg(x)
        elif op=="sqrt":v=math.sqrt(abs(x))
        elif op=="log":v=math.log1p(abs(x))
        else:raise ValueError(op)
    else:
        x=ev(e[2],a,b);y=ev(e[3],a,b);op=e[1]
        if op=="add":v=x+y
        elif op=="sub":v=x-y
        elif op=="mul":v=x*y
        elif op=="mean":v=(x+y)/2.0
        elif op=="min":v=min(x,y)
        elif op=="max":v=max(x,y)
        elif op=="div":v=sd(x,y)
        else:raise ValueError(op)
    if not math.isfinite(v): raise ValueError("nonfinite")
    return max(-1e12,min(1e12,float(v)))

def src(e):
    if e[0]=="v":return e[1]
    if e[0]=="u":
        x=src(e[2]);op=e[1]
        return {"abs":f"abs({x})","tanh":f"math.tanh({x})","sigmoid":f"sg({x})","sqrt":f"math.sqrt(abs({x}))","log":f"math.log1p(abs({x}))"}[op]
    x=src(e[2]);y=src(e[3]);op=e[1]
    return {"add":f"(({x})+({y}))","sub":f"(({x})-({y}))","mul":f"(({x})*({y}))","mean":f"(({x}+{y})/2.0)","min":f"min({x},{y})","max":f"max({x},{y})","div":f"sd({x},{y})"}[op]

def target(epoch,a,b):
    if epoch==1:return abs(a-b)
    if epoch==2:return sg(a*b)
    return math.tanh(a+b)*((a+b)/2.0)

def data():
    xs=[];vals=(-4,-2,-1,-.25,0,.25,1,2,4)
    for a in vals:
        for b in vals:xs.append((float(a),float(b)))
    return xs

def err(e,epoch):
    xs=data();ys=[target(epoch,a,b) for a,b in xs]
    try:ps=[ev(e,a,b) for a,b in xs]
    except Exception:return 1e99
    scale=sum(abs(y) for y in ys)/len(ys)+.25
    return sum(abs(p-y) for p,y in zip(ps,ys))/len(xs)/scale

def base_exprs():
    a,b=V("a"),V("b");out=[]
    for op in BINARY:out.append(B(op,a,b))
    for op in UNARY:out.extend((U(op,a),U(op,b)))
    return out

def beam(epoch):
    base=base_exprs();baseline=min((err(e,epoch),e) for e in base)
    ranked=sorted((err(e,epoch),e) for e in base)[:18]
    seen={H(e) for _,e in ranked}
    for _ in range(3):
        elite=[e for _,e in ranked[:12]];cand=list(ranked)
        for e in elite:
            for op in UNARY:
                q=U(op,e);h=H(q)
                if h not in seen and size(q)<=18:seen.add(h);cand.append((err(q,epoch),q))
            for v in (V("a"),V("b")):
                for op in BINARY:
                    for q in (B(op,e,v),B(op,v,e)):
                        h=H(q)
                        if h not in seen and size(q)<=18:seen.add(h);cand.append((err(q,epoch),q))
        for i,x in enumerate(elite[:6]):
            for y in elite[:6]:
                for op in ("add","sub","mul","mean"):
                    q=B(op,x,y);h=H(q)
                    if h not in seen and size(q)<=18:seen.add(h);cand.append((err(q,epoch),q))
        ranked=sorted(cand,key=lambda z:(z[0],size(z[1]),H(z[1])))[:24]
    return baseline,ranked[0]

BASE_SIGNATURES=set()
for e in base_exprs():
    BASE_SIGNATURES.add(tuple(round(ev(e,a,b),9) for a in (-3,-1,0,1,3) for b in (-2,0,2)))

def validate(e,existing):
    reasons=[];vals=[]
    try:
        for a in PROBES:
            for b in PROBES:
                x=ev(e,a,b);y=ev(e,a,b)
                if x!=y:reasons.append("nondeterministic")
                if not math.isfinite(x):reasons.append("nonfinite")
                vals.append(x)
    except Exception as ex:reasons.append(type(ex).__name__)
    sig=tuple(round(ev(e,a,b),9) for a in (-3,-1,0,1,3) for b in (-2,0,2)) if not reasons else ()
    sh=H(sig)
    if sig in BASE_SIGNATURES:reasons.append("baseline_duplicate")
    if sh in existing:reasons.append("registry_duplicate")
    if len(set(round(x,8) for x in vals))<3:reasons.append("degenerate")
    return not reasons,sorted(set(reasons)),sh

def primitive_source(name,e):
    nl=chr(10)
    return nl.join(["import math","def sd(a,b): return a/(b if abs(b)>1e-9 else (1e-9 if b>=0 else -1e-9))","def sg(x): x=max(-30.0,min(30.0,x)); return 1.0/(1.0+math.exp(-x))",f"def {name}(a,b):",f"    return float({src(e)})",""])

def fetch(url):
    req=urllib.request.Request(url,headers={"User-Agent":"MICCGI-M010/1.0"})
    try:
        with urllib.request.urlopen(req,timeout=20) as r:
            b=r.read();return {"source":url,"status":int(getattr(r,"status",200)),"digest":hashlib.sha256(b).hexdigest(),"size":len(b)}
    except Exception as ex:
        b=(type(ex).__name__+":"+str(ex)).encode();return {"source":url,"status":599,"digest":hashlib.sha256(b).hexdigest(),"size":len(b)}

def push(root,epoch,label):
    subprocess.run(["git","config","user.name","MICCGI M010 Runtime"],cwd=root,check=True)
    subprocess.run(["git","config","user.email","miccgi-runtime@users.noreply.github.com"],cwd=root,check=True)
    subprocess.run(["git","add","miccgi_m010_state","miccgi_m010_generated_primitives.py","miccgi_m010_active_language.py"],cwd=root,check=True)
    if subprocess.run(["git","diff","--cached","--quiet"],cwd=root).returncode:
        subprocess.run(["git","commit","-m",f"MICCGI M010 {label} {epoch}"],cwd=root,check=True)
        subprocess.run(["git","push","origin","HEAD"],cwd=root,check=True)

def main():
    root=Path(".").resolve();out=root/"miccgi_m010_state";out.mkdir(exist_ok=True)
    reg=[];signatures=set();states=[];parent=None
    for epoch in range(1,4):
        observations=[fetch(u) for u in SOURCES]
        if any(o["status"]!=200 for o in observations):raise RuntimeError("OBSERVATION_FAILURE")
        (be,bexpr),(ce,expr)=beam(epoch)
        ok,reasons,bh=validate(expr,signatures);improvement=(be-ce)/max(1e-12,be)
        if not ok or improvement<.08 or size(expr)<=1:raise RuntimeError("NO_VALID_PRIMITIVE")
        semantic=H(expr);name="pi_"+semantic[:12];ps=primitive_source(name,expr);compile(ps,f"<{name}>","exec")
        ns={};exec(ps,ns,ns)
        for a,b in ((-3,2),(-.5,.7),(0,0),(1.5,-2.2)):
            if abs(ns[name](a,b)-ev(expr,a,b))>1e-12:raise RuntimeError("SOURCE_MISMATCH")
        reg.append({"name":name,"expr":expr,"semantic_sha256":semantic,"behavior_sha256":bh,"baseline_error":be,"primitive_error":ce,"improvement_ratio":improvement,"target_epoch":epoch,"size":size(expr)})
        signatures.add(bh)
        allsrc="# M010 externally admitted primitives"+chr(10)+chr(10).join(primitive_source(x["name"],x["expr"]) for x in reg)
        (root/"miccgi_m010_generated_primitives.py").write_text(allsrc)
        lang=allsrc+chr(10)+f"def active_controller(a,b): return {name}(a,b)"+chr(10)
        compile(lang,"<m010_active_language>","exec");lns={};exec(lang,lns,lns)
        if abs(lns["active_controller"](.7,-.2)-ns[name](.7,-.2))>1e-12:raise RuntimeError("LANGUAGE_NOT_USING_PRIMITIVE")
        (root/"miccgi_m010_active_language.py").write_text(lang)
        st={"epoch":epoch,"parent_state_sha256":parent,"observations":observations,"registry":reg,"registry_sha256":H(reg),"new_primitive":reg[-1],"active_language_source_sha256":H(lang.encode()),"paid_actions":0,"contract_actions":0,"financial_actions":0}
        state_sha=H(st);receipt={"epoch":epoch,"state_sha256":state_sha,"registry_sha256":st["registry_sha256"],"primitive_name":name,"improvement_ratio":improvement,"compiled":True,"active_use_verified":True,"stop":epoch==3}
        (out/f"state_{epoch}.json").write_text(json.dumps(st,indent=2,sort_keys=True));(out/f"receipt_{epoch}.json").write_text(json.dumps(receipt,indent=2,sort_keys=True))
        states.append(st);parent=state_sha;push(root,epoch,"primitive-epoch")
        if epoch<3:time.sleep(1)
    reasons=[]
    if len(states)!=3:reasons.append("epoch_count")
    if any(s["new_primitive"]["improvement_ratio"]<.08 for s in states):reasons.append("utility")
    if len({s["new_primitive"]["behavior_sha256"] for s in states})!=3:reasons.append("novelty")
    if any(s[x]!=0 for s in states for x in ("paid_actions","contract_actions","financial_actions")):reasons.append("side_effect")
    verdict={"admitted":not reasons,"reasons":reasons,"epochs":3,"terminal_registry_sha256":states[-1]["registry_sha256"],"terminal_primitive_count":len(states[-1]["registry"]),"terminal_language_source_sha256":states[-1]["active_language_source_sha256"],"claim_boundary":{"BOUNDED_EXTERNAL_COMPOSITE_PRIMITIVE_INVENTION":"ESTABLISHED_FOR_RECORDED_LINEAGE" if not reasons else "NOT_ESTABLISHED","FUNDAMENTALLY_NEW_PRIMITIVE_SEMANTICS":"NOT_ESTABLISHED","OPEN_ENDED_LANGUAGE_INVENTION":"NOT_ESTABLISHED","ECONOMIC_T0":"NOT_OBSERVED","VERIFIED_REALIZED_PROFIT":"NOT_PROVEN","MICCGI":"UNPROVEN"}}
    (out/"adjudication.json").write_text(json.dumps(verdict,indent=2,sort_keys=True));push(root,3,"final-adjudication");print(json.dumps(verdict,sort_keys=True))
    raise SystemExit(0 if verdict["admitted"] else 2)
if __name__=="__main__":main()
