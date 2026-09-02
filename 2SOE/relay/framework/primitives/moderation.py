#!/usr/bin/env python3
"""Primitive moderer 2SIN - FIREWALL SEMANTIQUE. PREMIER organe du flux.
Classe la demande par domaine sensible AVANT tout appel au modele.
Un domaine sensible non couvert (detresse, medical, pharmaco, financier) n'atteint
JAMAIS le LLM : le core repond directement et ARRETE le flux.
Config vivante : domaines_sensibles.json (data-seed), relue a CHAQUE appel (pas de restart).
Contrat : fn(entree, ctx) -> {"domaine","action","message","_arret": bool}
"""
import os
_RACINE = os.environ.get("SEED_ROOT", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "data-seed"))

import json, os, re, unicodedata

DOMAINES_PATH = os.environ.get("DOMAINES_PATH",
                               os.path.join(_RACINE, "domaines_sensibles.json"))

# Actions qui STOPPENT le flux : le modele ne doit pas etre appele.
ACTIONS_ARRET = ("refus_redirection", "refus_strict")


def _normaliser(s):
    """Accents, ponctuation et pluriels ne doivent pas faire echouer une garde.
    « J'ai des envies de mourir » ne matchait pas « envie de mourir »."""
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    # pluriels simples : le singulier doit matcher le pluriel et l'inverse
    s = re.sub(r"(\w{3,}?)s\b", r"\1", s)
    return " " + s.strip() + " "


def _load_domaines():
    """Config rechargee a chaud a chaque appel (aucun redemarrage necessaire)."""
    with open(DOMAINES_PATH, encoding="utf-8") as f:
        return json.load(f).get("domaines", [])


def moderer(entree, ctx):
    """entree = question (str). Le premier domaine qui matche gagne (ordre = priorite)."""
    question = entree if isinstance(entree, str) else str(entree)
    lu = _normaliser(question)
    try:
        domaines = _load_domaines()
    except Exception as e:
        # UNE GARDE ABSENTE NE DOIT PAS OUVRIR LE PASSAGE. La config etait lue
        # hors du conteneur : l'echec rendait « libre » et
        # AUCUNE question sensible n'etait arretee depuis la conteneurisation --
        # sans erreur ni trace, la defaillance d'un garde est silencieuse.
        return {"domaine": None, "action": "refus_strict",
                "message": ("Je ne peux pas traiter votre demande : ma "
                            "configuration de securite est indisponible."),
                "_arret": True, "erreur": str(e)[:150]}
    for dom in domaines:
        for kw in dom.get("mots_cles", []):
            if _normaliser(kw).strip() in lu:
                action = dom.get("action")
                return {"domaine": dom.get("nom"),
                        "action": action,
                        "message": dom.get("message", ""),
                        "_arret": action in ACTIONS_ARRET}
    return {"domaine": None, "action": "libre", "message": "", "_arret": False}
