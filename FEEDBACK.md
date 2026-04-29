# Uniswap Integration Feedback

## Integration Summary

- Mode: mock scaffold pending live Sepolia run.
- Target flow: approval check, quote, swap, receipt capture.
- Current artifact: `data/snapshots/uniswap-quote.seed.json`.

## What Worked

- Placeholder quote schema captures amount in, amount out, route, price impact, approval state, and transaction shape.
- Environment variables keep API key, swapper, and token addresses out of source control.

## Issues / Questions

- Confirm final Sepolia token pair and liquidity before the live demo.
- Confirm whether the selected route should force protocol filters or accept default routing.
- Capture any API error messages or request IDs here during live testing.

## API Notes

| Date | Endpoint | Chain | Result | Notes |
| --- | --- | --- | --- | --- |
| 2026-04-26 | `/v1/quote` | Sepolia mock | Seeded | No live request made by this scaffold worker. |

## Swap Evidence

| Date | Agent | Token In | Token Out | Tx Hash | Receipt Status | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| TBD | agent-alpha | ETH | USDC | TBD | TBD | Fill after human-reviewed Sepolia swap. |

## Feedback For Uniswap

- Document any Sepolia token support gaps encountered.
- Record approval flow clarity, quote latency, error readability, and transaction construction notes.
- Add concrete suggestions only after live API testing.

## Uniswap API Integration Notes

### Initial Setup & Authentication

_Pending live run. Capture: dashboard signup friction, key issuance time, header name (`x-api-key`), any rate-limit headers observed._

### Quote Endpoint Experience

_Pending live run. Capture: `/v1/quote` p50/p95 latency, response size, route shape, presence/absence of `priceImpact` on Sepolia, any deprecation warnings._

### Swap Execution Experience

_Pending live run. Capture: `/v1/swap` payload requirements, gas fields returned vs needed, permit2 / approval flow on Sepolia, signing surprises in `eth_account`._

### Sepolia Testnet Gaps

_Pending live run. Capture: pools that exist on mainnet but not Sepolia, liquidity issues for WETH/USDC, RPC reliability across providers (publicnode, Alchemy, Infura)._

### Bugs Encountered

_Pending live run. Capture: error response shapes, opaque error codes, mismatches between docs and actual response, any retries needed._
