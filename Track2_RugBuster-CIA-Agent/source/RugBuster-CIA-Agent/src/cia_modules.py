"""
CIA Intelligence Engine — the 7 detection modules, ported for the hackathon agent.

Source of truth (read-only reference, NOT modified in place):
  rugbuster-api/avax_collector_v6.py  (functions trace_funding_origin_avax,
  get_deployment_latency_avax, analyze_transaction_entropy_avax,
  detect_wash_pattern_avax, analyze_holder_cluster_avax,
  detect_contract_backdoor_avax, analyze_holder_concentration_avax)

Per hackathon task scope, this file does NOT change any detection thresholds,
scoring math, or heuristics — it only:
  1. swaps the AVAX-only module-level `requests` calls for the chain-agnostic
     `ChainClient` from chain_client.py, so the same code runs against any
     configured chain instead of being copy-pasted per chain, and
  2. drops the direct `psycopg2` / dataset-collection side effects (this agent
     scores on demand, it does not write training records to Postgres).

Each function below is exposed as a LangChain Tool in tools.py.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .chain_client import ChainClient

# ---------------------------------------------------------------------------
# Module 6: Contract Backdoor Detection
# (same BACKDOOR_SIGNATURES bytecode selector table as production)
# ---------------------------------------------------------------------------

BACKDOOR_SIGNATURES = {
    "40c10f19": "mint(address,uint256)",
    "a0712d68": "mint(uint256)",
    "449a52f8": "mintTo(address,uint256)",
    "2e1a7d4d": "withdraw(uint256)",
    "51cff8d9": "withdrawToken(address)",
    "3659cfe6": "upgradeTo(address)",
    "4f1ef286": "upgradeToAndCall(address,bytes)",
    "5c60da1b": "implementation()",
    "8456cb59": "pause()",
    "3f4ba83a": "unpause()",
    "5c975abb": "paused()",
    "044df020": "blacklist(address)",
    "537df3b6": "unBlacklist(address)",
    "fe575a87": "isBlacklisted(address)",
}


def detect_contract_backdoor(client: ChainClient, contract_address: str) -> dict[str, Any]:
    """Module 6: scan deployed bytecode for backdoor function selectors."""
    result = {
        "has_backdoor": False,
        "backdoor_functions": [],
        "has_upgrade_authority": False,
        "has_pause_function": False,
        "has_mint_function": False,
        "has_drain_function": False,
        "has_blacklist": False,
        "is_proxy": False,
        "backdoor_risk_score": 0,
    }
    try:
        bytecode = client.get_contract_bytecode(contract_address)
        if bytecode and len(bytecode) > 10:
            bytecode_clean = bytecode.lower().replace("0x", "")
            for sig, func_name in BACKDOOR_SIGNATURES.items():
                if sig in bytecode_clean:
                    result["backdoor_functions"].append(func_name)
                    lowered = func_name.lower()
                    if "upgradeto" in lowered or "implementation" in lowered:
                        result["is_proxy"] = True
                        result["has_upgrade_authority"] = True
                    if "pause" in lowered:
                        result["has_pause_function"] = True
                    if "mint" in lowered:
                        result["has_mint_function"] = True
                    if "withdraw" in lowered or "drain" in lowered:
                        result["has_drain_function"] = True
                    if "blacklist" in lowered:
                        result["has_blacklist"] = True
            result["has_backdoor"] = len(result["backdoor_functions"]) > 0
    except Exception:
        pass

    danger_count = sum(
        [
            result["has_upgrade_authority"],
            result["has_mint_function"],
            result["has_drain_function"],
            result["has_pause_function"],
            result["has_blacklist"],
            result["is_proxy"],
        ]
    )
    result["backdoor_risk_score"] = min(danger_count * 20, 100)
    return result


def analyze_holder_concentration(client: ChainClient, contract_address: str) -> dict[str, Any]:
    """Module 7: top-holder share of supply."""
    result = {"top5_pct": 0.0, "top1_pct": 0.0, "is_concentrated": False, "concentration_risk": "LOW"}
    holders = client.get_token_holders(contract_address)
    if not holders or len(holders) < 2:
        return result
    try:
        amounts = []
        for h in holders[:10]:
            qty = h.get("TokenHolderQuantity", "0") or "0"
            amounts.append(float(str(qty).replace(",", "")))
        total = sum(amounts)
        if total == 0:
            return result
        top5 = sum(amounts[:5])
        top1 = amounts[0]
        result["top5_pct"] = round(top5 / total * 100, 1)
        result["top1_pct"] = round(top1 / total * 100, 1)
        result["is_concentrated"] = result["top5_pct"] > 80
        if result["top5_pct"] > 90:
            result["concentration_risk"] = "CRITICAL"
        elif result["top5_pct"] > 80:
            result["concentration_risk"] = "HIGH"
        elif result["top5_pct"] > 60:
            result["concentration_risk"] = "MEDIUM"
        else:
            result["concentration_risk"] = "LOW"
    except Exception:
        pass
    return result


def trace_funding_origin(client: ChainClient, deployer: str, depth: int = 3) -> dict[str, Any]:
    """Module 1: walk the deployer's funding chain up to `depth` hops."""
    result = {
        "master_wallet": "",
        "hop_count": 0,
        "is_fresh_wallet": False,
        "funding_chain": [deployer],
        "all_fresh": False,
        "wallet_ages_days": [],
    }
    current = deployer
    chain_trace = [deployer]

    for hop in range(depth):
        txs = client.get_account_transactions(current, limit=10)
        if not txs:
            result["is_fresh_wallet"] = True
            break
        first_tx = txs[0]
        sender = first_tx.get("from", "").lower()
        if sender and sender != current.lower() and sender != "0x0000000000000000000000000000000000000000":
            chain_trace.append(sender)
            current = sender
            result["hop_count"] = hop + 1
        else:
            break

    result["funding_chain"] = chain_trace
    result["master_wallet"] = chain_trace[-1] if len(chain_trace) > 1 else ""

    ages = [client.get_account_age_days(addr) for addr in chain_trace[1:]]
    result["wallet_ages_days"] = ages
    result["all_fresh"] = all(a < 7 for a in ages) if ages else False
    return result


def get_deployment_latency(client: ChainClient, contract_address: str, deploy_timestamp: int) -> dict[str, Any]:
    """Module 2: time between contract deploy and first buy (sniper detection)."""
    result = {"deploy_time": deploy_timestamp, "first_buy_time": 0, "latency_ms": -1, "is_sniped": False}
    transfers = client.get_token_transfers(contract_address, limit=10)
    if not transfers or len(transfers) < 2:
        return result
    for tx in transfers:
        ts = int(tx.get("timeStamp", 0))
        if ts > deploy_timestamp:
            result["first_buy_time"] = ts
            latency_ms = (ts - deploy_timestamp) * 1000
            result["latency_ms"] = int(latency_ms)
            result["is_sniped"] = latency_ms < 3000
            break
    return result


def analyze_transaction_entropy(client: ChainClient, contract_address: str) -> dict[str, Any]:
    """Module 3: Shannon-style entropy over transfer amounts (bot-farm signature)."""
    result = {
        "total_txs": 0,
        "unique_amounts": 0,
        "entropy_score": 1.0,
        "is_bot_pattern": False,
        "dominant_amount": 0,
        "dominant_amount_pct": 0.0,
    }
    transfers = client.get_token_transfers(contract_address, limit=30)
    if not transfers:
        return result

    amounts = []
    for tx in transfers:
        try:
            decimals = int(tx.get("tokenDecimal", 18))
            amount = int(tx.get("value", "0")) / (10**decimals)
            if amount > 0:
                amounts.append(round(amount, 2))
        except (ValueError, TypeError):
            continue

    if not amounts:
        return result

    result["total_txs"] = len(amounts)
    counter = Counter(amounts)
    result["unique_amounts"] = len(counter)
    most_common_amount, most_common_count = counter.most_common(1)[0]
    dominant_pct = most_common_count / len(amounts)
    result["dominant_amount"] = most_common_amount
    result["dominant_amount_pct"] = round(dominant_pct * 100, 1)
    result["entropy_score"] = round(1.0 - dominant_pct, 2)
    result["is_bot_pattern"] = dominant_pct > 0.6
    return result


def detect_wash_pattern(
    client: ChainClient, contract_address: str, deployer: str, deploy_timestamp: int
) -> dict[str, Any]:
    """Module 4: fast dev-sell combined with a thin deployer tx history."""
    result = {"wash_detected": False, "dev_sold_fast": False, "dev_sell_latency_s": -1, "linker_wallets_connected": False}
    if not deployer:
        return result
    transfers = client.get_token_transfers(contract_address, limit=20)
    if not transfers:
        return result
    for tx in transfers:
        if tx.get("from", "").lower() == deployer.lower():
            latency = int(tx.get("timeStamp", 0)) - deploy_timestamp
            if 0 < latency < 60:
                result["dev_sold_fast"] = True
                result["dev_sell_latency_s"] = latency
                break
    deployer_txs = client.get_account_transactions(deployer, limit=10)
    result["linker_wallets_connected"] = len(deployer_txs) < 5
    result["wash_detected"] = result["dev_sold_fast"] and result["linker_wallets_connected"]
    return result


def analyze_holder_cluster(client: ChainClient, contract_address: str) -> dict[str, Any]:
    """Module 5: average holder wallet age (bot-farm detection)."""
    result = {"avg_age_days": 0.0, "new_wallets_count": 0, "total_checked": 0, "is_bot_farm": False}
    holders = client.get_token_holders(contract_address)
    if not holders:
        transfers = client.get_token_transfers(contract_address, limit=20)
        holder_addrs = list({tx.get("to", "") for tx in transfers if tx.get("to")})[:10]
    else:
        holder_addrs = [h.get("TokenHolderAddress", "") for h in holders[:10]]

    if not holder_addrs:
        return result

    ages = []
    new_count = 0
    for addr in holder_addrs[:10]:
        if not addr:
            continue
        age = client.get_account_age_days(addr)
        ages.append(age)
        if age < 7:
            new_count += 1

    if not ages:
        return result

    result["total_checked"] = len(ages)
    result["avg_age_days"] = round(sum(ages) / len(ages), 1)
    result["new_wallets_count"] = new_count
    result["is_bot_farm"] = new_count / len(ages) > 0.7
    return result
