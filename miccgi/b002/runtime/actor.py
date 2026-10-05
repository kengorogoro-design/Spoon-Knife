from __future__ import annotations
import base64, hashlib, json, urllib.error, urllib.parse, urllib.request

def _api(token,method,url,payload=None):
    data=None if payload is None else json.dumps(payload).encode()
    req=urllib.request.Request(url,data=data,method=method,headers={
      "Accept":"application/vnd.github+json","Authorization":"Bearer "+token,
      "X-GitHub-Api-Version":"2022-11-28","User-Agent":"MICCGI-B002-actor","Content-Type":"application/json"})
    try:
      with urllib.request.urlopen(req,timeout=30) as r:
        raw=r.read(); return None if not raw else json.loads(raw)
    except urllib.error.HTTPError as e:
      raise RuntimeError(f"github_http_{e.code}:"+e.read().decode(errors="replace")[:300])

def execute(plan:dict, *, token:str, run_id:str, trigger_sha:str)->dict:
    if plan.get("provider")!="GitHub" or plan.get("protocol")!="github.isolated_relational_write.v1": raise ValueError("unsupported plan")
    repo=plan["repository"]; base=f"https://api.github.com/repos/{repo}"
    branch=plan["branch"].replace("{run_id}",run_id)
    _api(token,"POST",base+"/git/refs",{"ref":"refs/heads/"+branch,"sha":trigger_sha})
    final_commit=trigger_sha; primary_text=None
    for op in plan["operations"]:
      kind=op["op"]
      if kind=="create_branch": continue
      if kind=="put_text":
        primary_text=op["content_template"].format(contract_sha256=plan["contract_sha256"],challenge_nonce=plan["challenge_nonce"],run_id=run_id,repository=repo)
        content=primary_text
      elif kind=="put_sha256_of":
        if primary_text is None: raise RuntimeError("primary_not_written")
        content=hashlib.sha256(primary_text.encode()).hexdigest()
      elif kind=="readback_files_at_final_commit":
        continue
      else: raise RuntimeError("unexpected_operation")
      path=op["path"]
      write=_api(token,"PUT",base+"/contents/"+urllib.parse.quote(path,safe="/"),{
        "message":f"MICCGI B002 {kind} {plan['challenge_nonce'][:12]}",
        "content":base64.b64encode((content+"\n").encode()).decode(),"branch":branch})
      final_commit=write["commit"]["sha"]
    observations={}
    for path in plan["operations"][-1]["paths"]:
      got=_api(token,"GET",base+"/contents/"+urllib.parse.quote(path,safe="/")+"?ref="+final_commit)
      observations[path]=base64.b64decode(got["content"]).decode().rstrip("\n")
    return {"repository":repo,"branch":branch,"final_commit":final_commit,"observations":observations,"actor_statement":"locators_and_observations_only_no_admission_authority"}
