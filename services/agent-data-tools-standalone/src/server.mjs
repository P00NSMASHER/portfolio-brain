import express from 'express';
import { pathToFileURL } from 'node:url';
import {
  ROUTES,
  PAYMENT,
  requirements,
  paymentDocument,
  paidRoute,
  requestOrigin,
} from './x402.mjs';
import {
  normalizeSearchTerm,
  parseLimit,
  paSearch,
  secFilings,
  censusGeocode,
  ofacScreen,
  normalizeDomain,
  rdapLookup,
  treasuryRates,
  vendorIntake,
} from './data.mjs';

export const app = express();
app.disable('x-powered-by');
app.use(express.json({ limit: '64kb' }));
app.use((req, res, next) => {
  res.set({
    'access-control-allow-origin': '*',
    'access-control-allow-methods': 'GET, OPTIONS',
    'access-control-allow-headers': 'PAYMENT-SIGNATURE, X-PAYMENT, Content-Type, Accept',
    'access-control-expose-headers': 'PAYMENT-REQUIRED, PAYMENT-RESPONSE, x402-settled, x402-price, x402-network, x402-asset, x402-pay-to, Retry-After',
  });
  if (req.method === 'OPTIONS') return res.status(204).end();
  next();
});

function origin(req) {
  return requestOrigin(req);
}

function jsonSchema(properties = {}, required = []) {
  return { type: 'object', properties, required, additionalProperties: false };
}

const INPUT_SCHEMAS = {
  '/api/pa-entity-one': jsonSchema({ q: { type: 'string', minLength: 2, maxLength: 120 } }, ['q']),
  '/api/pa-business': jsonSchema({
    q: { type: 'string', minLength: 2, maxLength: 120 },
    limit: { type: 'integer', minimum: 1, maximum: 25, default: 10 },
  }, ['q']),
  '/api/vendor-intake-gate': jsonSchema({
    name: { type: 'string', minLength: 2, maxLength: 120 },
    address: { type: 'string', minLength: 6, maxLength: 240 },
    domain: { type: 'string', minLength: 3, maxLength: 253 },
  }, ['name', 'address', 'domain']),
  '/api/sec-filings': jsonSchema({
    ticker: { type: 'string', maxLength: 12 },
    cik: { type: 'string', maxLength: 16 },
    form: { type: 'string', maxLength: 20 },
    limit: { type: 'integer', minimum: 1, maximum: 25, default: 10 },
  }),
  '/api/us-address-geocode': jsonSchema({
    address: { type: 'string', minLength: 6, maxLength: 240 },
  }, ['address']),
  '/api/ofac-sdn-screen': jsonSchema({
    name: { type: 'string', minLength: 2, maxLength: 160 },
    limit: { type: 'integer', minimum: 1, maximum: 10, default: 5 },
    minScore: { type: 'integer', minimum: 70, maximum: 100, default: 85 },
  }, ['name']),
  '/api/domain-rdap': jsonSchema({
    domain: { type: 'string', minLength: 3, maxLength: 253 },
  }, ['domain']),
  '/api/treasury-average-rates': jsonSchema({
    security: { type: 'string', maxLength: 100 },
  }),
};

const OUTPUT_SCHEMA = { type: 'object', additionalProperties: true };

function queryParameters(path) {
  const schema = INPUT_SCHEMAS[path];
  return Object.entries(schema.properties).map(([name, value]) => ({
    name,
    in: 'query',
    required: schema.required?.includes(name) ?? false,
    schema: value,
    example: ROUTES[path].sample?.[name],
  }));
}

function openApi(req) {
  const base = origin(req);
  const paths = {};
  for (const [path, cfg] of Object.entries(ROUTES)) {
    paths[path] = {
      get: {
        operationId: path.slice(5).replace(/[^a-zA-Z0-9]+(.)/g, (_, c) => c.toUpperCase()),
        summary: cfg.serviceName,
        description: cfg.description,
        tags: cfg.tags,
        security: [],
        'x-payment-info': {
          price: { mode: 'fixed', currency: 'USD', amount: cfg.decimal },
          protocols: [{ x402: {} }],
          network: PAYMENT.NETWORK,
          payTo: PAYMENT.PAY_TO,
        },
        parameters: queryParameters(path),
        responses: {
          '200': {
            description: 'Paid result',
            content: { 'application/json': { schema: OUTPUT_SCHEMA } },
          },
          '400': { description: 'Invalid input after a payment credential is supplied' },
          '402': { description: 'Payment Required' },
          '502': { description: 'Authoritative upstream unavailable; payment is not settled' },
          '503': { description: 'Payment facilitator unavailable or settlement state unresolved' },
        },
      },
    };
  }
  return {
    openapi: '3.1.0',
    info: {
      title: 'Agent Data Tools x402',
      version: '2.0.0',
      description: 'Eight standalone pay-per-call x402 endpoints backed by authoritative public sources, including a composed Pennsylvania vendor-intake decision gate.',
      contact: { email: 'jayp19386@gmail.com' },
      'x-guidance': 'Use /api/vendor-intake-gate when an agent needs a bounded proceed or human_review workflow decision with evidence. Use the lower-cost raw data routes for direct source facts. Prices are $0.001-$0.020 USDC on Base. Unpaid paid routes return x402 v2 HTTP 402 challenges. Discovery endpoints are free.',
    },
    servers: [{ url: base }],
    paths,
  };
}

function discovery(req) {
  const base = origin(req);
  return {
    x402Version: 2,
    name: 'Agent Data Tools x402',
    description: 'Eight pay-per-call x402 tools backed by authoritative public data, including a vendor-intake decision gate.',
    network: PAYMENT.NETWORK,
    asset: 'USDC',
    payTo: PAYMENT.PAY_TO,
    resources: Object.entries(ROUTES).map(([path, cfg]) => ({
      resource: base + path,
      method: 'GET',
      price: cfg.price,
      description: cfg.description,
      tags: cfg.tags,
      inputSchema: INPUT_SCHEMAS[path],
      outputSchema: OUTPUT_SCHEMA,
      accepts: [requirements(path)],
    })),
  };
}

function agentJson(req) {
  const base = origin(req);
  return {
    version: '1.3',
    origin: new URL(base).host,
    display_name: 'Agent Data Tools x402',
    description: 'Pay-per-call agent tools for Pennsylvania entity lookup, vendor intake, SEC, Census, OFAC, RDAP, and Treasury data.',
    payout_address: PAYMENT.PAY_TO,
    payments: {
      x402: {
        networks: [{
          network: 'base',
          asset: 'USDC',
          contract: PAYMENT.USDC,
        }],
      },
    },
    intents: Object.entries(ROUTES).map(([path, cfg]) => ({
      name: path.slice('/api/'.length).replaceAll('-', '_'),
      description: cfg.description,
      endpoint: path,
      method: 'GET',
      price: { amount: Number(cfg.decimal), currency: 'USDC' },
    })),
  };
}

function validatePaOne(query) {
  return { q: normalizeSearchTerm(query.q ?? '') };
}

function validatePaBusiness(query) {
  return { q: normalizeSearchTerm(query.q ?? ''), limit: parseLimit(query.limit, 10, 25) };
}

function validateVendor(query) {
  const name = normalizeSearchTerm(query.name ?? '');
  const address = String(query.address ?? '').trim().replace(/\s+/g, ' ');
  if (address.length < 6 || address.length > 240) throw new Error('address must be 6-240 characters.');
  const domain = normalizeDomain(query.domain ?? '');
  if (!domain) throw new Error('domain must be a valid ASCII or punycode domain.');
  return { name, address, domain };
}

function validateSec(query) {
  const ticker = String(query.ticker ?? '').trim();
  const cik = String(query.cik ?? '').trim();
  const form = String(query.form ?? '').trim();
  const limit = parseLimit(query.limit, 10, 25);
  if (!ticker && !cik) throw new Error('Provide ticker or cik.');
  if (ticker.length > 12) throw new Error('ticker is too long.');
  if (cik && !/^\D*\d{1,10}\D*$/.test(cik)) throw new Error('cik must contain 1 to 10 digits.');
  if (form.length > 20) throw new Error('form is too long.');
  return { ticker, cik, form, limit };
}

function validateCensus(query) {
  const address = String(query.address ?? '').trim();
  if (address.length < 6 || address.length > 240) throw new Error('address must be 6-240 characters.');
  return { address };
}

function validateOfac(query) {
  const name = String(query.name ?? '').trim();
  if (name.length < 2 || name.length > 160) throw new Error('name must be 2-160 characters.');
  const limit = parseLimit(query.limit, 5, 10);
  const raw = query.minScore ?? 85;
  if (!/^\d+$/.test(String(raw))) throw new Error('minScore must be an integer.');
  const minScore = Number(raw);
  if (minScore < 70 || minScore > 100) throw new Error('minScore must be 70-100.');
  return { name, limit, minScore };
}

function validateRdap(query) {
  const domain = normalizeDomain(query.domain ?? '');
  if (!domain) throw new Error('domain must be a valid ASCII or punycode domain.');
  return { domain };
}

function validateTreasury(query) {
  const security = String(query.security ?? '').trim();
  if (security.length > 100) throw new Error('security filter must be 100 characters or fewer.');
  return { security };
}

app.get('/', (req, res) => {
  const base = origin(req);
  res.type('html').send(`<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="/favicon.svg" type="image/svg+xml"><title>Agent Data Tools x402</title></head><body style="font-family:system-ui;max-width:860px;margin:48px auto;padding:0 20px"><h1>Agent Data Tools x402</h1><p>Eight pay-per-call agent tools backed by authoritative public data. Prices: $0.001-$0.020 USDC on Base.</p><p>Discovery: <a href="/openapi.json">OpenAPI</a> · <a href="/.well-known/x402">x402</a> · <a href="/.well-known/agent.json">agent.json</a> · <a href="/skill.md">skill.md</a></p><p>Paid routes verify before fetching and settle only after a successful result exists.</p><code>${base}</code></body></html>`);
});

app.get('/favicon.svg', (req, res) => res.type('image/svg+xml').send('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="%23111"/><text x="32" y="42" text-anchor="middle" font-size="28" font-family="system-ui,sans-serif" fill="white">402</text></svg>'));
app.get('/api/health', (req, res) => res.json({ ok: true, service: 'Agent Data Tools x402', paidRoutes: Object.keys(ROUTES).length }));
app.get('/api/payment-info', (req, res) => res.json({
  asset: PAYMENT.USDC,
  network: PAYMENT.NETWORK,
  payTo: PAYMENT.PAY_TO,
  facilitator: PAYMENT.FACILITATOR,
  prices: Object.fromEntries(Object.entries(ROUTES).map(([path, cfg]) => [path, cfg.price])),
}));
app.get('/.well-known/x402', (req, res) => res.set('cache-control', 'public, max-age=300').json(discovery(req)));
app.get('/.well-known/x402.json', (req, res) => res.set('cache-control', 'public, max-age=300').json(discovery(req)));
app.get('/.well-known/agent.json', (req, res) => res.set('cache-control', 'public, max-age=300').json(agentJson(req)));
app.get('/openapi.json', (req, res) => res.set('cache-control', 'public, max-age=300').json(openApi(req)));
app.get('/llms.txt', (req, res) => {
  const base = origin(req);
  res.type('text/plain').send(`# Agent Data Tools x402

Eight paid endpoints across Pennsylvania registry/vendor intake, SEC, Census, OFAC, RDAP, and Treasury.

Prices: $0.001-$0.020 USDC on Base.
Payment recipient: ${PAYMENT.PAY_TO}
OpenAPI: ${base}/openapi.json
x402 discovery: ${base}/.well-known/x402
Agent manifest: ${base}/.well-known/agent.json
Skill guide: ${base}/skill.md
`);
});
app.get('/skill.md', (req, res) => res.type('text/markdown').send(`# Agent Data Tools x402

## Use
Choose the paid route that matches the task. Unpaid calls return an x402 v2 PAYMENT-REQUIRED challenge. Pay the quoted USDC amount on Base and retry with PAYMENT-SIGNATURE (or legacy X-PAYMENT).

For Pennsylvania vendor intake, use /api/vendor-intake-gate for a bounded proceed or human_review decision with source evidence.

## Safety and limits
A vendor-gate proceed result means only that configured automated review triggers were not hit. It is not legal, sanctions, fraud, credit, or compliance approval. OFAC screening is name matching only and does not perform the 50 Percent Rule. Registry, Census, and RDAP facts do not prove ownership or control.
`));
app.get('/robots.txt', (req, res) => res.type('text/plain').send('User-agent: *\nAllow: /\nSitemap: ' + origin(req) + '/sitemap.xml\n'));
app.get('/sitemap.xml', (req, res) => {
  const base = origin(req);
  res.type('application/xml').send('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>' + base + '/</loc></url><url><loc>' + base + '/openapi.json</loc></url><url><loc>' + base + '/.well-known/x402</loc></url></urlset>');
});

app.get('/api/pa-entity-one', (req, res) => paidRoute(req, res, '/api/pa-entity-one', validatePaOne, async ({ q }) => {
  const { results, principals } = await paSearch(q, 1, true);
  return {
    query: q,
    found: results.length > 0,
    match: results[0] ?? null,
    source: 'Pennsylvania Department of State via data.pa.gov',
    enrichment: { principals },
  };
}));

app.get('/api/pa-business', (req, res) => paidRoute(req, res, '/api/pa-business', validatePaBusiness, async ({ q, limit }) => {
  const { results, principals } = await paSearch(q, limit, true);
  return {
    query: q,
    count: results.length,
    results,
    source: 'Pennsylvania Department of State via data.pa.gov',
    enrichment: { principals },
  };
}));

app.get('/api/vendor-intake-gate', (req, res) => paidRoute(req, res, '/api/vendor-intake-gate', validateVendor, vendorIntake));
app.get('/api/sec-filings', (req, res) => paidRoute(req, res, '/api/sec-filings', validateSec, secFilings));
app.get('/api/us-address-geocode', (req, res) => paidRoute(req, res, '/api/us-address-geocode', validateCensus, ({ address }) => censusGeocode(address)));
app.get('/api/ofac-sdn-screen', (req, res) => paidRoute(req, res, '/api/ofac-sdn-screen', validateOfac, ofacScreen));
app.get('/api/domain-rdap', (req, res) => paidRoute(req, res, '/api/domain-rdap', validateRdap, ({ domain }) => rdapLookup(domain)));
app.get('/api/treasury-average-rates', (req, res) => paidRoute(req, res, '/api/treasury-average-rates', validateTreasury, ({ security }) => treasuryRates(security)));

app.use((req, res) => res.status(404).json({ error: 'not_found' }));

const port = Number(process.env.PORT || 3000);
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  app.listen(port, '0.0.0.0', () => {
    console.log('Agent Data Tools x402 listening on port ' + port);
  });
}
