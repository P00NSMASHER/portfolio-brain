"""Layered product tests: real calculations, persistence, retrieval, failure isolation."""
import base64
import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from brain.core import Store,BrainError,digest,utcnow
from brain.adapters import GitHub,event,policy
from brain.intelligence import holdings_report,validate_payload
from brain.experiments import invoice_dedup_experiment
from brain.__main__ import monitor,research,experiment,doctor

SHA='a'*40
NOW='2026-10-07T21:00:00Z'
REPOSITORY='P00NSMASHER/portfolio-brain'

def payload(repo=REPOSITORY):
 return {'repository':repo,'head_sha':SHA,'default_branch':'main','checks':[],'open_issues':3,'source_ref':f'https://github.com/{repo}/commit/{SHA}'}

class ProductTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.path=Path(self.tmp.name);self.store=Store(self.path/'state.sqlite',visibility='PUBLIC');self.addCleanup(self.store.close)
 def seed(self):
  self.store.submit([event('repository',REPOSITORY,payload(),SHA,now=NOW)],now=NOW);self.store.drain()
 def test_idempotency_and_collision_batch_rollback(self):
  item=event('repository',REPOSITORY,payload(),SHA,now=NOW)
  self.store.submit([item],now=NOW);self.store.submit([item],now=NOW)
  self.assertEqual(self.store.pending(),1)
  bad=copy.deepcopy(item);bad['payload']['open_issues']=99
  with self.assertRaisesRegex(BrainError,'IDEMPOTENCY_CONFLICT'): self.store.submit([event('repository','example/other',payload('example/other'),SHA,now=NOW),bad],now=NOW)
  self.assertEqual(self.store.db.execute('select count(*) from events').fetchone()[0],1)
 def test_backup_restart_and_history_replay(self):
  self.seed();original=self.store.report(SHA,now=NOW)
  self.store.backup(self.path/'backup.sqlite')
  restored=Store(self.path/'backup.sqlite',visibility='PUBLIC')
  try: self.assertEqual(restored.read_report(SHA,now=NOW),original)
  finally: restored.close()
 def test_hash_chain_corruption_fail_closed(self):
  self.seed();self.store.db.execute("UPDATE ledger SET chain_hash=?",('f'*64,))
  with self.assertRaises(BrainError): self.store.report(SHA,now=NOW)
 def test_fresh_wrapper_cannot_launder_old_source(self):
  self.seed();old=self.store.report(SHA,now='2026-10-10T21:00:00Z')
  self.assertEqual(old['status'],'BLOCKED')
  with self.assertRaises(BrainError):self.store.read_report(SHA,now='2026-10-10T21:00:00Z')
 def test_stale_projection_and_changed_source_sha_rejected(self):
  self.seed();self.store.report(SHA,now=NOW)
  with self.assertRaises(BrainError):self.store.read_report('b'*40,now=NOW)
  new=event('repository',REPOSITORY,payload(),SHA,now='2026-10-07T21:01:00Z')
  self.store.submit([new],now='2026-10-07T21:01:00Z');self.store.drain()
  with self.assertRaises(BrainError): self.store.read_report(SHA,now='2026-10-07T21:01:00Z')
 def test_simulated_experiment_never_claims_revenue(self):
  self.seed();p=invoice_dedup_experiment(1000)
  self.assertGreater(p['duplicate_cases'],0);self.assertEqual(p['near_duplicates'],2)
  self.assertLess(p['candidate_operations'],p['baseline_operations']);self.assertTrue(p['equal_outputs'])
  result=experiment(self.store,SHA,self.path/'experiment')
  self.assertIsNone(result['learning']['verified_revenue']);self.assertIsNone(result['learning']['prediction_confidence'])
 def test_experiment_cannot_mislabel_simulation(self):
  p=invoice_dedup_experiment();item=event('experiment',p['experiment'],p,SHA,now=NOW)
  with self.assertRaises(BrainError):self.store.submit([item],now=NOW)
 def test_actual_market_math_and_unavailable_cost(self):
  p={'currency':'USD','cash':'100','positions':[{'symbol':'A','quantity':'2','cost_basis':'160','sector':'Tech'},{'symbol':'B','quantity':'1','cost_basis':None,'sector':'Health'}], 'quotes':{'A':{'price':'100','observed_at':NOW,'source_ref':'operator supplied permitted input','data_kind':'ACTUAL'},'B':{'price':'200','observed_at':NOW,'source_ref':'operator supplied permitted input','data_kind':'ACTUAL'}},'authorization':'USER_AUTHORIZED','historical_prices':[{'observed_at':'2026-10-05T21:00:00Z','prices':{'A':'80','B':'140'},'source_ref':'licensed operator export','data_kind':'ACTUAL'},{'observed_at':'2026-10-06T21:00:00Z','prices':{'A':'60','B':'100'},'source_ref':'licensed operator export','data_kind':'ACTUAL'},{'observed_at':NOW,'prices':{'A':'100','B':'200'},'source_ref':'licensed operator export','data_kind':'ACTUAL'}]}
  validate_payload('holdings',p,NOW);result=holdings_report(p)
  self.assertEqual(result['net_asset_value_usd'],'500');self.assertIsNone(result['unrealized_gain_usd'])
  self.assertAlmostEqual(result['concentration_hhi'],.36);self.assertEqual(result['stress_minus_20_percent_equities_usd'],'420.0')
  self.assertAlmostEqual(result['history']['max_drawdown'],-.2);self.assertAlmostEqual(result['history']['total_price_return'],.25)
  self.assertIsNone(result['history']['annualized_volatility']);self.assertFalse(result['execution_authority'])
  broken=copy.deepcopy(p);broken['quotes']['A']['price']='NaN'
  with self.assertRaises(BrainError):validate_payload('holdings',broken,NOW)
  broken=copy.deepcopy(p);broken['historical_prices'][1]['observed_at']=NOW
  with self.assertRaises(BrainError):validate_payload('holdings',broken,NOW)
 def test_code_discovery_retains_missing_and_restrictive_license(self):
  raw=b'def audit_invoice(rows):\n    return rows  # duplicate freight invoice\n'
  blob=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
  meta={'full_name':'example/audit','private':False,'default_branch':'main','license':{'spdx_id':'GPL-3.0'}}
  def transport(path):
   if path.startswith('/search/'):return {'incomplete_results':False,'items':[meta]}
   if '/branches/' in path:return {'commit':{'sha':SHA}}
   if '/trees/' in path:return {'truncated':False,'tree':[{'type':'blob','path':'invoice.py','sha':blob,'size':len(raw)},{'type':'blob','path':'tests/test_invoice.py','sha':'b'*40,'size':30}]}
   if '/blobs/' in path:return {'encoding':'base64','sha':blob,'content':base64.b64encode(raw).decode()}
   raise AssertionError(path)
  api=GitHub(transport=transport);found=api.discover(policy()['research_targets'][0]);self.assertEqual(found[0][0]['license'],'GPL-3.0')
  self.assertIn('invoice',found[0][0]['matched_terms']);self.assertEqual(found[0][0]['test_paths'],['tests/test_invoice.py'])
  meta['license']=None;self.assertEqual(GitHub(transport=transport).discover(policy()['research_targets'][0])[0][0]['license'],'UNKNOWN')
 def test_discovery_never_promotes_tests_and_credits_only_related_test_paths(self):
  implementation=b'def audit_invoice(rows):\n    return rows  # duplicate freight invoice\n'
  test_body=b'test("invoice duplicate", () => expect(true).toBe(true))\n'
  implementation_blob=hashlib.sha1(b'blob '+str(len(implementation)).encode()+b'\0'+implementation).hexdigest()
  test_blob=hashlib.sha1(b'blob '+str(len(test_body)).encode()+b'\0'+test_body).hexdigest()
  meta={'full_name':'example/audit','private':False,'default_branch':'main','license':{'spdx_id':'MIT'}}
  def transport(path):
   if path.startswith('/search/'):return {'incomplete_results':False,'items':[meta]}
   if '/branches/' in path:return {'commit':{'sha':SHA}}
   if '/trees/' in path:return {'truncated':False,'tree':[
    {'type':'blob','path':'api.test.js','sha':test_blob,'size':len(test_body)},
    {'type':'blob','path':'tests/test_invoice.py','sha':test_blob,'size':len(test_body)},
    {'type':'blob','path':'src/invoice.py','sha':implementation_blob,'size':len(implementation)}
   ]}
   if path.endswith('/'+implementation_blob):return {'encoding':'base64','sha':implementation_blob,'content':base64.b64encode(implementation).decode()}
   raise AssertionError(path)
  candidate=GitHub(transport=transport).discover(policy()['research_targets'][0])[0][0]
  self.assertEqual(candidate['path'],'src/invoice.py')
  self.assertEqual(candidate['test_paths'],['tests/test_invoice.py'])

 def test_report_does_not_recommend_historical_test_file_candidates(self):
  self.seed()
  candidate={'repository':'example/audit','head_sha':SHA,'path':'api.test.js','blob_sha':'b'*40,'code_sha256':'c'*64,'bytes':50,'test_paths':['api.test.js'],'license':'UNKNOWN','source_ref':f'https://github.com/example/audit/blob/{SHA}/api.test.js','target':'freight-recovery','query':'invoice audit','matched_terms':['invoice','audit']}
  self.store.submit([event('candidate','example/audit:api.test.js',candidate,SHA,now=NOW)],now=NOW)
  self.store.drain()
  report=self.store.report(SHA,now=NOW)
  self.assertEqual(report['reuse_candidates'],[])
  self.assertEqual(report['business_opportunities'],[])
  self.assertEqual(report['learning']['facts'],2)

 def test_malformed_or_mismatched_blob_rejected(self):
  api=GitHub(transport=lambda _: {'full_name':'example/repo','private':True,'default_branch':'main'})
  with self.assertRaises(BrainError):api.observe('example/repo')
  with self.assertRaises(BrainError):api.get('//evil.invalid')
 def test_targeted_failure_retains_other_observations_but_doctor_fails(self):
  class API:
   requests=2
   def observe(self,repo):
    if repo.endswith('bad'):raise BrainError('SOURCE_API_503')
    return payload(repo),False
  with self.assertRaises(BrainError):monitor(self.store,SHA,self.path/'report',api=API(),repositories=['example/good','example/bad'])
  self.assertEqual(self.store.db.execute('select count(*) from events').fetchone()[0],1)
  self.assertEqual(self.store.pending(),0)
  with self.assertRaises(BrainError):doctor(self.store,SHA,self.path/'doctor')
 def test_full_useful_operation_from_source_to_html_and_doctor(self):
  class API:
   requests=1
   def observe(self,repo):return payload(repo),False
   def discover(self,target,repository=None):return []
  monitor(self.store,SHA,self.path/'monitor',api=API())
  research(self.store,SHA,self.path/'research',api=API());experiment(self.store,SHA,self.path/'experiment')
  result=doctor(self.store,SHA,self.path/'doctor')
  self.assertEqual(result['status'],'PASS');self.assertEqual(result['pending_events'],0)
  self.assertTrue((self.path/'monitor/report.html').exists())
  # A code upgrade cannot borrow workload successes from another SHA.
  self.store.report('b'*40)
  with self.assertRaises(BrainError):doctor(self.store,'b'*40,self.path/'doctor')
 def test_html_escapes_untrusted_repository_data(self):
  from brain.render import write_report
  report={'status':'FAIL','repositories':[{'repository':'<script>alert(1)</script>','head_sha':SHA,'checks':[],'source_ref':'https://github.com/example/repo'}]}
  write_report(report,self.path/'html')
  raw=(self.path/'html/report.html').read_text();self.assertNotIn('<script>',raw);self.assertIn('&lt;script&gt;',raw)
 def test_request_budget_is_enforced(self):
  api=GitHub(transport=lambda _: {})
  for _ in range(24):api.get('/repos/example/repo')
  with self.assertRaises(BrainError):api.get('/repos/example/repo')

if __name__=='__main__': unittest.main()

class UpgradeTests(unittest.TestCase):
 def test_private_database_cannot_propose_public_upgrade(self):
  from brain.upgrades import evolve
  with tempfile.TemporaryDirectory() as directory:
   store=Store(Path(directory)/'state.sqlite',visibility='PRIVATE')
   try:
    with self.assertRaises(BrainError):evolve(store,SHA,api=object())
   finally:store.close()
 def test_insufficient_or_synthetic_sources_do_not_upgrade(self):
  from brain.upgrades import build_knowledge
  with self.assertRaises(BrainError):build_knowledge({'status':'PASS','reuse_candidates':[]})
  with self.assertRaises(BrainError):build_knowledge({'status':'FAIL','reuse_candidates':[{}]*3})
 def test_upgrade_api_never_merges_or_writes_other_project(self):
  from brain.upgrades import UpgradeAPI
  api=UpgradeAPI(transport=lambda *args:{})
  for path,method in (('/repos/P00NSMASHER/abvmschoolstarworld/git/refs','POST'),('/repos/P00NSMASHER/portfolio-brain/pulls/1/merge','PUT'),('/repos/P00NSMASHER/portfolio-brain/git/refs/heads/main','PATCH')):
   with self.assertRaises(BrainError):api.request(path,method,{})

class UpgradeEndToEndTests(unittest.TestCase):
 def test_upgrade_payload_cannot_write_main_or_arbitrary_ref(self):
  from brain.upgrades import UpgradeAPI,REPOSITORY as repo,PATH
  calls=[];api=UpgradeAPI(transport=lambda *args:calls.append(args))
  bad=[('git/refs','POST',{'ref':'refs/heads/main','sha':SHA}),('contents/'+PATH,'PUT',{'message':'test','branch':'main','sha':SHA,'content':'e30='}),('pulls','POST',{'head':'main','base':'other','title':'test','body':'AUTO_REPAIR_FINGERPRINT: test'})]
  for endpoint,method,payload in bad:
   with self.assertRaises(BrainError):api.request('/repos/'+repo+'/'+endpoint,method,payload)
  self.assertEqual(calls,[])

 def test_historical_unrelated_tests_cannot_qualify_upgrade(self):
  from brain.upgrades import build_knowledge
  candidate={'data_kind':'ACTUAL','freshness':'CURRENT','path':'hosted-x402/src/dynamic-payment.ts','test_paths':['tests/test_buyer_profile.py','tests/test_mcp_security.py'],'matched_terms':['payment','x402']}
  with self.assertRaisesRegex(BrainError,'INSUFFICIENT_UPGRADE_EVIDENCE'):build_knowledge({'status':'PASS','reuse_candidates':[dict(candidate) for _ in range(3)]})

 def test_validation_dispatch_cannot_target_main_or_other_workflow(self):
  from brain.upgrades import UpgradeAPI,VALIDATION,REPOSITORY as repo
  calls=[];api=UpgradeAPI(transport=lambda *args:calls.append(args))
  for path,payload in [(VALIDATION,{'ref':'main'}),(VALIDATION,{'ref':'factory/auto-repair-v2-knowledge-'+'a'*16,'inputs':{}}),('actions/workflows/brain-cycle.yml/dispatches',{'ref':'main'})]:
   with self.assertRaises(BrainError):api.request('/repos/'+repo+'/'+path,'POST',payload)
  self.assertEqual(calls,[])

 def test_upgrade_http_failure_preserves_status_without_token(self):
  import urllib.error
  from brain.upgrades import UpgradeAPI,REPOSITORY as repo
  api=UpgradeAPI(token='secret-never-in-diagnostics')
  class Opener:
   def open(self,*args,**kwargs):raise urllib.error.HTTPError('https://api.github.com',403,'Forbidden',{},None)
  api.opener=Opener()
  with self.assertRaisesRegex(BrainError,'UPGRADE_API_403: POST pulls') as failure:api.request('/repos/'+repo+'/pulls','POST',{'head':'factory/auto-repair-v2-knowledge-'+'a'*16,'base':'main','title':'test','body':'AUTO_REPAIR_FINGERPRINT: '+'a'*64})
  self.assertNotIn('secret-never-in-diagnostics',str(failure.exception))

 def test_evidence_qualified_proposal_uses_only_protected_path(self):
  from brain.upgrades import evolve
  with tempfile.TemporaryDirectory() as directory:
   store=Store(Path(directory)/'state.sqlite',visibility='PUBLIC')
   now=utcnow();items=[event('repository',REPOSITORY,payload(),SHA,now=now)]
   for index in range(3):
    repo=f'example/invoice{index}'
    candidate={'repository':repo,'head_sha':SHA,'path':'invoice.py','blob_sha':'b'*40,'code_sha256':'c'*64,'bytes':50,'test_paths':['tests/test_invoice.py'],'license':'UNKNOWN','source_ref':f'https://github.com/{repo}/blob/{SHA}/invoice.py','target':'freight-recovery','query':'invoice audit','matched_terms':['invoice','audit']}
    items.append(event('candidate',repo+':invoice.py',candidate,SHA,now=now))
   store.submit(items);store.drain();store.report(SHA)
   calls=[]
   class API:
    def __init__(self,fail_dispatch=False):self.head=None;self.pr=None;self.content=None;self.fail_dispatch=fail_dispatch
    def request(self,path,method='GET',body=None):
     calls.append((path,method,body))
     if path.endswith('/branches/main'):return {'commit':{'sha':SHA}}
     if '/branches/factory/' in path:
      if self.head is None:raise BrainError('UPGRADE_API_404: absent')
      return {'commit':{'sha':self.head}}
     if '/pulls?' in path:return [self.pr] if self.pr else []
     if '/compare/' in path:return {'merge_base_commit':{'sha':SHA},'files':[{'filename':'brain/REUSE_KNOWLEDGE.json'}]}
     if '/contents/' in path and method=='GET' and path.endswith('e'*40):return {'encoding':'base64','content':self.content}
     if '/contents/' in path and method=='GET':return {'sha':'d'*40}
     if '/git/refs' in path:self.head=SHA;return {}
     if '/contents/' in path and method=='PUT':self.head='e'*40;self.content=body['content'];return {'commit':{'sha':self.head}}
     if path.endswith('/pulls') and method=='POST':
      self.pr={'number':100,'html_url':'https://github.com/P00NSMASHER/portfolio-brain/pull/100','head':{'sha':self.head,'ref':body['head'],'repo':{'full_name':REPOSITORY}},'base':{'ref':'main'},'user':{'login':'github-actions[bot]'}};return self.pr
     if path.endswith('/actions/workflows/foundation-ci.yml/dispatches') and method=='POST':
      if self.fail_dispatch:self.fail_dispatch=False;raise BrainError('UPGRADE_API_503: delivery interrupted')
      return {}
     raise AssertionError(path)
   try:
    result=evolve(store,SHA,api=API());self.assertEqual(result['status'],'CANDIDATE_PR_CREATED');self.assertEqual(result['independent_review'],'PENDING')
    self.assertTrue(all('/merge' not in c[0] for c in calls))
    self.assertEqual(evolve(store,SHA,api=API())['status'],'COOLDOWN')
    create=[c for c in calls if c[0].endswith('/pulls') and c[1]=='POST'][0]
    self.assertEqual(create[2]['base'],'main');self.assertIn('AUTO_REPAIR_FINGERPRINT:',create[2]['body'])
    dispatched=[c for c in calls if c[0].endswith('/dispatches')]
    self.assertEqual(len(dispatched),1);self.assertEqual(dispatched[0][2]['ref'],create[2]['head'])
    self.assertEqual(result['validation_dispatch'],'DELIVERED')
    # An interrupted dispatch resumes the same verified branch/PR once after an
    # hour, without creating another proposal or dropping the weekly cooldown.
    from unittest.mock import patch
    from datetime import timedelta
    from brain.core import timestamp
    recovery=Store(Path(directory)/'recovery.sqlite',visibility='PUBLIC');recovery.submit(items);recovery.drain();recovery.report(SHA)
    api=API(fail_dispatch=True);calls.clear()
    with self.assertRaisesRegex(BrainError,'UPGRADE_API_503'):evolve(recovery,SHA,api=api)
    future=(timestamp(utcnow())+timedelta(seconds=3602)).isoformat().replace('+00:00','Z')
    with patch('brain.upgrades.utcnow',return_value=future):
     resumed=evolve(recovery,SHA,api=api);self.assertEqual(resumed['validation_dispatch'],'DELIVERED')
     self.assertEqual(evolve(recovery,SHA,api=api)['status'],'COOLDOWN')
    self.assertEqual(sum(p.endswith('/git/refs') and m=='POST' for p,m,_ in calls),1)
    self.assertEqual(sum(p.endswith('/pulls') and m=='POST' for p,m,_ in calls),1)
    self.assertEqual(sum(p.endswith('/dispatches') for p,m,_ in calls),2)
    recovery.close()
   finally:store.close()
 def test_doctor_rejects_partial_monitor_borrowing_old_full_coverage(self):
  with tempfile.TemporaryDirectory() as directory:
   store=Store(Path(directory)/'state.sqlite',visibility='PUBLIC')
   class API:
    requests=1
    def observe(self,repo):return payload(repo),False
    def discover(self,target,repository=None):return []
   try:
    monitor(store,SHA,Path(directory)/'monitor',api=API());research(store,SHA,Path(directory)/'research',api=API());experiment(store,SHA,Path(directory)/'experiment')
    self.assertEqual(doctor(store,SHA,Path(directory)/'doctor')['status'],'PASS')
    monitor(store,SHA,Path(directory)/'partial',api=API(),repositories=[REPOSITORY]);research(store,SHA,Path(directory)/'research',api=API());experiment(store,SHA,Path(directory)/'experiment')
    with self.assertRaises(BrainError):doctor(store,SHA,Path(directory)/'doctor')
   finally:store.close()
 def test_repeated_execution_and_restart_keep_zero_backlog(self):
  with tempfile.TemporaryDirectory() as directory:
   db=Path(directory)/'state.sqlite'
   for index in range(30):
    store=Store(db,visibility='PUBLIC')
    item=event('repository',REPOSITORY,payload(),SHA,now=utcnow())
    store.submit([item]);store.submit([item]);store.drain();report=store.report(SHA)
    self.assertEqual(store.pending(),0);self.assertEqual(report['state_sequence'],index+1)
    self.assertEqual(store.read_report(SHA)['canonical_hash'],report['canonical_hash']);store.close()

class CheckPaginationTests(unittest.TestCase):
 def test_175_checks_complete_in_two_pages_with_verified_unique_ids(self):
  def transport(path):
   if '/branches/' in path:return {'commit':{'sha':SHA}}
   if '/check-runs?' in path:
    rows=[{'id':i,'name':'validate','status':'completed','conclusion':'success','head_sha':SHA,'html_url':f'https://github.com/{REPOSITORY}/runs/{i}'} for i in range(1,176)]
    return {'total_count':175,'check_runs':rows[100:] if 'page=2' in path else rows[:100]}
   return {'full_name':REPOSITORY,'private':False,'default_branch':'main','open_issues_count':3}
  api=GitHub(transport=transport);p,_=api.observe(REPOSITORY);validate_payload('repository',p,NOW)
  self.assertEqual(len(p['checks']),175);self.assertEqual(api.requests,5)
 def test_paginated_duplicates_cannot_claim_complete_delivery(self):
  def transport(path):
   if '/branches/' in path:return {'commit':{'sha':SHA}}
   if '/check-runs?' in path:
    rows=[{'id':i,'name':'validate','status':'completed','conclusion':'success','head_sha':SHA,'html_url':f'https://github.com/{REPOSITORY}/runs/{i}'} for i in range(1,101)]
    return {'total_count':101,'check_runs':rows[:1] if 'page=2' in path else rows}
   return {'full_name':REPOSITORY,'private':False,'default_branch':'main','open_issues_count':3}
  with self.assertRaises(BrainError):GitHub(transport=transport).observe(REPOSITORY)

class RuntimeAuthorizationTests(unittest.TestCase):
 def test_public_reads_use_existing_token_but_still_reject_private_content(self):
  with patch.dict('os.environ',{'GITHUB_TOKEN':'existing-test-token'}):
   api=GitHub(transport=lambda _: {'full_name':'example/private','private':True,'default_branch':'main'})
   self.assertEqual(api.token,'existing-test-token');self.assertFalse(api.private)
   with self.assertRaises(BrainError):api.observe('example/private')
 def test_deleted_acknowledged_tail_is_not_silently_accepted(self):
  with tempfile.TemporaryDirectory() as directory:
   store=Store(Path(directory)/'state.sqlite',visibility='PUBLIC')
   try:
    store.submit([event('repository',REPOSITORY,payload(),SHA,now=utcnow())]);store.drain()
    store.db.execute('DELETE FROM ledger');store.db.execute('DELETE FROM events')
    with self.assertRaises(BrainError):store.report(SHA)
   finally:store.close()
