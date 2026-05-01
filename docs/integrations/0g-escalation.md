# 0G Storage Escalation Notes

## Summary

Historical blocker record from 2026-04-29. HIVEMIND could run live 0G Compute and reach the 0G Storage turbo indexer, but the live iNFT mint was blocked before the Galileo mint transaction because encrypted strategy upload could not complete.

Resolved on 2026-05-01 by the direct storage-node fallback. Current proof: `docs/evidence/0g-inft-mint-2026-05-01.md`.

## Environment

- Date: 2026-04-29
- Chain: 0G Galileo, chain ID `16602`
- Public deployer: `0xb9123E486471D366210318F9eEB80B934e770caA`
- Wallet balance at retry: `1.990395423983191992 OG`
- Contract: `0x55924a84BD2A5f5e4C63885a2d8f4c129E897A36`
- SDK: `@0glabs/0g-ts-sdk@0.3.3`

## Standard Indexer Result

- Endpoint: `https://indexer-storage-testnet-standard.0g.ai`
- Result: 4 attempts returned HTTP 503.
- API response: `detail.status="storage_unavailable"`.
- Evidence: ignored local file `runs/proof-20260429-161627/04b-mint-retry-error.json`.

## Turbo Indexer Result

- Endpoint: `https://indexer-storage-testnet-turbo.0g.ai`
- Result: indexer selected storage nodes and prepared upload data, then Flow submit reverted.
- Selected nodes:
  - `http://34.83.53.209:5678`
  - `http://34.169.28.106:5678`
- Flow address returned by node status: `0x22e03a6a89b950f1c82ec5e74f8eca321a105296`
- Market address: `0x26c8f001C94b0fd287DB5397F05EF8Bd8EF2cF4B`
- Error: `Failed to submit transaction: ProviderError: execution reverted`
- Evidence: ignored local file `runs/proof-turbo-20260429-165426/03-mint-turbo-error.json`.

## Flow Static Call Probe

Static calls to `flow.submit(submission)` using exact fee and 10 percent padded fee both reverted with no data:

- Exact fee: `30733644962`
- Padded fee: `33807009459`
- Exact result: `execution reverted (no data present; likely require(false) occurred`
- Padded result: `execution reverted (no data present; likely require(false) occurred`
- Evidence: ignored local file `runs/proof-turbo-20260429-165426/05-flow-staticcall-probe.json`.

## Follow-Up Implementation

The mint script now has a direct storage-node fallback that targets the wrapped Flow `submit(((Submission),address))` ABI before segment upload. The 2026-05-01 proof confirms this path through storage upload and Galileo mint.

## What Is Not Included

- No private keys.
- No bearer/API tokens.
- No encrypted strategy keyfiles.
- No generated identity files.
