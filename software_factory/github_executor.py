#!/usr/bin/env python3
"""Narrow GitHub executor for Step 16 candidate branches/commits/PRs only."""
from __future__ import annotations
import base64,json,os,urllib.request
from pathlib import Path
from software_factory.software_factory import SoftwareFactoryError,hashv,load,policy,req

class GitHubExecutor:
    def __init__(self,token,transport=None):
        req(isinstance(token,str) and token,"GitHub token required")
        self.token=token;self.transport=transport or self._http
    def _http(self,method,url,payload=None):
        data=None if payload is None else json.dumps(payload).encode()
        reqq=urllib.request.Request(url,data=data,method=method,headers={"Authorization":f"Bearer {self.token}","Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28","User-Agent":"portfolio-brain-factory/1.0","Content-Type":"application/json"})
        with urllib.request.urlopen(reqq,timeout=30) as resp:
            body=resp.read();return json.loads(body.decode()) if body else {}
    def _repo_policy(self,full):
        rows=[x for x in policy()["repository_policies"] if x["repository_full_name"]==full];req(len(rows)==1,"repository policy missing/duplicate");return rows[0]
    def validate_packet(self,p):
        given=p.get("action_hash");body=dict(p);body.pop("action_hash",None);req(given==hashv(body),"action packet hash mismatch")
        req(p["operation"] in policy()["executor_operations"],"operation not allowed");rp=self._repo_policy(p["repository_full_name"])
        req(rp["candidate_modify_enabled"],"repository not candidate-write enabled");req(p["default_branch"]==rp["default_branch"],"default branch mismatch")
        req(p["branch_name"].startswith(policy()["branch_prefix"]) and p["branch_name"]!=rp["default_branch"],"branch isolation violation")
        if p["operation"]=="CREATE_PR":req(rp["pr_create_enabled"],"PR creation disabled")
        return rp
    def execute(self,p):
        rp=self.validate_packet(p);owner_repo=p["repository_full_name"];base=f"https://api.github.com/repos/{owner_repo}"
        op=p["operation"]
        if op=="CREATE_BRANCH":
            return self.transport("POST",base+"/git/refs",{"ref":"refs/heads/"+p["branch_name"],"sha":p["base_sha"]})
        if op=="COMMIT_CANDIDATE":
            head=self.transport("GET",base+"/git/ref/heads/"+p["branch_name"],None);current=head["object"]["sha"]
            req(current==p["expected_head_sha"],"candidate branch head drifted")
            parent=self.transport("GET",base+"/git/commits/"+current,None);tree_sha=parent["tree"]["sha"];entries=[]
            for f in p["files"]:
                raw=base64.b64decode(f["content_b64"],validate=True);blob=self.transport("POST",base+"/git/blobs",{"content":base64.b64encode(raw).decode(),"encoding":"base64"})
                entries.append({"path":f["path"],"mode":"100644","type":"blob","sha":blob["sha"]})
            tree=self.transport("POST",base+"/git/trees",{"base_tree":tree_sha,"tree":entries})
            commit=self.transport("POST",base+"/git/commits",{"message":p["commit_message"],"tree":tree["sha"],"parents":[current]})
            self.transport("PATCH",base+"/git/refs/heads/"+p["branch_name"],{"sha":commit["sha"],"force":False})
            return commit
        if op=="CREATE_PR":
            head=self.transport("GET",base+"/git/ref/heads/"+p["branch_name"],None);req(head["object"]["sha"]==p["expected_head_sha"],"verified PR head drifted")
            return self.transport("POST",base+"/pulls",{"title":p["pr_title"],"body":p["pr_body"],"head":p["branch_name"],"base":rp["default_branch"],"draft":False})
        raise SoftwareFactoryError("unreachable executor operation")

def main():
    packet=load(Path(os.environ["PORTFOLIO_FACTORY_PACKET"]))
    token=os.environ.get("PORTFOLIO_FACTORY_TOKEN") or os.environ.get("GITHUB_TOKEN")
    result=GitHubExecutor(token).execute(packet)
    print(json.dumps(result))
if __name__=="__main__":main()
