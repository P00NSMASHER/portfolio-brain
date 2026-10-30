#!/usr/bin/env node
// Read-only Bazaar diagnostic: sends GET requests only, never /verify or /settle.
import { Buffer } from 'node:buffer';

const facilitator = 'https://facilitator.payai.network';
const pa = 'https://pa-entity-x402.floot.app/_api/pa-entity-one';
const netlify = 'https://agent-data-tools-x402.netlify.app/api/pa-entity-one';
const payTo = '0x708f7b52b56eafd7fc1de65fc7752ed732914021';
const expected = {
  scheme: 'exact',
  network: 'eip155:8453',
  amount: '1000',
  asset: '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913',
  payTo,
  extra: { name: 'USD Coin', version: '2' }
};

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const short = (s) => typeof s === 'string' ? s.slice(0, 256) : s ?? null;
const requirementsValid = (r) => Boolean(r) && Object.entries(expected).every(([key, value]) =>
  key === 'extra' ? same(r.extra, value) : r[key] === value
);

async function get(url) {
  try {
    const response = await fetch(url, {
      method: 'GET',
      redirect: 'follow',
      headers: { accept: 'application/json' },
      signal: AbortSignal.timeout(10000)
    });
    const raw = await response.text();
    let body = null;
    try { body = JSON.parse(raw); } catch { /* non-JSON/404 is reported by status */ }
    return { status: response.status, body, paymentRequired: response.headers.get('payment-required') };
  } catch (error) {
    return { status: null, body: null, paymentRequired: null, error: short(String(error)) };
  }
}

function challenge(result, url) {
  let header = null;
  try {
    if (result.paymentRequired) header = JSON.parse(Buffer.from(result.paymentRequired, 'base64').toString('utf8'));
  } catch { /* invalid header */ }
  const body = result.body;
  return {
    status: result.status,
    valid: result.status === 402 &&
      body?.x402Version === 2 && header?.x402Version === 2 &&
      body?.resource?.url === url && header?.resource?.url === url &&
      same(body?.resource, header?.resource) &&
      same(body?.accepts, header?.accepts) &&
      same(body?.extensions, header?.extensions) &&
      requirementsValid(body?.accepts?.[0]) &&
      body?.extensions?.bazaar?.info?.input?.method === 'GET',
    resource: body?.resource,
    payment: body?.accepts?.[0],
    extensions: body?.extensions
  };
}

async function main() {
  const statusUrl = (url) => facilitator + '/discovery/listing-status?resource=' + encodeURIComponent(url);
  const [paidPa, manifest, status, catalog, paidNetlify, netlifyManifest, netlifyStatus] = await Promise.all([
    get(pa + '?q=OpenAI'),
    get('https://pa-entity-x402.floot.app/.well-known/x402.json'),
    get(statusUrl(pa)),
    get(facilitator + '/discovery/resources?payTo=' + payTo + '&network=eip155%3A8453&limit=1000'),
    get(netlify + '?q=OpenAI'),
    get('https://agent-data-tools-x402.netlify.app/.well-known/x402'),
    get(statusUrl(netlify))
  ]);

  const challengePa = challenge(paidPa, pa);
  const catalogItem = catalog.body?.items?.find((item) => item.resource === pa);
  const declaredPa = manifest.body?.resources?.find((item) => item.resource === pa);
  const netlifyChallenge = challenge(paidNetlify, netlify);
  const listing = status.body || {};
  const health = {
    resource: pa,
    unpaidHttpStatus: paidPa.status,
    valid402: challengePa.valid,
    manifestHttpStatus: manifest.status,
    manifestURLMatches: Boolean(declaredPa),
    manifestPaymentMatches: same(declaredPa?.accepts, paidPa.body?.accepts),
    manifestExtensionsMatchLive402: same(declaredPa?.extensions, paidPa.body?.extensions),
    payaiListingStatusHttp: status.status,
    listed: listing.listed === true,
    hidden: listing.hidden ?? null,
    hiddenReason: short(listing.hiddenReason),
    lastUpdated: listing.lastUpdated ?? null,
    lastWrite: listing.lastWrite ? {
      status: listing.lastWrite.status,
      reason: short(listing.lastWrite.reason),
      at: listing.lastWrite.at,
      source: listing.lastWrite.source
    } : null,
    lastProbe: listing.lastProbe ?? null,
    publicCatalogHttpStatus: catalog.status,
    publicCatalogContainsExactURL: Boolean(catalogItem),
    catalogServiceNameMatchesLive402: Boolean(catalogItem) && catalogItem.serviceName === challengePa.resource?.serviceName,
    catalogTagsMatchLive402: Boolean(catalogItem) && same(catalogItem.tags, challengePa.resource?.tags)
  };

  const fallback = {
    resource: netlify,
    unpaidHttpStatus: paidNetlify.status,
    valid402: netlifyChallenge.valid,
    manifestHttpStatus: netlifyManifest.status,
    payaiListingStatusHttp: netlifyStatus.status,
    listed: netlifyStatus.body?.listed ?? false,
    hiddenReason: short(netlifyStatus.body?.hiddenReason),
    lastWriteReason: short(netlifyStatus.body?.lastWrite?.reason),
    lastProbe: netlifyStatus.body?.lastProbe ?? null
  };
  const healthy = health.valid402 && health.manifestURLMatches &&
    health.manifestPaymentMatches && health.listed && !health.hidden &&
    health.publicCatalogContainsExactURL;
  const requireNetlify = process.argv.includes('--require-netlify') || process.env.REQUIRE_NETLIFY === 'true';
  console.log(JSON.stringify({
    checkedAt: new Date().toISOString(),
    note: 'GET-only diagnostic; no payment, verify, settle, or buyer activity',
    primaryHealthy: Boolean(healthy),
    primary: health,
    fallback,
    fallbackRequired: requireNetlify
  }, null, 2));
  if (!healthy || (requireNetlify && !fallback.valid402)) process.exitCode = 1;
}

main().catch((error) => {
  console.error('Read-only Bazaar audit failed: ' + short(String(error)));
  process.exitCode = 1;
});
