# Uniswap Integration Feedback

## Integration Summary

- Mode: live Sepolia end-to-end — quote, swap submission, and receipt all verified on chain.
- Target flow: quote, automated swap (`--yes` flag for non-interactive runs), receipt capture.
- Current artifacts: `docs/evidence/uniswap-swap-receipt.md`, raw script output in `docs/evidence/uniswap-swap-raw.txt`, plus `runs/proof-20260429-161627/06b-uniswap-quote-formatted.txt`.

## What Worked

- Placeholder quote schema captures amount in, amount out, route, price impact, approval state, and transaction shape.
- Environment variables keep API key, swapper, and token addresses out of source control.
- Live `/v1/quote` returned a Sepolia WETH to USDC route for `0.001 WETH`.
- `run_swap.py` correctly refused to sign when `HIVEMIND_ALLOW_TESTNET_SWAP=true` was not enabled.
- Live Sepolia swap submitted and confirmed in block `10776538` (status 1) — `0.001 WETH -> 8.139153 USDC`, gas used `115567`.
- New `--yes` / `HIVEMIND_SWAP_SKIP_CONFIRM` flag lets the script run non-interactively from CI/demo automation while keeping the interactive prompt as the default safety net.

## Issues / Questions

- Confirm whether the selected route should force protocol filters or accept default routing.
- Quote response route is nested, so client formatting needed recursive `amountOut` extraction for readable demo output.
- `/v1/swap` rejects bodies whose `permitData` is JSON `null` with `"permitData" must be of type object`, even though `/v1/quote` returns `permitData: null` when no permit is required. Workaround: strip top-level keys whose value is `None` before posting (now applied in `UniswapClient.build_swap_tx`). Suggest the API either accepts `null` or omits the field in the quote response when no permit is needed.

## API Notes

| Date | Endpoint | Chain | Result | Notes |
| --- | --- | --- | --- | --- |
| 2026-04-26 | `/v1/quote` | Sepolia mock | Seeded | No live request made by this scaffold worker. |
| 2026-04-29 | `/v1/quote` | Sepolia | Live success | Quote id `3301ca8c-df76-4c88-a6ee-efc2ebfef35d`; `0.001 WETH -> 8.75588 USDC`; price impact `0.02`. |
| 2026-04-29 | `run_swap.py` | Sepolia | Guarded | Refused to sign because `HIVEMIND_ALLOW_TESTNET_SWAP=true` was not enabled. |
| 2026-05-02 | `run_swap.py --yes` | Sepolia | **Live success** | tx `0xeaa747da08941805d3fe3bf521163a2ac1e16762caa3803eb6ab6a9f52d047e8`, block `10776538`, `0.001 WETH -> 8.139153 USDC`, status=1 confirmed. Quote id `d8057c9f-47a9-4c90-8a0f-7d7267d7c93f`. |

## Swap Evidence

Swap executed 2026-05-02. Full output in [`docs/evidence/uniswap-swap-receipt.md`](docs/evidence/uniswap-swap-receipt.md).

- TX: `0xeaa747da08941805d3fe3bf521163a2ac1e16762caa3803eb6ab6a9f52d047e8`
- Explorer: https://sepolia.etherscan.io/tx/0xeaa747da08941805d3fe3bf521163a2ac1e16762caa3803eb6ab6a9f52d047e8
- Status: `success` (receipt status = 1)

| Date | Agent | Token In | Token Out | Tx Hash | Receipt Status | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-04-29 | agent-014 | WETH | USDC | Not submitted | Gated | Quote only; no transaction signed. |
| 2026-05-02 | manual rehearsal | WETH | USDC | `0xeaa747da08941805d3fe3bf521163a2ac1e16762caa3803eb6ab6a9f52d047e8` | success (1) | `0.001 WETH -> 8.139153 USDC`, block `10776538`, gas `115567`, Universal Router `0x3A9D48AB9751398BbFa63ad67599Bb04e4BdF98b`. |

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

Live Sepolia submission worked end-to-end after the `permitData: null` workaround
was added to `UniswapClient.build_swap_tx`. The CLASSIC routing path went through
the Universal Router and confirmed in a single block (~12 seconds wall-clock from
submission to receipt). Submission remains gated behind
`HIVEMIND_ALLOW_TESTNET_SWAP=true`; non-interactive runs require the new
`--yes` / `HIVEMIND_SWAP_SKIP_CONFIRM=true` opt-in so demos and CI can drive the
script without keyboard input while leaving the interactive prompt as the
default for ad-hoc operators.

### Sepolia Testnet Gaps

WETH/USDC liquidity was sufficient for a `0.001 WETH` quote in this rehearsal.

### Bugs Encountered

Client formatting bug: the first quote-only output printed `amount out: ?` because `amountOut` was nested inside the route. Fixed by recursively extracting `amountOut`.
