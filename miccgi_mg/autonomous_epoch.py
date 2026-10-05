from __future__ import annotations
from dataclasses import dataclass, asdict
import hashlib, json
from typing import Iterable

ALLOWED_ACTIONS=("OBSERVE","REFRAME","PRESERVE")

@dataclass(frozen=True)
class EpochObservation:
    source: str
    status: int
    digest: str
    size_bytes: int

@dataclass(frozen=True)
class EpochReceipt:
    epoch: int
    parent_state_sha256: str
    action: str
    observations: tuple[EpochObservation,...]
    state_sha256: str
    stop: bool
    reason: str

    def fingerprint(self)->str:
        raw=json.dumps(asdict(self),sort_keys=True,separators=(",",":"),ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()

def stable_hash(obj)->str:
    raw=json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()

def choose_action(epoch:int, observations:Iterable[EpochObservation], previous:dict)->str:
    obs=list(observations)
    if any(o.status!=200 for o in obs): return "PRESERVE"
    novelty=len({o.digest for o in obs})
    if novelty>=2 and epoch % 2 == 0: return "REFRAME"
    return "OBSERVE"

def transition(epoch:int, observations:tuple[EpochObservation,...], previous:dict, max_epochs:int)->tuple[dict,EpochReceipt]:
    parent=stable_hash(previous)
    action=choose_action(epoch,observations,previous)
    counts=dict(previous.get("action_counts",{}));counts[action]=counts.get(action,0)+1
    state={
        "epoch":epoch,
        "action":action,
        "action_counts":counts,
        "observation_digests":[o.digest for o in observations],
        "observation_sources":[o.source for o in observations],
        "parent_state_sha256":parent,
        "bounded":True,
        "paid_actions":0,
        "contract_actions":0,
        "financial_actions":0,
    }
    state_sha=stable_hash(state)
    stop=epoch>=max_epochs
    reason="MAX_EPOCHS_REACHED" if stop else "CONTINUE_WITHIN_BOUND"
    receipt=EpochReceipt(epoch,parent,action,observations,state_sha,stop,reason)
    return state,receipt

def verify_chain(initial_state:dict, states:list[dict], receipts:list[EpochReceipt], max_epochs:int)->dict:
    reasons=[]
    if len(states)!=len(receipts): reasons.append("length_mismatch")
    prev=initial_state
    for i,(s,r) in enumerate(zip(states,receipts),start=1):
        if r.epoch!=i or s.get("epoch")!=i: reasons.append(f"epoch_mismatch:{i}")
        if r.parent_state_sha256!=stable_hash(prev): reasons.append(f"parent_mismatch:{i}")
        if r.state_sha256!=stable_hash(s): reasons.append(f"state_hash_mismatch:{i}")
        if r.action not in ALLOWED_ACTIONS: reasons.append(f"action_not_allowed:{i}")
        if s.get("paid_actions")!=0 or s.get("contract_actions")!=0 or s.get("financial_actions")!=0: reasons.append(f"forbidden_side_effect:{i}")
        prev=s
    if receipts:
        if not receipts[-1].stop: reasons.append("terminal_not_stopped")
        if receipts[-1].epoch!=max_epochs: reasons.append("wrong_terminal_epoch")
        if any(r.stop for r in receipts[:-1]): reasons.append("early_stop")
    else: reasons.append("no_receipts")
    return {"admitted":not reasons,"reasons":reasons,"epochs":len(receipts),"terminal_state_sha256":stable_hash(prev),
            "claim_boundary":{"BOUNDED_EXTERNAL_EPOCH_LOGIC":"ESTABLISHED" if not reasons else "NOT_ESTABLISHED",
                              "INDEPENDENT_EXTERNAL_RUNTIME":"NOT_ESTABLISHED_BY_LOCAL_TEST",
                              "ECONOMIC_T0":"NOT_OBSERVED","VERIFIED_REALIZED_PROFIT":"NOT_PROVEN","MICCGI":"UNPROVEN"}}
