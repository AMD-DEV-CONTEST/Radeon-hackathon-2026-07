"""Analytics router — aggregates indexed evidence for global insights."""
from collections import Counter
from fastapi import APIRouter, Depends
from ..security.jwt import get_current_user
from ..services.rag_service import rag

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("")
def get_analytics(user: dict = Depends(get_current_user)):
    records = rag.all_records()
    failure_counter: Counter = Counter()
    action_counter: Counter = Counter()
    asset_failures: dict[str, Counter] = {}
    asset_docs: dict[str, set] = {}

    for rec in records:
        meta = rec["metadata"]
        for f in filter(None, meta.get("failures", "").split(",")):
            failure_counter[f] += 1
        for a in filter(None, meta.get("actions", "").split(",")):
            action_counter[a] += 1
        for tag in filter(None, meta.get("asset_tags", "").split(",")):
            asset_failures.setdefault(tag, Counter())
            asset_docs.setdefault(tag, set())
            asset_docs[tag].add(meta.get("source", ""))
            for f in filter(None, meta.get("failures", "").split(",")):
                asset_failures[tag][f] += 1

    assets_ranked = sorted(
        [
            {
                "assetTag": tag,
                "failureEvents": sum(asset_failures[tag].values()),
                "topFailure": asset_failures[tag].most_common(1)[0][0] if asset_failures[tag] else None,
                "documentCount": len(asset_docs.get(tag, set())),
            }
            for tag in asset_failures
        ],
        key=lambda x: x["failureEvents"],
        reverse=True,
    )

    return {
        "totalChunks": len(records),
        "totalAssets": len(asset_failures),
        "topFailureModes": [
            {"failure": f, "count": c} for f, c in failure_counter.most_common(10)
        ],
        "topActions": [
            {"action": a, "count": c} for a, c in action_counter.most_common(10)
        ],
        "assetsRankedByRisk": assets_ranked[:20],
    }
