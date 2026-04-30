"""Uniswap Trading API client for Sepolia execution.

Talks to the Uniswap Trading API (`/v1/quote`, `/v1/swap`) and submits
the resulting transactions through a Sepolia RPC. The client intentionally
refuses any non-Sepolia chain id; broader networks belong in a separate
adapter so a misconfigured env can't accidentally trade on mainnet.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from eth_account import Account
from web3 import Web3

SEPOLIA_CHAIN_ID = 11155111
SEPOLIA_WETH = "0xfFf9976782d46CC05630D1f6eBAb18b2324d6B14"
SEPOLIA_USDC = "0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238"


class UniswapClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        rpc_url: str,
        *,
        timeout: float = 20.0,
    ) -> None:
        if not api_key:
            raise ValueError("UNISWAP_API_KEY is required")
        if not base_url:
            raise ValueError("UNISWAP_API_BASE_URL is required")
        if not rpc_url:
            raise ValueError("SEPOLIA_RPC_URL is required")

        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._rpc_url = rpc_url
        self._timeout = timeout
        self._http = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "x-api-key": api_key,
                "accept": "application/json",
                "content-type": "application/json",
            },
        )
        self._w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": timeout}))

    @staticmethod
    def _require_sepolia(chain_id: int) -> None:
        if chain_id != SEPOLIA_CHAIN_ID:
            raise ValueError(
                f"UniswapClient is Sepolia-only; got chain_id={chain_id}"
            )

    async def get_quote(
        self,
        token_in: str,
        token_out: str,
        amount_in: int,
        *,
        chain_id: int = SEPOLIA_CHAIN_ID,
        recipient: str | None = None,
    ) -> dict[str, Any]:
        self._require_sepolia(chain_id)
        if amount_in <= 0:
            raise ValueError("amount_in must be positive")

        body: dict[str, Any] = {
            "type": "EXACT_INPUT",
            "tokenInChainId": chain_id,
            "tokenOutChainId": chain_id,
            "tokenIn": token_in,
            "tokenOut": token_out,
            "amount": str(amount_in),
        }
        if recipient:
            body["swapper"] = recipient

        resp = await self._http.post(f"{self._base_url}/v1/quote", json=body)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Uniswap /v1/quote failed: {resp.status_code} {resp.text}"
            )
        return resp.json()

    def get_quote_sync(
        self,
        token_in: str,
        token_out: str,
        amount_in: int,
        *,
        chain_id: int = SEPOLIA_CHAIN_ID,
        recipient: str | None = None,
    ) -> dict[str, Any]:
        """Synchronous variant of get_quote; safe to call from non-async contexts."""
        self._require_sepolia(chain_id)
        if amount_in <= 0:
            raise ValueError("amount_in must be positive")

        body: dict[str, Any] = {
            "type": "EXACT_INPUT",
            "tokenInChainId": chain_id,
            "tokenOutChainId": chain_id,
            "tokenIn": token_in,
            "tokenOut": token_out,
            "amount": str(amount_in),
        }
        if recipient:
            body["swapper"] = recipient

        headers = {
            "x-api-key": self._api_key,
            "accept": "application/json",
            "content-type": "application/json",
        }
        with httpx.Client(timeout=self._timeout, headers=headers) as client:
            resp = client.post(f"{self._base_url}/v1/quote", json=body)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Uniswap /v1/quote failed: {resp.status_code} {resp.text}"
            )
        return resp.json()

    async def build_swap_tx(self, quote: dict[str, Any], *, signature: str | None = None) -> dict[str, Any]:
        body = dict(quote)
        if signature:
            body["signature"] = signature
        resp = await self._http.post(f"{self._base_url}/v1/swap", json=body)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Uniswap /v1/swap failed: {resp.status_code} {resp.text}"
            )
        return resp.json()

    def _sign_permit(self, permit_data: dict[str, Any], wallet_private_key: str) -> str:
        """Sign a Permit2 EIP-712 permitData object and return the hex signature."""
        account = Account.from_key(wallet_private_key)
        domain = permit_data["domain"]
        types = permit_data["types"]
        values = permit_data["values"]
        signed = account.sign_typed_data(
            domain_data=domain,
            message_types=types,
            message_data=values,
        )
        sig = signed.signature.hex()
        return sig if sig.startswith("0x") else "0x" + sig

    async def execute_swap(
        self,
        quote: dict[str, Any],
        wallet_private_key: str,
    ) -> str:
        if not wallet_private_key:
            raise ValueError("wallet_private_key is required")

        account = Account.from_key(wallet_private_key)

        # Sign Permit2 EIP-712 data if included in quote response
        signature = None
        permit_data = quote.get("permitData")
        if permit_data and permit_data.get("values"):
            signature = self._sign_permit(permit_data, wallet_private_key)

        swap_resp = await self.build_swap_tx(quote, signature=signature)
        swap_tx = swap_resp.get("swap") or swap_resp.get("transaction") or swap_resp

        tx: dict[str, Any] = {
            "to": Web3.to_checksum_address(swap_tx["to"]),
            "data": swap_tx["data"],
            "value": int(swap_tx.get("value", 0) or 0, 16)
            if isinstance(swap_tx.get("value"), str) and swap_tx["value"].startswith("0x")
            else int(swap_tx.get("value", 0) or 0),
            "chainId": int(swap_tx.get("chainId", SEPOLIA_CHAIN_ID)),
            "from": account.address,
        }
        self._require_sepolia(int(tx["chainId"]))

        gas_limit = swap_tx.get("gasLimit") or swap_tx.get("gas")
        if gas_limit is not None:
            tx["gas"] = int(gas_limit, 16) if isinstance(gas_limit, str) and gas_limit.startswith("0x") else int(gas_limit)

        tx["nonce"] = self._w3.eth.get_transaction_count(account.address)

        if "maxFeePerGas" in swap_tx and "maxPriorityFeePerGas" in swap_tx:
            tx["maxFeePerGas"] = int(swap_tx["maxFeePerGas"], 16) if isinstance(swap_tx["maxFeePerGas"], str) and swap_tx["maxFeePerGas"].startswith("0x") else int(swap_tx["maxFeePerGas"])
            tx["maxPriorityFeePerGas"] = int(swap_tx["maxPriorityFeePerGas"], 16) if isinstance(swap_tx["maxPriorityFeePerGas"], str) and swap_tx["maxPriorityFeePerGas"].startswith("0x") else int(swap_tx["maxPriorityFeePerGas"])
        else:
            tx["gasPrice"] = self._w3.eth.gas_price

        if "gas" not in tx:
            tx["gas"] = self._w3.eth.estimate_gas({k: v for k, v in tx.items() if k != "from"} | {"from": account.address})

        signed = account.sign_transaction(tx)
        tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
        return tx_hash.hex() if isinstance(tx_hash, (bytes, bytearray)) else str(tx_hash)

    async def get_tx_receipt(
        self,
        tx_hash: str,
        *,
        poll_interval: float = 3.0,
        timeout: float = 300.0,
    ) -> dict[str, Any]:
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            try:
                receipt = self._w3.eth.get_transaction_receipt(tx_hash)
            except Exception:
                receipt = None

            if receipt is not None:
                return {
                    "status": int(receipt.get("status", 0)),
                    "block_number": int(receipt.get("blockNumber", 0)),
                    "gas_used": int(receipt.get("gasUsed", 0)),
                    "transaction_hash": tx_hash,
                }

            if asyncio.get_event_loop().time() >= deadline:
                raise TimeoutError(f"Receipt for {tx_hash} not found within {timeout}s")

            await asyncio.sleep(poll_interval)

    async def aclose(self) -> None:
        await self._http.aclose()
