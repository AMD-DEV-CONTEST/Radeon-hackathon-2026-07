"""Read-only assembly of a day's graph for the frontend.

Builds a simple node/edge view of everything recorded for a calendar day:
the Day node, its spoken Entries, the Entity/mention facets each Entry links
to, and the Todos/Plans scheduled for that day (with their ``for_date``). Also
maps any generated thumbnail image onto the matching entity node so the graph
can show it as a node picture.

This is strictly read-only from the caller's perspective (it does not mutate
the diary); the only writes that can occur are idempotent Day-node upserts
performed by the shared schema helpers.
"""

from __future__ import annotations

import json
import os

from diary import runtime
from diary import schema as S
from diary.tools import DiaryContext
from diary.image_agent import read_day_rich

# media manifest lives at <repo>/media/<date>/manifest.json
MEDIA_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "media"
)


def _norm(s: str) -> str:
    return "".join(c for c in (s or "").lower() if c.isalnum())


def _load_thumbnails(date: str) -> dict[str, str]:
    """Return {normalized_subject: image_url} for the day's thumbnails."""
    out: dict[str, str] = {}
    path = os.path.join(MEDIA_ROOT, date, "manifest.json")
    if not os.path.exists(path):
        return out
    try:
        manifest = json.load(open(path, encoding="utf-8"))
    except Exception:
        return out
    for item in manifest if isinstance(manifest, list) else []:
        if (item.get("type") != "thumb") or not item.get("subject"):
            continue
        # The on-disk manifest stores image_path; build the browser-facing URL
        # the same way the /api/media endpoint does.
        url = item.get("image_url")
        if not url:
            fname = os.path.basename(item.get("image_path", ""))
            if fname:
                url = f"/media/{date}/{fname}"
        if url:
            out[_norm(item["subject"])] = url
    return out


def get_day_view(date: str) -> dict:
    """Return the day's graph + flat entry list for the UI.

    Shape::
        {
          "date": "<YYYY-MM-DD>",
          "nodes": [ {"id","type","label","key","text","for_date","status",
                      "has_thumb":bool,"thumb_url":null} ],
          "edges": [ {"from","to","type":"has_entry|mentions|has_todo"} ],
          "entries": [ {"ts","text","lang","mentions":[{"label","key"}]} ],
          "todos": [ {"text","for_date","status"} ]
        }
    """
    client = runtime.get_client()
    ctx = DiaryContext(client=client)

    entries = read_day_rich(ctx, date)
    day_id = S.ensure_day(client, date)
    todo_verts = S.todos_for_day(client, day_id)

    nodes: list[dict] = []
    edges: list[dict] = []
    entities: dict[str, dict] = {}  # stable entity id -> node (dedup across entries)

    day_node_id = f"day:{date}"
    nodes.append(
        {"id": day_node_id, "type": "day", "label": "Day", "key": date,
         "text": date, "for_date": None, "status": None,
         "has_thumb": False, "thumb_url": None}
    )

    thumbs = _load_thumbnails(date)

    for e in entries:
        eid = e.get("id")
        eid_str = f"entry:{eid}"
        nodes.append(
            {"id": eid_str, "type": "entry", "label": "Entry", "key": str(eid),
             "text": e.get("text", ""), "for_date": None, "status": None,
             "has_thumb": False, "thumb_url": None}
        )
        edges.append({"from": day_node_id, "to": eid_str, "type": "has_entry"})
        for m in e.get("mentions", []):
            label = (m.get("label") or S.L_THING)
            key = (m.get("key") or (m.get("properties") or {}).get("key")
                   or (m.get("properties") or {}).get("text") or "")
            if not key:
                continue
            ent_id = f"entity:{label}:{key}"
            if ent_id not in entities:
                node = {
                    "id": ent_id, "type": "entity", "label": label, "key": key,
                    "text": key, "for_date": None, "status": None,
                    "has_thumb": False, "thumb_url": None,
                }
                entities[ent_id] = node
                nodes.append(node)
            edges.append({"from": eid_str, "to": ent_id, "type": "mentions"})

    # Attach thumbnails to matching entity nodes (best-effort subject match).
    for node in entities.values():
        nk = _norm(node["key"])
        for subj, url in thumbs.items():
            if nk and (nk == subj or subj in nk or nk in subj):
                node["has_thumb"] = True
                node["thumb_url"] = url
                break

    todos = []
    for t in todo_verts:
        props = t.get("properties") or {}
        text = props.get("text", "")
        for_date = props.get("for_date")
        status = props.get("status", "open")
        tid = t.get("id")
        tid_str = f"todo:{tid}"
        nodes.append(
            {"id": tid_str, "type": "todo", "label": "Todo", "key": str(tid),
             "text": text, "for_date": for_date, "status": status,
             "has_thumb": False, "thumb_url": None}
        )
        edges.append({"from": day_node_id, "to": tid_str, "type": "has_todo"})
        todos.append({"text": text, "for_date": for_date, "status": status})

    flat_entries = [
        {
            "ts": e.get("ts"),
            "text": e.get("text", ""),
            "lang": e.get("lang", "zh"),
            "mentions": [
                {"label": m.get("label", S.L_THING), "key": m.get("key", "")}
                for m in e.get("mentions", [])
                if m.get("key")
            ],
        }
        for e in entries
    ]

    return {
        "date": date,
        "nodes": nodes,
        "edges": edges,
        "entries": flat_entries,
        "todos": todos,
    }
