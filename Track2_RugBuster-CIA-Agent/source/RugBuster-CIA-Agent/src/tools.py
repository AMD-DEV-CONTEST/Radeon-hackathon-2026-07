"""
LangChain Tool wrappers around the 7 CIA Intelligence Engine modules.

AMD Track 2 capability #1 (Tool invocation): each module is exposed as a
`langchain_core.tools.StructuredTool` with a typed args schema, so the agent
(src/orchestrator.py) invokes them the same way it would invoke any other
LangChain tool — the underlying detection logic in cia_modules.py is
untouched, this file is purely an adapter layer.
"""

from __future__ import annotations

from typing import Any, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from . import cia_modules
from .chain_client import get_chain_client


class ContractArgs(BaseModel):
    chain: str = Field(description="Chain preset name, e.g. AVAX, BASE, BNB")
    contract_address: str = Field(description="Token contract address to inspect")


class DeployerArgs(BaseModel):
    chain: str = Field(description="Chain preset name, e.g. AVAX, BASE, BNB")
    deployer_address: str = Field(description="Contract deployer / creator wallet address")
    depth: int = Field(default=3, description="Number of funding hops to trace back")


class LatencyArgs(BaseModel):
    chain: str
    contract_address: str
    deploy_timestamp: int = Field(description="Unix timestamp of contract deployment")


class WashPatternArgs(BaseModel):
    chain: str
    contract_address: str
    deployer_address: str
    deploy_timestamp: int


def _funding_origin(chain: str, deployer_address: str, depth: int = 3) -> dict[str, Any]:
    client = get_chain_client(chain)
    return cia_modules.trace_funding_origin(client, deployer_address, depth=depth)


def _deployment_latency(chain: str, contract_address: str, deploy_timestamp: int) -> dict[str, Any]:
    client = get_chain_client(chain)
    return cia_modules.get_deployment_latency(client, contract_address, deploy_timestamp)


def _tx_entropy(chain: str, contract_address: str) -> dict[str, Any]:
    client = get_chain_client(chain)
    return cia_modules.analyze_transaction_entropy(client, contract_address)


def _wash_pattern(chain: str, contract_address: str, deployer_address: str, deploy_timestamp: int) -> dict[str, Any]:
    client = get_chain_client(chain)
    return cia_modules.detect_wash_pattern(client, contract_address, deployer_address, deploy_timestamp)


def _holder_cluster_age(chain: str, contract_address: str) -> dict[str, Any]:
    client = get_chain_client(chain)
    return cia_modules.analyze_holder_cluster(client, contract_address)


def _contract_backdoor(chain: str, contract_address: str) -> dict[str, Any]:
    client = get_chain_client(chain)
    return cia_modules.detect_contract_backdoor(client, contract_address)


def _holder_concentration(chain: str, contract_address: str) -> dict[str, Any]:
    client = get_chain_client(chain)
    return cia_modules.analyze_holder_concentration(client, contract_address)


funding_origin_tool = StructuredTool.from_function(
    func=_funding_origin,
    name="funding_origin",
    description=(
        "Trace the deployer wallet's funding chain up to 3 hops back. Flags a master "
        "wallet financing multiple scam deployments when every hop is a wallet younger "
        "than 7 days. Requires the deployer address."
    ),
    args_schema=DeployerArgs,
)

deployment_latency_tool = StructuredTool.from_function(
    func=_deployment_latency,
    name="deployment_latency",
    description=(
        "Measure milliseconds between contract deployment and the first buy. Under "
        "3000ms indicates a sniper bot with mempool visibility. Requires deploy_timestamp."
    ),
    args_schema=LatencyArgs,
)

tx_entropy_tool = StructuredTool.from_function(
    func=_tx_entropy,
    name="tx_entropy",
    description=(
        "Compute entropy over recent transfer amounts. A single amount dominating >60% "
        "of transfers is a bot-farm signature (repetitive buy sizing)."
    ),
    args_schema=ContractArgs,
)

wash_pattern_tool = StructuredTool.from_function(
    func=_wash_pattern,
    name="wash_pattern",
    description=(
        "Detect mint -> dev instant sell -> thin deployer history wash-trading pattern. "
        "Requires deployer address and deploy_timestamp."
    ),
    args_schema=WashPatternArgs,
)

holder_cluster_age_tool = StructuredTool.from_function(
    func=_holder_cluster_age,
    name="holder_cluster_age",
    description=(
        "Check top holder wallet ages. >70% of holders being wallets younger than 7 days "
        "indicates a coordinated bot farm."
    ),
    args_schema=ContractArgs,
)

contract_backdoor_tool = StructuredTool.from_function(
    func=_contract_backdoor,
    name="contract_backdoor",
    description=(
        "Scan deployed bytecode for hidden mint/drain/pause/blacklist/upgradeTo function "
        "selectors. Flags upgradeable proxy contracts where the dev can change code post-deploy."
    ),
    args_schema=ContractArgs,
)

holder_concentration_tool = StructuredTool.from_function(
    func=_holder_concentration,
    name="holder_concentration",
    description=(
        "Compute top-5 / top-1 holder share of total supply. Top-5 holding >80% of supply "
        "is a CRITICAL concentration risk (rug-pull exposure)."
    ),
    args_schema=ContractArgs,
)

ALL_TOOLS: list[StructuredTool] = [
    funding_origin_tool,
    deployment_latency_tool,
    tx_entropy_tool,
    wash_pattern_tool,
    holder_cluster_age_tool,
    contract_backdoor_tool,
    holder_concentration_tool,
]

TOOLS_BY_NAME: dict[str, StructuredTool] = {tool.name: tool for tool in ALL_TOOLS}
