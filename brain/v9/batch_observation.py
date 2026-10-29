"""Budgeted read-only observation cache, never a source-freshness certificate."""
from brain.v9.batch_queue import instant,hashval
class ObservationBudget:
    def __init__(self,*,max_gets=24,ttl_seconds=1200):
        if type(max_gets) is not int or not 1<=max_gets<=24: raise ValueError("GET_BUDGET_INVALID")
        if type(ttl_seconds) is not int or not 1<=ttl_seconds<=86400: raise ValueError("OBSERVATION_TTL_INVALID")
        self.max_gets=max_gets
        self.ttl_seconds=ttl_seconds
        self._count=0
        self._cache={}
    def _check(self,key,fingerprint):
        if type(key) is not str or not 0<len(key)<=160 or not hashval(fingerprint):
            raise ValueError("OBSERVATION_ID_INVALID")
    def should_fetch(self,key,*,fingerprint,now):
        self._check(key,fingerprint)
        at=instant(now)
        if self._count>=self.max_gets: return False
        old=self._cache.get(key)
        if old is None: return True
        if at<old[1]: raise ValueError("OBSERVATION_CLOCK_REVERSED")
        return old[0]!=fingerprint or (at-old[1]).total_seconds()>self.ttl_seconds
    def record(self,key,*,fingerprint,now):
        self._check(key,fingerprint)
        at=instant(now)
        if key in self._cache and at<self._cache[key][1]:
            raise ValueError("OBSERVATION_CLOCK_REVERSED")
        if self._count>=self.max_gets: raise ValueError("GET_BUDGET_EXHAUSTED")
        self._count+=1
        self._cache[key]=(fingerprint,at)
        return {"status":"OBSERVED_NOT_INDEPENDENTLY_VERIFIED",
                "gets_remaining":self.max_gets-self._count}
    def health(self,key,*,now):
        if type(key) is not str: raise ValueError("OBSERVATION_ID_INVALID")
        at=instant(now)
        if key not in self._cache: return "UNKNOWN_UNOBSERVED"
        if at<self._cache[key][1]: raise ValueError("OBSERVATION_CLOCK_REVERSED")
        if (at-self._cache[key][1]).total_seconds()>self.ttl_seconds:
            return "STALE_NOT_VERIFIED"
        return "CACHED_NOT_SOURCE_CERTIFIED"
    def metrics(self):
        return {"gets_used":self._count,"gets_remaining":self.max_gets-self._count,
                "cache_entries":len(self._cache),"production_accepted":False}
