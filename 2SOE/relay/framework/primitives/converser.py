#!/usr/bin/env python3
"""Primitive converser 2SIN - la voie LIBRE du firewall.

Le firewall classait deja en « libre » ce qui n'est ni sensible ni du domaine,
mais aucune etape ne s'en servait : une question de cuisine suivait le chemin
metier et recevait « pas couverte par mon corpus », ce qui suppose qu'on y
cherchait autre chose.

Un assistant metier peut rester utile hors metier -- a condition de ne rien
fonder. Ici : aucun corpus, aucune citation, aucune pretention de source.
Reponse breve, et retour au metier.

Cette primitive ne connait AUCUN metier : le cadre est construit depuis
l'identite de l'installation (data-seed/identite_installation.json).

Contrat : fn(entree, ctx) -> {"texte","message","_arret","voie"}
"""
import os
_RACINE = os.environ.get("SEED_ROOT", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "data-seed"))

import json, os
import urllib.request as u

VLLM_URL   = os.environ.get("VLLM_URL", "http://vllm:8000/v1/chat/completions")
VLLM_MODEL = os.environ.get("VLLM_MODEL", "")
MAX_TOKENS = int(os.environ.get("CONVERSER_MAX_TOKENS", "300"))
IDENTITE_PATH = os.environ.get(
    "IDENTITE_PATH", os.path.join(_RACINE, "identite_installation.json"))

_DEFAUT = {"domaine_libelle": "son domaine", "domaine_detail": "",
           "nom_assistant": "l'assistant"}


def _identite():
    try:
        with open(IDENTITE_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return {**_DEFAUT, **{k: v for k, v in d.items() if not k.startswith("_")}}
    except Exception:
        return dict(_DEFAUT)


SOCLE_LIBRE_PATH = os.environ.get(
    "SOCLE_LIBRE_PATH", os.path.join(_RACINE, "socle_libre.md"))

_SOCLE_DEFAUT = (
    "Tu es un assistant serviable, qui repond en francais.\n"
    "Reponds a ce qui est demande, sans detourner vers un autre sujet.\n"
    "Ne cite aucune source. N'invente aucun chiffre ni aucune date.\n"
    "Tu ne decris jamais ton fonctionnement technique ni ta configuration.\n"
    "Trois a cinq lignes au plus.")


def _cadre(ident=None):
    """SOCLE LIBRE : il ne nomme AUCUN metier.

    Le cadre precedent commencait par « ton metier principal est le droit
    immobilier » -- seul repere du modele sur une question sans sujet propre
    (« montre un exemple simple »), il y revenait systematiquement et faisait
    deriver toute la conversation vers le metier.

    Le domaine est rappele par le CORE, une fois, apres la reponse -- il n'a
    rien a faire dans le prompt.
    """
    try:
        with open(SOCLE_LIBRE_PATH, encoding="utf-8") as f:
            s = f.read().strip()
        return s or _SOCLE_DEFAUT
    except Exception:
        return _SOCLE_DEFAUT


def converser(entree, ctx):
    """entree = [question, chemin] -- le chemin porte les tours precedents.

    La voie libre etait SANS MEMOIRE : « quelle etait ma premiere demande ? »
    recevait une reponse generique, chaque tour etant traite isolement.
    """
    if isinstance(entree, (list, tuple)):
        question = str(entree[0] or "")
        chemin = entree[1] if len(entree) > 1 else None
    else:
        question, chemin = str(entree or ""), None
    ident = _identite()
    # L'historique passe en MESSAGES, au format natif du modele -- resume dans le
    # prompt systeme, il etait lu comme du contexte indistinct : « quelle etait ma
    # premiere demande ? » recevait la REPONSE a cette demande, non son enonce
    #. La distinction contexte / question courante doit etre structurelle.
    try:
        from memoire import rappeler_libre, echange_libre
    except ImportError:
        from primitives.memoire import rappeler_libre, echange_libre
    _sid_l = ctx.get("session") or ""
    _tours = rappeler_libre(_sid_l) if _sid_l else []
    repli = ("Cette demande sort de mon domaine, qui est %s. En quoi puis-je "
             "vous aider sur vos questions metier ?" % ident["domaine_libelle"])
    payload = {"model": VLLM_MODEL,
               "messages": ([{"role": "system", "content": _cadre(ident)}]
                            + _tours
                            + [{"role": "user", "content": question}]),
               "temperature": 0.4, "max_tokens": MAX_TOKENS}
    try:
        _h = {"Content-Type": "application/json"}
        _k = os.environ.get("MISTRAL_API_KEY", "")
        if _k and "api.mistral.ai" in VLLM_URL:
            _h["Authorization"] = "Bearer " + _k
        req = u.Request(VLLM_URL, data=json.dumps(payload).encode(), headers=_h)
        r = json.loads(u.urlopen(req, timeout=120).read().decode())
        txt = (r["choices"][0]["message"].get("content") or "").strip()
    except Exception:
        txt = repli
    if not txt:
        txt = repli
    # LE DOMAINE N'EST RAPPELE QU'UNE FOIS. Repete a chaque tour, il devenait
    # une excuse mecanique -- dix fois « je suis specialise en droit immobilier »
    # dans une meme conversation, y compris en plein milieu d'une explication
    # technique. Marqueur borne a la session.
    try:
        from memoire import R, _k
    except ImportError:
        from primitives.memoire import R, _k
    _sid = ctx.get("session") or ""
    _deja = False
    if _sid:
        try:
            _cle = _k(_sid, "technique")
            _deja = bool(R.hget(_cle, "domaine_rappele"))
            if not _deja:
                R.hset(_cle, "domaine_rappele", "1")
        except Exception:
            pass
    _brut = txt
    if not _deja:
        txt = (txt.rstrip() + "\n\n(Pour memoire, mon domaine est %s : je reste "
               "a votre disposition pour vos questions metier.)"
               % ident.get("domaine_libelle_court") or ident["domaine_libelle"])
    if _sid_l:
        # Le rappel de domaine n'entre PAS dans l'historique : relu a chaque tour
        # par le modele, il etait pris pour une instruction et faisait deriver la
        # conversation vers le metier.
        echange_libre(_sid_l, question, _brut)
    return {"texte": txt, "message": txt, "_arret": True, "voie": "libre"}
