#!/usr/bin/env python3
"""Primitive TACHE EN COURS 2SIN.
Un travail (etablir un acte, monter un dossier) s'etend sur PLUSIEURS tours : il
est ouvert par une demande, il reclame des elements, il s'enrichit, il se ferme.
Un tour qui ne porte pas de sujet propre se RATTACHE a la tache ouverte au lieu
d'etre requalifie a tort (constate : "pour M. TOTO, avril 2026, 599 euros"
requalifie en charges de copropriete alors qu'une relance de loyer etait en cours).

BORNES (une tache n'est jamais eternelle) :
  TTL             : une tache oubliee expire seule et ne contamine rien
  RATTACHEMENTS   : au-dela, elle se ferme -- un travail qui n'aboutit pas apres
                    N apports releve de l'insistance, pas de la constitution
Contrat : fn(entree, ctx) -> etat de la tache ; ecrit ctx["tache"].
"""
import os, json, time, re

try:
    from memoire import R
except ImportError:
    from primitives.memoire import R

TTL_TACHE         = int(os.environ.get("TTL_TACHE", "3600"))         # 1 h --
# 15 min ne suffisaient pas : un gestionnaire interrompu perdait ce qu'il
# avait deja donne, sans que rien ne le lui dise.
RATTACHEMENTS_MAX = int(os.environ.get("TACHE_RATTACHEMENTS_MAX", "6"))

def _kt(sid): return "tache:%s" % sid

# Un tour PORTEUR ouvre ou requalifie ; un tour d'APPORT complete la tache en cours.
_RE_PORTEUR = re.compile(
    r"\b(r[ée]dige|[ée]cris|pr[ée]pare|g[ée]n[èe]re|produis|courrier|lettre|"
    r"mise en demeure|relance|cong[ée]|quittance|attestation|quel|quelle|"
    r"comment|pourquoi|est-ce que)\b", re.I)


def lire_tache(sid):
    try:
        b = R.get(_kt(sid))
        return json.loads(b) if b else None
    except Exception:
        return None


def fermer_tache(sid):
    try:
        R.delete(_kt(sid))
    except Exception:
        pass


def _ecrire(sid, t):
    try:
        R.setex(_kt(sid), TTL_TACHE, json.dumps(t, ensure_ascii=False))
    except Exception:
        pass
    return t


def ouvrir_tache(sid, nature, sujet=""):
    return _ecrire(sid, {"nature": nature, "sujet": sujet, "elements": {},
                         "rattachements": 0, "ouverte_le": int(time.time())})


def rattacher(sid, elements=None):
    """Ajoute des elements a la tache en cours. Rend None si aucune tache ou si
    la limite de rattachements est atteinte (la tache est alors fermee)."""
    t = lire_tache(sid)
    if not t:
        return None
    t["rattachements"] = int(t.get("rattachements", 0)) + 1
    if t["rattachements"] > RATTACHEMENTS_MAX:
        fermer_tache(sid)
        return None
    for k, v in (elements or {}).items():
        if str(v or "").strip():
            t["elements"][k] = v          # le tour courant fait autorite
    return _ecrire(sid, t)


_RE_ABANDON = re.compile(
    r"\b(laisse tomber|laissez tomber|annule[rz]?|j'annule|abandonne|oublie[zr]?|"
    r"on oublie|stop|arr[êe]te[rz]?|autre chose|passons a autre chose|"
    r"non merci|c'est bon)\b", re.I)


def detecter_abandon(q):
    """Un travail s'abandonne A LA DEMANDE, sans attendre l'expiration."""
    return bool(_RE_ABANDON.search(str(q or "")))


def situer_tache(entree, ctx):
    """PRIMITIVE : le tour ouvre-t-il un travail, ou complete-t-il celui en cours ?
    Decision DETERMINISTE prise UNE FOIS, en amont du flux ; les etapes suivantes
    la recoivent par le workflow au lieu de rededuire la nature du travail.

    N'ECRIT RIEN dans le contexte : ce qu'elle produit est sa sortie,
    le workflow decide qui la recoit.
    -> {"tache": {...}|None, "rattache": bool, "nature": str|None,
        "ferme": bool, "raison": str|None}
    """
    q = entree[0] if isinstance(entree, (list, tuple)) and entree else entree
    sid = ctx.get("session") or "anonyme"
    encours = lire_tache(sid)

    # FERMETURE A LA DEMANDE : deux voies de sortie, le temps (TTL) et la volonte.
    # Un gestionnaire doit pouvoir abandonner un travail sans attendre l'expiration.
    if encours and detecter_abandon(q):
        fermer_tache(sid)
        # Un abandon efface le TRAVAIL et son CONTEXTE : sans cela l'intention
        # « redaction » survivait dans la memoire technique et la question
        # suivante, pourtant une consultation, etait traitee comme un acte a
        # rediger.
        try:
            from memoire import oublier_contexte
        except ImportError:
            from primitives.memoire import oublier_contexte
        oublier_contexte(sid)
        # L'ABANDON S'ACCUSE. Fermer en silence laissait le tour partir en
        # conversation libre : le gestionnaire disait « oublie » et recevait un
        # expose sur les types de baux. Un travail abandonne doit etre
        # confirme comme tel -- et le flux s'arrete la.
        _t = ("Tres bien, j'abandonne ce courrier en cours. "
              "Que puis-je faire pour vous ?")
        return {"tache": None, "rattache": False, "nature": None,
                "ferme": True, "raison": "abandon demande",
                "texte": _t, "message": _t, "_arret": True}

    porteur = bool(_RE_PORTEUR.search(str(q or "")))
    if encours and not porteur:
        t = rattacher(sid)                # tour d'apport : on complete
        if t:
            return {"tache": t, "rattache": True, "nature": t.get("nature"),
                    "ferme": False, "raison": None}
        return {"tache": None, "rattache": False, "nature": None,
                "ferme": True, "raison": "limite de rattachements"}

    # UNE TACHE S'OUVRE VIERGE : un tour PORTEUR ouvre un nouveau travail. Ce qui
    # restait d'un travail precedent ne lui appartient pas et ne doit pas s'y
    # deverser -- sans quoi un courrier herite du dossier d'un autre locataire.
    # La tache precedente est fermee ; l'ouverture proprement dite est faite par
    # la qualification (selectionner_gabarit), qui sait de quel acte il s'agit.
    if encours and porteur:
        fermer_tache(sid)
        return {"tache": None, "rattache": False, "nature": None,
                "ferme": True, "raison": "nouveau travail"}

    return {"tache": encours, "rattache": False,
            "nature": (encours or {}).get("nature"),
            "ferme": False, "raison": None}


def appliquer_tache(entree, ctx):
    """PRIMITIVE D'ECRITURE : applique la decision prise par la selection.
    Rendre l'ecriture VISIBLE dans le workflow -- l'ouverture etait enfouie dans
    la selection, le rattachement dans l'extraction, la fermeture dans la
    generation. Trois modifications d'etat qu'aucun fichier ne montrait.
    entree = [decision(str), nature(str), sujet(str), elements(dict|None)]
    -> {"tache": {...}|None, "applique": str|None}
    """
    dec      = entree[0] if len(entree) > 0 else None
    nature   = entree[1] if len(entree) > 1 else None
    sujet    = entree[2] if len(entree) > 2 else ""
    elements = entree[3] if len(entree) > 3 else None
    sid = ctx.get("session") or "anonyme"

    if dec == "ouvrir" and nature:
        return {"tache": ouvrir_tache(sid, nature, sujet), "applique": "ouvrir"}
    if dec == "rattacher":
        t = rattacher(sid, elements or {})
        return {"tache": t, "applique": "rattacher" if t else "limite"}
    if dec == "fermer":
        fermer_tache(sid)
        return {"tache": None, "applique": "fermer"}
    return {"tache": lire_tache(sid), "applique": None}
