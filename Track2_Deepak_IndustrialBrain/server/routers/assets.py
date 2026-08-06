"""Asset 360° router — aggregates evidence for a specific asset tag."""
from fastapi import APIRouter, Depends, HTTPException
from ..security.jwt import get_current_user
from ..services.rag_service import rag

router = APIRouter(prefix="/api/assets", tags=["assets"])


@router.get("/{tag}")
def get_asset(tag: str, user: dict = Depends(get_current_user)):
    evidence = rag.asset_evidence(tag)
    if not evidence:
        raise HTTPException(404, f"No indexed evidence found for {tag.upper()}")

    sources, failures, actions, dates, measurements = set(), set(), set(), set(), set()
    events = []
    for item in evidence:
        meta = item["metadata"]
        sources.add(meta.get("source", ""))
        failures.update(filter(None, meta.get("failures", "").split(",")))
        actions.update(filter(None, meta.get("actions", "").split(",")))
        dates.update(filter(None, meta.get("dates", "").split(",")))
        measurements.update(filter(None, meta.get("measurements", "").split(",")))
        if meta.get("dates"):
            events.append({
                "date": meta["dates"].split(",")[0],
                "source": meta.get("source", ""),
                "summary": item["text"][:220],
            })

    return {
        "tag": tag.upper(),
        "sources": sorted(sources),
        "failures": sorted(failures),
        "maintenanceActions": sorted(actions),
        "dates": sorted(dates),
        "measurements": sorted(measurements),
        "timeline": events[:12],
        "evidenceChunks": len(evidence),
    }
