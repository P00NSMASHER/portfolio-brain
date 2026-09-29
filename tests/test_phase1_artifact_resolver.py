import copy
import hashlib
import io
import json
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from verification.evidence import GitHubArtifactResolver, resolve_claim


class Phase1ArtifactResolverTests(unittest.TestCase):
    def fixture(self):
        now=datetime.now(timezone.utc); iso=lambda seconds:(now+timedelta(seconds=seconds)).isoformat()
        row={'schema_version':'1.0.0','kind':'ADAPTER_RESULT','subject':{'candidate_id':'C'},'producer_id':'111','verifier_id':'222','verified_at':iso(-40),'expires_at':iso(600),'measurements':{'executed':True}}
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as z:z.writestr('claim.json',json.dumps(row))
        raw=buf.getvalue();sha='a'*40
        policy={'schema_version':'1.0.0','approved_sources':[{'repository':'owner/proof','workflow_id':10,'workflow_revision_sha':sha,'branch':'trusted-verifier','principal_id':222}], 'max_archive_bytes':4000000,'max_evidence_age_seconds':86400}
        run={'id':7,'status':'completed','conclusion':'success','repository':{'full_name':'owner/proof'},'head_repository':{'full_name':'owner/proof'},'workflow_id':10,'head_sha':sha,'head_branch':'trusted-verifier','actor':{'id':222},'run_started_at':iso(-60),'updated_at':iso(-20)}
        artifact={'id':8,'expired':False,'workflow_run':{'id':7,'head_sha':sha},'created_at':iso(-30),'digest':'sha256:'+hashlib.sha256(raw).hexdigest()}
        api={'https://api.github.com/repos/owner/proof/actions/runs/7':run,'https://api.github.com/repos/owner/proof/actions/artifacts/8':artifact}
        return policy,run,artifact,api,raw,now

    def resolver(self,f):
        p,_,_,api,raw,now=f
        return GitHubArtifactResolver(p,get_json=lambda u:copy.deepcopy(api[u]),download=lambda _:raw,now=now)

    def test_simulated_provider_metadata_and_bytes_reconcile(self):
        result=resolve_claim(self.resolver(self.fixture()),'gha:owner/proof:7:8:claim.json',kind='ADAPTER_RESULT',subject={'candidate_id':'C'})
        self.assertEqual(result.scope,'PROVIDER_VERIFIED')  # simulated adapter path, not real-world evidence

    def test_default_allowlist_denies_before_network(self):
        resolver=GitHubArtifactResolver(get_json=lambda _:self.fail('network should not run'))
        with self.assertRaises(ValueError):resolver.resolve('gha:owner/proof:7:8:claim.json')

    def test_modified_archive_digest_rejected(self):
        f=list(self.fixture());f[4]=f[4]+b'tampered'
        with self.assertRaises(ValueError):self.resolver(f).resolve('gha:owner/proof:7:8:claim.json')

    def test_wrong_run_reference_rejected(self):
        f=self.fixture();f[2]['workflow_run']['id']=9
        with self.assertRaises(ValueError):self.resolver(f).resolve('gha:owner/proof:7:8:claim.json')

    def test_expired_artifact_rejected(self):
        f=self.fixture();f[2]['expired']=True
        with self.assertRaises(ValueError):self.resolver(f).resolve('gha:owner/proof:7:8:claim.json')

    def test_unknown_workflow_revision_rejected(self):
        f=self.fixture();f[1]['head_sha']='b'*40
        with self.assertRaises(ValueError):self.resolver(f).resolve('gha:owner/proof:7:8:claim.json')

    def test_unapproved_workflow_id_rejected(self):
        f=self.fixture();f[1]['workflow_id']=666
        with self.assertRaises(ValueError):self.resolver(f).resolve('gha:owner/proof:7:8:claim.json')

    def test_unapproved_principal_rejected(self):
        f=self.fixture();f[1]['actor']['id']=333
        with self.assertRaises(ValueError):self.resolver(f).resolve('gha:owner/proof:7:8:claim.json')

    def test_fork_source_rejected(self):
        f=self.fixture();f[1]['head_repository']['full_name']='other/fork'
        with self.assertRaises(ValueError):self.resolver(f).resolve('gha:owner/proof:7:8:claim.json')

    def test_old_attempt_artifact_rejected(self):
        f=self.fixture();f[1]['run_started_at']=f[1]['updated_at']
        with self.assertRaises(ValueError):self.resolver(f).resolve('gha:owner/proof:7:8:claim.json')

    def test_safe_member_and_repository_references_only(self):
        for ref in ('gha:owner/proof:7:8:../claim.json','gha:owner/proof:7:8:/claim.json','https://example.com/claim.json'):
            with self.subTest(ref=ref):
                with self.assertRaises(ValueError):self.resolver(self.fixture()).resolve(ref)

    def test_failed_source_run_rejected(self):
        f=self.fixture();f[1]['conclusion']='failure'
        with self.assertRaises(ValueError):self.resolver(f).resolve('gha:owner/proof:7:8:claim.json')

    def test_subject_not_inferred_from_matching_artifact_name(self):
        with self.assertRaises(ValueError):resolve_claim(self.resolver(self.fixture()),'gha:owner/proof:7:8:claim.json',kind='ADAPTER_RESULT',subject={'candidate_id':'OTHER'})
