#!/usr/bin/env python3
"""Ingestion des fragments SOUL dans Qdrant (SOUL vectoriel étage 2).
Le socle (soul_socle.md) reste toujours injecté ; les fragments sont
récupérés par pertinence selon la requête."""
import os
# Racine du depot, deduite de l'emplacement du script : le paquet est
# reproductible ou qu'il soit clone, sans chemin absolu a adapter.
RACINE = os.environ.get("SEED_ROOT", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data-seed"))

import json, requests

TEI_URL = os.environ.get("TEI_URL", "http://localhost:8080/embed")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION = "soul_fragments"
VECTOR_SIZE = 1024

def embed(text):
    r = requests.post(TEI_URL, json={"inputs": text}, timeout=30)
    r.raise_for_status()
    return r.json()[0]

def ensure_collection(name):
    if requests.get(f"{QDRANT_URL}/collections/{name}").status_code == 200:
        requests.delete(f"{QDRANT_URL}/collections/{name}")
    requests.put(f"{QDRANT_URL}/collections/{name}",
                 json={"vectors": {"size": VECTOR_SIZE, "distance": "Cosine"}}).raise_for_status()

def main():
    frags = json.load(open(os.path.join(RACINE, "soul_fragments.json"), encoding="utf-8"))
    ensure_collection(COLLECTION)
    points = []
    for f in frags:
        # embed sur theme + mots-cles (ce qui déclenche), pas tout le contenu
        embed_text = f["theme"].replace("_"," ") + " : " + " ".join(f["mots_cles"])
        vec = embed(embed_text)
        points.append({
            "id": f["id"],
            "vector": vec,
            "payload": {"theme": f["theme"], "mots_cles": f["mots_cles"], "contenu": f["contenu"]},
        })
    r = requests.put(f"{QDRANT_URL}/collections/{COLLECTION}/points",
                     json={"points": points}, timeout=60)
    r.raise_for_status()
    cnt = requests.post(f"{QDRANT_URL}/collections/{COLLECTION}/points/count", json={}).json()
    print(f"soul_fragments: {r.json()['status']}, {cnt['result']['count']} fragments")

if __name__ == "__main__":
    main()
