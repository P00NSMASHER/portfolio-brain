const PA_SOURCE = 'https://data.pa.gov/resource/xvd7-5r2c.json';
const TREASURY_API = 'https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/avg_interest_rates';
const OFAC_BASE = 'https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports';
const IANA_RDAP_BOOTSTRAP = 'https://data.iana.org/rdap/dns.json';
const SOURCE_TIMEOUT_MS = 12000;
const OFAC_CACHE_MS = 10 * 60 * 1000;
const RDAP_CACHE_MS = 60 * 60 * 1000;

function upstreamError(message, status = 502) {
  const e = new Error(message);
  e.status = status;
  return e;
}

async function fetchWithTimeout(url, init = {}, timeoutMs = SOURCE_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

function canonicalBusinessName(value) {
  let text = String(value ?? '')
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  const suffix = /\s+(?:L\s+L\s+C|LLC|INCORPORATED|INC|CORPORATION|CORP|COMPANY|CO|LIMITED|LTD|L\s+P|LP|L\s+L\s+P|LLP|P\s+C|PC)$/;
  let previous = '';
  while (text !== previous) {
    previous = text;
    text = text.replace(suffix, '').trim();
  }
  return text;
}

function paMatchScore(name, query) {
  const candidate = canonicalBusinessName(name);
  const wanted = canonicalBusinessName(query);
  if (candidate === wanted) return 0;
  if (candidate.startsWith(wanted + ' ')) return 1;
  if ((' ' + candidate + ' ').includes(' ' + wanted + ' ')) return 2;
  if (candidate.replaceAll(' ', '').includes(wanted.replaceAll(' ', ''))) return 3;
  return 4;
}

export function normalizeSearchTerm(raw) {
  const trimmed = String(raw ?? '').trim();
  if (trimmed.length > 120) throw new Error('query must be 120 characters or fewer.');
  const cleaned = trimmed
    .replace(/[%_]/g, ' ')
    .replace(/[\u0000-\u001F\u007F]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  const significant = [...cleaned].filter(ch => /[\p{L}\p{N}]/u.test(ch));
  if (significant.length < 2) throw new Error('query must contain at least two letters or numbers.');
  return cleaned;
}

export function parseLimit(raw, fallback = 10, max = 25) {
  if (raw === undefined || raw === null || raw === '') return fallback;
  if (!/^\d+$/.test(String(raw))) throw new Error('limit must be an integer.');
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < 1 || value > max) {
    throw new Error('limit must be between 1 and ' + max + '.');
  }
  return value;
}

function entityProjection() {
  return [
    'business_name',
    'filing_number',
    'address_line1',
    'address_line2',
    'city',
    'state',
    'zip',
    'typeofbusinessregistration',
    'creationdate',
    'shortcountyname',
    'county_code',
  ].join(',');
}

function normalizeCreationDate(value) {
  if (value == null) return null;
  const raw = String(value);
  if (raw.startsWith('1753-01-01')) return null;
  return raw.slice(0, 10);
}

function mapEntity(row) {
  return {
    businessName: row.business_name == null ? null : String(row.business_name),
    filingNumber: row.filing_number == null ? null : String(row.filing_number),
    registrationType: row.typeofbusinessregistration == null ? null : String(row.typeofbusinessregistration),
    creationDate: normalizeCreationDate(row.creationdate),
    address1: row.address_line1 == null ? null : String(row.address_line1),
    address2: row.address_line2 == null ? null : String(row.address_line2),
    city: row.city == null ? null : String(row.city),
    state: row.state == null ? null : String(row.state),
    zip: row.zip == null ? null : String(row.zip),
    county: row.shortcountyname == null ? null : String(row.shortcountyname),
    countyCode: row.county_code == null ? null : String(row.county_code),
    principals: [],
  };
}

async function fetchPaCandidates(query, mode, limit = 100) {
  const escaped = query.toUpperCase().replaceAll("'", "''");
  const pattern = mode === 'starts' ? escaped + '%' : '%' + escaped + '%';
  const url = new URL(PA_SOURCE);
  url.searchParams.set('$select', 'distinct ' + entityProjection());
  url.searchParams.set('$where', "upper(business_name) like '" + pattern + "'");
  url.searchParams.set('$limit', String(limit));
  const response = await fetchWithTimeout(url.toString(), {
    headers: { 'user-agent': 'Agent-Data-Tools-x402/1.0' },
  });
  if (!response.ok) throw upstreamError('Pennsylvania Open Data returned ' + response.status + '.');
  const rows = await response.json();
  return rows.map(mapEntity);
}

function dedupeAndRank(rows, query, limit) {
  const unique = new Map();
  for (const row of rows) {
    const key = row.filingNumber ?? [row.businessName, row.address1, row.city].join('|');
    if (!unique.has(key)) unique.set(key, row);
  }
  return [...unique.values()]
    .sort((a, b) => {
      const aName = a.businessName ?? '';
      const bName = b.businessName ?? '';
      const score = paMatchScore(aName, query) - paMatchScore(bName, query);
      if (score) return score;
      if (aName.length !== bName.length) return aName.length - bName.length;
      return aName.localeCompare(bName);
    })
    .slice(0, limit);
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
    const response = await fetchWithTimeout(url.toString(), {
      headers: { 'user-agent': 'Agent-Data-Tools-x402/1.0' },
    });
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
        lastName: row.last_name == null ? null : String(row.last_name),
      };
      const list = byFiling.get(filing) ?? [];
      const key = JSON.stringify(principal).toUpperCase();
      if (!list.some(x => JSON.stringify(x).toUpperCase() === key)) list.push(principal);
      byFiling.set(filing, list);
    }
    for (const result of results) {
      result.principals = result.filingNumber ? (byFiling.get(result.filingNumber) ?? []) : [];
    }
    return 'complete';
  } catch {
    return 'unavailable';
  }
}

export async function paSearch(query, limit = 10, enriched = true) {
  const starts = await fetchPaCandidates(query, 'starts');
  let ranked = dedupeAndRank(starts, query, limit);
  if (ranked.length < limit) {
    const contains = await fetchPaCandidates(query, 'contains');
    ranked = dedupeAndRank([...starts, ...contains], query, limit);
  }
  const principals = enriched ? await enrichPrincipals(ranked) : 'unavailable';
  return { results: ranked, principals };
}

export async function secFilings({ ticker = '', cik = '', form = '', limit = 10 }) {
  const normalizeCik = value => {
    const digits = String(value).replace(/\D/g, '');
    if (!digits || digits.length > 10) return null;
    return digits.padStart(10, '0');
  };
  async function secJson(url) {
    const res = await fetchWithTimeout(url, {
      headers: { 'User-Agent': 'agent-data-tools-x402/1.0 contact: jayp19386@gmail.com', Accept: 'application/json' },
    });
    if (!res.ok) throw upstreamError('SEC EDGAR returned ' + res.status + '.');
    return await res.json();
  }
  let normalized = cik ? normalizeCik(cik) : null;
  if (!normalized && ticker) {
    const map = await secJson('https://www.sec.gov/files/company_tickers.json');
    const wanted = String(ticker).trim().toUpperCase();
    for (const value of Object.values(map)) {
      if (String(value.ticker ?? '').toUpperCase() === wanted) {
        normalized = normalizeCik(String(value.cik_str ?? ''));
        break;
      }
    }
  }
  if (!normalized) throw upstreamError('Company not found.', 404);
  const data = await secJson('https://data.sec.gov/submissions/CIK' + normalized + '.json');
  const recent = data.filings?.recent ?? {};
  const forms = recent.form ?? [];
  const filter = String(form).trim().toUpperCase();
  const cikNoZero = String(Number.parseInt(normalized, 10));
  const filings = [];
  for (let i = 0; i < forms.length && filings.length < limit; i += 1) {
    const itemForm = String(forms[i] ?? '');
    if (filter && itemForm.toUpperCase() !== filter) continue;
    const accessionNumber = String((recent.accessionNumber ?? [])[i] ?? '');
    const primaryDocument = String((recent.primaryDocument ?? [])[i] ?? '');
    const accessionCompact = accessionNumber.replace(/-/g, '');
    filings.push({
      form: itemForm,
      filingDate: (recent.filingDate ?? [])[i] ?? null,
      reportDate: (recent.reportDate ?? [])[i] ?? null,
      acceptanceDateTime: (recent.acceptanceDateTime ?? [])[i] ?? null,
      accessionNumber,
      primaryDocument,
      primaryDocDescription: (recent.primaryDocDescription ?? [])[i] ?? null,
      filingUrl: accessionCompact && primaryDocument
        ? 'https://www.sec.gov/Archives/edgar/data/' + cikNoZero + '/' + accessionCompact + '/' + primaryDocument
        : null,
    });
  }
  return {
    company: {
      name: data.name ?? null,
      cik: normalized,
      tickers: data.tickers ?? [],
      exchanges: data.exchanges ?? [],
      sic: data.sic ?? null,
      sicDescription: data.sicDescription ?? null,
    },
    count: filings.length,
    filings,
    source: 'U.S. Securities and Exchange Commission EDGAR',
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

export async function censusGeocode(address) {
  const url = new URL('https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress');
  url.searchParams.set('address', address);
  url.searchParams.set('benchmark', 'Public_AR_Current');
  url.searchParams.set('vintage', 'Current_Current');
  url.searchParams.set('format', 'json');
  const res = await fetchWithTimeout(url.toString());
  if (!res.ok) throw upstreamError('U.S. Census Geocoding Services returned ' + res.status + '.');
  const data = await res.json();
  const match = data.result?.addressMatches?.[0];
  if (!match) {
    return {
      input: address,
      matched: false,
      matchedAddress: null,
      coordinates: null,
      addressComponents: null,
      geographies: null,
      source: 'U.S. Census Bureau Geocoding Services',
    };
  }
  const geos = match.geographies ?? {};
  const state = firstGeoByKey(geos, 'States');
  const county = firstGeoByKey(geos, 'Counties');
  const tract = firstGeoByKey(geos, 'Census Tracts');
  const block = firstGeoByKey(geos, 'Census Blocks') ?? firstGeoByPattern(geos, /^\d{4} Census Blocks$/i);
  const district = firstGeoByPattern(geos, /^(?:\d+(?:st|nd|rd|th) )?Congressional Districts$/i);
  return {
    input: address,
    matched: true,
    matchedAddress: match.matchedAddress ?? null,
    coordinates: {
      longitude: match.coordinates?.x ?? null,
      latitude: match.coordinates?.y ?? null,
    },
    addressComponents: match.addressComponents ?? null,
    geographies: {
      stateFips: state?.STATE ?? null,
      countyFips: county?.COUNTY ?? null,
      countyGeoid: county?.GEOID ?? null,
      tract: tract?.TRACT ?? null,
      tractGeoid: tract?.GEOID ?? null,
      block: block?.BLOCK ?? null,
      blockGeoid: block?.GEOID ?? null,
      congressionalDistrict: district?.CD ?? district?.BASENAME ?? null,
    },
    source: 'U.S. Census Bureau Geocoding Services',
  };
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = '';
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') {
        field += '"';
        i += 1;
      } else if (ch === '"') quoted = false;
      else field += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ',') { row.push(field); field = ''; }
    else if (ch === '\n') {
      row.push(field.replace(/\r$/, ''));
      if (row.some(v => v.length)) rows.push(row);
      row = [];
      field = '';
    } else field += ch;
  }
  if (field.length || row.length) {
    row.push(field.replace(/\r$/, ''));
    if (row.some(v => v.length)) rows.push(row);
  }
  return rows;
}

function normalizeName(value) {
  return String(value ?? '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toUpperCase()
    .replace(/[^A-Z0-9 ]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
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

function scoreName(query, candidate) {
  const q = normalizeName(query);
  const c = normalizeName(candidate);
  if (!q || !c) return 0;
  if (q === c) return 100;
  const qTokens = q.split(' ').filter(Boolean).sort().join(' ');
  const cTokens = c.split(' ').filter(Boolean).sort().join(' ');
  if (qTokens === cTokens) return 99;
  if (q.length >= 5 && c.length >= 5 && (q.includes(c) || c.includes(q))) return 94;
  const maxLen = Math.max(q.length, c.length);
  const editScore = maxLen ? (1 - levenshtein(q, c) / maxLen) * 100 : 0;
  const qa = new Set(q.split(' ').filter(Boolean));
  const ca = new Set(c.split(' ').filter(Boolean));
  let shared = 0;
  for (const token of qa) if (ca.has(token)) shared += 1;
  const union = new Set([...qa, ...ca]).size || 1;
  const tokenScore = (shared / union) * 100;
  return Math.max(0, Math.min(100, Math.round(Math.max(editScore, tokenScore))));
}

let ofacCache = null;

async function fetchOfacFile(name) {
  const res = await fetchWithTimeout(OFAC_BASE + '/' + name, {
    headers: { 'User-Agent': 'agent-data-tools-x402/1.0', Accept: 'text/csv,*/*' },
    redirect: 'follow',
  }, 20000);
  if (!res.ok) throw upstreamError('OFAC returned ' + res.status + ' for ' + name + '.');
  return await res.text();
}

async function loadOfacEntries() {
  if (ofacCache && Date.now() - ofacCache.loadedAt < OFAC_CACHE_MS) return ofacCache.entries;
  const [sdnText, altText] = await Promise.all([fetchOfacFile('SDN.CSV'), fetchOfacFile('ALT.CSV')]);
  const map = new Map();
  for (const cols of parseCsv(sdnText)) {
    const uid = String(cols[0] ?? '').trim();
    const name = String(cols[1] ?? '').trim();
    if (!uid || !name) continue;
    map.set(uid, {
      uid,
      name,
      type: String(cols[2] ?? '').trim() || null,
      program: String(cols[3] ?? '').trim() || null,
      title: String(cols[4] ?? '').trim() || null,
      remarks: String(cols[11] ?? '').trim() || null,
      aliases: [],
    });
  }
  for (const cols of parseCsv(altText)) {
    const uid = String(cols[0] ?? '').trim();
    const alias = String(cols[3] ?? '').trim();
    const entry = map.get(uid);
    if (entry && alias) entry.aliases.push({ type: String(cols[2] ?? '').trim() || null, name: alias });
  }
  const entries = [...map.values()];
  ofacCache = { loadedAt: Date.now(), entries };
  return entries;
}

export async function ofacScreen({ name, limit = 5, minScore = 85 }) {
  const entries = await loadOfacEntries();
  const candidates = [];
  for (const entry of entries) {
    let best = { score: scoreName(name, entry.name), matchedOn: 'primary', matchedName: entry.name };
    for (const alias of entry.aliases) {
      const score = scoreName(name, alias.name);
      if (score > best.score) best = { score, matchedOn: 'alias', matchedName: alias.name };
    }
    if (best.score >= minScore) {
      candidates.push({
        uid: entry.uid,
        primaryName: entry.name,
        score: best.score,
        matchedOn: best.matchedOn,
        matchedName: best.matchedName,
        type: entry.type,
        program: entry.program,
        title: entry.title,
        remarks: entry.remarks,
      });
    }
  }
  candidates.sort((a, b) => b.score - a.score || a.primaryName.localeCompare(b.primaryName));
  const totalCandidatesAboveThreshold = candidates.length;
  return {
    query: name,
    minScore,
    count: Math.min(limit, candidates.length),
    totalCandidatesAboveThreshold,
    candidates: candidates.slice(0, limit),
    source: 'U.S. Treasury OFAC SDN List',
    reviewRequired: true,
    limitations: [
      'Name screening only; a no-match is not sanctions clearance.',
      'Does not perform ownership or OFAC 50 Percent Rule analysis.',
      'Candidate similarity requires human review.',
    ],
  };
}

let rdapCache = null;

async function rdapBootstrap() {
  if (rdapCache && Date.now() - rdapCache.loadedAt < RDAP_CACHE_MS) return rdapCache.data;
  const res = await fetchWithTimeout(IANA_RDAP_BOOTSTRAP, { headers: { Accept: 'application/json' } });
  if (!res.ok) throw upstreamError('IANA RDAP bootstrap returned ' + res.status + '.');
  const data = await res.json();
  rdapCache = { loadedAt: Date.now(), data };
  return data;
}

export function normalizeDomain(raw) {
  let value = String(raw ?? '').trim().toLowerCase();
  if (value.endsWith('.')) value = value.slice(0, -1);
  if (value.length < 3 || value.length > 253 || !/^[a-z0-9.-]+$/.test(value)) return null;
  const labels = value.split('.');
  if (labels.length < 2 || labels.some(label => !label || label.length > 63 || label.startsWith('-') || label.endsWith('-'))) return null;
  return value;
}

function findRdapBase(data, tld) {
  for (const service of data.services ?? []) {
    const tlds = service?.[0] ?? [];
    const urls = service?.[1] ?? [];
    if (tlds.map(x => String(x).toLowerCase()).includes(tld) && urls.length) return String(urls[0]);
  }
  return null;
}

function vcardName(entity) {
  const v = entity?.vcardArray?.[1];
  if (!Array.isArray(v)) return null;
  for (const item of v) {
    if (Array.isArray(item) && item[0] === 'fn') return String(item[3] ?? '') || null;
  }
  return null;
}

export async function rdapLookup(domain) {
  const tld = domain.split('.').at(-1);
  const bootstrap = await rdapBootstrap();
  const base = findRdapBase(bootstrap, tld);
  if (!base) throw upstreamError('No authoritative RDAP service found for .' + tld + '.');
  const url = new URL('domain/' + encodeURIComponent(domain), base.endsWith('/') ? base : base + '/');
  const res = await fetchWithTimeout(url.toString(), {
    headers: { Accept: 'application/rdap+json, application/json', 'User-Agent': 'agent-data-tools-x402/1.0' },
  });
  if (res.status === 404) {
    return {
      domain,
      registered: false,
      registrar: null,
      status: [],
      events: {},
      nameservers: [],
      secureDNS: null,
      authoritativeRdap: base,
      source: 'Authoritative RDAP server discovered via IANA bootstrap',
    };
  }
  if (!res.ok) throw upstreamError('Authoritative RDAP returned ' + res.status + '.');
  const data = await res.json();
  const registrarEntity = (data.entities ?? []).find(x => (x.roles ?? []).includes('registrar')) ?? null;
  const events = {};
  for (const event of data.events ?? []) {
    const action = String(event.eventAction ?? '');
    if (action) events[action] = event.eventDate ?? null;
  }
  return {
    domain,
    registered: true,
    handle: data.handle ?? null,
    unicodeName: data.unicodeName ?? null,
    status: data.status ?? [],
    registrar: registrarEntity ? { name: vcardName(registrarEntity), handle: registrarEntity.handle ?? null } : null,
    events,
    nameservers: (data.nameservers ?? []).map(x => x.ldhName ?? x.unicodeName).filter(Boolean),
    secureDNS: data.secureDNS ?? null,
    authoritativeRdap: base,
    source: 'Authoritative RDAP server discovered via IANA bootstrap',
  };
}

export async function treasuryRates(security = '') {
  const url = new URL(TREASURY_API);
  url.searchParams.set('fields', 'record_date,security_type_desc,security_desc,avg_interest_rate_amt');
  url.searchParams.set('sort', '-record_date');
  url.searchParams.set('page[size]', '100');
  const res = await fetchWithTimeout(url.toString(), {
    headers: { Accept: 'application/json', 'User-Agent': 'agent-data-tools-x402/1.0' },
  });
  if (!res.ok) throw upstreamError('U.S. Treasury Fiscal Data returned ' + res.status + '.');
  const payload = await res.json();
  const rows = payload.data ?? [];
  if (!rows.length) throw upstreamError('U.S. Treasury Fiscal Data returned no data.');
  const recordDate = String(rows[0].record_date ?? '');
  const needle = String(security).trim().toLowerCase();
  const latest = rows.filter(row => String(row.record_date ?? '') === recordDate);
  const filtered = needle
    ? latest.filter(row => String(row.security_desc ?? '').toLowerCase().includes(needle))
    : latest;
  return {
    recordDate,
    count: filtered.length,
    rates: filtered.map(row => ({
      securityDescription: row.security_desc ?? null,
      securityType: row.security_type_desc ?? null,
      averageInterestRatePercent: row.avg_interest_rate_amt == null || row.avg_interest_rate_amt === '' ? null : Number(row.avg_interest_rate_amt),
    })),
    source: 'U.S. Treasury Fiscal Data — Average Interest Rates on U.S. Treasury Securities',
    frequency: 'monthly',
  };
}

function registryAddress(entity) {
  const parts = [entity?.address1, entity?.address2, entity?.city, entity?.state, entity?.zip].filter(v => v && String(v).trim());
  return parts.length ? parts.join(', ') : null;
}

function censusIdentity(value) {
  const text = String(value ?? '').toUpperCase().trim();
  return {
    streetNumber: text.match(/^\s*(\d+[A-Z-]?)/)?.[1] ?? null,
    zip: text.match(/\b(\d{5})(?:-\d{4})?\s*$/)?.[1] ?? null,
  };
}

function distanceMiles(a, b) {
  const radians = d => d * Math.PI / 180;
  const radius = 3958.7613;
  const dLat = radians(b.latitude - a.latitude);
  const dLon = radians(b.longitude - a.longitude);
  const lat1 = radians(a.latitude);
  const lat2 = radians(b.latitude);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * radius * Math.asin(Math.min(1, Math.sqrt(h)));
}

function domainNameAligned(domain, vendorName) {
  const vendor = canonicalBusinessName(vendorName).replace(/[^A-Z0-9]/g, '').toLowerCase();
  const tokens = canonicalBusinessName(vendorName).toLowerCase().split(' ').filter(x => x.length >= 3);
  const hosts = domain.split('.').slice(0, -1).map(x => x.replace(/[^a-z0-9]/g, '')).filter(Boolean);
  return hosts.some(host => host === vendor || host.includes(vendor) || vendor.includes(host) || tokens.some(t => host === t || host.includes(t) || t.includes(host)));
}

export async function vendorIntake({ name, address, domain }) {
  const { results, principals } = await paSearch(name, 3, true);
  const match = results[0] ?? null;
  const strongCandidates = results.filter(x => paMatchScore(x.businessName ?? '', name) <= 1);
  const registryAddressValue = registryAddress(match);

  const [providedCensus, registeredCensus, ofac, rdap] = await Promise.all([
    censusGeocode(address),
    registryAddressValue ? censusGeocode(registryAddressValue) : Promise.resolve(null),
    ofacScreen({ name, limit: 3, minScore: 90 }),
    rdapLookup(domain),
  ]);

  const triggers = [];
  if (!match) triggers.push({ code: 'pa_registry_match_not_found', detail: 'No Pennsylvania registry candidate was found.' });
  if (strongCandidates.length > 1) triggers.push({ code: 'pa_registry_name_ambiguous', detail: 'More than one strong Pennsylvania registry candidate matched the name.' });
  if (match && paMatchScore(match.businessName ?? '', name) > 1) triggers.push({ code: 'pa_registry_name_needs_review', detail: 'The best Pennsylvania registry name match is not strong enough for automated continuation.' });
  if (match && (principals !== 'complete' || !match.filingNumber || !match.registrationType || !registryAddressValue)) triggers.push({ code: 'pa_registry_evidence_incomplete', detail: 'Registry evidence is incomplete.' });

  if (!providedCensus.matched) triggers.push({ code: 'provided_address_not_geocoded', detail: 'The supplied address did not resolve through the Census geocoder.' });
  if (!registryAddressValue) triggers.push({ code: 'registry_address_missing', detail: 'The registry record did not provide a usable registered address.' });
  if (registryAddressValue && !registeredCensus?.matched) triggers.push({ code: 'registry_address_not_geocoded', detail: 'The registered address did not resolve through the Census geocoder.' });

  let distance = null;
  let sameStreetNumber = false;
  let sameZip = false;
  if (providedCensus.matched && registeredCensus?.matched && providedCensus.coordinates && registeredCensus.coordinates) {
    const a = { latitude: Number(providedCensus.coordinates.latitude), longitude: Number(providedCensus.coordinates.longitude) };
    const b = { latitude: Number(registeredCensus.coordinates.latitude), longitude: Number(registeredCensus.coordinates.longitude) };
    if ([a.latitude, a.longitude, b.latitude, b.longitude].every(Number.isFinite)) distance = Number(distanceMiles(a, b).toFixed(3));
    const ia = censusIdentity(providedCensus.matchedAddress);
    const ib = censusIdentity(registeredCensus.matchedAddress);
    sameStreetNumber = Boolean(ia.streetNumber && ia.streetNumber === ib.streetNumber);
    sameZip = Boolean(ia.zip && ia.zip === ib.zip);
    if (!(sameStreetNumber && sameZip && distance != null && distance <= 0.25)) {
      triggers.push({ code: 'registered_address_differs', detail: 'The supplied address differs materially from the registry address.' });
    }
  }

  if (ofac.totalCandidatesAboveThreshold > 0) triggers.push({ code: 'ofac_name_candidate_present', detail: 'OFAC name screening returned one or more review candidates at score 90 or higher.' });
  if (rdap.registered !== true) triggers.push({ code: 'domain_registration_not_confirmed', detail: 'RDAP did not confirm a current domain registration.' });
  const nameAligned = domainNameAligned(domain, name);
  if (!nameAligned) triggers.push({ code: 'domain_name_not_aligned', detail: 'The domain label is not obviously aligned with the vendor name.' });

  const decision = triggers.length ? 'human_review' : 'proceed';
  return {
    decision,
    agentAction: decision === 'proceed' ? 'continue_vendor_intake' : 'pause_and_request_human_review',
    reviewTriggers: triggers,
    checkedAt: new Date().toISOString(),
    input: { name, address, domain },
    policy: {
      ofacReviewThreshold: 90,
      maxAddressDistanceMiles: 0.25,
      proceedMeaning: 'Configured automated checks did not trigger human review.',
    },
    evidence: {
      registry: {
        found: Boolean(match),
        candidateCount: results.length,
        strongCandidateCount: strongCandidates.length,
        ambiguous: strongCandidates.length > 1,
        matchScore: match ? paMatchScore(match.businessName ?? '', name) : null,
        match,
        source: 'Pennsylvania Department of State via data.pa.gov',
      },
      address: {
        provided: providedCensus,
        registered: registeredCensus,
        sameStreetNumber,
        sameZip,
        distanceMiles: distance,
      },
      ofac,
      domain: { ...rdap, requestedDomain: domain, nameAligned },
    },
    limitations: [
      'Proceed is a workflow signal only, not legal, sanctions, fraud, credit, or compliance approval.',
      'OFAC screening is name matching only and does not perform 50 Percent Rule ownership analysis.',
      'Pennsylvania registry records do not prove ownership or current good standing.',
      'Census matches do not prove control of an address.',
      'RDAP registration does not prove control of a domain.',
    ],
  };
}
