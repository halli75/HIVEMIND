# Uniswap Integration Plan

## Target

Use the Uniswap API for quote and swap flow on Sepolia, then preserve the receipt as the final proof that the winning iNFT-backed agent executed a trade.

## Current Scaffold

- Seed quote shape lives in `data/snapshots/uniswap-quote.seed.json`.
- `.env.example` includes placeholders for `UNISWAP_API_KEY`, chain ID, token addresses, slippage, and swapper address.
- `FEEDBACK.md` provides a template for integration notes and sponsor feedback.

## Official Reference Points

Uniswap documents the swapping flow as approval check, quote request, then order or swap request depending on route/protocol. The quickstart uses `x-api-key` authentication and the `/v1/quote` endpoint for quotes.

References:

- https://developers.uniswap.org/docs/get-started/quickstart
- https://developers.uniswap.org/docs/trading/swapping-api/getting-started

## Integration Steps

1. Validate API key access with a small quote request.
2. Use Sepolia token addresses from environment variables, not hard-coded secrets.
3. Call approval check when token input is ERC-20.
4. Request quote with expected protocols and display price impact.
5. Require human review before signing.
6. Submit swap transaction on Sepolia.
7. Capture transaction hash, route, amount in/out, price impact, and observed API issues in `FEEDBACK.md`.

## Safety

- Sepolia only for the hackathon demo.
- No autonomous mainnet execution.
- Final submit/signing should remain behind operator review.
