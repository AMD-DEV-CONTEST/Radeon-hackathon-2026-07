#!/usr/bin/env python3
"""Primitive abstenir 2SIN - l'abstention est STRUCTURELLE.

Le garde-fou etait une consigne dans le prompt (« n'invente ni article, ni
date ») : une esperance comportementale, que le modele a ignoree en repondant
sur le divorce avec des articles inventes -- 237-1 puis 238-1, et un formulaire
qui n'existe pas.

Quand le corpus n'a rien servi sur une question du domaine, le modele n'est PAS
appele : le core repond. C'est la seule forme d'abstention qui ne peut pas fuir.

Cette primitive ne connait AUCUN metier : les libelles viennent de l'identite de
l'installation (data-seed/identite_installation.json). Un corpus n'est pas
necessairement juridique.

Contrat : fn(entree, ctx) -> {"texte","message","_arret","abstention","raison"}
"""
import os
_RACINE = os.environ.get("SEED_ROOT", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "data-seed"))

import json, os

IDENTITE_PATH = os.environ.get(
    "IDENTITE_PATH", os.path.join(_RACINE, "identite_installation.json"))

_DEFAUT = {"domaine_libelle": "son domaine",
           "domaine_detail": "",
           "corpus_libelle": "corpus",
           "recours": "l'avis d'un professionnel",
           "nom_assistant": "l'assistant",
           "domaines_libelles": {}}


def _identite():
    """Relue a chaque appel : changer d'installation ne demande aucun
    redemarrage, comme les profils et les domaines sensibles."""
    try:
        with open(IDENTITE_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return {**_DEFAUT, **{k: v for k, v in d.items() if not k.startswith("_")}}
    except Exception:
        return dict(_DEFAUT)


def abstenir(entree, ctx):
    """Trois situations, trois reponses.

    HORS DROITS   le sujet releve du domaine, mais le corpus qui le traite n'est
                  pas ouvert a ce profil -- ET un autre profil le detient.
                  « Demandez un acces » n'a de sens que si l'acces existe.
    HORS DOMAINE  la demande ne releve pas du domaine couvert.
    HORS CORPUS   la demande en releve, mais aucune source verifiee ne la couvre.
    """
    ident = _identite()
    domaine = (ctx.get("intention") or {}).get("domaine") or ""
    lib_dom = (ident.get("domaines_libelles") or {}).get(domaine)

    if ctx.get("rag_statut") == "hors_droits" and domaine not in ("", "hors_domaine"):
        _t = ("Votre question releve bien %s%s mais le corpus qui la traite "
              "n'est pas ouvert a votre profil.\n"
              "Je ne peux pas y repondre depuis les seules sources auxquelles "
              "j'ai acces : ce serait repondre a cote.\n"
              "Rapprochez-vous de votre administrateur si cet acces vous est "
              "necessaire."
              % (ident["domaine_libelle"], (" - %s -" % lib_dom) if lib_dom else ""))
        return {"texte": _t, "message": _t, "_arret": True,
                "abstention": True, "raison": "hors_droits"}

    # HORS DOMAINE ou HORS CORPUS ? Le plancher de resonance classe « divorce »
    # en hors_domaine parce qu'aucune description de domaine ne lui ressemble --
    # or le firewall, lui, l'a reconnu comme relevant du metier. Quand il l'a
    # reconnu, la demande EST du domaine : elle n'est simplement pas couverte
    #. On lit la garde RECUE, pas le contexte.
    _garde = entree[1] if isinstance(entree, (list, tuple)) and len(entree) > 1 else {}
    _reconnu_metier = (_garde or {}).get("action") == "corpus"
    if domaine == "hors_domaine" and not _reconnu_metier:
        _t = ("Je suis un assistant specialise en %s%s. Cette demande sort de "
              "mon domaine.\n"
              "En quoi puis-je vous aider sur vos questions metier ?"
              % (ident.get("domaine_libelle_court") or ident["domaine_libelle"],
                 (" : " + ident["domaine_detail"]) if ident.get("domaine_detail") else ""))
        return {"texte": _t, "message": _t, "_arret": True,
                "abstention": True, "raison": "hors_domaine"}

    lignes = ["Cette question n'est pas couverte par mon %s." % ident["corpus_libelle"]]
    if lib_dom:
        lignes.append("Mon %s porte sur %s ; je ne dispose d'aucune source "
                      "verifiee pour y repondre." % (ident["corpus_libelle"], lib_dom))
    else:
        lignes.append("Je ne dispose d'aucune source verifiee pour y repondre.")
    lignes.append("Je prefere m'abstenir plutot que de vous exposer une reponse "
                  "que je ne peux pas fonder. Pour ce point, %s est necessaire."
                  % ident["recours"])
    texte = "\n".join(lignes)
    return {"texte": texte, "message": texte, "_arret": True,
            "abstention": True, "raison": "hors_corpus"}
