#!/usr/bin/env python3
"""Ingestion corpus juridique 2SIN — structure Code -> Branche -> Source -> Article.
Une collection Qdrant par CODE (code civil, code de commerce...).
Payload porte l'appartenance complete (exigence de rigueur juridique)."""
import os
# Racine du depot, deduite de l'emplacement du script : le paquet est
# reproductible ou qu'il soit clone, sans chemin absolu a adapter.
RACINE = os.environ.get("SEED_ROOT", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data-seed"))

import json, os, re, requests, unicodedata

TEI_URL = os.environ.get("TEI_URL", "http://localhost:8080/embed")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
VECTOR_SIZE = 1024

CORPUS_FILES = [
    os.path.join(RACINE, "corpus-juridique", "loi_89.json"),
    os.path.join(RACINE, "corpus-juridique", "loi_65.json"),
    os.path.join(RACINE, "corpus-juridique", "code_commerce_baux.json"),
    os.path.join(RACINE, "corpus-juridique", "cch_gestion_locative.json"),
    os.path.join(RACINE, "corpus-juridique", "code_penal_immo.json"),
    os.path.join(RACINE, "corpus-juridique", "code_urbanisme_immo.json"),
    os.path.join(RACINE, "corpus-juridique", "jurisprudence_baux.json"),
]

def slug(s):
    """Code civil -> code_civil (nom de collection normalise)."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return "juridique_" + s

def embed(text):
    r = requests.post(TEI_URL, json={"inputs": text}, timeout=30)
    r.raise_for_status()
    return r.json()[0]

def ensure_collection(name):
    """Cree la collection si absente."""
    r = requests.get(f"{QDRANT_URL}/collections/{name}")
    if r.status_code == 200:
        return
    requests.put(f"{QDRANT_URL}/collections/{name}", json={
        "vectors": {"size": VECTOR_SIZE, "distance": "Cosine"}
    }, timeout=30).raise_for_status()
    print(f"  collection creee: {name}")

SEUIL_DECOUPE = int(os.environ.get("CORPUS_SEUIL_DECOUPE", "2500"))

# Subdivisions juridiques, de la plus forte a la plus faible. Un article long se
# lit par parties : l'article 15 de la loi de 1989 a un I (conge et preavis), un
# II (vente), un III et IV (protections), un V (sanctions). Servir le tout pour
# une question sur le preavis noyait la reponse dans 11 800 caracteres -- et le
# modele citait les articles mentionnes EN PASSANT dans le texte (17, L.831-1,
# 46 de la loi de 1965) comme s'ils repondaient a la question.
_SUBDIVISIONS = (
    # Les alternatives vont de la PLUS LONGUE a la plus courte : « I{1,3}V? »
    # acceptait « I » seul, donc « III » etait coupe en trois.
    (r"(?:(?<=\s)|^)(?=(?:IX|IV|VI{1,3}|V|I{1,3})\s*\.\s*-\s)", "romain"),
    (r"\n?(?=\d{1,2}\s*°\s)", "numero"),
    (r"\n?(?=[a-h]\)\s)", "lettre"),
)


MIN_PARTIE = int(os.environ.get("CORPUS_MIN_PARTIE", "400"))


def _marque(p):
    m = re.match(r"^((?:IX|IV|VI{1,3}|V|I{1,3})\s*\.|\d{1,2}\s*°(?:\s*bis)?|[a-h]\))", p)
    return m.group(1).strip().rstrip(".") if m else ""


def _decouper(texte, seuil=None, prefixe=""):
    """Rend [(marque, texte)]. La marque situe la partie DANS l'article --
    la tracabilite est preservee : chaque morceau reste rattache a sa source.

    Deux bornes, l'une contre l'autre :
      SEUIL      au-dela, on decoupe -- servir 11 800 caracteres pour une
                 question de trois phrases noyait la reponse
      MIN_PARTIE en deca, on regroupe -- « 1° Sur les territoires mentionnes
                 au premier alinea du I de l'article 17 » ne dit rien seul.
    """
    seuil = seuil or SEUIL_DECOUPE
    texte = (texte or "").strip()
    if len(texte) <= seuil:
        return [(prefixe, texte)]

    for motif, _ in _SUBDIVISIONS:
        parts = [p.strip() for p in re.split(motif, texte) if p.strip()]
        if len(parts) < 2:
            continue
        # regroupement des fragments trop courts avec le precedent
        groupes = []
        for p in parts:
            if groupes and len(groupes[-1]) < MIN_PARTIE:
                groupes[-1] = groupes[-1] + "\n" + p
            else:
                groupes.append(p)
        # Un regroupement qui rend le texte inchange ne decoupe rien : recurser
        # dessus boucle indefiniment. On passe au motif suivant.
        if len(groupes) < 2:
            continue
        out = []
        for g in groupes:
            _m = _marque(g)
            # La marque du PARENT est toujours portee : une partie doit dire d'ou
            # elle vient. « 1° » seul ne situe rien ; « I 1° » situe.
            mq = prefixe
            if _m and _m not in prefixe.split():
                mq = (prefixe + " " + _m).strip()
            if len(g) > seuil and g != texte:
                out.extend(_decouper(g, seuil, mq))
            else:
                out.append((mq, g))
        return out

    # aucune subdivision reconnue : coupe aux phrases, jamais au milieu de l'une
    # d'elles -- une regle tronquee est une regle fausse.
    phrases, courant, out = re.split(r"(?<=[.;])\s+", texte), "", []
    for ph in phrases:
        if len(courant) + len(ph) > seuil and courant:
            out.append((prefixe, courant.strip()))
            courant = ""
        courant += ph + " "
    if courant.strip():
        out.append((prefixe, courant.strip()))
    return out


def build_chunks(filepath):
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    code = data.get("code", "Non classe")
    # Rangement DECLARE, distinct du libelle : corriger un label ne doit
    # pas renommer la collection ni casser le routage.
    collection = data.get("collection", "")
    branche = data.get("branche", "")
    source = data.get("loi", "")
    chunks = []
    for art_key, art in data.get("articles", {}).items():
        theme = art.get("theme", "")
        texte = art.get("texte", "")
        for marque, morceau in _decouper(texte):
            ref = art_key + ((" " + marque) if marque else "")
            # embed enrichi : appartenance + theme + texte pour un bon retrieval
            full = f"{code} — {branche} — {source} — {ref} ({theme}) : {morceau}"
            chunks.append({
                "code": code, "collection": collection,
                "branche": branche, "source": source,
                "article": art_key, "partie": marque, "reference": ref,
                "theme": theme, "texte": morceau,
                "embed_text": full,
            })
    return chunks

def main():
    # Regroupe les chunks par collection (= par code)
    par_collection = {}
    for fp in CORPUS_FILES:
        chunks = build_chunks(fp)
        if not chunks:
            continue
        # Le nom de collection est DECLARE (champ "collection"), avec repli sur le
        # label. Sans cela, corriger un label renommerait la collection et
        # casserait le routage : le rangement et le libelle sont deux choses.
        coll = slug(chunks[0].get("collection") or chunks[0]["code"])
        par_collection.setdefault(coll, []).extend(chunks)
        print(f"  {fp.split('/')[-1]}: {len(chunks)} articles -> {coll}")

    for coll, chunks in par_collection.items():
        ensure_collection(coll)
        points = []
        for i, ch in enumerate(chunks):
            vec = embed(ch["embed_text"])
            points.append({
                "id": i,
                "vector": vec,
                "payload": {
                    "code": ch["code"], "branche": ch["branche"],
                    "source": ch["source"], "article": ch["article"],
                    "theme": ch["theme"], "texte": ch["texte"],
                },
            })
        r = requests.put(f"{QDRANT_URL}/collections/{coll}/points",
                         json={"points": points}, timeout=60)
        r.raise_for_status()
        cnt = requests.post(f"{QDRANT_URL}/collections/{coll}/points/count", json={}).json()
        print(f"  {coll}: upsert {r.json()['status']}, {cnt['result']['count']} points")

if __name__ == "__main__":
    main()
