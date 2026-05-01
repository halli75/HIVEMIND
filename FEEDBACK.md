# Uniswap Integration Feedback

## Integration Summary

- Mode: live Sepolia quote verified; swap remains gated.
- Target flow: quote, human-reviewed swap, receipt capture.
- Current artifacts: `runs/proof-20260429-161627/06b-uniswap-quote-formatted.txt` and API quote in `02-scenario.json`.

## What Worked

- Placeholder quote schema captures amount in, amount out, route, price impact, approval state, and transaction shape.
- Environment variables keep API key, swapper, and token addresses out of source control.
- Live `/v1/quote` returned a Sepolia WETH to USDC route for `0.001 WETH`.
- `run_swap.py` correctly refused to sign when `HIVEMIND_ALLOW_TESTNET_SWAP=true` was not enabled.

## Issues / Questions

- Confirm whether the selected route should force protocol filters or accept default routing.
- Quote response route is nested, so client formatting needed recursive `amountOut` extraction for readable demo output.
- Approval flow is not yet proven because no Sepolia swap was submitted in this rehearsal.

## API Notes

| Date | Endpoint | Chain | Result | Notes |
| --- | --- | --- | --- | --- |
| 2026-04-26 | `/v1/quote` | Sepolia mock | Seeded | No live request made by this scaffold worker. |
| 2026-04-29 | `/v1/quote` | Sepolia | Live success | Quote id `3301ca8c-df76-4c88-a6ee-efc2ebfef35d`; `0.001 WETH -> 8.75588 USDC`; price impact `0.02`. |
| 2026-04-29 | `run_swap.py` | Sepolia | Guarded | Refused to sign because `HIVEMIND_ALLOW_TESTNET_SWAP=true` was not enabled. |

## Swap Evidence

| Date | Agent | Token In | Token Out | Tx Hash | Receipt Status | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-04-29 | agent-014 | WETH | USDC | Not submitted | Gated | Quote only; no transaction signed. |

## Feedback For Uniswap

- Document any Sepolia token support gaps encountered.
- Record approval flow clarity, quote latency, error readability, and transaction construction notes.
- Add concrete suggestions only after live API testing.

## Uniswap API Integration Notes

### Initial Setup & Authentication

API key authentication worked with the `x-api-key` header. No additional auth ceremony was needed for quote-only access.

### Quote Endpoint Experience

Quote endpoint returned a usable Sepolia route and `priceImpact`. The route shape is nested enough that demo tooling should not assume `amountOut` is top-level.

### Swap Execution Experience

Not exercised yet. Swap submission remains behind `HIVEMIND_ALLOW_TESTNET_SWAP=true` and the script's explicit prompt.

### Sepolia Testnet Gaps

WETH/USDC liquidity was sufficient for a `0.001 WETH` quote in this rehearsal.

### Bugs Encountered

Client formatting bug: the first quote-only output printed `amount out: ?` because `amountOut` was nested inside the route. Fixed by recursively extracting `amountOut`.
