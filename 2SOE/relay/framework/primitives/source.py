#!/usr/bin/env python3
"""Primitive rechercher_source 2SIN - CANAL N3 : Legifrance live (MCP OpenLegi).
Declenchee UNIQUEMENT sur intention EXPLICITE de l'utilisateur ("verifie sur Legifrance").
Le corpus local (N1) reste la source par defaut ; ce canal sert la verification externe.

ANONYMISATION PAR CONSTRUCTION : seule la REFERENCE extraite (article, loi) ou les
mots-cles du SUJET juridique sont envoyes. Jamais le prompt brut, jamais les donnees
client. Les mots de commande sont retires, les termes < 3 caracteres ecartes.

Contrat : fn(entree, ctx) -> {"trouve": "oui"|"non", "message": str, "_arret": bool}
Effet de bord assume : pose ctx["rag"] quand la source officielle est trouvee
(elle est PRIORITAIRE sur le corpus local : l'utilisateur l'a demandee explicitement).
"""
import json, os, re
import urllib.request as _urlreq

from .corpus import detecter_references

OPENLEGI_TOKEN = os.environ.get("OPENLEGI_TOKEN", "")
OPENLEGI_BASE  = os.environ.get("OPENLEGI_BASE", "https://mcp.openlegi.fr/legifrance/mcp")

# Intention EXPLICITE : l'utilisateur demande la consultation externe.
LEGIFRANCE_INTENTS = [
    "legifrance", "l\u00e9gifrance", "complete avec", "compl\u00e8te avec",
    "verifie en ligne", "v\u00e9rifie en ligne", "hors corpus", "hors-corpus",
    "texte officiel", "source officielle", "en ligne", "verifie sur",
    "v\u00e9rifie sur", "\u00e0 jour sur", "a jour sur", "consulte legifrance",
]

# Lois hors code (LODA). Sinon : routage code.
LODA_TEXTS = {"89-462": "89-462", "65-557": "65-557"}

# Noms EXACTS attendus par OpenLegi (accents compris).
_CODES_CONNUS = {
    "construction": "Code de la construction et de l'habitation",
    "habitation":   "Code de la construction et de l'habitation",
    "cch":          "Code de la construction et de l'habitation",
    "commerce":     "Code de commerce",
    "commercial":   "Code de commerce",
    "penal":        "Code p\u00e9nal",
    "p\u00e9nal":   "Code p\u00e9nal",
    "urbanisme":    "Code de l'urbanisme",
    "civil":        "Code civil",
}

# Mots de COMMANDE retires avant tout envoi externe (anonymisation thematique).
_STOP_LEGI = {
    "v\u00e9rifie", "verifie", "sur", "l\u00e9gifrance", "legifrance", "donne", "moi",
    "les", "le", "la", "des", "du", "de", "un", "une", "article", "articles",
    "depuis", "dans", "en", "ligne", "compl\u00e8te", "complete", "avec", "hors",
    "corpus", "texte", "officiel", "source", "officielle", "\u00e0", "a", "jour",
    "consulte", "cherche", "recherche", "quels", "quel", "sont", "est", "que",
    "qui", "pour", "et", "ou", "au", "aux", "code", "loi", "je", "veux",
}


def intention_legifrance(question):
    """L'utilisateur demande-t-il EXPLICITEMENT la consultation externe ?"""
    lu = (question or "").lower()
    return any(kw in lu for kw in LEGIFRANCE_INTENTS)


def _detect_code_name(question):
    lu = (question or "").lower()
    for kw, nom in _CODES_CONNUS.items():
        if kw in lu:
            return nom
    return None


def _mots_cles_sujet(question):
    """Mots-cles du SUJET juridique, sans les mots de commande (anonymisation)."""
    mots = re.findall(r"[a-z\u00e0\u00e2\u00e4\u00e9\u00e8\u00ea\u00eb\u00ef\u00ee\u00f4\u00f6\u00f9\u00fb\u00fc\u00e7]+",
                      (question or "").lower())
    sujet = [m for m in mots if m not in _STOP_LEGI and len(m) > 2]
    # OpenLegi cherche en TOUS_LES_MOTS (ET logique) : plus il y a de mots,
    # moins il y a de resultats. Mesure du 11/07 : 3 mots -> 0 resultat.
    # On garde les 3 termes les plus longs (les plus discriminants).
    sujet = sorted(sujet, key=len, reverse=True)[:3]
    return " ".join(sujet)


def _openlegi_call(tool, args):
    """Appel MCP direct (urllib, stdlib). Retourne le texte, 'RATE_LIMIT', ou None.
    N'envoie QUE les args fournis : references publiques ou mots-cles anonymises."""
    if not OPENLEGI_TOKEN:
        return None
    try:
        hdr = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream",
               "Authorization": "Bearer " + OPENLEGI_TOKEN}
        p = {"jsonrpc": "2.0", "id": 0, "method": "initialize",
             "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                        "clientInfo": {"name": "2sin-moteur", "version": "1.0"}}}
        req = _urlreq.Request(OPENLEGI_BASE, data=json.dumps(p).encode("utf-8"), headers=hdr)
        with _urlreq.urlopen(req, timeout=15) as r:
            sid = r.headers.get("mcp-session-id")
            r.read()
        if sid:
            hdr["mcp-session-id"] = sid
        p = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": tool, "arguments": args}}
        req = _urlreq.Request(OPENLEGI_BASE, data=json.dumps(p).encode("utf-8"), headers=hdr)
        with _urlreq.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8")
        for line in body.strip().split(chr(10)):
            if line.startswith("data: "):
                res = json.loads(line[6:])
                if "error" in res:
                    return None
                return res["result"]["content"][0]["text"]
    except _urlreq.HTTPError as e:
        if e.code == 429:
            return "RATE_LIMIT"
        return None
    except Exception:
        return None
    return None


def _bloc(blocs, thematique=False):
    titre = ("[CONTEXTE LEGIFRANCE - recherche thematique externe, source a citer]"
             if thematique else
             "[CONTEXTE LEGIFRANCE - consultation externe officielle, source a citer]")
    ctx = titre + "\n"
    ctx += "\n---\n".join(b[:3000] for b in blocs)
    ctx += ("\n[FIN CONTEXTE LEGIFRANCE - source : Legifrance (consultation externe en temps reel). "
            "Cite les numeros d'articles trouves. N'utilise QUE ce texte. Si une information "
            "n'y figure pas, dis 'non precise dans la source' au lieu de l'inventer.]")
    return ctx


def _thematique(question):
    """SUPPRIME. La recherche PLEIN TEXTE externe est structurellement inapte,
    demontre par la mesure :

      1. Le NOM DOCTRINAL n'est pas dans le texte. "violation de domicile" -> 0 resultat :
         l'article 226-4 dit "l'introduction dans le domicile d'autrui...". Le plein texte
         cherche des MOTS, la notion juridique porte un NOM. Les deux ne coincident pas.

      2. ET logique (TOUS_LES_MOTS) : 3 mots -> 0 resultat.

      3. OU logique (UN_DES_MOTS) : 99 articles de BRUIT, dont un article ABROGE
         (446-1, vente a la sauvette, ABROGE_DIFF) -- servi comme "source officielle
         Legifrance". Servir un article abroge a un cabinet est la faute maximale.

    => Le canal externe N3 ne sert QUE sur REFERENCE EXPLICITE (fait objectif,
       resultat exact, verifiable). Sans reference : on DEMANDE, on ne devine pas.
       Le corpus local vectorise (N1) reste seul capable de chercher du SENS.
    """
    return None, ("Pour consulter Legifrance, indiquez le NUMERO de l'article "
                  "(exemple : \"verifie sur Legifrance l'article 226-4 du code penal\").\n\n"
                  "La consultation externe s'appuie sur la reference exacte : c'est le seul "
                  "moyen d'obtenir le texte officiel en vigueur, sans risque de servir un "
                  "article hors sujet ou abroge. Une recherche par mots-cles sur Legifrance "
                  "ne retrouve pas une notion juridique par son nom (l'expression "
                  "\"violation de domicile\" ne figure pas dans le texte de l'article qui "
                  "la definit).")


def rechercher_source(entree, ctx):
    """entree = question (str). Ne fait RIEN sans intention explicite de l'utilisateur."""
    question = entree if isinstance(entree, str) else str(entree)

    if not intention_legifrance(question):
        return {"trouve": "non", "message": "", "_arret": False}

    refs = detecter_references(question)
    art_nums = re.findall(r'article\s+((?:[LRD])?\d+(?:-\d+)*)', refs)
    loi_nums = re.findall(r'loi\s+(\d{2}-\d{3})', refs)

    if not art_nums and not loi_nums:
        contexte, msg = _thematique(question)
    else:
        blocs = []
        msg = None
        for art in art_nums:
            loi = loi_nums[0] if loi_nums else None
            if loi and loi in LODA_TEXTS:
                # Loi hors code (89-462 / 65-557) -> fond LODA
                num = art if art.startswith(("L", "R", "D")) else art.lstrip("LRD")
                res = _openlegi_call("rechercher_dans_texte_legal",
                                     {"search": num, "text_id": LODA_TEXTS[loi],
                                      "champ": "NUM_ARTICLE"})
            else:
                res = None
                code_name = _detect_code_name(question)
                if code_name:
                    res = _openlegi_call("rechercher_code",
                                         {"search": art, "code_name": code_name,
                                          "champ": "NUM_ARTICLE"})
            if res == "RATE_LIMIT":
                return {"trouve": "non", "_arret": True,
                        "message": ("La consultation Legifrance est temporairement limitee "
                                    "(trop de requetes). Reessayez dans quelques minutes.")}
            if res and len(res) > 100 and "invalide" not in res[:80]:
                blocs.append(res)
        if blocs:
            contexte = _bloc(blocs)
        else:
            contexte = None
            msg = ("Je n'ai pas pu recuperer cet article sur Legifrance. "
                   "Verifiez le numero et le code, ou reessayez.")

    if contexte:
        # Source officielle PRIORITAIRE : l'utilisateur l'a demandee explicitement.
        ctx["rag"] = contexte
        ctx["rag_statut"] = "servi"
        ctx["source_canal"] = "legifrance_n3"
        return {"trouve": "oui", "message": "", "_arret": False}

    # Intention exprimee mais rien recupere : le core repond, le modele n'est pas appele.
    return {"trouve": "non", "message": msg, "_arret": True}
