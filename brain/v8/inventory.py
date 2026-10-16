"""Registry-bound engineering contracts. Contracts do not confirm runtime access."""
from brain.core import require
from brain.projects import load_project_registry
from brain.v8.contracts import SHA, matches

CONTRACTS = {
 'portfolio-brain': ('brain-reliability','state replay, original automatic execution, independent checks'),
 'abvm': ('school-data-owner','curriculum freshness, source accuracy, phone/tablet study and print journeys'),
 'retally': ('retally-product-owner','invoice correctness, evidence integrity, restricted access and deployed navigation'),
 'research-labs': ('research-methods-owner','reproducible experiments and independent source corroboration'),
 'product-factory': ('factory-owner','isolated builds, restart persistence, browser journeys and package integrity'),
 'pips-classroom': ('classroom-owner','reference parity, Studio runtime and authorized publish identity'),
 'trading-platform': ('data-quality-owner','market-data completeness and reproducibility; no trading'),
 'permitplate': ('portfolio-health-owner','licensing data provenance, security and exact-source checks'),
 'capturebrief': ('portfolio-health-owner','capture, evidence and publication integrity'),
}
STATES = frozenset({'SOURCE_UNOBSERVED','CHECK_EVIDENCE_UNVERIFIED','NO_CHECK_RUNS_OBSERVED',
 'ADVERSE_CHECKS_OBSERVED','INCOMPLETE_OR_INCONCLUSIVE_CHECKS_OBSERVED',
 'NO_ADVERSE_CHECKS_OBSERVED_NOT_RELEASE_APPROVAL'})


def project_maps(observations):
    registry=load_project_registry()['projects']
    by_id={p['id']:p for p in registry}
    require(type(observations) is list and len(observations)<=16,'V8_MAP_BOUND')
    observed={}
    for row in observations:
        require(type(row) is dict and type(row.get('id')) is str and row['id'] in by_id,
                'V8_MAP_PROJECT_UNKNOWN')
        ident=row['id']
        require(ident not in observed and row.get('repository')==by_id[ident]['repository'],
                'V8_MAP_IDENTITY_CONFLICT')
        sha=row.get('repository_revision')
        require(sha is None or matches(SHA,sha),'V8_MAP_SOURCE_INVALID')
        require(type(row.get('source_check_state')) is str and row['source_check_state'] in STATES,
                'V8_MAP_CHECK_STATE_INVALID')
        observed[ident]=row
    result=[]
    for p in registry:
        row=observed.get(p['id'],{})
        owner,contract=CONTRACTS[p['id']]
        result.append(dict(project_id=p['id'],repository=p['repository'],
            source_sha=row.get('repository_revision'),
            source_check_state=row.get('source_check_state','SOURCE_UNOBSERVED'),
            owner=owner,owner_runtime_access_verified=False,verification_contract=contract,
            research_target=p['research_target'],write_capability_verified=False))
    return result
