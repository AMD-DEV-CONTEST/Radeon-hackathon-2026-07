"""Primitive router_skill 2SIN - routage par catalogue vectoriel.

Cherche dans le catalogue de skills (Qdrant) le skill le plus proche
semantiquement de la demande. Si un skill depasse le seuil ET que l'intention
est une action/redaction, retourne le nom du skill a executer. Sinon None
(le flux normal continue).

Reutilise le pattern embed (TEI) + search (Qdrant) du RAG existant.
Contrat : router_skill(entree, ctx) -> {"skill": nom} ou {"skill": None}
"""
import os, json, urllib.request as u

TEI_URL     = os.environ.get("TEI_URL", "http://localhost:8080/embed")
QDRANT_URL  = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLL        = os.environ.get("SKILLS_COLLECTION", "skills_catalogue")
SEUIL       = float(os.environ.get("SKILL_ROUTE_SEUIL", "0.75"))
# Intentions qui autorisent le routage vers un skill (tache composee).
INTENTIONS_SKILL = set(
    os.environ.get("SKILL_INTENTIONS", "redaction,action").split(",")
)

def _post(url, payload, timeout=30):
    req = u.Request(url, data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"})
    with u.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def router_skill(entree, ctx):
    # entree : la question (str ou liste). Fallback sur ctx["question"].
    q = entree[0] if isinstance(entree, (list, tuple)) and entree else entree
    if not q or not isinstance(q, str):
        q = ctx.get("question", "")
    if not q:
        return {"skill": None}

    # Garde-fou : ne router que si l'intention est une tache composee.
    intent = ctx.get("intention", {}) or {}
    intention = intent.get("intention", "")
    if intention not in INTENTIONS_SKILL:
        return {"skill": None, "_raison": "intention '%s' hors routage" % intention}

    # Embed la demande + search dans le catalogue.
    try:
        vec = _post(TEI_URL, {"inputs": q})[0]
        res = _post(QDRANT_URL + "/collections/" + COLL + "/points/search",
                    {"vector": vec, "limit": 3, "with_payload": True})
        hits = res.get("result", [])
    except Exception as e:
        return {"skill": None, "_raison": "catalogue indisponible: " + str(e)[:80]}

    if not hits:
        return {"skill": None, "_raison": "catalogue vide"}

    top = hits[0]
    score = top.get("score", 0.0)
    nom = (top.get("payload") or {}).get("skill")
    if score >= SEUIL and nom:
        return {"skill": nom, "_score": round(score, 3)}
    return {"skill": None, "_score": round(score, 3), "_raison": "sous le seuil"}
