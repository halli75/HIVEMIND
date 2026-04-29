import asyncio
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

EXECUTION_ROOT = Path(__file__).resolve().parents[1]
if str(EXECUTION_ROOT) not in sys.path:
    sys.path.insert(0, str(EXECUTION_ROOT))

try:
    import eth_account  # noqa: F401
    import httpx  # noqa: F401
    import web3  # noqa: F401
except ModuleNotFoundError:
    class _FakeAccount:
        address = "0x0000000000000000000000000000000000000001"

    class _FakeAccountFactory:
        @staticmethod
        def from_key(_private_key):
            return _FakeAccount()

    class _FakeWeb3:
        @staticmethod
        def to_checksum_address(address):
            return address

        @staticmethod
        def HTTPProvider(*_args, **_kwargs):
            return object()

    sys.modules.setdefault("eth_account", SimpleNamespace(Account=_FakeAccountFactory))
    sys.modules.setdefault("httpx", SimpleNamespace(AsyncClient=object))
    sys.modules.setdefault("web3", SimpleNamespace(Web3=_FakeWeb3))

from uniswap_client import UniswapClient  # noqa: E402


def test_execute_swap_refuses_non_sepolia_transaction() -> None:
    client = UniswapClient.__new__(UniswapClient)

    async def fake_build_swap_tx(_quote):
        return {
            "to": "0x000000000000000000000000000000000000dEaD",
            "data": "0x",
            "value": 0,
            "chainId": 1,
        }

    client.build_swap_tx = fake_build_swap_tx

    with pytest.raises(ValueError, match="Sepolia-only"):
        asyncio.run(
            client.execute_swap(
                {},
                "0x" + "1".rjust(64, "0"),
            )
        )
