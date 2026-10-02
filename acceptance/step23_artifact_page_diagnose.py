#!/usr/bin/env python3
import json, os, urllib.request
from datetime import datetime

repo=os.environ["GITHUB_REPOSITORY"]
token=os.environ["GITHUB_TOKEN"]
seen={}
prev_oldest=None
row_prev=None
row_order=True
page_envelope=True
unseen_pages=0
out=[]

def get(path):
    req=urllib.request.Request(
        "https://api.github.com/repos/"+repo+path,
        headers={
            "Authorization":"Bearer "+token,
            "Accept":"application/vnd.github+json",
            "X-GitHub-Api-Version":"2022-11-28",
            "User-Agent":"portfolio-step23-artifact-diagnostic/1.0",
        },
    )
    with urllib.request.urlopen(req,timeout=30) as r:
        return json.load(r)

for page in range(1,21):
    doc=get(f"/actions/artifacts?per_page=100&page={page}")
    rows=doc.get("artifacts",[])
    page_times=[]
    unseen_times=[]
    duplicates=0
    changed_duplicates=0
    unseen_newer_than_prev=0
    for row in rows:
        aid=row["id"]
        at=datetime.fromisoformat(row["created_at"].replace("Z","+00:00"))
        page_times.append(at)
        if row_prev is not None and at>row_prev:
            row_order=False
        row_prev=at
        if aid in seen:
            duplicates+=1
            if seen[aid]!=row:
                changed_duplicates+=1
        else:
            seen[aid]=row
            unseen_times.append(at)
            if prev_oldest is not None and at>prev_oldest:
                unseen_newer_than_prev+=1
    if unseen_times:
        unseen_pages+=1
        newest=max(unseen_times); oldest=min(unseen_times)
        if prev_oldest is not None and newest>prev_oldest:
            page_envelope=False
        prev_oldest=oldest
    elif rows:
        page_envelope=False
    out.append({
        "page":page,
        "count":len(rows),
        "total_count":doc.get("total_count"),
        "duplicates":duplicates,
        "changed_duplicates":changed_duplicates,
        "unseen_count":len(unseen_times),
        "unseen_newer_than_prev":unseen_newer_than_prev,
        "page_newest":max(page_times).isoformat() if page_times else None,
        "page_oldest":min(page_times).isoformat() if page_times else None,
        "unseen_newest":max(unseen_times).isoformat() if unseen_times else None,
        "unseen_oldest":min(unseen_times).isoformat() if unseen_times else None,
        "row_order_so_far":row_order,
        "page_envelope_so_far":page_envelope,
    })
print(json.dumps({
    "pages":out,
    "unique_artifacts":len(seen),
    "row_order_proven":row_order,
    "page_envelope_proven":page_envelope,
    "unseen_pages":unseen_pages,
},indent=2,sort_keys=True))
