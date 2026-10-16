"""Explicit local v8 tooling; no provider credentials, execution or migration."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import stat
from brain.core import BrainError, require
from brain.v8 import SCOPE
from brain.v8.contracts import validate_work
from brain.v8.journal import KernelJournal
from brain.v8.planning import select_work


class Parser(argparse.ArgumentParser):
    def error(self,message):
        raise BrainError('V8_ARGUMENTS_INVALID')


def _pairs(pairs):
    result={}
    for key,value in pairs:
        require(key not in result,'V8_JSON_DUPLICATE_KEY')
        result[key]=value
    return result


def _constant(value):
    raise BrainError('V8_JSON_NONFINITE')


def _load(path):
    path=Path(os.path.abspath(path))
    require(not any(p.is_symlink() for p in (path,*path.parents)),'V8_SYMLINK_REFUSED')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        st=os.fstat(stream.fileno())
        require(stat.S_ISREG(st.st_mode) and st.st_nlink==1 and st.st_size<=1048576,
                'V8_INPUT_FILE_INVALID')
        data=stream.read(1048577)
    require(len(data)<=1048576,'V8_INPUT_BOUND')
    return json.loads(data.decode('utf-8'),object_pairs_hook=_pairs,parse_constant=_constant)


def main(argv=None):
    envelope=dict(scope=SCOPE,runtime_actions_executed=0,production_accepted=False)
    try:
        parser=Parser(description='Local v8 kernel; no production actions')
        commands=parser.add_subparsers(dest='command',required=True)
        for command in ('validate','plan'):
            cmd=commands.add_parser(command)
            cmd.add_argument('--input',required=True,type=Path)
            if command=='plan':
                cmd.add_argument('--cycle',required=True,type=int)
                cmd.add_argument('--limit',required=True,type=int)
        commands.add_parser('replay').add_argument('--journal',required=True,type=Path)
        args=parser.parse_args(argv)
        if args.command=='validate':
            row=validate_work(_load(args.input))
            result=dict(work_id=row['work_id'],state=row['state'])
        elif args.command=='plan':
            result=select_work(_load(args.input),cycle=args.cycle,limit=args.limit)
        else:
            with KernelJournal(args.journal,readonly=True) as journal:
                records=journal.replay()
            pending=set()
            for record in records:
                if record['kind']!='WORK':
                    continue
                op=record['operation']
                if op['outcome']=='EXTERNAL_INTENT': pending.add(op['work']['work_id'])
                elif op['outcome']=='EXTERNAL_CONFIRMED': pending.discard(op['work']['work_id'])
            result=dict(record_count=len(records),unresolved_external_count=len(pending),
                        chain_tip=records[-1]['chain_hash'] if records else '0'*64)
        print(json.dumps(dict(result,**envelope,status='PASS'),allow_nan=False,sort_keys=True))
        return 0
    except (BrainError,OSError,ValueError,RecursionError,sqlite3.Error):
        print(json.dumps(dict(envelope,status='BLOCKED',error='V8_LOCAL_INPUT_OR_JOURNAL_INVALID'),sort_keys=True))
        return 2


if __name__=='__main__':
    raise SystemExit(main())
