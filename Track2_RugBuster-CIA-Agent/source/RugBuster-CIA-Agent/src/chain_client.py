"""
Generic EVM explorer/RPC client used by the CIA Intelligence Engine tools.

Adapted (read-only reference: rugbuster-api/avax_collector_v6.py) from RugBuster's
production Avalanche collector. The original file hardcoded a default SnowTrace API
key and was single-chain (AVAX). This version:
  - takes NO hardcoded secrets — every credential comes from the environment
  - is parametrized by a ChainConfig instead of module-level AVAX constants, so the
    same client works against any Etherscan-family explorer (SnowTrace, BscScan,
    Basescan, ...) by swapping config, which matters for the AMD Radeon Cloud
    portability requirement (dev on one box, run on another).

This module does NOT change any detection thresholds or scoring logic — it only
generalizes how raw on-chain facts are fetched.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests

API_TIMEOUT = float(os.getenv("CIA_API_TIMEOUT", "15"))
RPC_TIMEOUT = float(os.getenv("CIA_RPC_TIMEOUT", "15"))
API_MIN_INTERVAL = float(os.getenv("CIA_API_MIN_INTERVAL", "0.25"))


@dataclass(frozen=True)
class ChainConfig:
    """Everything the client needs to talk to one chain's explorer + RPC."""

    name: str
    rpc_url: str
    explorer_api_url: str
    explorer_api_key_env: str  # env var name holding the key, e.g. "SNOWTRACE_API_KEY"

    @property
    def explorer_api_key(self) -> str:
        return os.getenv(self.explorer_api_key_env, "").strip().strip('"').strip("'")


# Known presets. All values are public endpoints; the actual API key still comes
# from the environment (explorer_api_key_env), never hardcoded here.
CHAIN_PRESETS: dict[str, ChainConfig] = {
    "AVAX": ChainConfig(
        name="AVAX",
        rpc_url=os.getenv("AVAX_RPC", "https://api.avax.network/ext/bc/C/rpc"),
        explorer_api_url=os.getenv(
            "SNOWTRACE_API", "https://api.routescan.io/v2/network/mainnet/evm/43114/etherscan/api"
        ),
        explorer_api_key_env="SNOWTRACE_API_KEY",
    ),
    "BASE": ChainConfig(
        name="BASE",
        rpc_url=os.getenv("BASE_RPC", "https://mainnet.base.org"),
        explorer_api_url=os.getenv("BASESCAN_API", "https://api.basescan.org/api"),
        explorer_api_key_env="BASESCAN_API_KEY",
    ),
    "BNB": ChainConfig(
        name="BNB",
        rpc_url=os.getenv("BNB_RPC", "https://bsc-dataseed.binance.org"),
        explorer_api_url=os.getenv("BSCSCAN_API", "https://api.bscscan.com/api"),
        explorer_api_key_env="BSCSCAN_API_KEY",
    ),
}


class ChainClient:
    """Thin, chain-agnostic Etherscan-family explorer + JSON-RPC client."""

    def __init__(self, config: ChainConfig):
        self.config = config
        self._last_api_call = 0.0

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_api_call
        if elapsed < API_MIN_INTERVAL:
            time.sleep(API_MIN_INTERVAL - elapsed)
        self._last_api_call = time.time()

    def explorer_get(self, params: dict[str, Any]) -> Optional[Any]:
        self._throttle()
        params = {**params, "apikey": self.config.explorer_api_key}
        headers = {"User-Agent": "RugBuster-CIA-Agent/hackathon", "Accept": "application/json"}
        delays = [2, 4, 8]
        for attempt, delay in enumerate(delays):
            try:
                resp = requests.get(
                    self.config.explorer_api_url, params=params, headers=headers, timeout=API_TIMEOUT
                )
                if resp.status_code == 429:
                    time.sleep(delay)
                    continue
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict):
                    status = data.get("status")
                    result = data.get("result")
                    if status == "1":
                        return result
                    msg = data.get("message", "")
                    if "No transactions" in msg or "No records" in msg:
                        return []
                    if result is not None:
                        return result
                return []
            except requests.RequestException:
                time.sleep(delay)
        return None

    def rpc_call(self, method: str, params: list[Any]) -> Optional[Any]:
        try:
            payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
            resp = requests.post(self.config.rpc_url, json=payload, timeout=RPC_TIMEOUT)
            return resp.json().get("result")
        except requests.RequestException:
            return None

    def get_account_transactions(self, address: str, limit: int = 100) -> list:
        result = self.explorer_get(
            {
                "module": "account",
                "action": "txlist",
                "address": address,
                "startblock": 0,
                "endblock": 99999999,
                "page": 1,
                "offset": limit,
                "sort": "asc",
            }
        )
        return result if result else []

    def get_token_transfers(self, contract_address: str, limit: int = 50) -> list:
        result = self.explorer_get(
            {
                "module": "account",
                "action": "tokentx",
                "contractaddress": contract_address,
                "startblock": 0,
                "endblock": 99999999,
                "page": 1,
                "offset": limit,
                "sort": "asc",
            }
        )
        return result if result else []

    def get_token_holders(self, contract_address: str, limit: int = 10) -> list:
        result = self.explorer_get(
            {
                "module": "token",
                "action": "tokenholderlist",
                "contractaddress": contract_address,
                "page": 1,
                "offset": limit,
            }
        )
        return result if result else []

    def get_contract_bytecode(self, contract_address: str) -> str:
        result = self.rpc_call("eth_getCode", [contract_address, "latest"])
        return result or "0x"

    def get_account_age_days(self, address: str) -> float:
        txs = self.get_account_transactions(address, limit=1000)
        if not txs:
            return 0.0
        oldest_ts = int(txs[0].get("timeStamp", 0))
        if not oldest_ts:
            return 0.0
        return round((time.time() - oldest_ts) / 86400, 1)


def get_chain_client(chain: str) -> ChainClient:
    chain = chain.upper()
    if chain not in CHAIN_PRESETS:
        raise ValueError(f"Unsupported chain: {chain}. Known: {list(CHAIN_PRESETS)}")
    return ChainClient(CHAIN_PRESETS[chain])
