#!/usr/bin/env python3
"""Primitive extraire_variables_courrier 2SIN.
le modele ne renseigne QUE les variables metier ; la FORME (template, structure,
formats) appartient au code. Le modele ne touche jamais au docx.
Contrat : fn(entree, ctx) -> dict des 9 cles du template, ou {"erreur":...}
"""
import os
_RACINE = os.environ.get("SEED_ROOT", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "data-seed"))

import json, re, os, datetime
import urllib.request as u

VLLM_URL   = os.environ.get("VLLM_URL", "http://localhost:8000/v1/chat/completions")
VLLM_MODEL = os.environ.get("VLLM_MODEL", "mistralai/Mistral-7B-Instruct-v0.3")

CLES = ["nom_cabinet", "adresse_cabinet", "nom_destinataire", "adresse_destinataire",
        "date", "objet", "corps", "signataire", "fonction_signataire"]
# Le CORPS ne fait pas partie de ce que le modele redige : il TRAVERSE depuis le
# contenu deja verifie par le controle de fidelite. Le modele n'extrait que les
# metadonnees du dossier. Sinon il reformule et annule la verification amont.
CLES_MODELE = [k for k in CLES if k != "corps"]

_MOIS = ["janvier","fevrier","mars","avril","mai","juin","juillet",
         "aout","septembre","octobre","novembre","decembre"]

REGLE = (
    "Tu extrais UNIQUEMENT des metadonnees pour un courrier de cabinet immobilier.\n"
    "Tu ne rediges RIEN : ni le corps, ni les formules. La structure est imposee par un modele.\n\n"
    "Reponds par un objet JSON STRICT, sans texte avant ni apres, avec exactement ces cles :\n"
    "  nom_cabinet, adresse_cabinet, nom_destinataire, adresse_destinataire,\n"
    "  date, objet, signataire, fonction_signataire\n\n"
    "REGLES ABSOLUES :\n"
    "- N'INVENTE JAMAIS une information absente de la demande.\n"
    "- Si une information n'est pas fournie, mets une CHAINE VIDE \"\".\n"
    "- INTERDIT d'ecrire un marqueur de remplacement : pas de \"Votre Nom\", \"Votre Agence\",\n"
    "  \"[Adresse]\", \"XXX\", \"a completer\". Chaine vide obligatoire dans ce cas.\n"
    "- date : format francais lisible (ex : 18 juillet 2026). Jamais de format ISO.\n"
    "- objet : une ligne courte resumant l'objet du courrier.\n"
)

def _llm(sys_prompt, q, maxt=700):
    payload = {"model": VLLM_MODEL,
               "messages": [{"role": "system", "content": sys_prompt},
                            {"role": "user", "content": q}],
               "temperature": 0.0, "max_tokens": maxt}
    hdr = {"Content-Type": "application/json"}
    k = os.environ.get("MISTRAL_API_KEY", "")
    if k and "api.mistral.ai" in VLLM_URL:
        hdr["Authorization"] = "Bearer " + k
    req = u.Request(VLLM_URL, data=json.dumps(payload).encode(), headers=hdr)
    r = json.loads(u.urlopen(req, timeout=120).read().decode())
    m = r["choices"][0]["message"]
    return (m.get("content") or "") + " " + (m.get("reasoning") or "")

def _extract_json(txt):
    if not txt: return None
    for m in re.finditer(r'\{(?:[^{}]|"(?:[^"\\]|\\.)*")*\}', txt, re.S):
        try:
            d = json.loads(m.group(0))
            if isinstance(d, dict) and d:
                return d   # tout objet non vide : metadonnees OU variables de gabarit
        except Exception:
            continue
    return None

def _date_fr_aujourdhui():
    n = datetime.date.today()
    return "%d %s %d" % (n.day, _MOIS[n.month - 1], n.year)


# ---------------------------------------------------------------------------
# GABARITS DE MOTIF : le motif d'un acte est CONSTANT. Le modele
# n'en redige pas le texte, il renseigne les variables. Trois generations d'une
# meme demande donnaient trois motifs differents (constat 26/06 puis 18/07) :
# recopie de l'article, effet juridique invente, signature dupliquee.
# ---------------------------------------------------------------------------
GABARITS_PATH = os.environ.get("GABARITS_PATH",
                               os.path.join(_RACINE, "gabarits_motif.json"))

def _charger_gabarits():
    try:
        with open(GABARITS_PATH, encoding="utf-8") as fh:
            return json.load(fh).get("gabarits", {})
    except Exception:
        return {}

def _choisir_gabarit(question, sujet=""):
    """Selection DETERMINISTE par declencheur lexical. Aucun gabarit -> None
    (on retombe sur le motif redige, comportement precedent)."""
    txt = ((question or "") + " " + (sujet or "")).lower()
    for nom, g in _charger_gabarits().items():
        for d in g.get("declencheurs", []):
            if d.lower() in txt:
                return nom, g
    return None, None

REGLE_VARIABLES = (
    "Tu extrais des variables metier pour un acte de cabinet immobilier.\n"
    "Tu ne rediges AUCUNE phrase : le texte de l'acte est impose par un gabarit.\n\n"
    "Reponds par un objet JSON STRICT, sans texte avant ni apres, avec exactement "
    "ces cles : %s\n\n"
    "REGLES ABSOLUES :\n"
    "- N'INVENTE JAMAIS une valeur absente de la demande ou du contexte juridique.\n"
    "- Si une valeur manque, mets une chaine vide.\n"
    "- periode : ex 'juin 2026'. montant : ex '850 euros'.\n"
    "- fondement : reference seule, ex \"l'article 24 de la loi n 89-462 du 6 juillet 1989\".\n"
    "  Jamais le texte de l'article, jamais d'enumeration.\n"
    "- date_effet : date en francais lisible.\n"
)

def _motif_par_gabarit(gab, contenu, question, ctx):
    """Le core assemble le motif : le modele ne fournit que les valeurs."""
    champs = gab.get("variables", [])
    try:
        brut = _llm(REGLE_VARIABLES % ", ".join(champs),
                    "[DEMANDE]\n" + question + "\n\n[CONTEXTE JURIDIQUE]\n" + contenu,
                    maxt=300)
    except Exception:
        return None
    d = _extract_json(brut) or {}
    vals = {k: str(d.get(k, "") or "").strip() for k in champs}
    # NORMALISATION (le core corrige ce que le modele ecrit approximativement) :
    # "loi n 89-462" -> "loi n° 89-462", "article L145 5" -> "article L145-5".
    if "fondement" in vals and vals["fondement"]:
        vals["fondement"] = re.sub(r"\bn\s*[°o]?\s*(?=\d)", "n° ", vals["fondement"])
        vals["fondement"] = re.sub(r"\s{2,}", " ", vals["fondement"]).strip()
    if not all(vals.values()):
        return None          # variable manquante -> pas d'invention, on renonce
    try:
        return gab["motif"].format(**vals)
    except Exception:
        return None

def _norm_simple(s):
    s = (s or "").lower()
    for a, b in (("é","e"),("è","e"),("ê","e"),("à","a"),("â","a"),("î","i"),
                 ("ô","o"),("û","u"),("ù","u"),("ç","c")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", " ", s)


def _ancre_simple(valeur, source_norm):
    """La valeur est-elle REELLEMENT presente dans le tour courant ?"""
    jetons = [j for j in _norm_simple(valeur).split() if len(j) > 3 or j.isdigit()]
    return all(j in source_norm for j in jetons) if jetons else False


def extraire_variables_courrier(entree, ctx):
    """Assemble les champs du courrier. AUCUN appel au modele.

    Il y avait DEUX extractions concurrentes -- celle des champs de l'acte
    (gabarit.extraire_variables, controlee et accumulee dans la tache) et celle
    des metadonnees du courrier, qui redemandait au modele les memes champs sans
    les memes regles. Elles divergeaient a chaque tour : le signataire devenait
    destinataire, l'adresse du cabinet ecrasait celle du locataire.

    Une seule collecte fait foi : la TACHE. Ici on ne fait plus que servir ce
    qu'elle porte, completer la date et appliquer l'objet declare par le gabarit.
    """
    if isinstance(entree, list):
        contenu = entree[0] if len(entree) > 0 else ""
    else:
        contenu = str(entree)

    try:
        from tache import lire_tache
        from gabarit import _charger as _charger_gab
    except ImportError:
        from primitives.tache import lire_tache
        from primitives.gabarit import _charger as _charger_gab

    _t = lire_tache(ctx.get("session") or "") or {}
    _el = _t.get("elements") or {}
    out = {k: str(_el.get(k, "") or "").strip() for k in CLES_MODELE}

    # La date n'est pas une donnee du dossier : c'est celle du jour.
    if not out.get("date"):
        out["date"] = _date_fr_aujourdhui()

    # Presentation constante.
    for k in ("fonction_signataire",):
        if out.get(k):
            out[k] = out[k][0].upper() + out[k][1:]

    # OBJET DECLARE PAR LE GABARIT : c'est une propriete de l'acte, avec ses
    # trous. Format tolerant -- un element absent disparait de la parenthese.
    _g = (_charger_gab() or {}).get(_t.get("nature") or "") or {}
    if _g.get("objet"):
        class _Vide(dict):
            def __missing__(self, k): return ""
        out["objet"] = re.sub(r"\s*\(\s*\)", "", _g["objet"].format_map(_Vide(_el))).strip()

    # Le corps est servi par le gabarit (document.py) ; ce qui arrive ici n'est
    # qu'un repli quand aucun gabarit ne couvre l'acte.
    out["corps"] = str(contenu or "").strip()
    return out
