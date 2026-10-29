"""Compact public snapshots or disposable working copies; never publish state.

Keeps latest 128 reports, latest per source, and every non-PASS report. Immutable
Git snapshots remain the historical authority. Receipt lists removed report hashes.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import zlib
from brain.core import canonical, digest, require
from brain.state_archive import CHUNK_BYTES

MAX_BYTES = 5 * 1024 * 1024 * 1024
# Exact live brain-state-v2 image independently restored and replayed from
# commit 3de54070a8256073e667bfbf481170d693b6663a on 2026-10-16.
VERIFIED_PRODUCTION_RAW_BYTES = 120_512_512
VERIFIED_PRODUCTION_COMPRESSED_BYTES = 20_602_941
COMPACTION_TRIGGER_BYTES = 80 * 1024 * 1024
COMPACTION_TRIGGER_COMPRESSED_BYTES = VERIFIED_PRODUCTION_COMPRESSED_BYTES * 3 // 4
COMPACTION_TRIGGER_REPORTS = 256

def storage_pressure(source):
    """Measure the production codec with one bounded chunk in memory."""
    source=Path(source)
    require(not source.is_symlink() and source.is_file()
            and 0<source.stat().st_size<=MAX_BYTES,'capacity source invalid')
    require(not any(Path(str(source)+suffix).exists() for suffix in ('-wal','-journal')),
            'source must be an immutable snapshot')
    packed=0
    with source.open('rb') as stream:
        while chunk:=stream.read(CHUNK_BYTES):
            packed+=len(zlib.compress(chunk,level=6))
    with sqlite3.connect(source.resolve().as_uri()+'?mode=ro&immutable=1',uri=True) as db:
        reports=db.execute('SELECT count(*) FROM reports').fetchone()[0]
    raw=source.stat().st_size
    return dict(raw_bytes=raw,compressed_bytes=packed,reports=reports,
        raw_headroom_bytes=VERIFIED_PRODUCTION_RAW_BYTES-raw,
        compressed_headroom_bytes=VERIFIED_PRODUCTION_COMPRESSED_BYTES-packed,
        capacity_warning=('LOW_VERIFIED_HEADROOM' if
            raw*5>=VERIFIED_PRODUCTION_RAW_BYTES*4 or
            packed*5>=VERIFIED_PRODUCTION_COMPRESSED_BYTES*4 else None))

def image_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()

def preserved_tables(db):
    """Hash all non-report rows and schema, streaming without retaining bodies."""
    names=[r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name")]
    result={}
    for name in names:
        if name=='reports': continue
        quoted='"'+name.replace('"','""')+'"'
        h=hashlib.sha256()
        for row in db.execute(f'SELECT * FROM {quoted} ORDER BY rowid'):
            h.update(repr(tuple(row)).encode());h.update(b'\n')
        result[name]=h.hexdigest()
    result['schema']=digest(list(db.execute('SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name')))
    return result

def compact_snapshot(source, target, *, keep_recent=128):
    source=Path(source);target=Path(target)
    require(type(keep_recent) is int and 1<=keep_recent<=4096,'retention bound invalid')
    require(not source.is_symlink() and source.is_file() and 0<source.stat().st_size<=MAX_BYTES,'source invalid or oversized')
    require(not any(Path(str(source)+suffix).exists() for suffix in ('-wal','-journal')),'source must be an immutable snapshot')
    require(not target.exists() and not target.is_symlink() and target.parent.is_dir() and not target.parent.is_symlink(),'new destination required')
    original=image_hash(source)
    with sqlite3.connect(source.resolve().as_uri()+'?mode=ro&immutable=1',uri=True) as incoming:
        require(incoming.execute('PRAGMA integrity_check').fetchone()[0]=='ok','source corrupt')
        require(incoming.execute("SELECT value FROM meta WHERE key='visibility'").fetchone()==('PUBLIC',),'public snapshot required')
        require(incoming.execute('PRAGMA foreign_key_check').fetchone() is None,'source foreign keys invalid')
        before=preserved_tables(incoming)
        # Validate every report before choosing any retention action.
        rows=[];latest={};fingerprints={}
        for row in incoming.execute('SELECT * FROM reports ORDER BY id'):
            ident,seq,chain,sha,created,body,stored=row
            fingerprints[ident]=digest(tuple(row))
            parsed=json.loads(body)
            require(digest(parsed)==stored,'report digest invalid')
            rows.append((ident,stored,parsed.get('status')=='PASS'));latest[sha]=ident
        require(rows,'reports missing')
        keep={r[0] for r in rows[-keep_recent:]} | set(latest.values()) | {r[0] for r in rows if not r[2]}
        removed=[dict(id=ident,hash=sha) for ident,sha,_ in rows if ident not in keep]
        fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        try:
            with sqlite3.connect(target) as outgoing:
                incoming.backup(outgoing)
                outgoing.executemany('DELETE FROM reports WHERE id=?',[(r['id'],) for r in removed])
                outgoing.commit()
                outgoing.execute('VACUUM')
                require(outgoing.execute('PRAGMA integrity_check').fetchone()[0]=='ok','compacted image corrupt')
                require(outgoing.execute('PRAGMA foreign_key_check').fetchone() is None,'compacted foreign keys invalid')
                require(preserved_tables(outgoing)==before,'canonical history or schema changed')
                retained=[(r[0],digest(tuple(r))) for r in outgoing.execute('SELECT * FROM reports ORDER BY id')]
                require(retained==[(i,fingerprints[i]) for i,_,_ in rows if i in keep],'retained reports changed')
            require(image_hash(source)==original,'source changed during cleanup')
        except BaseException:
            # Target was exclusively created by this operation; source is untouched.
            target.unlink(missing_ok=True)
            raise
    return dict(status='COMPACTED_COPY_NOT_PUBLISHED',source_sha256=original,
        target_sha256=image_hash(target),source_bytes=source.stat().st_size,
        target_bytes=target.stat().st_size,kept_reports=len(keep),removed_reports=removed,
        canonical_tables_unchanged=True,remote_writes=0)

def maintain_within_verified_capacity(
        source, *, trigger_bytes=COMPACTION_TRIGGER_BYTES,
        verified_raw_bytes=VERIFIED_PRODUCTION_RAW_BYTES, keep_recent=128):
    """Atomically bound a working copy before the guarded state publication."""
    source=Path(source)
    require(type(trigger_bytes) is int and trigger_bytes>0,
            'capacity trigger invalid')
    require(type(verified_raw_bytes) is int and trigger_bytes<verified_raw_bytes<=MAX_BYTES,
            'verified raw capacity invalid')
    pressure=storage_pressure(source)
    before=pressure['raw_bytes']
    reasons=[]
    if before>trigger_bytes: reasons.append('RAW_SIZE')
    if pressure['compressed_bytes']>COMPACTION_TRIGGER_COMPRESSED_BYTES:
        reasons.append('COMPRESSED_SIZE')
    if pressure['reports']>COMPACTION_TRIGGER_REPORTS:
        reasons.append('REPORT_COUNT')
    if not reasons:
        return dict(status='WITHIN_VERIFIED_PRODUCTION_CAPACITY',
            source_bytes=before,target_bytes=before,compacted=False,
            storage_pressure=pressure,compaction_reasons=[],
            verified_raw_capacity_bytes=verified_raw_bytes,
            verified_compressed_capacity_bytes=VERIFIED_PRODUCTION_COMPRESSED_BYTES,
            remote_writes=0,published=False)
    fd,name=tempfile.mkstemp(prefix='.capacity-',suffix='.sqlite',dir=source.parent)
    os.close(fd);target=Path(name);target.unlink()
    try:
        receipt=compact_snapshot(source,target,keep_recent=keep_recent)
        require(receipt['target_bytes']<=verified_raw_bytes,
                'compacted state exceeds verified production capacity')
        after=storage_pressure(target)
        require(after['compressed_bytes']<=VERIFIED_PRODUCTION_COMPRESSED_BYTES,
                'compacted state exceeds verified compressed capacity')
        os.replace(target,source)
    finally:
        target.unlink(missing_ok=True)
    return dict(receipt,status='COMPACTED_TO_VERIFIED_PRODUCTION_CAPACITY',
        compacted=True,compaction_reasons=reasons,storage_pressure=after,
        verified_raw_capacity_bytes=verified_raw_bytes,
        verified_compressed_capacity_bytes=VERIFIED_PRODUCTION_COMPRESSED_BYTES,
        published=False)

def validate_publication_receipt(receipt):
    """Refuse a packed publication outside the measured durable envelope."""
    require(type(receipt) is dict
            and type(receipt.get('raw_size')) is int
            and type(receipt.get('compressed_size')) is int
            and type(receipt.get('chunks')) is int,
            'publication capacity receipt invalid')
    require(0<receipt['raw_size']<=VERIFIED_PRODUCTION_RAW_BYTES,
            'publication exceeds verified raw capacity')
    require(0<receipt['compressed_size']<=VERIFIED_PRODUCTION_COMPRESSED_BYTES,
            'publication exceeds verified compressed capacity')
    require(receipt['chunks']>0 and receipt.get('published') is False,
            'publication capacity receipt invalid')
    return dict(status='VERIFIED_PRODUCTION_CAPACITY_ENVELOPE_PASS',
        raw_size=receipt['raw_size'],compressed_size=receipt['compressed_size'],
        chunks=receipt['chunks'],
        raw_headroom_bytes=VERIFIED_PRODUCTION_RAW_BYTES-receipt['raw_size'],
        compressed_headroom_bytes=VERIFIED_PRODUCTION_COMPRESSED_BYTES-receipt['compressed_size'],
        verified_raw_capacity_bytes=VERIFIED_PRODUCTION_RAW_BYTES,
        verified_compressed_capacity_bytes=VERIFIED_PRODUCTION_COMPRESSED_BYTES,
        published=False)

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    operation=parser.add_mutually_exclusive_group(required=True)
    operation.add_argument('--target',type=Path)
    operation.add_argument('--apply-capacity-bound',action='store_true')
    parser.add_argument('--receipt',type=Path)
    args=parser.parse_args(argv)
    if args.apply_capacity_bound:
        require(args.receipt is not None and not args.receipt.exists()
                and not args.receipt.is_symlink()
                and args.receipt.parent.is_dir()
                and not args.receipt.parent.is_symlink(), 'new receipt required')
        result=maintain_within_verified_capacity(args.source)
        with args.receipt.open('x',encoding='utf-8') as output:
            output.write(canonical(result)+'\n')
    else:
        require(args.receipt is None,'prepare mode does not write a receipt')
        result=compact_snapshot(args.source,args.target)
    print(canonical(result))

if __name__=='__main__': main()
