"""Fail-closed public source preflight before minting a CaptureBrief writer token.

This trusted-main, read-only check only qualifies a previously reviewed source
commit. It never runs target code or grants repository/merge/deploy authority.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request

TARGET_URL = "https://api.github.com/repos/P00NSMASHER/capturebrief/branches/main"
EXPECTED_TARGET_HEAD = "a25ecfd74e8e19b03b470959772f964b3c78d8bb"
SHA = re.compile(r"[0-9a-f]{40}\Z")
MAX_RESPONSE = 16384


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def assess_branch(doc):
    """Treat absent, moved, or unprotected target source as ineligible."""
    if type(doc) is not dict or type(doc.get("commit")) is not dict:
        return {"ready": False, "status": "TARGET_SOURCE_UNVERIFIED_NO_TOKEN"}
    sha = doc["commit"].get("sha")
    if type(sha) is not str or SHA.fullmatch(sha) is None:
        return {"ready": False, "status": "TARGET_SOURCE_UNVERIFIED_NO_TOKEN"}
    if doc.get("protected") is not True:
        return {"ready": False, "status": "TARGET_PROTECTION_UNVERIFIED_NO_TOKEN",
                "target_sha": sha}
    if sha != EXPECTED_TARGET_HEAD:
        return {"ready": False, "status": "TARGET_SOURCE_CHANGED_NO_TOKEN",
                "target_sha": sha}
    return {"ready": True, "status": "EXACT_REVIEWED_TARGET_SOURCE",
            "target_sha": sha}


def fetch_target_branch():
    """One bounded, no-redirect, read-only public GitHub REST GET."""
    token = os.environ.get("GH_TOKEN", "")
    if not (20 <= len(token) <= 4096 and "\n" not in token):
        raise ValueError("NO_READ_TOKEN")
    req = urllib.request.Request(TARGET_URL, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "portfolio-brain-v8-premint",
    })
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=10) as resp:
        if resp.status != 200:
            raise ValueError("UNVERIFIED_PROVIDER_STATUS")
        raw = resp.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise ValueError("UNVERIFIED_PROVIDER_SIZE")
    doc = json.loads(raw.decode("utf-8"))
    if type(doc) is not dict:
        raise ValueError("UNVERIFIED_PROVIDER_DOCUMENT")
    return doc


def preflight(fetch=fetch_target_branch):
    try:
        return assess_branch(fetch())
    except (OSError, ValueError, TypeError, UnicodeError):
        return {"ready": False, "status": "TARGET_PROVIDER_UNAVAILABLE_NO_TOKEN"}


def main():
    result = preflight()
    output_path = os.environ["GITHUB_OUTPUT"]
    temp = Path(os.environ["RUNNER_TEMP"])
    with open(output_path, "a", encoding="utf-8") as output:
        output.write("ready=" + str(result["ready"]).lower() + "\n")
    receipt = {"schema_version": 1, "phase": "READ_ONLY_BEFORE_APP_TOKEN",
               "provider_gets_max": 1, "writer_token_issued": False, **result}
    (temp / "v8-target-preflight.json").write_text(
        json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("V8_TARGET_PREMINT:", result["status"], "token_not_yet_minted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
