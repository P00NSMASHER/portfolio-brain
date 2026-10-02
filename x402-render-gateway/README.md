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

Catalog inclusion is settlement-driven on Bazaar-style facilitators: a public route still needs a successful paid settlement that carries the discovery extension before that facilitator can catalog it. Self-funded catalog-seeding payments should be tracked separately from outside-buyer revenue.


## Netlify free-host runtime

The same gateway can run on the existing free Netlify project `agent-data-tools-x402` without changing any x402 payment terms. `netlify/functions/gateway.mjs` adapts Netlify's Web Request/Response API to the shared gateway handler, and `netlify.toml` pins Node 20 plus the functions directory.

Deploy from this `x402-render-gateway` directory into the existing Netlify site. The function owns the root page, discovery surfaces, health probes, and all eight `/api/*` paid routes on one origin. Do not proxy paid routes back to AppDeploy.
