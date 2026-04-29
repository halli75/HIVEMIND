# Uniswap Integration

## Target

Use the Uniswap API for quote and swap flow on Sepolia, then preserve the receipt as the final proof that the winning iNFT-backed agent executed a trade.

## Current Scaffold

- Seed quote shape lives in `data/snapshots/uniswap-quote.seed.json`.
- `.env.example` includes placeholders for `UNISWAP_API_KEY`, chain ID, token addresses, slippage, and swapper address.
- `FEEDBACK.md` provides a template for integration notes and sponsor feedback.
- `UniswapExecutionProvider` supplies live Sepolia quotes to the API when `HIVEMIND_USE_MOCK_UNISWAP=false`.
- `apps/execution/run_swap.py` refuses to submit a swap unless `HIVEMIND_ALLOW_TESTNET_SWAP=true`.

## Live Proof Rehearsal - 2026-04-29

Evidence directory: `runs/proof-20260429-161627/` (ignored, non-secret).

| Step | Result | Evidence |
| --- | --- | --- |
| API quote through `/scenario` | Passed | `mode=live`, Sepolia, quote id `4f9da6b5-5cd6-4a11-b40c-8c9cb12885cf` |
| Quote-only script | Passed | `0.001 WETH -> 8.75588 USDC`, price impact `0.02`, quote id `3301ca8c-df76-4c88-a6ee-efc2ebfef35d` |
| Swap guard | Passed | `run_swap.py` exited before signing because `HIVEMIND_ALLOW_TESTNET_SWAP=true` was not enabled |

No Sepolia swap transaction was submitted in this rehearsal.

## Official Reference Points

Uniswap documents the swapping flow as approval check, quote request, then order or swap request depending on route/protocol. The quickstart uses `x-api-key` authentication and the `/v1/quote` endpoint for quotes.

References:

- https://developers.uniswap.org/docs/get-started/quickstart
- https://developers.uniswap.org/docs/trading/swapping-api/getting-started

## Remaining Integration Steps

1. Validate API key access with a small quote request.
2. Use Sepolia token addresses from environment variables, not hard-coded secrets.
3. Call approval check when token input is ERC-20.
4. Request quote with expected protocols and display price impact.
5. Require human review before signing.
6. Enable `HIVEMIND_ALLOW_TESTNET_SWAP=true` only for the final operator-approved testnet swap.
7. Submit swap transaction on Sepolia.
8. Capture transaction hash, route, amount in/out, price impact, and observed API issues in `FEEDBACK.md`.

## Safety

- Sepolia only for the hackathon demo.
- No autonomous mainnet execution.
- Final submit/signing should remain behind operator review.
