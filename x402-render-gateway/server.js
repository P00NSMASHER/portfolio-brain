import http from 'node:http';

const PORT = Number(process.env.PORT || 10000);
const PAY_TO = '0x708f7b52b56eafd7fc1de65fc7752ed732914021';
const NETWORK = 'eip155:8453';
const USDC = '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913';
const FACILITATOR = 'https://facilitator.payai.network';
const PA_SOURCE = 'https://data.pa.gov/resource/xvd7-5r2c.json';
const TREASURY_API = 'https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/avg_interest_rates';
const OFAC_BASE = 'https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports';
const IANA_RDAP_BOOTSTRAP = 'https://data.iana.org/rdap/dns.json';
const CONTACT = 'jayp19386@gmail.com';

const ROUTES = {
  '/api/pa-entity-one': {
    amount: '1000',
    price: '$0.001',
    usd: '0.001000',
    serviceName: 'PA Entity Best Match',
    tags: ['business-registry', 'Pennsylvania', 'company-identity', 'vendor-verification', 'due-diligence'],
    description: 'Resolve one best Pennsylvania Department of State business-registry match by company name.',
    inputExample: { q: 'OpenAI' }
  },
  '/api/pa-business': {
    amount: '5000',
    price: '$0.005',
    usd: '0.005000',
    serviceName: 'PA Business Registry',
    tags: ['business-registry', 'Pennsylvania', 'company-identity', 'legal-entity', 'due-diligence'],
    description: 'Search Pennsylvania business-registration records by company name.',
    inputExample: { q: 'OpenAI', limit: 5 }
  },
  '/api/vendor-intake-gate': {
    amount: '20000',
    price: '$0.020',
    usd: '0.020000',
    serviceName: 'PA Vendor Intake Gate',
    tags: ['vendor-intake', 'agent-decision', 'human-review', 'business-registry', 'compliance'],
    description: 'Check a prospective Pennsylvania vendor and return proceed or human_review with source-linked evidence.',
    inputExample: {
      name: 'OpenAI OpCo',
      address: '600 North Second Street, Suite 401, Harrisburg, PA 17101',
      domain: 'openai.com'
    }
  },
  '/api/sec-filings': {
    amount: '5000',
    price: '$0.005',
    usd: '0.005000',
    serviceName: 'SEC Recent Filings',
    tags: ['SEC', 'EDGAR', 'filings', 'finance', 'company-data'],
    description: 'Retrieve recent SEC EDGAR filing metadata for a public company by ticker or CIK.',
    inputExample: { ticker: 'AAPL', form: '10-K', limit: 5 }
  },
  '/api/us-address-geocode': {
    amount: '5000',
    price: '$0.005',
    usd: '0.005000',
    serviceName: 'US Census Geocoder',
    tags: ['geocoding', 'Census', 'address', 'geography', 'US'],
    description: 'Geocode a U.S. address to a standardized Census match, coordinates, and Census geography identifiers.',
    inputExample: { address: '4600 Silver Hill Rd, Washington, DC 20233' }
  },
  '/api/ofac-sdn-screen': {
    amount: '5000',
    price: '$0.005',
    usd: '0.005000',
    serviceName: 'OFAC Name Screen',
    tags: ['OFAC', 'screening', 'compliance', 'name-match', 'risk'],
    description: 'Screen a person or organization name against current OFAC SDN primary names and aliases for review candidates.',
    inputExample: { name: 'VLADIMIR PUTIN', limit: 5, minScore: 85 }
  },
  '/api/domain-rdap': {
    amount: '5000',
    price: '$0.005',
    usd: '0.005000',
    serviceName: 'Domain RDAP Lookup',
    tags: ['RDAP', 'domain', 'registration', 'DNS', 'internet'],
    description: 'Retrieve live authoritative domain-registration metadata through RDAP.',
    inputExample: { domain: 'example.com' }
  },
  '/api/treasury-average-rates': {
    amount: '5000',
    price: '$0.005',
    usd: '0.005000',
    serviceName: 'Treasury Average Rates',
    tags: ['Treasury', 'interest-rates', 'government', 'macro', 'finance'],
    description: 'Get latest monthly average interest rates on outstanding U.S. Treasury securities.',
    inputExample: { security: 'Total Marketable' }
  }
};

const CORS = {
  'access-control-allow-origin': '*',
  'access-control-allow-methods': 'GET, OPTIONS',
  'access-control-allow-headers': 'PAYMENT-SIGNATURE, X-PAYMENT, Content-Type, Accept',
  'access-control-expose-headers': 'PAYMENT-REQUIRED, PAYMENT-RESPONSE, x402-settled, x402-price, x402-network, x402-asset, x402-pay-to'
};

function baseUrl(req) {
  const proto = String(req.headers['x-forwarded-proto'] || 'https').split(',')[0].trim();
  const host = String(req.headers['x-forwarded-host'] || req.headers.host || '').split(',')[0].trim();
  return proto + '://' + host;
}

function json(res, status, body, headers = {}) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    ...CORS,
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(payload),
    ...headers
  });
  res.end(payload);
}

function text(res, status, body, type = 'text/plain; charset=utf-8', headers = {}) {
  res.writeHead(status, {
    ...CORS,
    'content-type': type,
    'content-length': Buffer.byteLength(body),
    ...headers
  });
  res.end(body);
}

function encodeHeader(value) {
  return Buffer.from(JSON.stringify(value), 'utf8').toString('base64');
}

function decodePayment(value) {
  if (!value || value.length > 16384) throw new Error('invalid_payment_header');
  const normalized = value.replace(/-/g, '+').replace(/_/g, '/');
  const parsed = JSON.parse(Buffer.from(normalized, 'base64').toString('utf8'));
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed) || parsed.x402Version !== 2) {
    throw new Error('invalid_payment_payload');
  }
  return parsed;
}

function requirements(cfg) {
  return {
    scheme: 'exact',
    network: NETWORK,
    amount: cfg.amount,
    asset: USDC,
    payTo: PAY_TO,
    maxTimeoutSeconds: 60,
    extra: { name: 'USD Coin', version: '2' }
  };
}

function bazaarExtension(cfg) {
  const info = {
    input: { type: 'http', method: 'GET', queryParams: cfg.inputExample },
    output: { type: 'json', example: { paid: true } }
  };
  const schema = {
    type: 'object',
    properties: {
      input: {
        type: 'object',
        properties: {
          type: { const: 'http' },
          method: { const: 'GET' },
          queryParams: { type: 'object', additionalProperties: true }
        },
        required: ['type', 'method', 'queryParams']
      },
      output: {
        type: 'object',
        properties: {
          type: { const: 'json' },
          example: { type: 'object' }
        },
        required: ['type', 'example']
      }
    },
    required: ['input', 'output']
  };
  return { bazaar: { info, schema } };
}

function paymentDocument(req, path, cfg) {
  return {
    x402Version: 2,
    resource: {
      url: baseUrl(req) + path,
      description: cfg.description,
      mimeType: 'application/json',
      serviceName: cfg.serviceName,
      tags: cfg.tags,
      iconUrl: baseUrl(req) + '/icon.svg'
    },
    accepts: [requirements(cfg)],
    extensions: bazaarExtension(cfg)
  };
}

function paymentRequired(req, res, path, cfg, reason = 'payment_required') {
  const doc = paymentDocument(req, path, cfg);
  json(res, 402, {
    error: reason,
    ...doc,
    price: cfg.price,
    currency: 'USDC',
    network: NETWORK,
    payTo: PAY_TO
  }, {
    'PAYMENT-REQUIRED': encodeHeader(doc),
    'x402-price': cfg.price,
    'x402-asset': 'USDC',
    'x402-network': NETWORK,
    'x402-pay-to': PAY_TO,
    'cache-control': 'no-store'
  });
}

async function facilitatorPost(action, paymentPayload, cfg) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch(FACILITATOR + '/' + action, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        x402Version: 2,
        paymentPayload,
        paymentRequirements: requirements(cfg)
      }),
      signal: controller.signal
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error('facilitator_' + action + '_' + response.status);
    return body;
  } finally {
    clearTimeout(timer);
  }
}

async function servePaid(req, res, path, handler) {
  const cfg = ROUTES[path];
  const signature = req.headers['payment-signature'] || req.headers['x-payment'];
  if (!signature) return paymentRequired(req, res, path, cfg);
  let paymentPayload;
  try {
    paymentPayload = decodePayment(String(signature));
  } catch {
    return paymentRequired(req, res, path, cfg, 'invalid_payment_header');
  }

  try {
    const verified = await facilitatorPost('verify', paymentPayload, cfg);
    if (verified.isValid !== true && verified.success !== true) {
      return paymentRequired(req, res, path, cfg, String(verified.invalidReason || verified.errorReason || 'payment_verification_failed'));
    }

    let result;
    try {
      result = await handler();
    } catch (error) {
      const status = Number(error && error.status) || 502;
      return json(res, status, {
        error: error instanceof Error ? error.message : 'upstream_failure',
        paymentState: 'not_settled'
      }, { 'cache-control': 'no-store' });
    }

    const settled = await facilitatorPost('settle', paymentPayload, cfg);
    if (settled.success !== true) {
      return paymentRequired(req, res, path, cfg, String(settled.errorReason || 'payment_settlement_failed'));
    }

    return json(res, 200, { ...result, paid: true }, {
      'PAYMENT-RESPONSE': encodeHeader(settled),
      'x402-settled': 'true',
      'cache-control': 'no-store'
    });
  } catch {
    return json(res, 503, {
      error: 'Payment facilitator is temporarily unavailable; no result was served.',
      paymentState: 'unresolved'
    }, { 'cache-control': 'no-store' });
  }
}

function normalizeSearchTerm(raw) {
  const value = String(raw || '').trim().replace(/[%_]/g, ' ').replace(/[\u0000-\u001F\u007F]/g, ' ').replace(/\s+/g, ' ');
  if ([...value].filter(ch => /[\p{L}\p{N}]/u.test(ch)).length < 2) throw Object.assign(new Error('q must contain at least 2 letters or digits.'), { status: 400 });
  if (value.length > 120) throw Object.assign(new Error('q must be 120 characters or fewer.'), { status: 400 });
  return value;
}

function canonicalBusinessName(value) {
  let normalized = String(value || '').toUpperCase().replace(/[^A-Z0-9]+/g, ' ').replace(/\s+/g, ' ').trim();
  const suffix = /\s+(?:L\s+L\s+C|LLC|INCORPORATED|INC|CORPORATION|CORP|COMPANY|CO|LIMITED|LTD|L\s+P|LP|L\s+L\s+P|LLP|P\s+C|PC)$/;
  let prior = '';
  while (normalized !== prior) {
    prior = normalized;
    normalized = normalized.replace(suffix, '').trim();
  }
  return normalized;
}

function matchScore(name, query) {
  const candidate = canonicalBusinessName(name);
  const wanted = canonicalBusinessName(query);
  if (candidate === wanted) return 0;
  if (candidate.startsWith(wanted + ' ')) return 1;
  if ((' ' + candidate + ' ').includes(' ' + wanted + ' ')) return 2;
  if (candidate.replaceAll(' ', '').includes(wanted.replaceAll(' ', ''))) return 3;
  return 4;
}

function mapEntity(row) {
  const date = row.creationdate == null ? null : String(row.creationdate);
  return {
    businessName: row.business_name == null ? null : String(row.business_name),
    filingNumber: row.filing_number == null ? null : String(row.filing_number),
    registrationType: row.typeofbusinessregistration == null ? null : String(row.typeofbusinessregistration),
    creationDate: date && !date.startsWith('1753-01-01') ? date.slice(0, 10) : null,
    address1: row.address_line1 == null ? null : String(row.address_line1),
    address2: row.address_line2 == null ? null : String(row.address_line2),
    city: row.city == null ? null : String(row.city),
    state: row.state == null ? null : String(row.state),
    zip: row.zip == null ? null : String(row.zip),
    county: row.shortcountyname == null ? null : String(row.shortcountyname),
    countyCode: row.county_code == null ? null : String(row.county_code),
    principals: []
  };
}

function entityProjection() {
  return ['business_name', 'filing_number', 'address_line1', 'address_line2', 'city', 'state', 'zip', 'typeofbusinessregistration', 'creationdate', 'shortcountyname', 'county_code'].join(',');
}

async function fetchPaCandidates(query, mode, limit = 100) {
  const escaped = query.toUpperCase().replaceAll("'", "''");
  const pattern = mode === 'starts' ? escaped + '%' : '%' + escaped + '%';
  const url = new URL(PA_SOURCE);
  url.searchParams.set('$select', 'distinct ' + entityProjection());
  url.searchParams.set('$where', "upper(business_name) like '" + pattern + "'");
  url.searchParams.set('$limit', String(limit));
  const response = await fetch(url, { headers: { 'user-agent': 'Agent-Data-Tools-x402/1.0 ' + CONTACT } });
  if (!response.ok) throw new Error('PA Open Data returned ' + response.status);
  return (await response.json()).map(mapEntity);
}

function rankPa(rows, query, limit) {
  const unique = new Map();
  for (const row of rows) {
    const key = row.filingNumber || [row.businessName, row.address1, row.city].join('|');
    if (!unique.has(key)) unique.set(key, row);
  }
  return [...unique.values()].sort((a, b) => {
    const an = a.businessName || '';
    const bn = b.businessName || '';
    return matchScore(an, query) - matchScore(bn, query) || an.length - bn.length || an.localeCompare(bn);
  }).slice(0, limit);
}

async function enrichPrincipals(results) {
  const filings = results.map(x => x.filingNumber).filter(Boolean);
  if (!filings.length) return 'complete';
  const where = filings.map(v => "'" + String(v).replaceAll("'", "''") + "'").join(',');
  const url = new URL(PA_SOURCE);
  url.searchParams.set('$select', 'filing_number,party_type,first_name,middle_name,last_name');
  url.searchParams.set('$where', 'filing_number in(' + where + ')');
  url.searchParams.set('$limit', '1000');
  try {
    const response = await fetch(url, { headers: { 'user-agent': 'Agent-Data-Tools-x402/1.0 ' + CONTACT } });
    if (!response.ok) return 'unavailable';
    const rows = await response.json();
    const byFiling = new Map();
    for (const row of rows) {
      if (row.filing_number == null) continue;
      const filing = String(row.filing_number);
      const principal = {
        role: row.party_type == null ? null : String(row.party_type),
        firstName: row.first_name == null ? null : String(row.first_name),
        middleName: row.middle_name == null ? null : String(row.middle_name),
        lastName: row.last_name == null ? null : String(row.last_name)
      };
      const list = byFiling.get(filing) || [];
      const key = JSON.stringify(principal).toUpperCase();
      if (!list.some(x => JSON.stringify(x).toUpperCase() === key)) list.push(principal);
      byFiling.set(filing, list);
    }
    for (const result of results) result.principals = result.filingNumber ? (byFiling.get(result.filingNumber) || []) : [];
    return 'complete';
  } catch {
    return 'unavailable';
  }
}

async function paSearch(query, limit) {
  const starts = await fetchPaCandidates(query, 'starts');
  const rows = starts.length >= limit ? starts : starts.concat(await fetchPaCandidates(query, 'contains'));
  const ranked = rankPa(rows, query, limit);
  const principals = await enrichPrincipals(ranked);
  return { ranked, principals };
}

function registryAddress(entity) {
  const parts = [entity.address1, entity.address2, entity.city, entity.state, entity.zip]
    .filter(value => typeof value === 'string' && value.trim().length > 0);
  return parts.length ? parts.join(', ') : null;
}

function censusAddressIdentity(value) {
  if (typeof value !== 'string') return { streetNumber: null, zip: null };
  const normalized = value.toUpperCase().trim();
  return {
    streetNumber: normalized.match(/^\s*(\d+[A-Z-]?)/)?.[1] || null,
    zip: normalized.match(/\b(\d{5})(?:-\d{4})?\s*$/)?.[1] || null
  };
}

function distanceMiles(a, b) {
  const radians = degrees => degrees * Math.PI / 180;
  const earthRadiusMiles = 3958.7613;
  const dLat = radians(b.latitude - a.latitude);
  const dLon = radians(b.longitude - a.longitude);
  const lat1 = radians(a.latitude);
  const lat2 = radians(b.latitude);
  const h = Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * earthRadiusMiles * Math.asin(Math.min(1, Math.sqrt(h)));
}

function domainNameAligned(domain, vendorName) {
  const vendorCanonical = canonicalBusinessName(vendorName);
  const vendorCompact = vendorCanonical.replace(/[^A-Z0-9]/g, '').toLowerCase();
  const vendorTokens = vendorCanonical
    .toLowerCase()
    .split(' ')
    .map(token => token.replace(/[^a-z0-9]/g, ''))
    .filter(token => token.length >= 3);
  const ignored = new Set(['www', 'api', 'app', 'portal', 'secure', 'vendor', 'vendors']);
  const hostTokens = domain
    .toLowerCase()
    .split('.')
    .slice(0, -1)
    .map(label => label.replace(/[^a-z0-9]/g, ''))
    .filter(label => label.length >= 3 && !ignored.has(label));
  return hostTokens.some(host => {
    if (host === vendorCompact) return true;
    if (host.length >= 4 && vendorCompact.length >= 4 &&
        (host.includes(vendorCompact) || vendorCompact.includes(host))) return true;
    return vendorTokens.some(token =>
      host === token ||
      (host.length >= 4 && token.length >= 4 &&
       (host.includes(token) || token.includes(host)))
    );
  });
}

async function secJson(url) {
  const response = await fetch(url, { headers: { 'User-Agent': 'Agent-Data-Tools-x402/1.0 ' + CONTACT, Accept: 'application/json' } });
  if (!response.ok) throw new Error('SEC returned ' + response.status);
  return await response.json();
}

function normalizeCik(value) {
  const digits = String(value || '').replace(/\D/g, '');
  if (!digits || digits.length > 10) return null;
  return digits.padStart(10, '0');
}

async function resolveTicker(ticker) {
  const map = await secJson('https://www.sec.gov/files/company_tickers.json');
  const wanted = String(ticker || '').trim().toUpperCase();
  for (const value of Object.values(map)) {
    if (String(value.ticker || '').toUpperCase() === wanted) return normalizeCik(value.cik_str);
  }
  return null;
}

async function lookupFilings(ticker, cikRaw, formRaw, limit) {
  let cik = cikRaw ? normalizeCik(cikRaw) : null;
  if (!cik && ticker) cik = await resolveTicker(ticker);
  if (!cik) throw Object.assign(new Error('Company not found; payment was not settled.'), { status: 404 });
  const data = await secJson('https://data.sec.gov/submissions/CIK' + cik + '.json');
  const recent = (data.filings && data.filings.recent) || {};
  const forms = recent.form || [];
  const formFilter = String(formRaw || '').trim().toUpperCase();
  const cikNoZero = String(Number.parseInt(cik, 10));
  const filings = [];
  for (let i = 0; i < forms.length && filings.length < limit; i += 1) {
    const form = String(forms[i] || '');
    if (formFilter && form.toUpperCase() !== formFilter) continue;
    const accessionNumber = String((recent.accessionNumber || [])[i] || '');
    const primaryDocument = String((recent.primaryDocument || [])[i] || '');
    const compact = accessionNumber.replace(/-/g, '');
    filings.push({
      form,
      filingDate: (recent.filingDate || [])[i] || null,
      reportDate: (recent.reportDate || [])[i] || null,
      acceptanceDateTime: (recent.acceptanceDateTime || [])[i] || null,
      accessionNumber,
      primaryDocument,
      primaryDocDescription: (recent.primaryDocDescription || [])[i] || null,
      filingUrl: compact && primaryDocument ? 'https://www.sec.gov/Archives/edgar/data/' + cikNoZero + '/' + compact + '/' + primaryDocument : null
    });
  }
  return {
    company: { name: data.name || null, cik, tickers: data.tickers || [], exchanges: data.exchanges || [], sic: data.sic || null, sicDescription: data.sicDescription || null },
    count: filings.length,
    filings,
    source: 'U.S. Securities and Exchange Commission EDGAR'
  };
}

function firstGeoByKey(geographies, key) {
  const value = geographies[key];
  return Array.isArray(value) && value.length ? value[0] : null;
}

function firstGeoByPattern(geographies, pattern) {
  for (const [key, value] of Object.entries(geographies)) {
    if (pattern.test(key) && Array.isArray(value) && value.length) return value[0];
  }
  return null;
}

async function geocode(address) {
  const url = new URL('https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress');
  url.searchParams.set('address', address);
  url.searchParams.set('benchmark', 'Public_AR_Current');
  url.searchParams.set('vintage', 'Current_Current');
  url.searchParams.set('format', 'json');
  const response = await fetch(url);
  if (!response.ok) throw new Error('Census returned ' + response.status);
  const data = await response.json();
  const match = data.result && data.result.addressMatches && data.result.addressMatches[0];
  if (!match) return { input: address, matched: false, matchedAddress: null, coordinates: null, addressComponents: null, geographies: null, source: 'U.S. Census Bureau Geocoding Services' };
  const geos = match.geographies || {};
  const state = firstGeoByKey(geos, 'States');
  const county = firstGeoByKey(geos, 'Counties');
  const tract = firstGeoByKey(geos, 'Census Tracts');
  const block = firstGeoByKey(geos, 'Census Blocks') || firstGeoByPattern(geos, /^\d{4} Census Blocks$/i);
  const district = firstGeoByPattern(geos, /^(?:\d+(?:st|nd|rd|th) )?Congressional Districts$/i);
  return {
    input: address,
    matched: true,
    matchedAddress: match.matchedAddress || null,
    coordinates: { longitude: match.coordinates && match.coordinates.x != null ? match.coordinates.x : null, latitude: match.coordinates && match.coordinates.y != null ? match.coordinates.y : null },
    addressComponents: match.addressComponents || null,
    geographies: {
      stateFips: state && state.STATE || null,
      countyFips: county && county.COUNTY || null,
      countyGeoid: county && county.GEOID || null,
      tract: tract && tract.TRACT || null,
      tractGeoid: tract && tract.GEOID || null,
      block: block && block.BLOCK || null,
      blockGeoid: block && block.GEOID || null,
      congressionalDistrict: district && (district.CD || district.BASENAME) || null
    },
    source: 'U.S. Census Bureau Geocoding Services'
  };
}

let rdapBootstrapCache = null;

async function rdapBootstrap() {
  if (rdapBootstrapCache && Date.now() - rdapBootstrapCache.at < 3600000) return rdapBootstrapCache.data;
  const response = await fetch(IANA_RDAP_BOOTSTRAP, { headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error('IANA bootstrap returned ' + response.status);
  const data = await response.json();
  rdapBootstrapCache = { at: Date.now(), data };
  return data;
}

function findRdapBase(data, tld) {
  for (const service of data.services || []) {
    if ((service[0] || []).some(x => String(x).toLowerCase() === tld.toLowerCase()) && (service[1] || []).length) return service[1][0];
  }
  return null;
}

function vcardName(entity) {
  const card = entity && entity.vcardArray;
  if (!Array.isArray(card) || !Array.isArray(card[1])) return null;
  for (const item of card[1]) if (Array.isArray(item) && item[0] === 'fn') return String(item[3] || '') || null;
  return null;
}

function eventMap(events) {
  const out = {};
  if (!Array.isArray(events)) return out;
  for (const item of events) {
    const action = String(item.eventAction || '').toLowerCase().replace(/[^a-z0-9]+(.)/g, (_m, c) => c.toUpperCase());
    const date = String(item.eventDate || '');
    if (action && date && !out[action]) out[action] = date;
  }
  return out;
}

function normalizeDomain(raw) {
  let value = String(raw || '').trim().toLowerCase();
  if (value.endsWith('.')) value = value.slice(0, -1);
  if (value.length < 3 || value.length > 253 || !/^[a-z0-9.-]+$/.test(value)) return null;
  const labels = value.split('.');
  if (labels.length < 2 || labels.some(x => !x || x.length > 63 || x.startsWith('-') || x.endsWith('-'))) return null;
  return value;
}

async function lookupDomain(domain) {
  const tld = domain.split('.').pop() || '';
  const bootstrap = await rdapBootstrap();
  const base = findRdapBase(bootstrap, tld);
  if (!base) return { domain, registered: null, error: 'no_rdap_bootstrap_service', source: 'IANA RDAP Bootstrap Service Registry' };
  const url = base.replace(/\/+$/, '') + '/domain/' + encodeURIComponent(domain);
  const response = await fetch(url, { headers: { Accept: 'application/rdap+json, application/json', 'User-Agent': 'Agent-Data-Tools-x402/1.0 ' + CONTACT }, redirect: 'follow' });
  if (response.status === 404) return { domain, registered: false, authoritativeRdap: base, source: 'Authoritative RDAP server discovered via IANA bootstrap' };
  if (!response.ok) throw new Error('RDAP returned ' + response.status);
  const data = await response.json();
  const registrarEntity = Array.isArray(data.entities) ? data.entities.find(e => Array.isArray(e.roles) && e.roles.map(r => String(r).toLowerCase()).includes('registrar')) : undefined;
  const nameservers = Array.isArray(data.nameservers) ? data.nameservers.map(ns => String(ns.ldhName || ns.unicodeName || '')).filter(Boolean) : [];
  return {
    domain,
    registered: true,
    handle: data.handle || null,
    unicodeName: data.unicodeName || null,
    status: Array.isArray(data.status) ? data.status : [],
    registrar: registrarEntity ? { name: vcardName(registrarEntity), handle: registrarEntity.handle || null } : null,
    events: eventMap(data.events),
    nameservers,
    secureDns: data.secureDNS ? { delegationSigned: data.secureDNS.delegationSigned ?? null } : null,
    authoritativeRdap: base,
    source: 'Authoritative RDAP server discovered via IANA bootstrap'
  };
}

async function latestTreasuryRates(security) {
  const url = new URL(TREASURY_API);
  url.searchParams.set('fields', 'record_date,security_type_desc,security_desc,avg_interest_rate_amt');
  url.searchParams.set('sort', '-record_date');
  url.searchParams.set('page[size]', '100');
  const response = await fetch(url, { headers: { Accept: 'application/json', 'User-Agent': 'Agent-Data-Tools-x402/1.0 ' + CONTACT } });
  if (!response.ok) throw new Error('Treasury returned ' + response.status);
  const payload = await response.json();
  const rows = payload.data || [];
  if (!rows.length) throw new Error('Treasury returned no data');
  const recordDate = String(rows[0].record_date || '');
  const needle = String(security || '').trim().toLowerCase();
  const latest = rows.filter(row => String(row.record_date || '') === recordDate);
  const filtered = needle ? latest.filter(row => String(row.security_desc || '').toLowerCase().includes(needle)) : latest;
  return {
    recordDate,
    count: filtered.length,
    rates: filtered.map(row => ({ securityDescription: row.security_desc || null, securityType: row.security_type_desc || null, averageInterestRatePercent: row.avg_interest_rate_amt === '' || row.avg_interest_rate_amt == null ? null : Number(row.avg_interest_rate_amt) })),
    source: 'U.S. Treasury Fiscal Data — Average Interest Rates on U.S. Treasury Securities',
    frequency: 'monthly'
  };
}

function parseCsv(input) {
  const rows = [];
  let row = [];
  let field = '';
  let quoted = false;
  for (let i = 0; i < input.length; i += 1) {
    const ch = input[i];
    if (quoted) {
      if (ch === '"' && input[i + 1] === '"') { field += '"'; i += 1; }
      else if (ch === '"') quoted = false;
      else field += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ',') { row.push(field); field = ''; }
    else if (ch === '\n') { row.push(field.replace(/\r$/, '')); if (row.some(v => v.length)) rows.push(row); row = []; field = ''; }
    else field += ch;
  }
  if (field.length || row.length) { row.push(field.replace(/\r$/, '')); if (row.some(v => v.length)) rows.push(row); }
  return rows;
}

function clean(value) {
  if (!value || value === '-0-') return null;
  return String(value).trim() || null;
}

let ofacCache = null;

async function ofacFile(name) {
  const response = await fetch(OFAC_BASE + '/' + name, { headers: { 'User-Agent': 'Agent-Data-Tools-x402/1.0 ' + CONTACT, Accept: 'text/csv,*/*' }, redirect: 'follow' });
  if (!response.ok) throw new Error('OFAC returned ' + response.status + ' for ' + name);
  return await response.text();
}

async function loadOfacEntries() {
  if (ofacCache && Date.now() - ofacCache.at < 600000) return ofacCache.entries;
  const [sdnText, altText] = await Promise.all([ofacFile('SDN.CSV'), ofacFile('ALT.CSV')]);
  const map = new Map();
  for (const cols of parseCsv(sdnText)) {
    const uid = String(cols[0] || '').trim();
    const name = String(cols[1] || '').trim();
    if (!uid || !name) continue;
    map.set(uid, { uid, name, type: clean(cols[2]), program: clean(cols[3]), title: clean(cols[4]), remarks: clean(cols[11]), aliases: [] });
  }
  for (const cols of parseCsv(altText)) {
    const uid = String(cols[0] || '').trim();
    const altName = String(cols[3] || '').trim();
    const entry = map.get(uid);
    if (entry && altName) entry.aliases.push({ type: clean(cols[2]), name: altName, remarks: clean(cols[4]) });
  }
  const entries = [...map.values()];
  ofacCache = { at: Date.now(), entries };
  return entries;
}

function normalizeName(value) {
  return String(value || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toUpperCase().replace(/[^A-Z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim();
}

function sortedTokens(value) {
  return normalizeName(value).split(' ').filter(Boolean).sort().join(' ');
}

function levenshtein(a, b) {
  if (a === b) return 0;
  if (!a.length) return b.length;
  if (!b.length) return a.length;
  const prev = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i += 1) {
    const next = [i];
    for (let j = 1; j <= b.length; j += 1) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      next[j] = Math.min(next[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost);
    }
    for (let j = 0; j < next.length; j += 1) prev[j] = next[j];
  }
  return prev[b.length];
}

function jaccardTokens(a, b) {
  const aa = new Set(normalizeName(a).split(' ').filter(Boolean));
  const bb = new Set(normalizeName(b).split(' ').filter(Boolean));
  if (!aa.size || !bb.size) return 0;
  let shared = 0;
  for (const token of aa) if (bb.has(token)) shared += 1;
  return shared / new Set([...aa, ...bb]).size;
}

function scoreName(query, candidate) {
  const q = normalizeName(query);
  const c = normalizeName(candidate);
  if (!q || !c) return 0;
  if (q === c) return 100;
  if (sortedTokens(q) === sortedTokens(c)) return 99;
  const contains = q.length >= 5 && c.length >= 5 && (q.includes(c) || c.includes(q)) ? 94 : 0;
  const maxLen = Math.max(q.length, c.length);
  const edit = maxLen ? (1 - levenshtein(q, c) / maxLen) * 100 : 0;
  const qs = sortedTokens(q);
  const cs = sortedTokens(c);
  const editSorted = (1 - levenshtein(qs, cs) / Math.max(qs.length, cs.length, 1)) * 100;
  return Math.max(contains, edit, editSorted, jaccardTokens(q, c) * 100);
}

async function screenOfac(name, limit, minScore) {
  const entries = await loadOfacEntries();
  const candidates = [];
  for (const entry of entries) {
    let bestScore = scoreName(name, entry.name);
    let matchedOn = 'primary';
    let matchedName = entry.name;
    for (const alias of entry.aliases) {
      const score = scoreName(name, alias.name);
      if (score > bestScore) { bestScore = score; matchedOn = 'alias'; matchedName = alias.name; }
    }
    if (bestScore >= minScore) candidates.push({ uid: entry.uid, primaryName: entry.name, type: entry.type, program: entry.program, title: entry.title, remarks: entry.remarks, matchedOn, matchedName, score: Math.round(bestScore) });
  }
  candidates.sort((a, b) => b.score - a.score || a.primaryName.localeCompare(b.primaryName));
  return {
    query: name,
    minScore,
    count: Math.min(candidates.length, limit),
    totalCandidatesAboveThreshold: candidates.length,
    candidates: candidates.slice(0, limit),
    source: 'U.S. Treasury OFAC Specially Designated Nationals (SDN) List',
    sourceFiles: ['SDN.CSV', 'ALT.CSV'],
    reviewRequired: true,
    limitations: ['Candidate-name screening only; a match is not a legal determination.', 'A no-match is not a sanctions clearance.', 'This service does not implement OFAC 50 Percent Rule ownership analysis.', 'Review identifiers, addresses, dates of birth, program tags, and other OFAC data before acting.']
  };
}

async function vendorGate(name, address, domain) {
  const q = normalizeSearchTerm(name);
  const normalizedDomain = normalizeDomain(domain);
  if (address.length < 6 || address.length > 240) {
    throw Object.assign(new Error('address must contain 6 to 240 characters.'), { status: 400 });
  }
  if (!normalizedDomain) {
    throw Object.assign(new Error('domain must be a valid ASCII or punycode domain.'), { status: 400 });
  }

  const pa = await paSearch(q, 3);
  const registryMatch = pa.ranked[0] || null;
  const registryNameScore = registryMatch?.businessName
    ? matchScore(registryMatch.businessName, q)
    : null;
  const strongCandidates = pa.ranked.filter(candidate =>
    candidate.businessName ? matchScore(candidate.businessName, q) <= 1 : false
  );
  const registryAmbiguous = strongCandidates.length > 1;
  const registryStrong = registryNameScore != null && registryNameScore <= 1 && !registryAmbiguous;
  const registeredAddress = registryMatch ? registryAddress(registryMatch) : null;
  const registryEvidenceComplete = Boolean(
    registryMatch &&
    registryMatch.businessName &&
    registryMatch.filingNumber &&
    registryMatch.registrationType &&
    registeredAddress
  );

  const [submittedCensus, registryCensus, ofac, rdap] = await Promise.all([
    geocode(address),
    registeredAddress ? geocode(registeredAddress) : Promise.resolve(null),
    screenOfac(q, 3, 90),
    lookupDomain(normalizedDomain)
  ]);

  const submittedCoordinates = submittedCensus?.coordinates &&
    Number.isFinite(Number(submittedCensus.coordinates.latitude)) &&
    Number.isFinite(Number(submittedCensus.coordinates.longitude))
      ? {
          latitude: Number(submittedCensus.coordinates.latitude),
          longitude: Number(submittedCensus.coordinates.longitude)
        }
      : null;
  const registryCoordinates = registryCensus?.coordinates &&
    Number.isFinite(Number(registryCensus.coordinates.latitude)) &&
    Number.isFinite(Number(registryCensus.coordinates.longitude))
      ? {
          latitude: Number(registryCensus.coordinates.latitude),
          longitude: Number(registryCensus.coordinates.longitude)
        }
      : null;

  const submittedIdentity = censusAddressIdentity(submittedCensus?.matchedAddress);
  const registryIdentity = censusAddressIdentity(registryCensus?.matchedAddress);
  const sameStreetNumber = submittedIdentity.streetNumber != null &&
    submittedIdentity.streetNumber === registryIdentity.streetNumber;
  const sameZip = submittedIdentity.zip != null &&
    submittedIdentity.zip === registryIdentity.zip;
  const addressDistanceMiles = submittedCoordinates && registryCoordinates
    ? Number(distanceMiles(submittedCoordinates, registryCoordinates).toFixed(3))
    : null;
  const addressConsistent = Boolean(
    submittedCensus?.matched === true &&
    registryCensus?.matched === true &&
    sameStreetNumber &&
    sameZip &&
    addressDistanceMiles != null &&
    addressDistanceMiles <= 0.25
  );

  const domainRegistered = rdap.registered === true &&
    typeof rdap.authoritativeRdap === 'string' &&
    rdap.authoritativeRdap.length > 0;
  const domainAligned = domainRegistered && domainNameAligned(normalizedDomain, q);

  const reviewTriggers = [];
  const addTrigger = (code, detail) => reviewTriggers.push({ code, detail });

  if (!registryMatch) {
    addTrigger('pa_registry_match_not_found', 'No Pennsylvania registry candidate was found for the supplied vendor name.');
  } else if (registryAmbiguous) {
    addTrigger('pa_registry_name_ambiguous', 'Multiple Pennsylvania registry records are strong matches for the supplied vendor name.');
  } else if (!registryStrong) {
    addTrigger('pa_registry_name_needs_review', 'The best Pennsylvania registry name match was not strong enough for automatic continuation.');
  } else if (!registryEvidenceComplete) {
    addTrigger('pa_registry_evidence_incomplete', 'The selected registry record is missing a core identity field or usable registered address.');
  }

  if (submittedCensus?.matched !== true) {
    addTrigger('provided_address_not_geocoded', 'The supplied vendor address did not produce a Census match.');
  } else if (registryMatch && !registeredAddress) {
    addTrigger('registry_address_missing', 'The matched registry record did not provide a usable registered address.');
  } else if (registeredAddress && registryCensus?.matched !== true) {
    addTrigger('registry_address_not_geocoded', 'The Pennsylvania registry address did not produce a Census match.');
  } else if (registeredAddress && !addressConsistent) {
    addTrigger('registered_address_differs', 'The supplied address does not closely align with the Pennsylvania registry address under the configured street-number, ZIP, and distance checks.');
  }

  if (ofac.candidates.length > 0) {
    addTrigger('ofac_name_candidate_present', 'The OFAC SDN name screen returned at least one candidate at or above the 90 review threshold.');
  }

  if (!domainRegistered) {
    addTrigger('domain_registration_not_confirmed', 'Authoritative RDAP did not confirm that the supplied domain is currently registered.');
  } else if (!domainAligned) {
    addTrigger('domain_name_not_aligned', 'The registered domain hostname does not plausibly align with the submitted vendor name.');
  }

  const decision = reviewTriggers.length === 0 ? 'proceed' : 'human_review';
  return {
    decision,
    agentAction: decision === 'proceed'
      ? 'continue_vendor_intake'
      : 'pause_and_request_human_review',
    reviewTriggers,
    checkedAt: new Date().toISOString(),
    input: { name: q, address, domain: normalizedDomain },
    policy: {
      registryNameMatch: 'exactly one canonical exact or strong-prefix legal-entity candidate',
      registryEvidenceContract: 'business name, filing number, registration type, and usable registered address',
      addressMatch: 'Census-normalized street number and ZIP must match and coordinates must be within 0.25 miles',
      addressMaxDistanceMiles: 0.25,
      ofacReviewThreshold: 90,
      domainMustBeRegistered: true,
      domainNameAlignment: 'registered hostname labels must plausibly align with vendor name'
    },
    evidence: {
      registry: {
        found: Boolean(registryMatch),
        complete: registryEvidenceComplete,
        candidateCount: pa.ranked.length,
        strongCandidateCount: strongCandidates.length,
        ambiguous: registryAmbiguous,
        matchScore: registryNameScore,
        match: registryMatch,
        source: 'Pennsylvania Department of State via data.pa.gov'
      },
      address: {
        providedMatched: submittedCensus?.matched === true,
        registryMatched: registryCensus?.matched === true,
        sameStreetNumber,
        sameZip,
        distanceMiles: addressDistanceMiles,
        consistent: addressConsistent,
        provided: submittedCensus,
        registry: registryCensus
      },
      ofac: {
        reviewThreshold: 90,
        candidateCount: ofac.totalCandidatesAboveThreshold,
        candidates: ofac.candidates,
        source: ofac.source
      },
      domain: {
        requestedDomain: normalizedDomain,
        returnedDomain: rdap.domain || null,
        registered: rdap.registered === true,
        nameAligned: domainAligned,
        authoritativeRdap: rdap.authoritativeRdap || null,
        registrar: rdap.registrar || null,
        events: rdap.events || null,
        source: rdap.source || null
      }
    },
    limitations: [
      'proceed only means these configured review triggers were not hit.',
      'This is not legal, sanctions, fraud, credit, or compliance approval.',
      'OFAC screening is name-based and does not implement the 50 Percent Rule.',
      'Registry, address, and RDAP evidence do not prove ownership or control.'
    ]
  };
}

function queryNumber(url, name, fallback, min, max) {
  const raw = url.searchParams.get(name);
  if (raw == null || raw === '') return fallback;
  if (!/^\d+$/.test(raw)) throw Object.assign(new Error(name + ' must be an integer.'), { status: 400 });
  const n = Number(raw);
  if (!Number.isSafeInteger(n) || n < min || n > max) throw Object.assign(new Error(name + ' must be between ' + min + ' and ' + max + '.'), { status: 400 });
  return n;
}

function genericObjectSchema() {
  return { type: 'object', additionalProperties: true };
}

function openApi(req) {
  const base = baseUrl(req);
  function paidOp(cfg, operationId, summary, params) {
    return {
      get: {
        operationId,
        summary,
        tags: cfg.tags,
        security: [],
        'x-payment-info': { price: { mode: 'fixed', currency: 'USD', amount: cfg.usd }, protocols: [{ x402: {} }] },
        parameters: params,
        responses: {
          '200': { description: 'Paid result', content: { 'application/json': { schema: genericObjectSchema() } } },
          '400': { description: 'Invalid input after payment challenge is satisfied' },
          '402': { description: 'Payment Required' },
          '502': { description: 'Authoritative upstream unavailable; payment is not settled' },
          '503': { description: 'Payment facilitator unavailable' }
        }
      }
    };
  }
  return {
    openapi: '3.1.0',
    info: {
      title: 'Agent Data Tools x402',
      version: '1.0.0',
      description: 'Eight pay-per-call x402 endpoints backed by authoritative public data, including a composed Pennsylvania vendor-intake decision gate.',
      contact: { email: CONTACT },
      'x-guidance': 'Use /api/vendor-intake-gate when an agent needs a bounded proceed or human_review workflow decision with evidence. Use the lower-cost source endpoints for direct facts. Prices are $0.001-$0.020 USDC on Base; unpaid calls return x402 v2 HTTP 402 challenges.'
    },
    servers: [{ url: base }],
    paths: {
      '/api/pa-entity-one': paidOp(ROUTES['/api/pa-entity-one'], 'paEntityBestMatch', 'Best Pennsylvania entity match', [{ name: 'q', in: 'query', required: true, schema: { type: 'string', minLength: 2 }, example: 'OpenAI' }]),
      '/api/pa-business': paidOp(ROUTES['/api/pa-business'], 'paBusinessSearch', 'Search Pennsylvania business registry', [{ name: 'q', in: 'query', required: true, schema: { type: 'string', minLength: 2 }, example: 'OpenAI' }, { name: 'limit', in: 'query', required: false, schema: { type: 'integer', minimum: 1, maximum: 25, default: 10 } }]),
      '/api/vendor-intake-gate': paidOp(ROUTES['/api/vendor-intake-gate'], 'checkPennsylvaniaVendorIntakeGate', 'Pennsylvania vendor-intake decision gate', [{ name: 'name', in: 'query', required: true, schema: { type: 'string', minLength: 2 }, example: 'OpenAI OpCo' }, { name: 'address', in: 'query', required: true, schema: { type: 'string', minLength: 6 }, example: '600 North Second Street, Suite 401, Harrisburg, PA 17101' }, { name: 'domain', in: 'query', required: true, schema: { type: 'string', minLength: 3 }, example: 'openai.com' }]),
      '/api/sec-filings': paidOp(ROUTES['/api/sec-filings'], 'secRecentFilings', 'Recent SEC EDGAR filings', [{ name: 'ticker', in: 'query', schema: { type: 'string' }, example: 'AAPL' }, { name: 'cik', in: 'query', schema: { type: 'string' } }, { name: 'form', in: 'query', schema: { type: 'string' }, example: '10-K' }, { name: 'limit', in: 'query', schema: { type: 'integer', minimum: 1, maximum: 25, default: 10 } }]),
      '/api/us-address-geocode': paidOp(ROUTES['/api/us-address-geocode'], 'censusAddressGeocode', 'Census address geocoder', [{ name: 'address', in: 'query', required: true, schema: { type: 'string', minLength: 6 }, example: '4600 Silver Hill Rd, Washington, DC 20233' }]),
      '/api/ofac-sdn-screen': paidOp(ROUTES['/api/ofac-sdn-screen'], 'ofacSdnScreen', 'OFAC SDN name screen', [{ name: 'name', in: 'query', required: true, schema: { type: 'string', minLength: 2 }, example: 'VLADIMIR PUTIN' }, { name: 'limit', in: 'query', schema: { type: 'integer', minimum: 1, maximum: 10, default: 5 } }, { name: 'minScore', in: 'query', schema: { type: 'integer', minimum: 70, maximum: 100, default: 85 } }]),
      '/api/domain-rdap': paidOp(ROUTES['/api/domain-rdap'], 'domainRdap', 'Domain RDAP lookup', [{ name: 'domain', in: 'query', required: true, schema: { type: 'string', minLength: 3 }, example: 'example.com' }]),
      '/api/treasury-average-rates': paidOp(ROUTES['/api/treasury-average-rates'], 'treasuryAverageRates', 'Treasury average interest rates', [{ name: 'security', in: 'query', schema: { type: 'string', maxLength: 100 }, example: 'Total Marketable' }])
    }
  };
}

function discovery(req) {
  const base = baseUrl(req);
  return {
    x402Version: 2,
    name: 'Agent Data Tools x402',
    description: 'Eight same-origin pay-per-call agent tools backed by authoritative public data, including a composed Pennsylvania vendor-intake decision gate.',
    network: NETWORK,
    asset: 'USDC',
    assetContract: USDC,
    payTo: PAY_TO,
    openapi: base + '/openapi.json',
    agentManifest: base + '/.well-known/agent.json',
    resources: Object.entries(ROUTES).map(([path, cfg]) => ({
      resource: base + path,
      method: 'GET',
      price: cfg.price,
      serviceName: cfg.serviceName,
      description: cfg.description,
      tags: cfg.tags,
      iconUrl: base + '/icon.svg',
      accepts: [requirements(cfg)],
      extensions: bazaarExtension(cfg),
      inputExample: cfg.inputExample,
      inputSchema: { type: 'object', additionalProperties: true }
    }))
  };
}

function agentDocument(req) {
  const base = baseUrl(req);
  return {
    version: '1.3',
    origin: new URL(base).host,
    display_name: 'Agent Data Tools x402',
    description: 'Eight same-origin pay-per-call x402 tools for Pennsylvania entity and vendor intake, SEC filings, Census geocoding, OFAC name screening, RDAP, and Treasury rates.',
    payout_address: PAY_TO,
    payments: {
      x402: {
        networks: [{
          network: 'base',
          caip2: NETWORK,
          asset: 'USDC',
          contract: USDC
        }]
      }
    },
    intents: Object.entries(ROUTES).map(([path, cfg]) => ({
      name: path.slice(5).replaceAll('-', '_'),
      description: cfg.description,
      endpoint: path,
      method: 'GET',
      tags: cfg.tags,
      input_example: cfg.inputExample,
      price: { amount: Number(cfg.usd), currency: 'USDC' }
    }))
  };
}

function iconSvg() {
  return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128"><rect width="128" height="128" rx="28" fill="#111827"/><path d="M24 64h80" stroke="#fff" stroke-width="10" stroke-linecap="round"/><path d="M64 24v80" stroke="#fff" stroke-width="10" stroke-linecap="round"/><text x="64" y="73" text-anchor="middle" font-family="system-ui,sans-serif" font-size="22" font-weight="700" fill="#111827">402</text></svg>';
}

async function handlePaid(req, res, url) {
  const path = url.pathname;
  if (path === '/api/pa-entity-one') return servePaid(req, res, path, async () => {
    const q = normalizeSearchTerm(url.searchParams.get('q'));
    const result = await paSearch(q, 1);
    return { query: q, found: result.ranked.length > 0, match: result.ranked[0] || null, enrichment: { principals: result.principals }, source: 'Pennsylvania Department of State via data.pa.gov' };
  });
  if (path === '/api/pa-business') return servePaid(req, res, path, async () => {
    const q = normalizeSearchTerm(url.searchParams.get('q'));
    const limit = queryNumber(url, 'limit', 10, 1, 25);
    const result = await paSearch(q, limit);
    return { query: q, count: result.ranked.length, results: result.ranked, enrichment: { principals: result.principals }, source: 'Pennsylvania Department of State via data.pa.gov' };
  });
  if (path === '/api/vendor-intake-gate') return servePaid(req, res, path, async () => {
    const name = String(url.searchParams.get('name') || '').trim();
    const address = String(url.searchParams.get('address') || '').trim();
    const domain = String(url.searchParams.get('domain') || '').trim();
    return await vendorGate(name, address, domain);
  });
  if (path === '/api/sec-filings') return servePaid(req, res, path, async () => {
    const ticker = String(url.searchParams.get('ticker') || '').trim();
    const cik = String(url.searchParams.get('cik') || '').trim();
    const form = String(url.searchParams.get('form') || '').trim();
    if (!ticker && !cik) throw Object.assign(new Error('Provide ticker or cik.'), { status: 400 });
    if (ticker.length > 12 || form.length > 20 || (cik && !normalizeCik(cik))) throw Object.assign(new Error('Invalid SEC query.'), { status: 400 });
    return await lookupFilings(ticker, cik, form, queryNumber(url, 'limit', 10, 1, 25));
  });
  if (path === '/api/us-address-geocode') return servePaid(req, res, path, async () => {
    const address = String(url.searchParams.get('address') || '').trim();
    if (address.length < 6 || address.length > 240) throw Object.assign(new Error('address must contain 6 to 240 characters.'), { status: 400 });
    return await geocode(address);
  });
  if (path === '/api/ofac-sdn-screen') return servePaid(req, res, path, async () => {
    const name = String(url.searchParams.get('name') || '').trim();
    if (name.length < 2 || name.length > 160) throw Object.assign(new Error('name must contain 2 to 160 characters.'), { status: 400 });
    return await screenOfac(name, queryNumber(url, 'limit', 5, 1, 10), queryNumber(url, 'minScore', 85, 70, 100));
  });
  if (path === '/api/domain-rdap') return servePaid(req, res, path, async () => {
    const domain = normalizeDomain(url.searchParams.get('domain'));
    if (!domain) throw Object.assign(new Error('domain must be a valid ASCII or punycode domain name.'), { status: 400 });
    return await lookupDomain(domain);
  });
  if (path === '/api/treasury-average-rates') return servePaid(req, res, path, async () => {
    const security = String(url.searchParams.get('security') || '').trim();
    if (security.length > 100) throw Object.assign(new Error('security filter must be 100 characters or fewer.'), { status: 400 });
    return await latestTreasuryRates(security);
  });
}

const server = http.createServer(async (req, res) => {
  if (req.method === 'OPTIONS') {
    res.writeHead(204, { ...CORS, 'cache-control': 'public, max-age=86400' });
    return res.end();
  }
  if (req.method !== 'GET') return json(res, 405, { error: 'method_not_allowed' });
  const url = new URL(req.url || '/', baseUrl(req));
  try {
    if (ROUTES[url.pathname]) return await handlePaid(req, res, url);
    if (url.pathname === '/health' || url.pathname === '/healthz') return json(res, 200, { ok: true, service: 'Agent Data Tools x402', routes: Object.keys(ROUTES).length }, { 'cache-control': 'no-store' });
    if (url.pathname === '/openapi.json') return json(res, 200, openApi(req), { 'cache-control': 'public, max-age=300' });
    if (url.pathname === '/.well-known/x402') return json(res, 200, discovery(req), { 'cache-control': 'public, max-age=300' });
    if (url.pathname === '/.well-known/agent.json') return json(res, 200, agentDocument(req), { 'cache-control': 'public, max-age=300' });
    if (url.pathname === '/icon.svg') return text(res, 200, iconSvg(), 'image/svg+xml; charset=utf-8', { 'cache-control': 'public, max-age=86400' });
    if (url.pathname === '/llms.txt') return text(res, 200, '# Agent Data Tools x402\n\nEight paid endpoints on one origin. Prices: $0.001-$0.020 USDC on Base.\nOpenAPI: /openapi.json\nx402 discovery: /.well-known/x402\nAgent manifest: /.well-known/agent.json\nSkill guide: /skill.md\n\nTools: PA Vendor Intake Gate, PA Entity Best Match, PA Registry Search, SEC Recent Filings, Census Address Geocoder, OFAC SDN Name Screen, Domain RDAP, Treasury Average Interest Rates.\n', 'text/plain; charset=utf-8', { 'cache-control': 'public, max-age=300' });
    if (url.pathname === '/skill.md') return text(res, 200, '# Agent Data Tools x402\n\n## Use\nUse /api/vendor-intake-gate for a bounded Pennsylvania vendor intake decision with evidence. Use the lower-cost routes for direct source facts. Unpaid calls return HTTP 402 with PAYMENT-REQUIRED; after payment, retry with PAYMENT-SIGNATURE.\n\n## Prices\n- PA best match: $0.001\n- PA registry search: $0.005\n- Vendor intake gate: $0.020\n- SEC, Census, OFAC, RDAP, Treasury: $0.005 each\n\n## Limits\nThe vendor gate is a workflow signal, not legal/compliance approval. OFAC results are review candidates only and do not implement the 50 Percent Rule. Registry/address/RDAP facts do not prove ownership or control.\n', 'text/markdown; charset=utf-8', { 'cache-control': 'public, max-age=300' });
    if (url.pathname === '/') {
      const body = '<!doctype html><html><head><meta charset="utf-8"><title>Agent Data Tools x402</title><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><main style="font:16px system-ui;max-width:760px;margin:48px auto;padding:0 18px"><h1>Agent Data Tools x402</h1><p>Eight pay-per-call agent tools backed by authoritative public data.</p><ul><li>PA Entity Best Match — $0.001</li><li>PA Registry Search — $0.005</li><li>PA Vendor Intake Gate — $0.020</li><li>SEC Recent Filings — $0.005</li><li>Census Address Geocoder — $0.005</li><li>OFAC SDN Name Screen — $0.005</li><li>Domain RDAP — $0.005</li><li>Treasury Average Rates — $0.005</li></ul><p><a href="/openapi.json">OpenAPI</a> · <a href="/.well-known/x402">x402 discovery</a> · <a href="/.well-known/agent.json">agent manifest</a> · <a href="/skill.md">skill guide</a></p></main></body></html>';
      return text(res, 200, body, 'text/html; charset=utf-8', { 'cache-control': 'public, max-age=300' });
    }
    return json(res, 404, { error: 'not_found' });
  } catch (error) {
    return json(res, Number(error && error.status) || 500, { error: error instanceof Error ? error.message : 'internal_error' }, { 'cache-control': 'no-store' });
  }
});

server.listen(PORT, '0.0.0.0', () => {
  console.log('Agent Data Tools x402 listening on port ' + PORT);
});
