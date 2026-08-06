"""Scope ACL check for broker routing (Design §5.3)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def acl_allows(article_scope_str: str, src_org_did: str, dst_org_did: str) -> bool:
    if article_scope_str == "public":
        return True
    if article_scope_str.startswith("partner:"):
        return article_scope_str == f"partner:{dst_org_did}"
    return dst_org_did == src_org_did


@dataclass
class SubscriberRef:
    node_id: str
    org_did: str


def filter_subscribers(
    subscribers: list[Any],
    scope: str,
    src_org: str,
) -> list[Any]:
    return [s for s in subscribers if acl_allows(scope, src_org, s.org_did)]
