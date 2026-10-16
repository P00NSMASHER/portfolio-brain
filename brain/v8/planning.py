"""Deterministic advisory planning with no revenue or execution authority."""
from collections import defaultdict
from brain.core import require
from brain.v8.contracts import LOCAL_STATES, parse_utc, validate_work


def select_work(items, *, cycle, limit):
    require(type(items) is list and len(items)<=256, 'V8_PLAN_BOUND')
    require(type(cycle) is int and 0<=cycle<2**63 and type(limit) is int
            and 1<=limit<=5, 'V8_PLAN_COUNTER_INVALID')
    rows=[validate_work(row) for row in items]
    by_id={r['work_id']:r for r in rows}
    require(len(by_id)==len(rows), 'V8_PLAN_DUPLICATE_WORK')

    def dependency_gap(ident, visiting):
        if ident in visiting:
            return 'DEPENDENCY_CYCLE'
        if ident not in by_id:
            return 'DEPENDENCY_UNKNOWN'
        row=by_id[ident]
        for dep in row['dependencies']:
            gap=dependency_gap(dep,visiting|{ident})
            if gap:
                return gap
        if any(by_id[dep]['state']!='LEARNED' for dep in row['dependencies']):
            return 'DEPENDENCY_UNFINISHED'
        return None

    eligible,blocked=[],[]
    for row in rows:
        gap=dependency_gap(row['work_id'],set())
        if gap:
            blocked.append(dict(work_id=row['work_id'],reason=gap))
        elif row['state'] in LOCAL_STATES:
            eligible.append(row)
    ranked=[]
    for tier in range(5):
        groups=defaultdict(list)
        for row in eligible:
            if row['priority_tier']==tier:
                groups[row['project_id']].append(row)
        projects=sorted(groups)
        if not projects:
            continue
        offset=cycle%len(projects)
        projects=projects[offset:]+projects[:offset]
        for group in groups.values():
            group.sort(key=lambda r:(parse_utc(r['updated_at']),r['work_id']))
        while any(groups.values()):
            for project in projects:
                if groups[project]:
                    ranked.append(groups[project].pop(0))
    return dict(selected=ranked[:limit],deferred=ranked[limit:],
                blocked_dependencies=sorted(blocked,key=lambda r:r['work_id']),
                automatic_execution_authority=False)
