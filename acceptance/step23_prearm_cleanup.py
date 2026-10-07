"""Remove non-counting pre-arm workflow runs whose title captured credential material."""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any

SECRET_MARKERS=("ghs_","gho_","ghu_","ghr_","github_pat_")


def req(ok:bool,message:str)->None:
    if not ok:
        raise RuntimeError(message)


def leaked_title(value:Any)->bool:
    return isinstance(value,str) and value.startswith("prearm-") and any(marker in value for marker in SECRET_MARKERS)


class API:
    def __init__(self,repo:str,token:str):
        self.repo=repo
        self.token=token
        self.requests=0

    def request(self,path:str,*,method:str="GET")->tuple[int,bytes]:
        req(path.startswith("/") and "://" not in path and ".." not in path,"unsafe GitHub API path")
        self.requests+=1
        req(self.requests<=80,"pre-arm cleanup API budget exhausted")
        request=urllib.request.Request(
            "https://api.github.com/repos/"+self.repo+path,
            method=method,
            headers={
                "Authorization":"Bearer "+self.token,
                "Accept":"application/vnd.github+json",
                "X-GitHub-Api-Version":"2022-11-28",
                "User-Agent":"portfolio-step23-prearm-cleanup/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request,timeout=20) as response:
                return response.status,response.read(5_000_001)
        except urllib.error.HTTPError as exc:
            return exc.code,exc.read(5_000_001)

    def get(self,path:str)->Any:
        status,raw=self.request(path)
        req(status==200,f"unexpected GitHub GET status {status}")
        return json.loads(raw)

    def post(self,path:str)->int:
        status,_=self.request(path,method="POST")
        return status

    def delete(self,path:str)->int:
        status,_=self.request(path,method="DELETE")
        return status


def purge(api:API)->dict[str,Any]:
    rows=[]
    for page in range(1,4):
        doc=api.get(f"/actions/runs?event=workflow_dispatch&per_page=100&page={page}")
        batch=doc.get("workflow_runs",[])
        req(isinstance(batch,list),"workflow run listing malformed")
        rows.extend(batch)
        if len(batch)<100:
            break

    candidates=[
        row for row in rows
        if type(row.get("id")) is int and leaked_title(row.get("display_title"))
    ]
    deleted=[]
    for row in candidates:
        run_id=int(row["id"])
        status=row.get("status")
        if status!="completed":
            cancel=api.post(f"/actions/runs/{run_id}/cancel")
            req(cancel in {202,409},f"could not cancel leaked pre-arm run {run_id}: {cancel}")
            for _ in range(30):
                current=api.get(f"/actions/runs/{run_id}")
                if current.get("status")=="completed":
                    break
                time.sleep(2)
            else:
                raise RuntimeError(f"leaked pre-arm run {run_id} did not stop")
        result=api.delete(f"/actions/runs/{run_id}")
        req(result==204,f"could not delete leaked pre-arm run {run_id}: {result}")
        deleted.append(run_id)

    return {
        "schema_version":"1.0.0",
        "status":"PASS",
        "deleted_run_ids":deleted,
        "deleted_count":len(deleted),
        "api_requests":api.requests,
    }


def main()->None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    repo=os.environ.get("GITHUB_REPOSITORY","")
    token=os.environ.get("GITHUB_TOKEN","")
    req(repo and token,"GitHub context required for pre-arm cleanup")
    result=purge(API(repo,token))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(result,sort_keys=True))


if __name__=="__main__":
    main()
