"""Crystallization pipeline: winner → encrypt → upload → iNFT mint.

Glue layer that takes a leaderboard-winning agent, encrypts the strategy
payload, ships the ciphertext to 0G Storage (or a local fallback), and mints
an ERC-721-compatible HivemindINFT with ERC-7857-style private metadata hooks.

The pipeline is duck-typed across providers so the SDK keeps no mandatory
runtime dependency on web3 or cryptography. The two heavy deps are imported
lazily inside ``crystallize`` and ``_derive_fernet_key``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from typing import Any, Protocol


def _to_hex_address(value: str) -> str:
    return value if value.startswith("0x") else f"0x{value}"


class Storage0GProvider(Protocol):
    """Storage backend for the encrypted intelligence blob."""

    def upload(self, blob: bytes) -> str:
        """Persist ``blob`` and return a storage reference (URI / CID)."""


class Web3Provider(Protocol):
    """Mintable contract surface for HivemindINFT.mintAgent."""

    def mint_agent(
        self,
        *,
        to: str,
        storage_uri: str,
        storage_hash: str,
        model: str,
        strategy_digest: str,
        aiq: int,
    ) -> dict[str, Any]:
        """Submit mintAgent and return ``{tx_hash, token_id}`` once mined."""


class LocalStorageUploadProvider:
    """Mock 0G Storage that writes ciphertext under a local directory.

    Returns a deterministic ``mock://0g-storage/<sha256>`` reference. Used as
    the default when ``HIVEMIND_USE_MOCK_0G`` is truthy or when a live
    storage client isn't wired up.
    """

    def __init__(self, *, root: str | os.PathLike[str] | None = None) -> None:
        self._root = os.fspath(root) if root is not None else None

    def upload(self, blob: bytes) -> str:
        digest = hashlib.sha256(blob).hexdigest()
        if self._root is not None:
            os.makedirs(self._root, exist_ok=True)
            path = os.path.join(self._root, f"{digest}.bin")
            with open(path, "wb") as handle:
                handle.write(blob)
        return f"mock://0g-storage/{digest}"


class MockWeb3Provider:
    """Deterministic mock mint that returns a synthetic tx hash + token id.

    The token_id increments per pipeline instance; the tx hash is sha256 over
    the call args plus a tiny entropy nonce so re-mints don't alias.
    """

    def __init__(self) -> None:
        self._next_token_id = 1

    def mint_agent(
        self,
        *,
        to: str,
        storage_uri: str,
        storage_hash: str,
        model: str,
        strategy_digest: str,
        aiq: int,
    ) -> dict[str, Any]:
        token_id = self._next_token_id
        self._next_token_id += 1
        nonce = secrets.token_hex(4)
        payload = (
            f"{to}|{storage_uri}|{storage_hash}|{model}|{strategy_digest}|"
            f"{aiq}|{token_id}|{nonce}"
        )
        tx_hash = "0x" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return {"tx_hash": tx_hash, "token_id": token_id}


class Web3MintProvider:
    """Real mint path backed by web3.py. Imports lazily.

    Resolves the AgentCrystallized event from the receipt logs to extract the
    minted ``token_id``.
    """

    def __init__(
        self,
        *,
        web3_provider: Any,
        contract_address: str,
        contract_abi: list[dict[str, Any]],
        owner_private_key: str,
    ) -> None:
        from web3 import Web3  # type: ignore[import-not-found]

        self._web3 = web3_provider if isinstance(web3_provider, Web3) else Web3(web3_provider)
        self._account = self._web3.eth.account.from_key(owner_private_key)
        self._contract = self._web3.eth.contract(
            address=Web3.to_checksum_address(contract_address),
            abi=contract_abi,
        )

    def mint_agent(
        self,
        *,
        to: str,
        storage_uri: str,
        storage_hash: str,
        model: str,
        strategy_digest: str,
        aiq: int,
    ) -> dict[str, Any]:
        from web3 import Web3  # type: ignore[import-not-found]

        nonce = self._web3.eth.get_transaction_count(self._account.address)
        tx = self._contract.functions.mintAgent(
            Web3.to_checksum_address(to),
            storage_uri,
            storage_hash,
            model,
            strategy_digest,
            aiq,
        ).build_transaction({
            "from": self._account.address,
            "nonce": nonce,
        })
        signed = self._account.sign_transaction(tx)
        raw_transaction = getattr(signed, "rawTransaction", None) or signed.raw_transaction
        tx_hash = self._web3.eth.send_raw_transaction(raw_transaction)
        receipt = self._web3.eth.wait_for_transaction_receipt(tx_hash)
        token_id = self._extract_token_id(receipt)
        return {"tx_hash": tx_hash.hex(), "token_id": token_id}

    def _extract_token_id(self, receipt: Any) -> int:
        events = self._contract.events.AgentCrystallized().process_receipt(receipt)
        if not events:
            raise RuntimeError("AgentCrystallized event missing from receipt")
        return int(events[0]["args"]["tokenId"])


def _derive_fernet_key(owner_private_key: str) -> bytes:
    from cryptography.hazmat.primitives import hashes  # type: ignore[import-not-found]
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF  # type: ignore[import-not-found]

    secret = owner_private_key.removeprefix("0x").encode("utf-8")
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"hivemind-crystallize-v1",
        info=b"fernet-key",
    ).derive(secret)
    return base64.urlsafe_b64encode(derived)


class CrystallizationPipeline:
    """Crystallize a swarm winner into an iNFT.

    Composition:
      - ``storage_provider``: anything with ``upload(bytes) -> str``
      - ``web3_provider``: anything with ``mint_agent(...) -> {tx_hash, token_id}``,
        OR a raw web3.py provider if ``contract_address``/``contract_abi``/``owner_private_key``
        are supplied (in which case the pipeline wraps it in ``Web3MintProvider``).

    Pass ``HIVEMIND_USE_MOCK_0G=true`` and the API constructs this with
    ``LocalStorageUploadProvider`` + ``MockWeb3Provider`` so the demo runs
    without any chain or 0G credentials.
    """

    def __init__(
        self,
        *,
        storage_provider: Storage0GProvider,
        web3_provider: Any,
        contract_address: str | None = None,
        contract_abi: list[dict[str, Any]] | None = None,
        owner_private_key: str | None = None,
        owner_address: str | None = None,
        royalty_bps: int = 500,
    ) -> None:
        self._storage = storage_provider
        self._owner_private_key = owner_private_key
        self._owner_address = owner_address
        self._royalty_bps = royalty_bps

        if hasattr(web3_provider, "mint_agent"):
            self._minter: Web3Provider = web3_provider
        else:
            if contract_address is None or contract_abi is None or owner_private_key is None:
                raise ValueError(
                    "web3_provider missing mint_agent() — provide contract_address, contract_abi, and owner_private_key for Web3MintProvider"
                )
            self._minter = Web3MintProvider(
                web3_provider=web3_provider,
                contract_address=contract_address,
                contract_abi=contract_abi,
                owner_private_key=owner_private_key,
            )

    async def crystallize(self, winner: dict[str, Any], simulation_run_id: str) -> dict[str, Any]:
        strategy_payload = self._serialize_winner(winner, simulation_run_id)
        blob = json.dumps(strategy_payload, sort_keys=True).encode("utf-8")

        ciphertext = self._encrypt(blob)
        storage_hash = "0x" + hashlib.sha256(ciphertext).hexdigest()
        storage_ref = self._storage.upload(ciphertext)

        metadata = {
            "name": f"HIVEMIND Agent #{winner.get('agent_id', 'unknown')}",
            "archetype": winner.get("archetype"),
            "composite_score": winner.get("composite_score"),
            "simulation_run_id": simulation_run_id,
            "intelligence_ref": storage_ref,
        }
        metadata_bytes = json.dumps(metadata, sort_keys=True).encode("utf-8")
        metadata_uri = "data:application/json;base64," + base64.b64encode(metadata_bytes).decode(
            "ascii"
        )

        owner_address = winner.get("owner_address") or self._owner_address
        if not owner_address:
            raise ValueError("winner has no owner_address and pipeline has no default owner_address")

        aiq = int(round(winner.get("aiq") or winner.get("decision_weights", {}).get("aiq") or 0))
        model = str(winner.get("model") or "local-deterministic")
        strategy_digest = f"sha256:{storage_hash[2:18]}"

        mint_result = self._minter.mint_agent(
            to=_to_hex_address(owner_address),
            storage_uri=storage_ref,
            storage_hash=storage_hash,
            model=model,
            strategy_digest=strategy_digest,
            aiq=aiq,
        )

        return {
            "token_id": int(mint_result["token_id"]),
            "tx_hash": mint_result["tx_hash"],
            "storage_ref": storage_ref,
            "storage_hash": storage_hash,
            "metadata_uri": metadata_uri,
            "intelligence_ref": storage_ref,
            "model": model,
            "strategy_digest": strategy_digest,
            "aiq": aiq,
            "owner": _to_hex_address(owner_address),
            "composite_score": winner.get("composite_score"),
            "archetype": winner.get("archetype"),
            "simulation_run_id": simulation_run_id,
            "royalty_bps": self._royalty_bps,
        }

    @staticmethod
    def _serialize_winner(winner: dict[str, Any], simulation_run_id: str) -> dict[str, Any]:
        return {
            "schema": "hivemind.intelligence.v1",
            "simulation_run_id": simulation_run_id,
            "crystallized_at": int(time.time()),
            "agent_id": winner.get("agent_id"),
            "archetype": winner.get("archetype"),
            "tier": winner.get("tier"),
            "decision_weights": winner.get("decision_weights", {}),
            "archetype_params": winner.get("archetype_params", {}),
            "scoring_breakdown": {
                "sharpe_ratio": winner.get("sharpe_ratio"),
                "max_drawdown": winner.get("max_drawdown"),
                "consistency": winner.get("consistency"),
                "composite_score": winner.get("composite_score"),
            },
        }

    def _encrypt(self, blob: bytes) -> bytes:
        if not self._owner_private_key:
            # No key configured (e.g., pure mock with no chain) — derive a
            # deterministic placeholder so downstream upload still has stable
            # ciphertext bytes for testing.
            self._owner_private_key = (
                "0x" + hashlib.sha256(b"hivemind-mock-owner").hexdigest()
            )
        from cryptography.fernet import Fernet  # type: ignore[import-not-found]

        key = _derive_fernet_key(self._owner_private_key)
        return Fernet(key).encrypt(blob)
