"""Bounded original deployed-asset observation, never a release acceptance gate."""
import hashlib
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener, Request
from urllib.error import HTTPError
from brain.core import require
from brain.v8.contracts import SHA,HASH,matches

DESTINATIONS={
 'abvm':('p00nsmasher.github.io','/abvmschoolstarworld/'),
 'retally':('retallyrecovery.com','/'),
}
MAX_BYTES=1048576


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None


def read_public_asset(url):
    """Use only through probe_asset after destination validation. No auth/retries."""
    try:
        with build_opener(_NoRedirect()).open(Request(url,headers={'User-Agent':'Portfolio-Brain-v8-asset-probe'}),timeout=10) as response:
            return dict(status=response.status,body=response.read(MAX_BYTES+1))
    except HTTPError as exc:
        return dict(status=exc.code,body=b'')


def probe_asset(read, *, project_id,source_sha,url,expected_sha256):
    require(type(project_id) is str and project_id in DESTINATIONS and matches(SHA,source_sha)
            and matches(HASH,expected_sha256) and type(url) is str and len(url)<=2048,
            'V8_ASSET_IDENTITY_INVALID')
    host,prefix=DESTINATIONS[project_id]
    parsed=urlsplit(url)
    require(parsed.scheme=='https' and parsed.netloc==host and parsed.path.startswith(prefix)
            and '%' not in parsed.path and '\\' not in url and not parsed.query and not parsed.fragment
            and not any(p in {'.','..'} for p in parsed.path.split('/')),
            'V8_ASSET_DESTINATION_REFUSED')
    result=dict(project_id=project_id,source_sha=source_sha,url=url,expected_sha256=expected_sha256,
                production_accepted=False,recovery_verified=False,source_binding='CALLER_SUPPLIED_IMMUTABLE_ASSET_DIGEST_REQUIRED',
                status='UNAVAILABLE',observed_sha256=None)
    try: response=read(url)
    except (OSError,ValueError): return result
    require(type(response) is dict and set(response)=={'status','body'}
            and type(response['status']) is int and type(response['body']) is bytes,
            'V8_ASSET_RESPONSE_INVALID')
    if response['status']!=200:
        result['status']='HTTP_NOT_OK'
    elif len(response['body'])>MAX_BYTES:
        result['status']='ASSET_BOUND_EXCEEDED'
    else:
        result['observed_sha256']=hashlib.sha256(response['body']).hexdigest()
        result['status']='ORIGINAL_ASSET_MATCH' if result['observed_sha256']==expected_sha256 else 'ASSET_MISMATCH'
    return result
