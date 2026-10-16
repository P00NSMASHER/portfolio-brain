"""Prepare a compacted public snapshot; never edit the source or publish state.

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
from brain.core import canonical, digest, require

MAX_BYTES = 5 * 1024 * 1024 * 1024

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

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--target',type=Path,required=True)
    args=parser.parse_args()
    print(canonical(compact_snapshot(args.source,args.target)))

if __name__=='__main__': main()
