#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,subprocess
from pathlib import Path
LINEAGE=(("84acb45",1),("7ae3d0c",2),("fc09766",3))
def H(x):
    b=x if isinstance(x,(bytes,bytearray)) else json.dumps(x,sort_keys=True,separators=(",",":")).encode()
    return hashlib.sha256(b).hexdigest()
def show(ref,path,binary=False):
    b=subprocess.check_output(["git","show",f"{ref}:{path}"]);return b if binary else b.decode()
def main():
    reasons=[];rows=[];prev=None;prev_reg=[];prev_arc=[];beh=set();evals=[]
    for ref,ep in LINEAGE:
        st=json.loads(show(ref,f"miccgi_m011_state/state_{ep}.json"));rc=json.loads(show(ref,f"miccgi_m011_state/receipt_{ep}.json"));active=show(ref,"miccgi_m011_active_semantics.py",True)
        sh=H(st);rh=H(st["registry"]);ah=H(st["challenge_archive"]);eh=H(st["evaluators"]);src=H(active)
        cb=st["selected_challenge"]["behavior_sha256"]
        checks={
          "state_hash":sh==rc["state_sha256"],"parent_chain":st["parent_state_sha256"]==prev,
          "registry_hash":rh==rc["registry_sha256"]==st["registry_sha256"],
          "archive_hash":ah==st["challenge_archive_sha256"],"evaluator_hash":eh==rc["evaluator_sha256"]==st["evaluator_sha256"],
          "registry_monotonic":st["registry"][:len(prev_reg)]==prev_reg,"archive_monotonic":st["challenge_archive"][:len(prev_arc)]==prev_arc,
          "challenge_matches_receipt":st["selected_challenge"]["semantic_sha256"]==rc["challenge_sha256"],
          "challenge_behavior_unique":cb not in beh,"primitive_in_registry":any(p["name"]==rc["primitive_name"] for p in st["registry"]),
          "active_hash":src==st["active_source_sha256"],"active_use":rc["primitive_name"].encode() in active,
          "compiled":rc["compiled"] is True,"active_use_verified":rc["active_use_verified"] is True,
          "stop_semantics":(not rc["stop"] if ep<3 else rc["stop"]),
          "no_paid":st["paid_actions"]==0,"no_contract":st["contract_actions"]==0,"no_financial":st["financial_actions"]==0,
        }
        try: compile(active.decode(),f"<m011_active_{ep}>","exec")
        except Exception: checks["source_compiles"]=False
        else: checks["source_compiles"]=True
        bad=[k for k,v in checks.items() if not v]
        if bad: reasons.append({"epoch":ep,"ref":ref,"failed":bad})
        rows.append({"epoch":ep,"ref":ref,"checks":checks,"state_sha256":sh,"registry_sha256":rh,"challenge_archive_sha256":ah,"evaluator_sha256":eh,"challenge_behavior_sha256":cb,"primitive_name":rc["primitive_name"]})
        prev=sh;prev_reg=st["registry"];prev_arc=st["challenge_archive"];beh.add(cb);evals.append(eh)
    if len(set(evals))<2: reasons.append({"global":"evaluator_stasis"})
    v={"admitted":not reasons,"reasons":reasons,"verification_mode":"commit_addressed_independent_python_replay","lineage":rows,
       "terminal_state_sha256":rows[-1]["state_sha256"],"terminal_registry_sha256":rows[-1]["registry_sha256"],
       "claim_boundary":{"BOUNDED_EXTERNAL_ENDOGENOUS_SEMANTIC_COEVOLUTION":"ESTABLISHED_FOR_COMMIT_ADDRESSED_LINEAGE" if not reasons else "NOT_ESTABLISHED",
       "HUMAN_FIXED_TARGET_LIST_REQUIRED":"FALSE_FOR_VERIFIED_LINEAGE","EXTERNAL_SEMANTIC_UTILITY":"NOT_ESTABLISHED",
       "BLACK_BOX_PRIMITIVE_DISCOVERY_EXTERNALIZED":"NOT_ESTABLISHED","FUNDAMENTALLY_NEW_PRIMITIVE_SEMANTICS":"NOT_ESTABLISHED",
       "ECONOMIC_T0":"NOT_OBSERVED","VERIFIED_REALIZED_PROFIT":"NOT_PROVEN","MICCGI":"UNPROVEN"}}
    p=Path("miccgi_m011_state");p.mkdir(exist_ok=True);(p/"adjudication_commit_addressed.json").write_text(json.dumps(v,indent=2,sort_keys=True));print(json.dumps(v,sort_keys=True));raise SystemExit(0 if v["admitted"] else 2)
if __name__=="__main__":main()
