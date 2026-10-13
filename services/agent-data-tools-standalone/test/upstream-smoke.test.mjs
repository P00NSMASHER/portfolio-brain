import test from 'node:test';
import assert from 'node:assert/strict';
import {
  paSearch,
  secFilings,
  censusGeocode,
  ofacScreen,
  rdapLookup,
  treasuryRates,
} from '../src/data.mjs';

test('authoritative public upstreams are reachable', { timeout: 90000 }, async () => {
  const pa = await paSearch('OpenAI', 1, false);
  assert.ok(Array.isArray(pa.results));
  assert.ok(pa.results.length >= 1);
  assert.ok(pa.results[0].businessName);

  const sec = await secFilings({ ticker: 'AAPL', form: '10-K', limit: 1 });
  assert.equal(sec.company.cik, '0000320193');
  assert.ok(sec.filings.length >= 1);

  const census = await censusGeocode('4600 Silver Hill Rd, Washington, DC 20233');
  assert.equal(typeof census.matched, 'boolean');
  assert.ok(census.source.includes('Census'));

  const rdap = await rdapLookup('example.com');
  assert.equal(rdap.domain, 'example.com');
  assert.equal(rdap.registered, true);

  const treasury = await treasuryRates('Total Marketable');
  assert.ok(treasury.recordDate);
  assert.ok(Array.isArray(treasury.rates));

  const ofac = await ofacScreen({ name: 'VLADIMIR PUTIN', limit: 3, minScore: 85 });
  assert.ok(Array.isArray(ofac.candidates));
  assert.ok(ofac.totalCandidatesAboveThreshold >= 1);
  assert.ok(ofac.candidates.some(x => /PUTIN/i.test(x.primaryName)));
});
