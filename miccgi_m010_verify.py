#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,subprocess
from pathlib import Path

LINEAGE=(("1a44401",1),("7fca2d3",2),("de50630",3))

def H(x):
    if isinstance(x,(bytes,bytearray)): b=bytes(x)
    else: b=json.dumps(x,sort_keys=True,separators=(",",":")).encode()
    return hashlib.sha256(b).hexdigest()

def show(ref,path,binary=False):
    out=subprocess.check_output(["git","show",f"{ref}:{path}"])
    return out if binary else out.decode()

def main():
    reasons=[]; rows=[]; prev_state=None; prev_registry=[]
    behavior=set()
    for ref,ep in LINEAGE:
        st=json.loads(show(ref,f"miccgi_m010_state/state_{ep}.json"))
        rc=json.loads(show(ref,f"miccgi_m010_state/receipt_{ep}.json"))
        prim_src=show(ref,"miccgi_m010_generated_primitives.py",True)
        active_src=show(ref,"miccgi_m010_active_language.py",True)
        state_hash=H(st); reg_hash=H(st["registry"]); active_hash=H(active_src)
        checks={
          "state_hash_matches": state_hash==rc["state_sha256"],
          "registry_hash_matches_receipt": reg_hash==rc["registry_sha256"]==st["registry_sha256"],
          "parent_state_chain_ok": (st["parent_state_sha256"] is None if ep==1 else st["parent_state_sha256"]==prev_state),
          "compiled": rc["compiled"] is True,
          "active_use_verified": rc["active_use_verified"] is True,
          "stop_semantics": (rc["stop"] is False if ep<3 else rc["stop"] is True),
          "registry_monotonic": st["registry"][:len(prev_registry)]==prev_registry,
          "new_primitive_in_registry": any(p["name"]==rc["primitive_name"] for p in st["registry"]),
          "active_language_hash_matches": active_hash==st["active_language_source_sha256"],
          "active_language_references_new_primitive": rc["primitive_name"].encode() in active_src,
          "behavior_unique": st["new_primitive"]["behavior_sha256"] not in behavior,
          "no_paid_actions": st["paid_actions"]==0,
          "no_contract_actions": st["contract_actions"]==0,
          "no_financial_actions": st["financial_actions"]==0,
        }
        try: compile(prim_src.decode(),f"<m010_primitives_{ep}>","exec")
        except Exception: checks["primitive_source_compiles"]=False
        else: checks["primitive_source_compiles"]=True
        try: compile(active_src.decode(),f"<m010_active_{ep}>","exec")
        except Exception: checks["active_source_compiles"]=False
        else: checks["active_source_compiles"]=True
        bad=[k for k,v in checks.items() if not v]
        if bad: reasons.append({"epoch":ep,"ref":ref,"failed":bad})
        rows.append({"epoch":ep,"ref":ref,"checks":checks,"state_sha256":state_hash,
                     "registry_sha256":reg_hash,"active_language_source_sha256":active_hash,
                     "primitive_name":rc["primitive_name"],
                     "behavior_sha256":st["new_primitive"]["behavior_sha256"],
                     "registry_size":len(st["registry"])})
        behavior.add(st["new_primitive"]["behavior_sha256"]); prev_state=state_hash; prev_registry=st["registry"]
    v={"admitted":not reasons,"reasons":reasons,"verification_mode":"commit_addressed_independent_python_replay",
       "lineage":rows,"terminal_state_sha256":rows[-1]["state_sha256"],
       "terminal_registry_sha256":rows[-1]["registry_sha256"],
       "claim_boundary":{
         "BOUNDED_EXTERNAL_COMPOSITE_PRIMITIVE_INVENTION":"ESTABLISHED_FOR_COMMIT_ADDRESSED_LINEAGE" if not reasons else "NOT_ESTABLISHED",
         "ADVERSARIAL_SOURCE_EQUIVALENCE_EXTERNALIZED":"NOT_ESTABLISHED_FOR_THIS_OLDER_EXTERNAL_LINEAGE",
         "FUNDAMENTALLY_NEW_PRIMITIVE_SEMANTICS":"NOT_ESTABLISHED",
         "OPEN_ENDED_LANGUAGE_INVENTION":"NOT_ESTABLISHED",
         "ECONOMIC_T0":"NOT_OBSERVED","VERIFIED_REALIZED_PROFIT":"NOT_PROVEN","MICCGI":"UNPROVEN"}}
    p=Path("miccgi_m010_state");p.mkdir(exist_ok=True)
    (p/"adjudication_commit_addressed.json").write_text(json.dumps(v,indent=2,sort_keys=True))
    print(json.dumps(v,sort_keys=True)); raise SystemExit(0 if v["admitted"] else 2)
if __name__=="__main__": main()
