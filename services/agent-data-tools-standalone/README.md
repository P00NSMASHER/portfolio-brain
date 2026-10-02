# Agent Data Tools x402 — standalone seller

Isolated standalone seller for the x402 data-tool portfolio. This branch does not modify Portfolio Brain production code.

The service exposes free discovery endpoints plus paid x402 v2 routes for PA registry lookup, vendor intake, SEC filings, Census geocoding, OFAC SDN name screening, RDAP, and Treasury average rates. Payments settle directly to the configured seller wallet through PayAI's facilitator.

Run with Node 20+:

```sh
npm install
npm start
```

`PUBLIC_ORIGIN` should be set to the final public origin before production deployment.
