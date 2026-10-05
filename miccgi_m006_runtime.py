#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, subprocess, time, urllib.request
from dataclasses import asdict
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from miccgi_mg.autonomous_epoch import EpochObservation, transition, verify_chain

SOURCES=(
    "https://api.github.com/repos/kengorogoro-design/Spoon-Knife",
    "https://pypi.org/pypi/pytest/json",
)

def fetch(url:str)->EpochObservation:
    req=urllib.request.Request(url,headers={"User-Agent":"MICCGI-M006-Bounded-Runtime/1.0"})
    try:
        with urllib.request.urlopen(req,timeout=20) as r:
            body=r.read()
            return EpochObservation(url,int(getattr(r,"status",200)),hashlib.sha256(body).hexdigest(),len(body))
    except Exception as e:
        raw=(type(e).__name__+":"+str(e)).encode()
        return EpochObservation(url,599,hashlib.sha256(raw).hexdigest(),len(raw))

def git_commit_push(root:Path,epoch:int):
    subprocess.run(["git","config","user.name","MICCGI M006 Runtime"],cwd=root,check=True)
    subprocess.run(["git","config","user.email","miccgi-runtime@users.noreply.github.com"],cwd=root,check=True)
    subprocess.run(["git","add","miccgi_m006_state"],cwd=root,check=True)
    diff=subprocess.run(["git","diff","--cached","--quiet"],cwd=root)
    if diff.returncode!=0:
        subprocess.run(["git","commit","-m",f"MICCGI M006 bounded epoch {epoch}"],cwd=root,check=True)
        subprocess.run(["git","push","origin","HEAD"],cwd=root,check=True)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--epochs",type=int,default=3);ap.add_argument("--repo-root",default=".");ap.add_argument("--push",action="store_true")
    a=ap.parse_args();root=Path(a.repo_root).resolve();out=root/"miccgi_m006_state";out.mkdir(exist_ok=True)
    initial={"epoch":0,"action_counts":{},"bounded":True};prev=initial;states=[];receipts=[]
    (out/"initial_state.json").write_text(json.dumps(initial,indent=2,sort_keys=True))
    for epoch in range(1,a.epochs+1):
        observations=tuple(fetch(u) for u in SOURCES)
        state,receipt=transition(epoch,observations,prev,a.epochs)
        (out/f"state_{epoch}.json").write_text(json.dumps(state,indent=2,sort_keys=True))
        (out/f"receipt_{epoch}.json").write_text(json.dumps(asdict(receipt),indent=2,sort_keys=True))
        states.append(state);receipts.append(receipt);prev=state
        if a.push: git_commit_push(root,epoch)
        if receipt.stop: break
        time.sleep(1)
    verdict=verify_chain(initial,states,receipts,a.epochs)
    verdict["claim_boundary"]["INDEPENDENT_EXTERNAL_RUNTIME"]="ESTABLISHED_BY_THIS_RUN" if verdict["admitted"] and a.push else "NOT_ESTABLISHED"
    verdict["external_runtime"]={"sources":list(SOURCES),"git_push_enabled":bool(a.push)}
    (out/"adjudication.json").write_text(json.dumps(verdict,indent=2,sort_keys=True))
    if a.push: git_commit_push(root,a.epochs)
    print(json.dumps(verdict,sort_keys=True))
    raise SystemExit(0 if verdict["admitted"] else 2)
if __name__=="__main__":main()
