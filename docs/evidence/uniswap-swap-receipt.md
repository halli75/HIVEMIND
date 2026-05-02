# Uniswap Sepolia Swap Receipt

Date: 2026-05-02
Script: `apps/execution/run_swap.py`
Raw output: `docs/evidence/uniswap-swap-raw.txt`

## Transaction Receipt

| Field | Value |
|-------|-------|
| Chain | Sepolia (`11155111`) |
| Pair | WETH → USDC |
| Amount In | 0.001 WETH (`1000000000000000` wei) |
| Amount Out | 8.139153 USDC (`8139153` units, 6 decimals) |
| Price Impact | 0.01% |
| Slippage Tolerance | 0.50% |
| Min Amount Out | 8.098457 USDC (50 bps slippage) |
| Quote ID | `d8057c9f-47a9-4c90-8a0f-7d7267d7c93f` |
| TX Hash | `0xeaa747da08941805d3fe3bf521163a2ac1e16762caa3803eb6ab6a9f52d047e8` |
| Block | `10776538` |
| Gas Used | `115567` |
| Status | `success` (receipt status = 1) |
| Pool | Uniswap v3 `0xFeEd501c2B21D315F04946F85fC6416B640240b5` (fee tier 100 / 0.01%) |
| Routing | `CLASSIC` (Universal Router) |
| Universal Router | `0x3A9D48AB9751398BbFa63ad67599Bb04e4BdF98b` |
| Swapper | `0xb9123E486471D366210318F9eEB80B934e770caA` |
| Explorer | https://sepolia.etherscan.io/tx/0xeaa747da08941805d3fe3bf521163a2ac1e16762caa3803eb6ab6a9f52d047e8 |

## Post-Swap Wallet State

| Asset | Balance |
|-------|---------|
| ETH | 0.046714056624382221 |
| WETH | 0.001 (1000000000000000 wei — leftover from the 0.002 wrapped before the swap) |
| USDC | 16.882829 |

## Reproduction

```powershell
# 1. Wrap a small amount of Sepolia ETH into WETH (one-time prerequisite)
#    See c:\Users\arnav\AppData\Local\Temp\wrap_eth.py for the helper used here.
#    Wrap tx: 0xe4db80fd7b2ef876eb5541f2c8af513434e142ef113543007bf058a4f2c905c6

# 2. Confirm gating env var is set in .env (DO NOT COMMIT):
#    HIVEMIND_ALLOW_TESTNET_SWAP=true

# 3. Execute the swap (--yes skips the interactive y/N prompt):
$env:PYTHONPATH = 'apps/execution;packages/hivemind-sdk/src'
C:\Python313\python.exe apps/execution/run_swap.py --yes
```

## Notes

- **Fix applied during this run:** the Uniswap `/v1/swap` endpoint rejects
  `permitData: null` with `"permitData" must be of type object`. The
  `UniswapClient.build_swap_tx` body builder now strips any top-level keys with
  `None` values before posting, so quotes that legitimately have no permit
  payload (e.g. WETH already approved to Permit2) submit cleanly.
- The CLASSIC router on Sepolia accepts the swap without a Permit2 signature
  when WETH already carries an active Permit2 allowance from prior testing.
  For first-time swappers, an additional ERC-20 approval to the Permit2
  contract (`0x000000000022D473030F116dDEE9F6B43aC78BA3`) would be required.
