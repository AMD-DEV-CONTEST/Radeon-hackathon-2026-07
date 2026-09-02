#!/usr/bin/env python3
"""Traces de debogage des primitives 2SIN.

DISTINCT DU JOURNAL. Le journal (journal.py) consigne de quoi JUGER une decision
et ne porte jamais son contenu -- il tourne en permanence, en production. Ce
module-ci sert a COMPRENDRE une execution : il expose les entrees et sorties
reelles, donc des donnees de dossier (nom de locataire, montant, adresse).

    ACTIVATION : TRACE_PRIMITIVES=1
    PAR DEFAUT : eteint, cout nul.

    /!\\ CE MODE EXPOSE DES DONNEES METIER. Il n'a pas sa place en production.

Trois besoins, constates le 19/07 : comprendre pourquoi une primitive rend un
resultat inattendu, suivre ce qu'une valeur devient au fil des etapes (le
fondement, le destinataire), et distinguer une primitive d'une etape de skill.
"""
import os, sys, json, time

ACTIF     = os.environ.get("TRACE_PRIMITIVES", "0") not in ("0", "", "false", "non")
MAX_VAL   = int(os.environ.get("TRACE_MAX_VALEUR", "220"))
# Filtre optionnel : ne tracer que ces primitives (liste separee par des virgules)
_FILTRE   = [n.strip() for n in os.environ.get("TRACE_SEULEMENT", "").split(",") if n.strip()]


def _abrege(v, limite=None):
    """Une valeur lisible, bornee. Les gros blocs (corpus, brouillon) sont
    resumes a leur taille : les afficher noierait la trace."""
    limite = limite or MAX_VAL
    if v is None:
        return None
    if isinstance(v, (int, float, bool)):
        return v
    if isinstance(v, str):
        return v if len(v) <= limite else "%s… (%d car.)" % (v[:limite], len(v))
    if isinstance(v, dict):
        return {k: _abrege(x, 80) for k, x in list(v.items())[:12]}
    if isinstance(v, (list, tuple)):
        return [_abrege(x, 80) for x in v[:8]]
    return str(v)[:limite]


def tracer(nom, entree=None, sortie=None, duree=None, skill=None, **details):
    """Emet une ligne de trace sur stderr. Silencieux si le mode est eteint."""
    if not ACTIF or (_FILTRE and nom not in _FILTRE):
        return
    ligne = {"t": time.strftime("%H:%M:%S"),
             "primitive": nom,
             "type": "skill" if skill else "primitive"}
    if skill:
        ligne["skill"] = skill
    if entree is not None:
        ligne["entree"] = _abrege(entree)
    if sortie is not None:
        ligne["sortie"] = _abrege(sortie)
    if duree is not None:
        ligne["duree"] = round(duree, 3)
    for k, v in details.items():
        ligne[k] = _abrege(v, 120)
    try:
        print("[TRACE] " + json.dumps(ligne, ensure_ascii=False),
              file=sys.stderr, flush=True)
    except Exception:
        pass


def suivre(cle, valeur, ou=""):
    """Suit une VALEUR PARTICULIERE au fil des etapes.
    Repond a la question « d'ou vient cette valeur, et que devient-elle ? » --
    celle qui a coute le plus de temps aujourd'hui (le fondement qui derivait, le
    signataire devenu destinataire)."""
    if not ACTIF:
        return
    try:
        print("[SUIVI] %-22s %-16s = %s"
              % (ou, cle, json.dumps(_abrege(valeur, 160), ensure_ascii=False)),
              file=sys.stderr, flush=True)
    except Exception:
        pass
