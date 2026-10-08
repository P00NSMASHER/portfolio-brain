"""Verify external Cloudflare-only Cron signatures; never self-certify a soak.

The private P-256 key is a Cloudflare secret. Only a public verification key
is committed to the source. The Cloudflare Worker exposes no dispatch endpoint.
"""
from __future__ import annotations
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

PUBLIC_KEY=Path(__file__).with_name("cloudflare-clock-public.pem")
SHA=re.compile(r"[0-9a-f]{40}\Z")
B64=re.compile(r"[A-Za-z0-9_-]+\Z")
REQUIRED={"kind","worker","cron","source_sha","scheduled_at","issued_at","slot"}
CLOCK="*/10 * * * *"
WORKER="portfolio-brain-recovery"
MAX_AGE=20*60

class CloudflareClockError(ValueError):
    pass

def require(ok, code):
    if not ok:
        raise CloudflareClockError(code)

def decode(value, *, max_bytes):
    require(type(value) is str and 0<len(value)<=4*max_bytes and
            B64.fullmatch(value) and len(value)%4!=1, "CLOCK_BASE64_INVALID")
    try:
        blob=base64.urlsafe_b64decode(value+"="*((-len(value))%4))
    except (ValueError,base64.binascii.Error) as exc:
        raise CloudflareClockError("CLOCK_BASE64_INVALID") from exc
    require(0<len(blob)<=max_bytes,"CLOCK_BYTE_SIZE_INVALID")
    return blob

def utc(text):
    require(isinstance(text,str) and text.endswith("Z"),"CLOCK_TIME_NOT_UTC")
    try:
        timestamp=datetime.fromisoformat(text[:-1]+"+00:00")
    except ValueError as exc:
        raise CloudflareClockError("CLOCK_TIME_INVALID") from exc
    require(timestamp.utcoffset().total_seconds()==0,"CLOCK_TIME_NOT_UTC")
    return timestamp

def der_integer(raw):
    data=raw.lstrip(b"\x00") or b"\x00"
    if data[0]&0x80:data=b"\x00"+data
    return b"\x02"+bytes((len(data),))+data

def der_signature(raw):
    require(len(raw)==64,"CLOCK_SIGNATURE_LENGTH_INVALID")
    rs=der_integer(raw[:32])+der_integer(raw[32:])
    return b"\x30"+bytes((len(rs),))+rs

def verify(payload_b64,signature_b64,expected_sha,*,now=None,pubkey=PUBLIC_KEY):
    require(isinstance(expected_sha,str) and SHA.fullmatch(expected_sha),"CLOCK_SOURCE_INVALID")
    raw=decode(payload_b64,max_bytes=1800)
    signature=decode(signature_b64,max_bytes=64)
    require(len(signature)==64,"CLOCK_SIGNATURE_LENGTH_INVALID")
    try:
        payload=json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError,ValueError) as exc:
        raise CloudflareClockError("CLOCK_PAYLOAD_JSON_INVALID") from exc
    require(type(payload) is dict and set(payload)==REQUIRED,"CLOCK_PAYLOAD_FIELDS_INVALID")
    require(payload.get("kind")=="cloudflare_cron_v1" and payload.get("worker")==WORKER
            and payload.get("cron")==CLOCK,"CLOCK_IDENTITY_INVALID")
    require(payload.get("source_sha")==expected_sha,"CLOCK_SOURCE_MISMATCH")
    scheduled=utc(payload["scheduled_at"])
    issued=utc(payload["issued_at"])
    current=now or datetime.now(timezone.utc)
    require(current.tzinfo is not None and current.utcoffset().total_seconds()==0,"CLOCK_NOW_INVALID")
    require(0<=(issued-scheduled).total_seconds()<=900,"CLOCK_NOT_GENUINELY_SCHEDULED_RECENTLY")
    require(0<=(current-issued).total_seconds()<=MAX_AGE,"CLOCK_STALE_OR_FUTURE")
    require(type(payload["slot"]) is int and payload["slot"]==int(scheduled.timestamp()//600),
            "CLOCK_SLOT_MISMATCH")
    # Cloudflare scheduledTime is provider-supplied and may contain seconds of jitter.
    # The signed ten-minute slot and freshness bounds above remain mandatory.
    require(scheduled.minute%10==0,"CLOCK_WRONG_MINUTE")
    require(pubkey.is_file(),"CLOCK_PUBLIC_KEY_MISSING")
    with tempfile.TemporaryDirectory(prefix="brain-cf-clock-") as d:
        message=Path(d)/"payload"
        signature_file=Path(d)/"signature.der"
        message.write_bytes(raw)
        signature_file.write_bytes(der_signature(signature))
        try:
            result=subprocess.run(["openssl","dgst","-sha256","-verify",str(pubkey),
                "-signature",str(signature_file),str(message)],
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=8,check=False)
        except (OSError,subprocess.TimeoutExpired) as exc:
            raise CloudflareClockError("CLOCK_OPENSSL_UNAVAILABLE") from exc
    require(result.returncode==0,"CLOCK_SIGNATURE_NOT_VERIFIED")
    return {"schema_version":1,"kind":"cloudflare_cron_v1",
            "status":"CLOUDFLARE_SIGNED_ORIGIN_VERIFIED",
            "source_sha":expected_sha,"scheduled_at":payload["scheduled_at"],
            "issued_at":payload["issued_at"],"slot":payload["slot"],
            "envelope_sha256":hashlib.sha256(raw).hexdigest(),
            "signature_sha256":hashlib.sha256(signature).hexdigest(),
            "signed_origin":True,
            "note":"Signature proves the configured Cloudflare-only signing key; independent acceptance must still verify provider Cron activity, core job, artifacts, and state.",
            "soak_pass":False}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--envelope",required=True)
    p.add_argument("--signature",required=True)
    p.add_argument("--source-sha",required=True)
    p.add_argument("--output",required=True,type=Path)
    args=p.parse_args()
    try:
        result=verify(args.envelope,args.signature,args.source_sha)
    except CloudflareClockError as exc:
        result={"status":"BLOCKED","reason":str(exc),"soak_pass":False}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps(result,sort_keys=True))
    return 0 if result["status"]=="CLOUDFLARE_SIGNED_ORIGIN_VERIFIED" else 1

if __name__=="__main__":
    raise SystemExit(main())
