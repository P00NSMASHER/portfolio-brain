# Agent Data Tools x402 Gateway

A small same-origin gateway for the user's eight paid x402 v2 endpoints.

## Why this exists

The six AppDeploy products share the `api-v2.appdeploy.ai` host and live under different `/app/<id>` path prefixes. Some discovery systems canonicalize an endpoint to the bare origin before looking for `/openapi.json`, so they cannot register those path-prefixed sellers individually. This gateway gives the portfolio one unique origin while keeping payment verification and settlement on the existing backend services.

## Behavior

- Proxies eight GET routes to the existing paid AppDeploy backends.
- Preserves upstream HTTP status, JSON bodies, and payment headers including `PAYMENT-REQUIRED`, `PAYMENT-RESPONSE`, and client `PAYMENT-SIGNATURE`.
- Does not custody funds or settle payments.
- Does not persist payment signatures, request bodies, or API results.
- Exposes `/openapi.json` with x402scan-compatible `x-payment-info`.
- Exposes `/.well-known/x402` for x402 discovery.
- Exposes `/.well-known/agent.json` for Open 402 Directory discovery.
- Exposes `/skill.md`, `/llms.txt`, and `/healthz`.

## Routes

| Route | Price |
| --- | ---: |
| `/api/pa-entity-one` | $0.001 |
| `/api/pa-business` | $0.005 |
| `/api/vendor-intake-gate` | $0.020 |
| `/api/sec-filings` | $0.005 |
| `/api/us-address-geocode` | $0.005 |
| `/api/ofac-sdn-screen` | $0.005 |
| `/api/domain-rdap` | $0.005 |
| `/api/treasury-average-rates` | $0.005 |

## Validation

`npm run check` performs a syntax check. `npm test` starts the gateway locally, validates the discovery surfaces, and verifies representative unpaid proxied routes return HTTP 402 with `PAYMENT-REQUIRED`.

No paid request is made by the smoke test.
