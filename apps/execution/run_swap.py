"""Sepolia live swap. Quotes, prompts y/n, signs and submits, polls receipt.

Requires testnet ETH in the wallet that owns WALLET_PRIVATE_KEY. Refuses
any chain other than Sepolia.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from decimal import Decimal

from dotenv import load_dotenv
from eth_account import Account

from uniswap_client import (
    SEPOLIA_CHAIN_ID,
    SEPOLIA_USDC,
    SEPOLIA_WETH,
    UniswapClient,
)


DEFAULT_AMOUNT_IN_WEI = int(Decimal("0.001") * Decimal(10**18))
ALLOW_SWAP_ENV = "HIVEMIND_ALLOW_TESTNET_SWAP"
SKIP_CONFIRM_ENV = "HIVEMIND_SWAP_SKIP_CONFIRM"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Quote and (optionally) submit a Sepolia WETH->USDC swap via the Uniswap Trading API.",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help=(
            "Skip the interactive [y/N] confirmation prompt. Equivalent to "
            f"setting {SKIP_CONFIRM_ENV}=true in the environment."
        ),
    )
    return parser.parse_args(argv)


def _skip_confirm(args: argparse.Namespace) -> bool:
    if args.yes:
        return True
    return os.environ.get(SKIP_CONFIRM_ENV, "").strip().lower() in {"1", "true", "yes"}


def _find_first_key(value: object, key: str) -> object | None:
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for child in value.values():
            found = _find_first_key(child, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_first_key(child, key)
            if found is not None:
                return found
    return None


def _format_amount_out(quote: dict, fallback_decimals: int = 6) -> str:
    inner = quote.get("quote") or {}
    decimals_str = inner.get("amountOutDecimals")
    if decimals_str:
        return str(decimals_str)
    raw = inner.get("amountOut") or quote.get("amountOut") or _find_first_key(quote, "amountOut")
    if raw is None:
        return "?"
    return str(Decimal(int(raw)) / (Decimal(10) ** fallback_decimals))


def _format_weth(amount_in_wei: int) -> str:
    return str(Decimal(amount_in_wei) / Decimal(10**18)).rstrip("0").rstrip(".")


def _amount_in_wei() -> int:
    value = os.environ.get("UNISWAP_AMOUNT_IN_WEI", "").strip()
    if not value:
        return DEFAULT_AMOUNT_IN_WEI
    amount = int(value)
    if amount <= 0:
        raise ValueError("UNISWAP_AMOUNT_IN_WEI must be positive")
    return amount


async def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _parse_args(argv)
    skip_confirm = _skip_confirm(args)

    if os.environ.get(ALLOW_SWAP_ENV, "").strip().lower() not in {"1", "true", "yes"}:
        print(f"{ALLOW_SWAP_ENV}=true is required before submitting a Sepolia swap.", file=sys.stderr)
        return 1

    api_key = os.environ.get("UNISWAP_API_KEY", "").strip()
    base_url = os.environ.get(
        "UNISWAP_API_BASE_URL", "https://trade-api.gateway.uniswap.org"
    ).strip()
    rpc_url = os.environ.get(
        "SEPOLIA_RPC_URL", "https://ethereum-sepolia-rpc.publicnode.com"
    ).strip()
    private_key = os.environ.get("WALLET_PRIVATE_KEY", "").strip()

    if not api_key:
        print("UNISWAP_API_KEY missing in .env", file=sys.stderr)
        return 1
    if not private_key:
        print("WALLET_PRIVATE_KEY missing in .env", file=sys.stderr)
        return 1

    swapper = Account.from_key(private_key).address
    try:
        amount_in = _amount_in_wei()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    client = UniswapClient(api_key=api_key, base_url=base_url, rpc_url=rpc_url)
    try:
        quote = await client.get_quote(
            SEPOLIA_WETH,
            SEPOLIA_USDC,
            amount_in,
            chain_id=SEPOLIA_CHAIN_ID,
            recipient=swapper,
        )
    except Exception as exc:
        print(f"Quote failed: {exc}", file=sys.stderr)
        await client.aclose()
        return 1

    inner = quote.get("quote") or {}
    route = inner.get("route") or quote.get("route") or ["WETH", "USDC"]
    quote_id = inner.get("quoteId") or quote.get("quoteId") or "?"
    price_impact = inner.get("priceImpact") or inner.get("priceImpactBps") or "n/a"

    print("=== Uniswap Sepolia Quote ===")
    print(f"swapper:      {swapper}")
    print(f"amount in:    {_format_weth(amount_in)} WETH ({amount_in} wei)")
    print(f"route:        {route if isinstance(route, list) else json.dumps(route)}")
    print(f"amount out:   {_format_amount_out(quote)} USDC")
    print(f"price impact: {price_impact}")
    print(f"quote id:     {quote_id}")
    print()

    if skip_confirm:
        print("Submit swap on Sepolia? [y/N] y  (auto-confirmed via --yes / HIVEMIND_SWAP_SKIP_CONFIRM)")
    else:
        answer = input("Submit swap on Sepolia? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted. No transaction sent.")
            await client.aclose()
            return 0

    try:
        tx_hash = await client.execute_swap(quote, private_key)
    except Exception as exc:
        print(f"Swap submission failed: {exc}", file=sys.stderr)
        await client.aclose()
        return 1

    if not tx_hash.startswith("0x"):
        tx_hash = "0x" + tx_hash

    print(f"tx hash:      {tx_hash}")
    print(f"explorer:     https://sepolia.etherscan.io/tx/{tx_hash}")
    print("Polling for receipt...")

    try:
        receipt = await client.get_tx_receipt(tx_hash)
    except Exception as exc:
        print(f"Receipt poll failed: {exc}", file=sys.stderr)
        await client.aclose()
        return 1

    status_label = "success" if receipt["status"] == 1 else "reverted"
    print(f"status:       {status_label} ({receipt['status']})")
    print(f"block:        {receipt['block_number']}")
    print(f"gas used:     {receipt['gas_used']}")

    await client.aclose()
    return 0 if receipt["status"] == 1 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
