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
  // A body flag cannot override a failed HTTP response from the facilitator.
  // HTTP 202 means accepted for processing, not a final verification.
  const ok = result.status === 200;
  // A generic success flag is not proof of a valid payment. Reject absent or
  // contradictory isValid and malformed optional success values fail-closed.
  // V2 invalidReason is omitted (or empty in some facilitators) when valid.
  // A reason accompanying isValid:true is contradictory and cannot authorize data.
  const noInvalidity = result.body?.invalidReason == null ||
    result.body.invalidReason === '';
  const valid = ok && noInvalidity && result.body?.isValid === true &&
    (result.body.success === undefined || result.body.success === true);
  return {
    valid,
    reason: valid ? 'verified' : 'payment_verification_failed',
    requirements: reqs,
  };
}

export async function settlePayment(path, paymentPayload) {
  const reqs = requirements(path);
  // An ambiguous settlement response is a potential charge, not permission to
  // issue another POST. We make ONE original call, then fail closed pending
  // independently authorized settlement reconciliation.
  let result;
  try {
    result = await facilitatorPost('settle', paymentPayload, reqs);
  } catch {
    return { ok: false, unresolved: true, reason: 'settlement_transport_unknown' };
  }
  // A 202 or other non-final 2xx is not proof of settlement, even if a
  // facilitator incorrectly includes success:true. A success flag paired
  // with an errorReason is contradictory: do not serve paid data.
  const finalSuccess = result.status === 200 &&
    result.body?.success === true && result.body?.errorReason == null;
  if (finalSuccess) {
    return { ok: true, receipt: result.body };
  }
  const reason = result.body?.errorReason;
  const ambiguous2xx = result.status >= 200 && result.status < 300 &&
    (result.status !== 200 || result.body?.success === true);
  const pending = ambiguous2xx || result.status === 429 || result.status >= 500 ||
    ['settlement_pending', 'duplicate_settlement', 'rate_limited',
      'facilitator_unavailable'].includes(reason);
  return {
    ok: false,
    unresolved: pending,
    reason: pending ? 'settlement_status_unresolved' : 'payment_settlement_failed',
  };
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
      // An upstream exception is never an HTTP success or redirect. Reject
      // malformed/non-error statuses rather than leaking a 2xx/3xx as success.
      const candidateStatus = Number(error?.status);
      const status = Number.isInteger(candidateStatus) &&
        candidateStatus >= 400 && candidateStatus <= 599 ? candidateStatus : 502;
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
          retrySamePayment: false,
          action: 'reconcile_settlement_before_retry',
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
  // Never derive payment resource URLs from untrusted Host / forwarded headers.
  // Production must supply a reviewed public HTTPS origin. Loopback is allowed
  // without configuration strictly for local tests and development.
  const configured = process.env.PUBLIC_ORIGIN;
  if (configured) {
    let parsed;
    try {
      parsed = new URL(configured);
    } catch {
      throw new Error('public_origin_invalid');
    }
    if (parsed.protocol !== 'https:' || !parsed.hostname ||
        parsed.username || parsed.password || parsed.pathname !== '/' ||
        parsed.search || parsed.hash) {
      throw new Error('public_origin_invalid');
    }
    return parsed.origin;
  }
  const host = String(req.get('host') || '');
  const peer = req.socket?.remoteAddress;
  if (!/^(?:localhost|127\.0\.0\.1)(?::[1-9][0-9]{0,4})?$/.test(host) ||
      !['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(peer)) {
    throw new Error('public_origin_required');
  }
  return 'http://' + host;
}
