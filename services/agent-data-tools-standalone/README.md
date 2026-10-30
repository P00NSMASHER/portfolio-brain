# Agent Data Tools x402 | isolated seller code

**State: tested source proposal, not deployed.** This is an optional standalone service in Portfolio Brain, not a replacement for its existing running gateway. No production Render configuration, protected branch rule, billing permission, credential or scheduled task is changed by including these files.

The code serves eight pay-per-call public-data tools and free discovery endpoints. A separate, approved launch is required before accepting customer payments. A historic [offline mock CI run](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/40973212283) passed; a historic [live Census smoke test](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/40972971832) failed with upstream HTTP 502. Both records are preserved, and neither certifies the code on its own.

## Tools

| Endpoint | Display price |
|---|---:|
| `/api/pa-entity-one` | $0.001 USDC |
| `/api/pa-business` | $0.005 USDC |
| `/api/vendor-intake-gate` | $0.020 USDC |
| `/api/sec-filings` | $0.005 USDC |
| `/api/us-address-geocode` | $0.005 USDC |
| `/api/ofac-sdn-screen` | $0.005 USDC |
| `/api/domain-rdap` | $0.005 USDC |
| `/api/treasury-average-rates` | $0.005 USDC |

Discovery and health routes remain unpaid: `/.well-known/x402`, `/.well-known/agent.json`, `/openapi.json`, `/llms.txt`, `/skill.md`, `/robots.txt`, `/sitemap.xml`, `/api/health`.

Sources are public Pennsylvania registry data, SEC EDGAR, Census geocoding, Treasury OFAC, IANA/authoritative RDAP and Treasury Fiscal Data. Source availability and permission remain service-specific and must be checked again before a launch.

## Getting started, locally

Requires Node.js 20+ and network access **only to install the declared Express dependency**. After dependencies are installed, the following tests use mocked payment/provider responses and make no live paid requests.

```sh
npm install
npm run test:protocol
npm test
PORT=3000 npm start
```

Visit `http://127.0.0.1:3000/api/health`. Unpaid GETs to any paid route return a testable HTTP 402 challenge, never settle a payment without a valid signed payload. Local testing uses a loopback-only host and peer; spoofed public `Host` and `X-Forwarded-Proto` values are not trusted.

## Security and money controls

- x402 v2 exact, Base `eip155:8453`, Base USDC asset `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`, seller pay-to `0x708f7b52b56eafd7fc1de65fc7752ed732914021`, PayAI facilitator.
- A **public HTTPS deployment must set `PUBLIC_ORIGIN` to a reviewed HTTPS origin**, such as `https://tools.example.com`, with no path, query or embedded user credentials. It is never inferred from a client-supplied `Host` or proxy header. Without a valid origin, public paid/discovery challenges fail closed.
- Validate request inputs; verify the payment only against a successful facilitator HTTP response; fetch source data only after verification; settle **once** after a successful upstream result; serve paid data only when settlement has been positively confirmed.
- An ambiguous settlement may already have charged a payment. **Never automatically repeat that settlement POST.** Return `503` with `paymentState: unresolved` and `retrySamePayment: false`, requiring independent reconciliation before any subsequent financial action.
- Mocked fail-closed tests cover forged host/origin, HTTP-error success flags, duplicate-settlement risk, upstream failures, no-payment challenges and ordinary success. They are NOT live customer-payment certification.

The existing protected Foundation suite also syntax-checks the standalone JavaScript and executes its pure Node.js protocol-security tests without Express, paid API calls or a network connection. Full `npm test` additionally covers the Express route contract using local HTTP only.

## Qualification and deployment hold

`npm run test:upstreams` is intentionally **outside ordinary CI** because it calls live public third-party services. Do not run it without specific authorization. The previously observed Census 502 must be independently reproduced and addressed if it remains current. A production launch also requires host, wallet/payee, facilitator, real payment verification and reconciliation acceptance, security review and explicit approval for deployment and customer traffic.

The repository-root `render.yaml` still references the existing `x402-render-gateway`; it is never repointed by this code. No new active GitHub Actions workflow is installed for this package. The original inactive workflow recipe remains on the source PR branch for historical review, not as an enabled task.

**Current claim:** independently reviewable functionality and mocked/offline tests, not a deployed seller, realized revenue or permission to handle payments.
