"""Daily-graph schema for the diary app, backed by Bionic-Graph.

One shared graph. Node types cover a person's day across 衣食住行 (clothing / food /
lodging / travel) plus the people / places / events the user mentions.

Identity / upsert strategy
--------------------------
Every canonical node uses a STABLE, UNIQUE name ("<type>:<key>") so re-mentioning
the same person or place across days resolves to ONE node. We upsert by exact-name
search then create. We never rely on keyword *removal* (Bionic-Graph's token index is
append-only — see AGENTS.md "Known quirks"), only on stable names + `properties`.
"""

from __future__ import annotations

from database.bionic_graph_client import BionicGraphClient

# -- node labels ----------------------------------------------------------
L_ME = "Me"
L_DAY = "Day"
L_ENTRY = "Entry"
L_PERSON = "Person"
L_PLACE = "Place"
L_EVENT = "Event"
L_ORG = "Organization"
L_THING = "Thing"
L_ACTIVITY = "Activity"
L_MOOD = "Mood"
L_HEALTH = "Health"
L_WORK = "Work"
L_FINANCE = "Finance"
# 衣食住行
L_FOOD = "Food"
L_MEAL = "Meal"
L_CLOTHING = "Clothing"
L_SHELTER = "Shelter"
L_TRANSPORT = "Transport"
# tasks
L_TODO = "Todo"
L_PLAN = "Plan"

# -- edge names -----------------------------------------------------------
E_LIVES_DAY = "lives_day"
E_HAS_ENTRY = "has_entry"
E_MENTIONS = "mentions"
E_HAS_TODO = "has_todo"
E_FOR_DATE = "for_date"
E_KNOWS = "knows"
E_AT = "at"
E_ATTENDS = "attends"
E_RELATED = "related"

OWNER_NAME = "me"


def _stable_name(label: str, key: str) -> str:
    return f"{label.lower()}:{str(key).lower()}"


# -- builders -------------------------------------------------------------
def ensure_owner(client: BionicGraphClient, name: str = OWNER_NAME) -> int:
    """Create (or find) the singleton diary-owner node."""
    return _upsert(client, _stable_name(L_ME, name), [L_ME])


def ensure_day(client: BionicGraphClient, date_iso: str) -> int:
    """Create (or find) the Day node for `date_iso` and link Me -[:lives_day]-> Day."""
    day_id = _upsert(client, _stable_name(L_DAY, date_iso), [L_DAY], properties={"date": date_iso})
    owner_id = ensure_owner(client)
    _link_once(client, owner_id, day_id, E_LIVES_DAY)
    return day_id


def add_entry(
    client: BionicGraphClient,
    day_id: int,
    text: str,
    ts=None,
    lang: str = "zh",
    turn_id=None,
) -> int:
    """Append one spoken turn as an Entry under its Day.

    When ``turn_id`` is supplied the entry is upserted by a stable name, so a
    retransmitted turn (e.g. a flaky upload from the frontend) does not create a
    duplicate node.
    """
    props: dict = {"text": text, "ts": ts, "lang": lang}
    if turn_id is not None:
        props["turn_id"] = turn_id
    key = str(turn_id) if turn_id is not None else f"{day_id}:{ts}"
    eid = _upsert(client, _stable_name(L_ENTRY, key), [L_ENTRY], properties=props)
    client.create_edge(day_id, eid, E_HAS_ENTRY)
    return eid


def mention(
    client: BionicGraphClient,
    entry_id: int,
    label: str,
    key: str,
    properties: dict | None = None,
) -> int:
    """Link an Entry to a canonical facet node (person/place/food/...)."""
    fid = _upsert(client, _stable_name(label, key), [label], properties=properties)
    client.create_edge(entry_id, fid, E_MENTIONS)
    return fid


def add_todo(
    client: BionicGraphClient,
    day_id: int,
    text: str,
    for_date: str | None = None,
    status: str = "open",
) -> int:
    """Create a Todo/Plan under a Day; if `for_date` is set, point it forward.

    The todo is linked to the planning day via ``has_todo`` AND, when a future
    date is given, ALSO to the target day (``has_todo`` + ``for_date``) so it
    shows up as a scheduled task there and the agent's future-todo nudge can find
    it via ``get_todos(target_day)``.
    """
    props: dict = {"text": text, "status": status}
    if for_date:
        props["for_date"] = for_date
    # Key todos by (text, for_date) so re-stating a plan for a NEW target date
    # creates its own node instead of being collapsed onto the first one.
    # `_upsert` never updates an existing node's properties, so without this the
    # second statement's `for_date` was silently dropped and the future nudge
    # could never find the plan (the "todo_missing" structural failure).
    todo_key = f"{text}|{for_date or ''}"
    tid = _upsert(client, _stable_name(L_TODO, todo_key), [L_TODO], properties=props)
    client.create_edge(day_id, tid, E_HAS_TODO)
    if for_date:
        target = ensure_day(client, for_date)
        client.create_edge(tid, target, E_FOR_DATE)
        client.create_edge(target, tid, E_HAS_TODO)
    return tid


def todos_for_day(client: BionicGraphClient, day_id: int) -> list:
    """Return Todo nodes attached to a Day (for the clarification check)."""
    data = client.gremlin(
        [
            {"step": "V", "ids": [day_id]},
            {"step": "out", "name": E_HAS_TODO, "depth": 1},
        ]
    ) or []
    return [v for v in data if L_TODO in (v.get("labels") or [])]


# -- helpers --------------------------------------------------------------
# We mirror each node's stable name into a dedicated property so upsert lookup is
# reliable. Bionic-Graph caveats that make the obvious approaches unsafe:
#   * `search(mode="exact")` is token-based and skips short tokens (e.g. "me:me"),
#     and can return unrelated edges that merely share a token;
#   * the gremlin `has` step only matches *properties*, not the top-level `name`
#     field. So we store the stable name in `stable_key` and look it up via `has`.
STABLE_KEY_PROP = "stable_key"


def _upsert(client: BionicGraphClient, name: str, labels, properties=None) -> int:
    """Find-or-create a node by its stable ``name`` (reliable across token quirks)."""
    hits = client.gremlin(
        [
            {"step": "V"},
            {"step": "has", "key": STABLE_KEY_PROP, "value": name},
            {"step": "limit", "count": 1},
        ]
    ) or []
    for h in hits:
        if h.get("type") == "vertex" and h.get("name") == name:
            return int(h["id"])
    props = dict(properties or {})
    props[STABLE_KEY_PROP] = name
    return client.create_vertex(name, labels=list(labels), properties=props)


def _link_once(client: BionicGraphClient, src: int, tgt: int, name: str) -> None:
    """Create src->tgt edge only if it does not already exist (cheap out-check)."""
    reached = client.gremlin([{"step": "V", "ids": [src]}, {"step": "out", "depth": 1}]) or []
    if any(v.get("id") == tgt for v in reached):
        return
    client.create_edge(src, tgt, name)
