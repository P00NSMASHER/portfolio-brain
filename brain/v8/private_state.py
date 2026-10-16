"""Bounded owner-private durable files. Local digests are not external trust anchors."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile
from brain.core import canonical,digest,require
from brain.v8.contracts import HASH,matches

MAX_RECORDS = 256
MAX_DIRECTORY_ENTRIES = 2 * MAX_RECORDS + 1


class PrivateFiles:
    def __init__(self,root):
        self.root=Path(os.path.abspath(root))
        self._check_root()
        self.identity=(self.root.stat().st_dev,self.root.stat().st_ino)

    def _check_root(self):
        require(not any(p.is_symlink() for p in (self.root,*self.root.parents)), 'V8_PRIVATE_SYMLINK')
        st=self.root.stat()
        require(stat.S_ISDIR(st.st_mode) and st.st_uid==os.getuid() and st.st_mode&0o077==0,
                'V8_PRIVATE_DIRECTORY_REQUIRED')
        require(not hasattr(self,'identity') or self.identity==(st.st_dev,st.st_ino),
                'V8_PRIVATE_DIRECTORY_REPLACED')

    def path(self,namespace,ident):
        require(namespace in {'automation','outcome'} and matches(HASH,ident),'V8_PRIVATE_ID_INVALID')
        self._check_root()
        return self.root/(namespace+'-'+ident+'.json')

    @contextmanager
    def lock(self):
        self._check_root()
        fd=os.open(self.root/'.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
        try:
            st=os.fstat(fd)
            require(stat.S_ISREG(st.st_mode) and st.st_nlink==1 and st.st_uid==os.getuid()
                    and st.st_mode&0o077==0,'V8_PRIVATE_LOCK_UNSAFE')
            try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as exc:
                from brain.core import BrainError
                raise BrainError('V8_PRIVATE_WRITER_BUSY') from exc
            yield
        finally: os.close(fd)

    def read(self,namespace,ident):
        path=self.path(namespace,ident)
        if not path.exists() and not path.is_symlink(): return None
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as stream:
            st=os.fstat(stream.fileno())
            require(stat.S_ISREG(st.st_mode) and st.st_nlink==1 and st.st_uid==os.getuid()
                    and st.st_mode&0o077==0 and st.st_size<=1048576,'V8_PRIVATE_FILE_UNSAFE')
            raw=stream.read(1048577)
        require(len(raw)<=1048576,'V8_PRIVATE_FILE_BOUND')
        def pairs(values):
            result={}
            for k,v in values:
                require(k not in result,'V8_PRIVATE_DUPLICATE_KEY')
                result[k]=v
            return result
        doc=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs)
        require(type(doc) is dict and set(doc)=={'body','sha256'} and doc['sha256']==digest(doc['body']),
                'V8_PRIVATE_DIGEST_MISMATCH')
        return doc['body']

    def write(self,namespace,ident,body):
        path=self.path(namespace,ident)
        existing=path.exists() or path.is_symlink()
        if existing:
            # Full stores must still reconcile existing durable intents.
            self.read(namespace,ident)
        else:
            count=0
            for number,entry in enumerate(self.root.iterdir(),1):
                require(number<MAX_DIRECTORY_ENTRIES,'V8_PRIVATE_RECORD_BOUND')
                if entry.name.startswith(namespace+'-') and entry.name.endswith('.json'):
                    count+=1
                    require(count<MAX_RECORDS,'V8_PRIVATE_RECORD_BOUND')
        raw=canonical(dict(body=body,sha256=digest(body))).encode('utf-8')
        require(len(raw)<=1048576,'V8_PRIVATE_FILE_BOUND')
        fd,temp=tempfile.mkstemp(prefix='.pending-',dir=self.root)
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            self._check_root()
            os.replace(temp,path)
            directory=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try: os.fsync(directory)
            finally: os.close(directory)
        finally:
            if os.path.exists(temp): os.unlink(temp)

    def iter_records(self,namespace):
        require(namespace in {'automation','outcome'},'V8_PRIVATE_ID_INVALID')
        self._check_root()
        paths=[]
        for number,path in enumerate(self.root.iterdir(),1):
            require(number<=MAX_DIRECTORY_ENTRIES,'V8_PRIVATE_RECORD_BOUND')
            if path.name.startswith(namespace+'-') and path.name.endswith('.json'):
                paths.append(path)
                require(len(paths)<=MAX_RECORDS,'V8_PRIVATE_RECORD_BOUND')
        for path in sorted(paths):
            yield self.read(namespace,path.stem[len(namespace)+1:])

    def records(self,namespace):
        return list(self.iter_records(namespace))
