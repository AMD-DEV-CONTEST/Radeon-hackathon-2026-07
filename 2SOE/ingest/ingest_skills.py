#!/usr/bin/env python3
"""Ingestion du CATALOGUE de skills dans Qdrant.
Chaque declencheur d'un skill devient un point vectorise (payload = nom du skill).
Le routage par catalogue (primitive router_skill) cherche dans cette collection.
Relance idempotente : recree la collection a chaque fois.
"""
import os, json, glob, urllib.request as u

TEI_URL    = os.environ.get("TEI_URL", "http://localhost:8080/embed")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLL       = os.environ.get("SKILLS_COLLECTION", "skills_catalogue")
# Ancre sur l'emplacement du script : le glob ne doit pas dependre du
# repertoire courant depuis lequel on lance l'ingest.
WF_DIR     = os.environ.get("WORKFLOWS_DIR", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "relay", "framework", "workflows"))

def _post(url, payload, timeout=30):
    req = u.Request(url, data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"})
    with u.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def _put(url, payload):
    req = u.Request(url, data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"}, method="PUT")
    with u.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def main():
    # 1. Dimension de l'embed (BGE-M3 = 1024)
    dim = len(_post(TEI_URL, {"inputs": "test"})[0])
    print("dim embed:", dim)

    # 2. (Re)creer la collection
    try:
        req = u.Request(QDRANT_URL + "/collections/" + COLL, method="DELETE")
        u.urlopen(req, timeout=10)
    except Exception:
        pass
    _put(QDRANT_URL + "/collections/" + COLL,
         {"vectors": {"size": dim, "distance": "Cosine"}})
    print("collection", COLL, "recreee")

    # 3. Parcourir les skills, vectoriser chaque declencheur
    points = []
    pid = 1
    for path in glob.glob(os.path.join(WF_DIR, "skill_*.json")):
        skill = json.load(open(path, encoding="utf-8"))
        nom = skill.get("nom", os.path.basename(path))
        decls = skill.get("declencheurs", [])
        if not decls:
            print("  (skip", nom, ": aucun declencheur)")
            continue
        for phrase in decls:
            vec = _post(TEI_URL, {"inputs": phrase})[0]
            points.append({"id": pid, "vector": vec,
                           "payload": {"skill": nom, "phrase": phrase}})
            pid += 1
        print("  +", nom, ":", len(decls), "declencheurs")

    if points:
        _put(QDRANT_URL + "/collections/" + COLL + "/points",
             {"points": points})
        print("ingest skills : OK,", len(points), "points")
    else:
        print("ingest skills : aucun skill avec declencheurs")

if __name__ == "__main__":
    main()
