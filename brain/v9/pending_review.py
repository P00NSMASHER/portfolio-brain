"""Bind original provider readback to a durable pending intent; never confirm it."""
from brain.core import digest, require
from brain.v8.journal import KernelJournal, _private_path
from brain.v9.missions import project_mission
from brain.v9.reconciliation import observe_draft, validate_intent


def review_pending_draft(mission, journal, intent, *, token, now, transport=None):
    """Return read-only reconciliation evidence, retaining external uncertainty.

    There is deliberately no callback accepting observations as release approval,
    and no EXTERNAL_CONFIRMED append. A separate authorized reconciler must assess
    this point-in-time receipt before any write/retry or claim release.
    """
    intent = validate_intent(intent)
    require(type(journal) is KernelJournal and journal.readonly,
            'V9_REVIEW_READONLY_JOURNAL_REQUIRED')
    def check_identity():
        require(journal.db is not None and not journal.db.in_transaction,
                'V9_REVIEW_ACTIVE_SNAPSHOT_REFUSED')
        path = _private_path(journal.path)
        st = path.stat()
        require((st.st_dev, st.st_ino) == journal.identity, 'V9_REVIEW_JOURNAL_REPLACED')
    check_identity()
    before = project_mission(mission, journal, source_heads=mission['source_heads'], now=now)
    records = journal.replay()
    require((records[-1]['chain_hash'] if records else '0' * 64) == before['journal_tip'],
            'V9_REVIEW_JOURNAL_CHANGED')
    state, pending, claims, completed = {}, {}, {}, {}
    for record in records:
        KernelJournal._apply_record(record['kind'], record['operation'],
                                    state, pending, claims, completed)
    matching = [row for row in mission['work'] if row['repository'] == intent['repository']
                and row['source_sha'] == intent['base_sha'] and row['fingerprint'] == digest(intent)
                and row['resource'] == digest(dict(repository=intent['repository'].casefold()))]
    require(len(matching) == 1, 'V9_REVIEW_INTENT_MEMBERSHIP')
    row = matching[0]
    require(row['work_id'] in pending, 'V9_REVIEW_NO_PENDING_INTENT')
    claim = claims.get(row['resource'])
    require(claim is not None and claim['operation_id'] == pending[row['work_id']]
            and claim['owner'] == row['owner'] and claim['source_sha'] == row['source_sha'],
            'V9_REVIEW_CLAIM_IDENTITY')
    observed = observe_draft(intent, token=token, now=now, transport=transport)
    check_identity()
    after = project_mission(mission, journal, source_heads=mission['source_heads'], now=now)
    require(after['journal_tip'] == before['journal_tip'], 'V9_REVIEW_JOURNAL_CHANGED')
    check_identity()
    return dict(status='PENDING_DRAFT_READBACK_ONLY', mission_id=mission['mission_id'],
                work_id=row['work_id'], operation_id=pending[row['work_id']],
                journal_tip=before['journal_tip'], intent_digest=digest(intent), observation=observed,
                pending_retained=True, retry_authority=False, provider_writes=0,
                independently_accepted=False, release_authority=False, production_accepted=False)
