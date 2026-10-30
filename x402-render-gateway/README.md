# Agent Data Tools x402 Gateway

Quota-independent fallback for the eight paid x402 tools that were previously split across AppDeploy app-path origins.

## Purpose

Keep both paid execution and machine-readable discovery available when another hosting provider exhausts runtime credits.

The service exposes one public origin with:

- `/api/pa-entity-one` — $0.001 USDC
- `/api/pa-business` — $0.005 USDC
- `/api/vendor-intake-gate` — $0.020 USDC
- `/api/sec-filings` — $0.005 USDC
- `/api/us-address-geocode` — $0.005 USDC
- `/api/ofac-sdn-screen` — $0.005 USDC
- `/api/domain-rdap` — $0.005 USDC
- `/api/treasury-average-rates` — $0.005 USDC

Discovery surfaces:

- `/.well-known/x402`
- `/.well-known/agent.json`
- `/openapi.json`
- `/llms.txt`
- `/skill.md`
- `/health` and `/healthz`

## Payment contract

- x402 v2 exact
- Base: `eip155:8453`
- USDC: `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`
- EIP-712 domain: `USD Coin`, version `2`
- Seller wallet: `0x708f7b52b56eafd7fc1de65fc7752ed732914021`
- Facilitator: PayAI

The service verifies payment first, performs the authoritative-data operation, and settles only after a result is available. Upstream failures return without settlement.

## Data sources

- Pennsylvania Department of State via data.pa.gov
- U.S. SEC EDGAR
- U.S. Census Bureau Geocoder
- U.S. Treasury OFAC SDN exports
- IANA RDAP bootstrap + authoritative registry RDAP
- U.S. Treasury Fiscal Data

## Deploy

`render.yaml` defines a free Render web service rooted at this directory. The server is dependency-free Node 20+ and listens on `PORT`.

## Verification

The repository workflow `x402 Render Gateway Smoke` checks syntax, server startup, discovery resource count, OpenAPI route count, and the unpaid Base-USDC 402 challenge.

A separate isolated deep smoke was used during development to verify live government sources and the vendor decision policy without changing this production branch.


## Marketplace readiness

The 402 challenge includes x402 v2 Base USDC payment requirements plus Bazaar discovery metadata. The same-origin discovery document publishes the eight route URLs, accepted payment requirements, examples, tags, and service names. The Agent402-style manifest is available at `/.well-known/agent.json`.

PayAI Bazaar admission is **metadata-and-policy dependent**, not proof of a purchase. For x402 v2, participating buyers must preserve both `resource` and `extensions` from PAYMENT-REQUIRED in their payment payload. PayAI may queue catalog updates after either `/verify` or `/settle`; a verification-only flow with an appropriate signed payload can initiate discovery without transferring funds. Admission remains conditional, and an HTTP 402 probe plus the exact resource URL must validate. Do not self-fund or manufacture buyer transactions.

### Verified public Pennsylvania seller (2026-10-23)

The current canonical Pennsylvania best-match x402 resource is `https://pa-entity-x402.floot.app/_api/pa-entity-one` (without example query parameters). Its unpaid `?q=OpenAI` request returns HTTP 402, and Floot's `/.well-known/x402.json` advertises the same URL and Base USDC payment terms. PayAI's exact-URL `/discovery/listing-status` reports `listed:true`, `hidden:false`, and a healthy 402 reachability probe; its `/discovery/resources` public catalog also contains the Floot resource. The last catalog update is 2026-10-14, and catalog service metadata can be older than the current 402.

**Do not substitute the unverified Netlify fallback as canonical.** As of October 23, the candidate `https://agent-data-tools-x402.netlify.app/api/pa-entity-one` and its `/.well-known/x402` return Netlify HTTP 404. PR #495 implemented a local adapter and tests but does not establish an actual production deployment. Netlify must be deployed and observed returning a live 402 before its URL is used for discovery or catalog diagnostics.

Run a zero-payment live check with `node x402-render-gateway/scripts/bazaar-audit.mjs`. It uses GET only to compare live 402 challenges, manifest, PayAI listing-status, public catalog, and the fallback's deployment status. The default check fails if the **primary Floot** listing is unhealthy; use `--require-netlify` only when the Netlify deployment is expected to exist. Neither mode submits a payment nor invokes verify/settle. Review any proposed deployment or source-of-truth switch independently.


## Netlify free-host runtime

The same gateway can run on the existing free Netlify project `agent-data-tools-x402` without changing any x402 payment terms. `netlify/functions/gateway.mjs` adapts Netlify's Web Request/Response API to the shared gateway handler, and `netlify.toml` pins Node 20 plus the functions directory.

Deploy from this `x402-render-gateway` directory into the existing Netlify site. The function owns the root page, discovery surfaces, health probes, and all eight `/api/*` paid routes on one origin. Do not proxy paid routes back to AppDeploy.
