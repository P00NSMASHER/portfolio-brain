# Agent Data Tools x402 — standalone seller

[![Standalone CI](https://github.com/P00NSMASHER/portfolio-brain/actions/workflows/agent-data-tools-standalone.yml/badge.svg?branch=agent-data-tools-standalone)](https://github.com/P00NSMASHER/portfolio-brain/actions/workflows/agent-data-tools-standalone.yml?query=branch%3Aagent-data-tools-standalone)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/P00NSMASHER/portfolio-brain/tree/agent-data-tools-standalone)

Quota-independent standalone seller for the x402 data-tool portfolio. This isolated branch does not modify Portfolio Brain production code.

## Paid routes

- `/api/pa-entity-one` — $0.001 USDC
- `/api/pa-business` — $0.005 USDC
- `/api/vendor-intake-gate` — $0.020 USDC
- `/api/sec-filings` — $0.005 USDC
- `/api/us-address-geocode` — $0.005 USDC
- `/api/ofac-sdn-screen` — $0.005 USDC
- `/api/domain-rdap` — $0.005 USDC
- `/api/treasury-average-rates` — $0.005 USDC

## Discovery

These surfaces are deliberately free and unpaywalled:

- `/.well-known/x402`
- `/.well-known/agent.json`
- `/openapi.json`
- `/llms.txt`
- `/skill.md`
- `/robots.txt`
- `/sitemap.xml`
- `/api/health`

## Payment contract

- x402 v2 exact
- Base `eip155:8453`
- Base USDC `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`
- EIP-712 domain name `USD Coin`, version `2`
- Seller wallet `0x708f7b52b56eafd7fc1de65fc7752ed732914021`
- PayAI facilitator

The service verifies payment before doing paid work, obtains a successful authoritative result, and settles only after that result exists. Validation/upstream failures do not settle.

## Authoritative sources

- Pennsylvania Department of State via data.pa.gov
- U.S. SEC EDGAR
- U.S. Census Bureau Geocoding Services
- U.S. Treasury OFAC SDN exports
- IANA RDAP bootstrap + authoritative registry RDAP
- U.S. Treasury Fiscal Data

## Verification gates

CI runs all of the following on the isolated branch:

1. contract tests for public discovery and all eight unpaid HTTP 402 challenges;
2. exact Base USDC / `USD Coin` payment metadata checks;
3. mocked verify → data → settle ordering plus no-settle-on-upstream-failure;
4. live smoke tests against all six authoritative public-data families;
5. `@agentcash/discovery` origin discovery;
6. `@agentcash/discovery` checks against every paid route;
7. warning-free discovery enforcement.

## Render deployment

The repository-root `render.yaml` on branch `agent-data-tools-standalone` is pinned to this directory and defines a free Ohio web service named `agent-data-tools-x402`. Auto-deploy is off by design for Deploy-to-Render use.

No backend secrets are required. `PUBLIC_ORIGIN` is not required because discovery URLs are derived from the incoming public host.
