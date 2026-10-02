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
- `/openapi.json`
- `/llms.txt`
- `/skill.md`
- `/health`

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
