#!/usr/bin/env python3
import os
# Racine du depot, deduite de l'emplacement du script : le paquet est
# reproductible ou qu'il soit clone, sans chemin absolu a adapter.
RACINE = os.environ.get("SEED_ROOT", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data-seed"))

import json, os
SRC = os.path.join(RACINE, "soul_socle.md")
OUT = os.path.join(RACINE, "soul_socle_blocs.json")
SEC_MISTRAL = os.path.join(RACINE, "socle_securite_mistral.md")
JUR_MISTRAL = os.path.join(RACINE, "socle_juridique_mistral.md")
txt = open(SRC, encoding="utf-8").read()

def extraire(txt, debut, fin=None):
    i = txt.find(debut)
    if i < 0: return ""
    if fin:
        j = txt.find(fin, i)
        return txt[i:j].strip() if j > 0 else txt[i:].strip()
    return txt[i:].strip()

def lire(p):
    return open(p, encoding="utf-8").read().strip() if os.path.exists(p) else ""

# Blocs communs (du .md de base = calibres gpt-oss)
securite_base  = extraire(txt, "# REGLES DE SECURITE", "# 2SIN Agent")
identite       = extraire(txt, "# 2SIN Agent", "# CONSIGNES DE")
juridique_base = extraire(txt, "# CONSIGNES DE")
# Variantes mistral (fichiers dedies)
securite_mistral  = lire(SEC_MISTRAL)
juridique_mistral = lire(JUR_MISTRAL)

blocs = [
    # SECURITE : 2 variantes exclusives
    {"id": 1, "nature": "socle_core", "domaine": "securite", "ordre": 1,
     "contenu": securite_base, "version": "2026-07-17", "etat": "actif", "modele_cible": ["gpt-oss"]},
    {"id": 11, "nature": "socle_core", "domaine": "securite", "ordre": 1,
     "contenu": securite_mistral, "version": "2026-07-17", "etat": "actif", "modele_cible": ["mistral"]},
    # IDENTITE : commune
    {"id": 2, "nature": "socle_core", "domaine": "identite", "ordre": 2,
     "contenu": identite, "version": "2026-07-17", "etat": "actif", "modele_cible": ["tous"]},
    # JURIDIQUE : 2 variantes exclusives
    {"id": 3, "nature": "socle_juridique", "domaine": "juridique", "ordre": 3,
     "contenu": juridique_base, "version": "2026-07-17", "etat": "actif", "modele_cible": ["gpt-oss"]},
    {"id": 31, "nature": "socle_juridique", "domaine": "juridique", "ordre": 3,
     "contenu": juridique_mistral, "version": "2026-07-17", "etat": "actif", "modele_cible": ["mistral"]},
]
for b in blocs:
    assert b["contenu"], f"BLOC VIDE: {b['domaine']} / {b['modele_cible']}"
    print(f"  bloc id{b['id']} ordre{b['ordre']} [{b['domaine']}] cible={b['modele_cible']} : {len(b['contenu'])} car.")
json.dump(blocs, open(OUT,"w",encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"  -> {OUT} ({len(blocs)} blocs)")
