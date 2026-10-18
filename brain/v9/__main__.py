"""Explicit local v9 mission tools; no provider writes or release authority."""
import argparse
import json
import sqlite3
import subprocess
from pathlib import Path
from brain.core import BrainError, require
from brain.v8.__main__ import _load, Parser
from brain.v8.journal import KernelJournal
from brain.v9.missions import compile_mission, project_mission


def main(argv=None):
    try:
        parser = Parser(description='Compile or replay a local v9 mission; no provider writes')
        commands = parser.add_subparsers(dest='command', required=True)
        compile_parser = commands.add_parser('compile')
        compile_parser.add_argument('--input', required=True, type=Path)
        exercise = commands.add_parser('exercise')
        exercise.add_argument('--input', required=True, type=Path)
        exercise.add_argument('--mission', required=True, type=Path)
        exercise.add_argument('--journal', required=True, type=Path)
        exercise.add_argument('--now', required=True)
        plan = commands.add_parser('plan')
        plan.add_argument('--mission', required=True, type=Path)
        plan.add_argument('--heads', required=True, type=Path)
        plan.add_argument('--journal', required=True, type=Path)
        plan.add_argument('--now', required=True)
        args = parser.parse_args(argv)
        if args.command == 'compile':
            data = _load(args.input)
            require(type(data) is dict and set(data) == {'work', 'source_heads', 'max_parallel'},
                    'V9_COMPILE_INPUT_FIELDS')
            result = compile_mission(data['work'], source_heads=data['source_heads'],
                                     max_parallel=data['max_parallel'])
        elif args.command == 'exercise':
            from brain.v9.local_recipe import execute_recipe
            data = _load(args.input)
            require(type(data) is dict and set(data) == {'request', 'original_utf8', 'source_heads'}
                    and type(data['original_utf8']) is str, 'V9_EXERCISE_INPUT_FIELDS')
            mission = _load(args.mission)
            with KernelJournal(args.journal) as journal:
                result = execute_recipe(mission, journal, data['request'],
                    data['original_utf8'].encode('utf-8'), source_heads=data['source_heads'], now=args.now)
        else:
            mission, heads = _load(args.mission), _load(args.heads)
            with KernelJournal(args.journal, readonly=True) as journal:
                result = project_mission(mission, journal, source_heads=heads, now=args.now)
        print(json.dumps(dict(status='LOCAL_ONLY', result=result,
                              automatic_execution_authority=False,
                              production_accepted=False), sort_keys=True))
        return 0
    except (BrainError, OSError, ValueError, TypeError, KeyError, RecursionError, sqlite3.Error, subprocess.SubprocessError) as exc:
        code = str(exc) if isinstance(exc, BrainError) else 'V9_INPUT_UNAVAILABLE'
        print(json.dumps(dict(status='BLOCKED', code=code,
                              automatic_execution_authority=False,
                              production_accepted=False), sort_keys=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
