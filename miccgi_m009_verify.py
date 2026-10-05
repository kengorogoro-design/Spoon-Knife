#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,subprocess
from pathlib import Path

LINEAGE=(("360cc5b",1),("eb28071",2),("3d1e124",3))

def H(x):
    if isinstance(x,(bytes,bytearray)):
        b=bytes(x)
    else:
        b=json.dumps(x,sort_keys=True,separators=(",",":")).encode()
    return hashlib.sha256(b).hexdigest()

def show(ref,path,binary=False):
    out=subprocess.check_output(["git","show",f"{ref}:{path}"])
    return out if binary else out.decode()

def main():
    reasons=[]; rows=[]; prev_lang=None
    for ref,ep in LINEAGE:
        st=json.loads(show(ref,f"miccgi_m009_state/state_{ep}.json"))
        rc=json.loads(show(ref,f"miccgi_m009_state/receipt_{ep}.json"))
        src=show(ref,"miccgi_m009_generated_language.py",binary=True)
        state_hash=H(st); source_hash=H(src)
        checks={
          "state_hash_matches": state_hash==rc["state_sha256"],
          "language_matches": st["language_sha256"]==rc["language_sha256"],
          "source_record_matches": st["source_sha256"]==rc["source_sha256"],
          "source_bytes_match": source_hash==st["source_sha256"],
          "parent_chain_ok": (st["parent_language_sha256"] is None if ep==1 else st["parent_language_sha256"]==prev_lang),
          "compiled": rc["compiled"] is True,
          "source_changed": rc["source_changed"] is True,
          "stop_semantics": (rc["stop"] is False if ep<3 else rc["stop"] is True),
          "no_paid_actions": st["paid_actions"]==0,
          "no_contract_actions": st["contract_actions"]==0,
          "no_financial_actions": st["financial_actions"]==0,
        }
        bad=[k for k,v in checks.items() if not v]
        if bad: reasons.append({"epoch":ep,"ref":ref,"failed":bad})
        rows.append({
          "epoch":ep,"ref":ref,"checks":checks,
          "language_sha256":st["language_sha256"],
          "source_sha256":st["source_sha256"],
          "state_sha256":state_hash,
          "holdout":st["holdout"],
          "operator_count":st["operator_count"],
          "macro_count":st["macro_count"],
        })
        prev_lang=st["language_sha256"]
    verdict={
      "admitted":not reasons,
      "reasons":reasons,
      "verification_mode":"commit_addressed_independent_python_replay",
      "lineage":rows,
      "terminal_language_sha256":rows[-1]["language_sha256"],
      "terminal_source_sha256":rows[-1]["source_sha256"],
      "terminal_state_sha256":rows[-1]["state_sha256"],
      "claim_boundary":{
        "BOUNDED_EXTERNAL_LANGUAGE_GENESIS":"ESTABLISHED_FOR_COMMIT_ADDRESSED_LINEAGE" if not reasons else "NOT_ESTABLISHED",
        "OPEN_ENDED_LANGUAGE_INVENTION":"NOT_ESTABLISHED",
        "EXTERNAL_WHOLE_SYSTEM_DOMINANCE":"NOT_ESTABLISHED",
        "ECONOMIC_T0":"NOT_OBSERVED",
        "VERIFIED_REALIZED_PROFIT":"NOT_PROVEN",
        "MICCGI":"UNPROVEN"
      }
    }
    p=Path("miccgi_m009_state");p.mkdir(exist_ok=True)
    (p/"adjudication_commit_addressed.json").write_text(json.dumps(verdict,indent=2,sort_keys=True))
    print(json.dumps(verdict,sort_keys=True))
    raise SystemExit(0 if verdict["admitted"] else 2)

if __name__=="__main__":main()
