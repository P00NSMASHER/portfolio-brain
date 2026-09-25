#!/usr/bin/env python3
"""Safe GitHub Actions artifact HTTP helpers.

GitHub's artifact download endpoint redirects to a signed storage host. GitHub
credentials are valid only for github.com/api.github.com and must never be
forwarded across that host boundary.
"""
from __future__ import annotations
import urllib.parse
import urllib.request

class SafeArtifactRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected=super().redirect_request(req,fp,code,msg,headers,newurl)
        if redirected is None:
            return None
        old_host=(urllib.parse.urlsplit(req.full_url).hostname or "").casefold()
        new_host=(urllib.parse.urlsplit(newurl).hostname or "").casefold()
        if old_host!=new_host:
            redirected.remove_header("Authorization")
        return redirected

def open_url(request, *, timeout: int=20):
    opener=urllib.request.build_opener(SafeArtifactRedirectHandler())
    return opener.open(request,timeout=timeout)
