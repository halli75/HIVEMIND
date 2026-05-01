"""Sepolia quote-only smoke test. Prints a Uniswap quote and exits.

No transaction is signed or broadcast. Safe to run before the wallet
holds any testnet ETH.
"""

from __future__ import annotations

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


def _resolve_swapper(env_key: str | None) -> str:
    if env_key:
        return Account.from_key(env_key).address
    addr = os.environ.get("UNISWAP_SWAPPER_ADDRESS", "").strip()
    if not addr:
        print(
            "Set WALLET_PRIVATE_KEY (preferred) or UNISWAP_SWAPPER_ADDRESS in .env",
            file=sys.stderr,
        )
        sys.exit(1)
    return addr


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


async def main() -> int:
    load_dotenv()

    api_key = os.environ.get("UNISWAP_API_KEY", "").strip()
    base_url = os.environ.get(
        "UNISWAP_API_BASE_URL", "https://trade-api.gateway.uniswap.org"
    ).strip()
    rpc_url = os.environ.get(
        "SEPOLIA_RPC_URL", "https://ethereum-sepolia-rpc.publicnode.com"
    ).strip()
    private_key = os.environ.get("WALLET_PRIVATE_KEY", "").strip() or None

    if not api_key:
        print("UNISWAP_API_KEY missing in .env", file=sys.stderr)
        return 1

    swapper = _resolve_swapper(private_key)
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
    print("Quote-only mode. No transaction will be submitted.")

    await client.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
