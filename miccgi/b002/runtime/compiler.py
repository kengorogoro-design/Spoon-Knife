from __future__ import annotations
import hashlib, json, re
from dataclasses import dataclass
from typing import Any

ALLOWED_PROTOCOLS={"github.isolated_relational_write.v1"}
HEX64=re.compile(r"^[0-9a-f]{64}$")

def canonical(obj: Any)->bytes:
    return json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()

def sha256_obj(obj: Any)->str:
    return hashlib.sha256(canonical(obj)).hexdigest()

@dataclass(frozen=True)
class CompiledPlans:
    contract_sha256: str
    capability_id: str
    actor_plan: dict
    witness_plan: dict

class ContractError(ValueError): pass

def _strict_keys(obj:dict, allowed:set[str], where:str)->None:
    extra=set(obj)-allowed
    if extra: raise ContractError(f"{where}:unknown_keys:{sorted(extra)}")

def compile_contract(contract:dict, challenge:dict)->CompiledPlans:
    _strict_keys(contract,{"contract_version","protocol","provider","repository","branch_prefix","resources","authority","credit"},"contract")
    if contract.get("contract_version")!=1: raise ContractError("contract_version")
    if contract.get("protocol") not in ALLOWED_PROTOCOLS: raise ContractError("protocol_not_allowed")
    if contract.get("provider")!="GitHub": raise ContractError("provider")
    repo=contract.get("repository")
    if not isinstance(repo,str) or repo.count("/")!=1: raise ContractError("repository")
    prefix=contract.get("branch_prefix")
    if not isinstance(prefix,str) or not prefix.startswith("miccgi-") or len(prefix)>80: raise ContractError("branch_prefix")
    authority=contract.get("authority")
    if authority!={"contents":"write","actions":"read"}: raise ContractError("authority_not_minimal")
    if contract.get("credit")!="behavior_only_no_economic_credit": raise ContractError("credit_boundary")
    resources=contract.get("resources")
    if not isinstance(resources,list) or len(resources)!=2: raise ContractError("resources")
    for i,r in enumerate(resources):
        _strict_keys(r,{"id","path","kind","source"},f"resource[{i}]")
        if not isinstance(r.get("path"),str) or not r["path"].startswith("miccgi/b002/"): raise ContractError("resource_path_scope")
    a,b=resources
    if a.get("id")!="primary" or a.get("kind")!="challenge_canonical": raise ContractError("primary_shape")
    if b.get("id")!="digest" or b.get("kind")!="sha256_of" or b.get("source")!="primary": raise ContractError("digest_shape")
    csha=sha256_obj(contract)
    _strict_keys(challenge,{"contract_sha256","challenge_nonce","issuer_role","candidate_has_admission_authority"},"challenge")
    if challenge.get("contract_sha256")!=csha: raise ContractError("challenge_contract_mismatch")
    nonce=challenge.get("challenge_nonce")
    if not isinstance(nonce,str) or not HEX64.fullmatch(nonce): raise ContractError("challenge_nonce")
    if challenge.get("issuer_role")!="external_witness_challenge": raise ContractError("issuer_role")
    if challenge.get("candidate_has_admission_authority") is not False: raise ContractError("candidate_authority")
    cap_id=f"contract://{contract['protocol']}/{csha}"
    actor={
      "plan_version":1,"provider":"GitHub","protocol":contract["protocol"],"repository":repo,
      "contract_sha256":csha,"challenge_nonce":nonce,
      "branch":f"{prefix}-{{run_id}}",
      "operations":[
        {"op":"create_branch","base":"{trigger_sha}"},
        {"op":"put_text","path":a["path"],"content_template":"MICCGI_B002|contract={contract_sha256}|challenge={challenge_nonce}|run={run_id}|repo={repository}"},
        {"op":"put_sha256_of","path":b["path"],"source_path":a["path"]},
        {"op":"readback_files_at_final_commit","paths":[a["path"],b["path"]]},
      ]
    }
    witness={
      "plan_version":1,"provider":"GitHub","protocol":contract["protocol"],"repository":repo,
      "contract_sha256":csha,"challenge_nonce":nonce,
      "requirements":[
        "workflow_run_completed_success",
        "immutable_final_commit_exists",
        "primary_file_exact_challenge_binding",
        "digest_file_equals_sha256_primary",
        "response_branch_created_after_challenge",
        "actor_claims_ignored"
      ]
    }
    return CompiledPlans(csha,cap_id,actor,witness)
