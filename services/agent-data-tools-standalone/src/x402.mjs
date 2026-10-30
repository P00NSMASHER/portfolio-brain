const PAY_TO = '0x708f7b52b56eafd7fc1de65fc7752ed732914021';
const NETWORK = 'eip155:8453';
const USDC = '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913';
const FACILITATOR = 'https://facilitator.payai.network';

export const PAYMENT = { PAY_TO, NETWORK, USDC, FACILITATOR };

export const ROUTES = {
  '/api/pa-entity-one': {
    amount: '1000',
    price: '$0.001',
    decimal: '0.001000',
    serviceName: 'PA Entity Best Match',
    description: 'Resolve one best Pennsylvania legal-entity match by business name.',
    tags: ['business-registry', 'Pennsylvania', 'entity', 'verification'],
    sample: { q: 'OpenAI' },
  },
  '/api/pa-business': {
    amount: '5000',
    price: '$0.005',
    decimal: '0.005000',
    serviceName: 'PA Business Registry',
    description: 'Search Pennsylvania business-registration records by company name.',
    tags: ['business-registry', 'Pennsylvania', 'company', 'due-diligence'],
    sample: { q: 'OpenAI', limit: 5 },
  },
  '/api/vendor-intake-gate': {
    amount: '20000',
    price: '$0.020',
    decimal: '0.020000',
    serviceName: 'PA Vendor Intake Gate',
    description: 'Return proceed or human_review for a prospective Pennsylvania vendor with source-linked evidence.',
    tags: ['vendor-intake', 'agent-decision', 'human-review', 'business-registry', 'compliance'],
    sample: {
      name: 'OpenAI OpCo',
      address: '600 North Second Street, Suite 401, Harrisburg, PA 17101',
      domain: 'openai.com',
    },
  },
  '/api/sec-filings': {
    amount: '5000',
    price: '$0.005',
    decimal: '0.005000',
    serviceName: 'SEC Recent Filings',
    description: 'Retrieve recent SEC EDGAR filing metadata by ticker or CIK.',
    tags: ['SEC', 'EDGAR', 'filings', 'finance', 'company-data'],
    sample: { ticker: 'AAPL', form: '10-K', limit: 5 },
  },
  '/api/us-address-geocode': {
    amount: '5000',
    price: '$0.005',
    decimal: '0.005000',
    serviceName: 'Census Address Geocoder',
    description: 'Geocode one U.S. address to a Census match, coordinates, and geography identifiers.',
    tags: ['geocoding', 'Census', 'address', 'geography', 'US'],
    sample: { address: '4600 Silver Hill Rd, Washington, DC 20233' },
  },
  '/api/ofac-sdn-screen': {
    amount: '5000',
    price: '$0.005',
    decimal: '0.005000',
    serviceName: 'OFAC Name Screen',
    description: 'Screen one name against current OFAC SDN primary names and aliases for review candidates.',
    tags: ['OFAC', 'screening', 'compliance', 'name-match', 'risk'],
    sample: { name: 'VLADIMIR PUTIN', limit: 5, minScore: 85 },
  },
  '/api/domain-rdap': {
    amount: '5000',
    price: '$0.005',
    decimal: '0.005000',
    serviceName: 'Domain RDAP Lookup',
    description: 'Retrieve live authoritative domain-registration metadata through RDAP.',
    tags: ['RDAP', 'domain', 'registration', 'DNS', 'internet'],
    sample: { domain: 'example.com' },
  },
  '/api/treasury-average-rates': {
    amount: '5000',
    price: '$0.005',
    decimal: '0.005000',
    serviceName: 'Treasury Average Rates',
    description: 'Get latest monthly average interest rates on outstanding U.S. Treasury securities.',
    tags: ['Treasury', 'interest-rates', 'government', 'macro', 'finance'],
    sample: { security: 'Total Marketable' },
  },
};

function b64(value) {
  return Buffer.from(JSON.stringify(value), 'utf8').toString('base64');
}

export function decodePayment(value) {
  if (!value || value.length > 16384) throw new Error('invalid_payment_header');
  const normalized = value.replace(/-/g, '+').replace(/_/g, '/');
  const parsed = JSON.parse(Buffer.from(normalized, 'base64').toString('utf8'));
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed) || parsed.x402Version !== 2) {
    throw new Error('invalid_payment_payload');
  }
  return parsed;
}

export function requirements(path) {
  const cfg = ROUTES[path];
  if (!cfg) throw new Error('unknown_paid_route');
  return {
    scheme: 'exact',
    network: NETWORK,
    amount: cfg.amount,
    asset: USDC,
    payTo: PAY_TO,
    maxTimeoutSeconds: 60,
    extra: { name: 'USD Coin', version: '2' },
  };
}

export function bazaarExtension(path) {
  const cfg = ROUTES[path];
  return {
    bazaar: {
      info: {
        input: { type: 'http', method: 'GET', queryParams: cfg.sample },
        output: { type: 'json', example: { paid: true } },
      },
      schema: {
        type: 'object',
        properties: {
          input: {
            type: 'object',
            properties: {
              type: { const: 'http' },
              method: { const: 'GET' },
              queryParams: { type: 'object' },
            },
            required: ['type', 'method', 'queryParams'],
          },
          output: {
            type: 'object',
            properties: {
              type: { const: 'json' },
              example: { type: 'object' },
            },
            required: ['type', 'example'],
          },
        },
        required: ['input', 'output'],
      },
    },
  };
}

export function paymentDocument(origin, path) {
  const cfg = ROUTES[path];
  return {
    x402Version: 2,
    resource: {
      url: origin + path,
      description: cfg.description,
      mimeType: 'application/json',
      serviceName: cfg.serviceName,
      tags: cfg.tags,
    },
    accepts: [requirements(path)],
    extensions: bazaarExtension(path),
  };
}

export function sendPaymentRequired(res, origin, path, reason = 'payment_required') {
  const cfg = ROUTES[path];
  const doc = paymentDocument(origin, path);
  res.status(402);
  res.set({
    'PAYMENT-REQUIRED': b64(doc),
    'x402-price': cfg.price,
    'x402-asset': 'USDC',
    'x402-network': NETWORK,
    'x402-pay-to': PAY_TO,
    'cache-control': 'no-store',
  });
  return res.json({
    error: reason,
    ...doc,
    price: cfg.price,
    currency: 'USDC',
    network: NETWORK,
    payTo: PAY_TO,
  });
}

async function facilitatorPost(path, paymentPayload, paymentRequirements) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 7000);
  try {
    const response = await fetch(FACILITATOR + '/' + path, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        x402Version: 2,
        paymentPayload,
        paymentRequirements,
      }),
      signal: controller.signal,
    });
    let body = null;
    try {
      body = await response.json();
    } catch {}
    return { status: response.status, body };
  } finally {
    clearTimeout(timer);
  }
}

export async function verifyPayment(path, paymentPayload) {
  const reqs = requirements(path);
  const result = await facilitatorPost('verify', paymentPayload, reqs);
  const valid = result.body?.isValid === true || result.body?.success === true;
  return {
    valid,
    reason: String(result.body?.invalidReason ?? result.body?.errorReason ?? 'payment_verification_failed'),
    requirements: reqs,
  };
}

export async function settlePayment(path, paymentPayload) {
  const reqs = requirements(path);
  const waits = [0, 250, 750];
  for (let i = 0; i < waits.length; i += 1) {
    if (waits[i]) await new Promise(resolve => setTimeout(resolve, waits[i]));
    let result;
    try {
      result = await facilitatorPost('settle', paymentPayload, reqs);
    } catch {
      if (i === waits.length - 1) return { ok: false, unresolved: true, reason: 'settlement_transport_unknown' };
      continue;
    }
    if (result.body?.success === true) return { ok: true, receipt: result.body };
    const reason = String(result.body?.errorReason ?? (result.status === 429 ? 'rate_limited' : result.status >= 500 ? 'facilitator_unavailable' : 'payment_settlement_failed'));
    if (['settlement_pending', 'duplicate_settlement', 'rate_limited', 'facilitator_unavailable'].includes(reason)) {
      if (i === waits.length - 1) return { ok: false, unresolved: true, reason };
      continue;
    }
    return { ok: false, unresolved: false, reason };
  }
  return { ok: false, unresolved: true, reason: 'settlement_unknown' };
}

export function encodePaymentResponse(value) {
  return b64(value);
}

export async function paidRoute(req, res, path, validate, execute) {
  const origin = requestOrigin(req);
  const signature = req.get('payment-signature') || req.get('x-payment');
  if (!signature) return sendPaymentRequired(res, origin, path);

  let paymentPayload;
  try {
    paymentPayload = decodePayment(signature);
  } catch {
    return sendPaymentRequired(res, origin, path, 'invalid_payment_header');
  }

  let input;
  try {
    input = validate(req.query);
  } catch (error) {
    return res.status(400).json({ error: error instanceof Error ? error.message : 'invalid_input', paymentSettled: false });
  }

  try {
    const verified = await verifyPayment(path, paymentPayload);
    if (!verified.valid) return sendPaymentRequired(res, origin, path, verified.reason);

    let result;
    try {
      result = await execute(input);
    } catch (error) {
      const status = Number(error?.status) || 502;
      return res.status(status).json({
        error: error instanceof Error ? error.message : 'upstream_unavailable',
        paymentSettled: false,
      });
    }

    const settled = await settlePayment(path, paymentPayload);
    if (!settled.ok) {
      if (settled.unresolved) {
        res.set('Retry-After', '2');
        return res.status(503).json({
          error: settled.reason,
          paymentState: 'unresolved',
          retrySamePayment: true,
        });
      }
      return sendPaymentRequired(res, origin, path, settled.reason);
    }

    res.set({
      'PAYMENT-RESPONSE': encodePaymentResponse(settled.receipt),
      'x402-settled': 'true',
      'cache-control': 'no-store',
    });
    return res.json({ ...result, paid: true });
  } catch {
    return res.status(503).json({
      error: 'Payment facilitator is temporarily unavailable; no result was served.',
      paymentSettled: false,
    });
  }
}

export function requestOrigin(req) {
  const forwarded = String(req.get('x-forwarded-proto') || '').split(',')[0].trim();
  const protocol = forwarded || req.protocol || 'https';
  return protocol + '://' + req.get('host');
}
