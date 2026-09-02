#!/usr/bin/env python3
"""Ingestion du socle SOUL dans Qdrant (collection soul_socle).
Recuperation par SCROLL DETERMINISTE (jamais recherche vectorielle) :
le socle est toujours injecte en entier, pas selon un score.
Le vecteur est present (dimension cohérente) mais NON utilise pour le socle."""
import os
# Racine du depot, deduite de l'emplacement du script : le paquet est
# reproductible ou qu'il soit clone, sans chemin absolu a adapter.
RACINE = os.environ.get("SEED_ROOT", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data-seed"))

import json, requests

TEI_URL = os.environ.get("TEI_URL", "http://localhost:8080/embed")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION = "soul_socle"
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

def regenerer_blocs():
    """Le JSON est un PRODUIT des .md, pas une source : on le regenere avant
    de lire. Sans cela, un JSON perime ecrase les variantes par modele --
    constate le 23/07 : Qdrant avait 5 blocs, le JSON 3, les variantes
    Mistral ont ete perdues a la reingestion."""
    import subprocess, sys
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "decoupe_socle.py")

    # Les .md sont la SOURCE : absents, on ne regenere rien de valable.
    manquants = [f for f in ("soul_socle.md", "socle_securite_mistral.md",
                             "socle_juridique_mistral.md")
                 if not os.path.exists(os.path.join(RACINE, f))]
    if manquants:
        raise SystemExit(
            "\n  ECHEC : fichier(s) source du socle introuvable(s)\n"
            "  manquant(s) : %s\n"
            "  attendus dans : %s\n"
            "  -> Qdrant N'A PAS ete modifie. Retablir les .md puis relancer.\n"
            % (", ".join(manquants), os.path.normpath(RACINE)))

    r = subprocess.run([sys.executable, script], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(
            "\n  ECHEC : la regeneration du socle (decoupe_socle.py) a echoue\n"
            "  -> Qdrant N'A PAS ete modifie, le socle en place est intact.\n"
            "  Sortie du script :\n%s\n"
            % ((r.stderr or r.stdout or "(aucune sortie)").strip()))
    print((r.stdout or "").strip())

    # GARDE DE COHERENCE : un JSON techniquement valide mais vide ou ampute
    # ecraserait le socle sans erreur. Le socle de securite est incompressible :
    # on refuse d'ingerer plutot que de servir un socle mutile.
    chemin = os.path.join(RACINE, "soul_socle_blocs.json")
    try:
        blocs = json.load(open(chemin, encoding="utf-8"))
    except Exception as e:
        raise SystemExit("\n  ECHEC : JSON du socle illisible apres regeneration"
                         "\n  fichier : %s\n  cause : %s"
                         "\n  -> Qdrant N'A PAS ete modifie.\n" % (chemin, e))
    cores = [b for b in blocs if b.get("nature") == "socle_core"]
    if not cores:
        raise SystemExit(
            "\n  ECHEC : aucun bloc 'socle_core' apres regeneration (%d bloc(s) au total)\n"
            "  Le socle de securite ne peut pas etre absent : verifier les marqueurs\n"
            "  de section dans soul_socle.md et les .md de variantes.\n"
            "  -> Qdrant N'A PAS ete modifie, le socle en place est intact.\n" % len(blocs))
    cibles = sorted({c for b in blocs for c in (b.get("modele_cible") or [])})
    print("  controle : %d bloc(s), dont %d socle_core | cibles : %s"
          % (len(blocs), len(cores), ", ".join(cibles) or "aucune"))

def main():
    regenerer_blocs()
    blocs = json.load(open(os.path.join(RACINE, "soul_socle_blocs.json"), encoding="utf-8"))
    ensure_collection(COLLECTION)
    points = []
    for b in blocs:
        # embed sur domaine+nature (le socle n'est jamais cherche, vecteur = placeholder utile)
        vec = embed(b["domaine"] + " " + b["nature"])
        points.append({"id": b["id"], "vector": vec, "payload": b})
    r = requests.put(f"{QDRANT_URL}/collections/{COLLECTION}/points",
                     json={"points": points}, timeout=60)
    r.raise_for_status()
    cnt = requests.post(f"{QDRANT_URL}/collections/{COLLECTION}/points/count", json={}).json()
    print(f"soul_socle: {r.json()['status']}, {cnt['result']['count']} blocs ingeres")
    # Verif immediate : scroll deterministe reconstitue le socle dans l'ordre
    sc = requests.post(f"{QDRANT_URL}/collections/{COLLECTION}/points/scroll",
                       json={"limit": 20, "with_payload": True}).json()
    pts = sorted(sc["result"]["points"], key=lambda p: p["payload"]["ordre"])
    print(f"  scroll -> {len(pts)} blocs, ordres: {[p['payload']['ordre'] for p in pts]}")

if __name__ == "__main__":
    main()
