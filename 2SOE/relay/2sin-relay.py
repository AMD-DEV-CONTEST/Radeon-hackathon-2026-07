#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2sin-relay — pont OpenAI-compatible vers le moteur de workflow souverain.

But : la page 2sin-chat.html (et tout client OpenAI) parle à CE relais comme
à une API /v1/chat/completions. Le relay execute un workflow declaratif via
Le relay execute un WORKFLOW declaratif (framework/) : gardes, corpus verifie,
memoire de travail, gabarits d'actes. Aucune dependance a un agent externe.
Fini les hallucinations de vLLM nu.

Aucune dépendance : stdlib seule. Lancement :
    python3 2sin-relay.py

Configuration par variables d'environnement (toutes optionnelles) :
    RELAY_HOST           interface d'écoute        (def: 0.0.0.0)
    RELAY_PORT           port d'écoute             (def: 8787)
    RELAY_MODEL_ID       id annoncé dans /v1/models (def: 2sin-agent)
"""

import json
import os
import re
import shutil
import base64
import subprocess
import time
import uuid
from urllib.parse import quote, unquote
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Racine des donnees, deduite de l'emplacement du script : le paquet suit le
# depot ou qu'il soit installe, sans chemin absolu a adapter.
_SEED = os.environ.get("SEED_ROOT", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data-seed"))

HOST = os.environ.get("RELAY_HOST", "0.0.0.0")
PORT = int(os.environ.get("RELAY_PORT", "8787"))
TIMEOUT = int(os.environ.get("RELAY_TIMEOUT", "180"))
MODEL_ID = os.environ.get("RELAY_MODEL_ID", "2sin-agent")
WEB_FILE = os.environ.get("RELAY_WEB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "2sin-chat.html"))

# --- Download : fichiers produits par l'agent, récupérés puis servis ---
FILES_DIR = os.environ.get("RELAY_FILES", "/opt/2sin/files")   # où le relais dépose les fichiers servis
AGENT_OUT = os.environ.get("AGENT_OUT", "/opt/data")           # où l'agent écrit (côté container)
ALLOWED_EXT = {".docx", ".pdf", ".xlsx", ".csv", ".pptx", ".doc", ".odt"}
_MIME = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".csv": "text/csv",
    ".odt": "application/vnd.oasis.opendocument.text",
}
# chemins de fichiers livrables mentionnés par l'agent (sous AGENT_OUT, extension autorisée)
_PATH_RE = re.compile(re.escape(AGENT_OUT) + r"/[^\s\"'`)\]]+?\.(?:docx|pdf|xlsx|csv|pptx|doc|odt)", re.IGNORECASE)

# --- Upload : fichiers envoyés par l'utilisateur, déposés dans le container pour l'agent ---
UP_HOST = os.environ.get("RELAY_UPLOADS", "/opt/2sin/uploads")     # zone de transit côté hôte
UP_CONTAINER = os.environ.get("RELAY_DEPOTS",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "depots"))  # zone de depot du relay
UP_EXT = {".pdf", ".docx", ".doc", ".odt", ".txt", ".md", ".csv", ".xlsx", ".png", ".jpg", ".jpeg"}
MAX_UPLOAD = int(os.environ.get("MAX_UPLOAD_MB", "20")) * 1024 * 1024



import urllib.request as _urlreq

TEI_URL = os.environ.get("TEI_URL", "http://localhost:8080/embed")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
RAG_COLLECTION = os.environ.get("RAG_COLLECTION", "juridique_code_civil")
RAG_TOPK = int(os.environ.get("RAG_TOPK", "3"))
RAG_MIN_SCORE = float(os.environ.get("RAG_MIN_SCORE", "0.60"))

def _post_json(url, payload, timeout=30):
    data = json.dumps(payload).encode("utf-8")
    req = _urlreq.Request(url, data=data, headers={"Content-Type": "application/json"})
    with _urlreq.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

DOMAINES_PATH = os.environ.get("DOMAINES_PATH",
    os.path.join(_SEED, "domaines_sensibles.json"))

def _load_domaines():
    """Charge la config des domaines sensibles (rechargee a chaque appel = a chaud)."""
    try:
        with open(DOMAINES_PATH, encoding="utf-8") as f:
            return json.load(f).get("domaines", [])
    except Exception:
        return []

def moderer(question):
    """Firewall semantique : classe la question par domaine sensible.
    Retourne (domaine, action, message) ou (None, None, None) si neutre.
    Le premier domaine qui matche un mot-cle gagne (ordre du fichier = priorite).
    """
    lu = question.lower()
    for dom in _load_domaines():
        for kw in dom.get("mots_cles", []):
            if kw in lu:
                return dom.get("nom"), dom.get("action"), dom.get("message", "")
    return None, None, None

PROFILS_PATH = os.environ.get("PROFILS_PATH",
    os.path.join(_SEED, "profils.json"))
RAG_PROFIL = os.environ.get("RAG_PROFIL", "")  # vide = profil_defaut du fichier

def _collections_actives():
    """Retourne la liste des collections Qdrant du profil actif (config vivante)."""
    try:
        with open(PROFILS_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        profil = RAG_PROFIL or cfg.get("profil_defaut", "residentiel")
        p = cfg.get("profils", {}).get(profil)
        if p and p.get("collections"):
            return p["collections"]
    except Exception:
        pass
    return [RAG_COLLECTION]  # fallback : collection unique

def detecter_references(question):
    """Detecte les references d'articles/lois citees explicitement dans le texte.
    Retourne une chaine de mots-cles cibles pour guider l'embed RAG, ou "".
    Resout le cas : extrait de jugement citant "article 24 III loi 89-462"
    -> on cible la recherche sur l'article, pas sur le paragraphe bruite."""
    refs = []
    q = question
    for m in re.finditer(r'(?:article|art\.?)\s+((?:[LRD]\.?\s*)?\d+(?:[-\u2011]\d+)*)', q, re.IGNORECASE):
        num = re.sub(r'\s+', '', m.group(1)).replace('.', '').replace('\u2011', '-')
        refs.append("article " + num)
    for m in re.finditer(r'\b([LRD])\.?\s*(\d+[-\u2011]\d+(?:[-\u2011]\d+)*)\b', q):
        ref = m.group(1) + m.group(2).replace('\u2011', '-')
        if ("article " + ref) not in refs:
            refs.append("article " + ref)
    for m in re.finditer(r'loi\s+(?:n[\u00b0o]?\s*)?(\d{2}[-\u2011]\d{3})', q, re.IGNORECASE):
        refs.append("loi " + m.group(1).replace('\u2011', '-'))
    seen = set(); out = []
    for r in refs:
        if r not in seen:
            seen.add(r); out.append(r)
    return " ".join(out)

# ============ EXTENSION LÉGIFRANCE (POC, canal opérateur/intention explicite) ============
OPENLEGI_TOKEN = os.environ.get("OPENLEGI_TOKEN", "")
OPENLEGI_BASE = os.environ.get("OPENLEGI_BASE", "https://mcp.openlegi.fr/legifrance/mcp")

# Mots-cles d'intention : l'utilisateur demande EXPLICITEMENT de consulter Legifrance.
LEGIFRANCE_INTENTS = [
    "legifrance", "légifrance", "complete avec", "complète avec",
    "verifie en ligne", "vérifie en ligne", "hors corpus", "hors-corpus",
    "texte officiel", "source officielle", "en ligne", "verifie sur",
    "vérifie sur", "à jour sur", "a jour sur", "consulte legifrance",
]

# Mapping reference -> texte LODA (lois hors code). Sinon = code.
LODA_TEXTS = {"89-462": "89-462", "65-557": "65-557"}

def intention_legifrance(question):
    """Detecte si l'utilisateur demande explicitement une consultation Legifrance."""
    lu = question.lower()
    return any(kw in lu for kw in LEGIFRANCE_INTENTS)

def _openlegi_call(tool, args):
    """Appel HTTP direct a OpenLegi (MCP/SSE) via urllib. Retourne le texte ou None.
    ANONYMISATION : n'envoie QUE les args fournis (references publiques),
    jamais le prompt brut ni les donnees client."""
    if not OPENLEGI_TOKEN:
        return None
    try:
        hdr = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer " + OPENLEGI_TOKEN,
        }
        # init
        p = {"jsonrpc":"2.0","id":0,"method":"initialize","params":{
            "protocolVersion":"2024-11-05","capabilities":{},
            "clientInfo":{"name":"2sin-relay","version":"1.0"}}}
        data = json.dumps(p).encode("utf-8")
        req = _urlreq.Request(OPENLEGI_BASE, data=data, headers=hdr)
        with _urlreq.urlopen(req, timeout=15) as r:
            sid = r.headers.get("mcp-session-id")
            r.read()
        if sid:
            hdr["mcp-session-id"] = sid
        # call
        p = {"jsonrpc":"2.0","id":1,"method":"tools/call",
             "params":{"name":tool,"arguments":args}}
        data = json.dumps(p).encode("utf-8")
        req = _urlreq.Request(OPENLEGI_BASE, data=data, headers=hdr)
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

# Mots vides a retirer pour extraire le SUJET juridique (anonymisation thematique).
_STOP_LEGI = {
    "vérifie", "verifie", "sur", "légifrance", "legifrance", "donne", "moi",
    "les", "le", "la", "des", "du", "de", "un", "une", "article", "articles",
    "depuis", "dans", "en", "ligne", "complète", "complete", "avec", "hors",
    "corpus", "texte", "officiel", "source", "officielle", "à", "a", "jour",
    "consulte", "cherche", "recherche", "quels", "quel", "sont", "est", "que",
    "qui", "pour", "et", "ou", "au", "aux", "code", "loi", "je", "veux",
}
def _mots_cles_sujet(question):
    """Extrait les mots-cles du SUJET juridique, sans les mots de commande.
    ANONYMISATION : ne garde que des termes juridiques generiques, pas les
    donnees client (noms propres filtres via capitalisation + longueur)."""
    mots = re.findall(r"[a-zàâäéèêëïîôöùûüç]+", question.lower())
    sujet = [m for m in mots if m not in _STOP_LEGI and len(m) > 2]
    return " ".join(sujet[:8])  # limite a 8 mots-cles

def _legifrance_thematique(question):
    """Recherche THEMATIQUE (par mots-cles) quand aucune reference precise.
    Retourne (contexte, message)."""
    code_name = _detect_code_name(question)
    sujet = _mots_cles_sujet(question)
    if not sujet:
        return "", ("Precisez le sujet juridique a rechercher sur Legifrance.")
    if not code_name:
        # Pas de code identifie : on tente le code penal par defaut si termes penaux,
        # sinon on demande. Pour le POC (ouvert), on tente Code penal + Code civil.
        codes_a_tenter = ["Code pénal", "Code civil"]
    else:
        codes_a_tenter = [code_name]
    blocs = []
    for cn in codes_a_tenter:
        res = _openlegi_call("rechercher_code", {"search": sujet, "code_name": cn})
        if res == "RATE_LIMIT":
            return "", ("Consultation Legifrance temporairement limitee. Reessayez.")
        if res and len(res) > 150 and "invalide" not in res[:80] and "aucun" not in res[:120].lower():
            blocs.append(res)
    if not blocs:
        return "", ("Aucun article trouve sur Legifrance pour ce sujet. "
                    "Precisez le code ou le numero d'article.")
    ctx = "[CONTEXTE LEGIFRANCE - recherche thematique externe, source a citer]\n"
    ctx += "\n---\n".join(b[:3000] for b in blocs)
    ctx += "\n[FIN CONTEXTE LEGIFRANCE - source : Legifrance (consultation externe). Cite les numeros d'articles trouves.]"
    return ctx, ""

def legifrance_search(question):
    """Si intention explicite + reference detectee, consulte Legifrance.
    ANONYMISATION PAR CONSTRUCTION : seule la reference extraite est envoyee.
    Retourne (contexte_formate, message_si_manque) : l'un des deux, jamais les deux."""
    if not intention_legifrance(question):
        return "", ""
    refs = detecter_references(question)
    # Extrait les numeros bruts : "article L631-7" -> "L631-7", "loi 89-462" -> "89-462"
    art_nums = re.findall(r'article\s+((?:[LRD])?\d+(?:-\d+)*)', refs)
    loi_nums = re.findall(r'loi\s+(\d{2}-\d{3})', refs)
    if not art_nums and not loi_nums:
        # Intention mais pas de reference precise : recherche THEMATIQUE (mots-cles).
        return _legifrance_thematique(question)
    blocs = []
    # Cas LODA (lois 89/65) si un numero de loi est cite avec un article
    for art in art_nums:
        # Si une loi LODA est citee, on route en LODA, sinon en code
        loi_ctx = loi_nums[0] if loi_nums else None
        if loi_ctx and loi_ctx in LODA_TEXTS:
            res = _openlegi_call("rechercher_dans_texte_legal",
                {"search": art.lstrip("L").lstrip("R").lstrip("D") if not art.startswith(("L","R","D")) else art,
                 "text_id": LODA_TEXTS[loi_ctx], "champ": "NUM_ARTICLE"})
        else:
            # Code : deviner le code par le prefixe n'est pas fiable -> on tente
            # les codes courants. Pour le POC, on route via rechercher_code
            # en laissant OpenLegi resoudre avec le nom de code detecte.
            res = None
            code_name = _detect_code_name(question)
            if code_name:
                res = _openlegi_call("rechercher_code",
                    {"search": art, "code_name": code_name, "champ": "NUM_ARTICLE"})
        if res == "RATE_LIMIT":
            return "", ("La consultation Legifrance est temporairement limitee "
                        "(trop de requetes). Reessayez dans quelques minutes.")
        if res and len(res) > 100 and "invalide" not in res[:80]:
            blocs.append(res)
    if not blocs:
        return "", ("Je n'ai pas pu recuperer cet article sur Legifrance. "
                    "Verifiez le numero et le code, ou reessayez.")
    ctx = "[CONTEXTE LEGIFRANCE - consultation externe officielle, source a citer]\n"
    ctx += "\n---\n".join(b[:3000] for b in blocs)
    ctx += "\n[FIN CONTEXTE LEGIFRANCE - indique que la source est Legifrance (consultation externe en temps reel).]"
    return ctx, ""

# Codes reconnus pour router rechercher_code (nom EXACT avec accents attendu par OpenLegi)
_CODES_CONNUS = {
    "construction": "Code de la construction et de l'habitation",
    "habitation": "Code de la construction et de l'habitation",
    "cch": "Code de la construction et de l'habitation",
    "commerce": "Code de commerce",
    "commercial": "Code de commerce",
    "penal": "Code pénal",
    "pénal": "Code pénal",
    "urbanisme": "Code de l'urbanisme",
    "civil": "Code civil",
}
def _detect_code_name(question):
    """Devine le code vise par le prefixe d'article ou un mot-cle du prompt."""
    lu = question.lower()
    for kw, nom in _CODES_CONNUS.items():
        if kw in lu:
            return nom
    return None

def rag_search(question):
    """Recherche RAG deterministe : embed question -> Qdrant -> chunks.
    Retourne un bloc contexte formate ou chaine vide."""
    try:
        refs = detecter_references(question)
        # Embed toujours sur la question naturelle (BGE-M3 prefere les phrases).
        vec = _post_json(TEI_URL, {"inputs": "Question juridique immobili\u00e8re : " + question + " ?"})[0]
        # Si des articles sont cites explicitement, on ajoute une recherche
        # DETERMINISTE par filtre sur le numero d'article (le core tranche,
        # pas la geometrie). Extrait les numeros bruts : "article 24" -> "24".
        ref_nums = re.findall(r'article\s+((?:[LRD])?\d+(?:-\d+)*)', refs)
        # Multi-collection : interroge toutes les collections du profil actif.
        merged = []
        for coll in _collections_actives():
            try:
                r = _post_json(
                    f"{QDRANT_URL}/collections/{coll}/points/search",
                    {"vector": vec, "limit": RAG_TOPK, "with_payload": True},
                )
                merged.extend(r.get("result", []))
            except Exception:
                continue  # collection absente ou erreur : on ignore, non bloquant
        # Recherche DETERMINISTE par filtre article si reference explicite citee.
        # On force ces hits en tete (le core tranche : article cite = article servi).
        ref_hit = False
        if ref_nums:
            for coll in _collections_actives():
                for num in ref_nums:
                    try:
                        r = _post_json(
                            f"{QDRANT_URL}/collections/{coll}/points/scroll",
                            {"filter": {"must": [{"key": "article",
                                "match": {"text": num}}]},
                             "limit": 3, "with_payload": True},
                        )
                        pts = r.get("result", {}).get("points", [])
                        for p in pts:
                            # match strict : le numero cite figure dans l'article
                            art = p.get("payload", {}).get("article", "")
                            if num.lower() in art.lower().replace(" ", ""):
                                p["score"] = 0.99  # force en tete
                                merged.append(p)
                                ref_hit = True
                    except Exception:
                        continue
        results = sorted(merged, key=lambda h: h.get("score", 0), reverse=True)
        if not results:
            return ""
        # Seuil adaptatif : top1 franc OU top1 correct + ecart net avec top2.
        top1 = results[0].get("score", 0)
        top2 = results[1].get("score", 0) if len(results) > 1 else 0.0
        accept = ref_hit or (top1 >= RAG_MIN_SCORE) or (top1 >= RAG_MIN_SCORE - 0.05 and (top1 - top2) >= 0.05)
        if not accept:
            return ""
        # On garde les hits proches du top1 (dans une fenetre), pas le bruit.
        hits = [h for h in results if h.get("score", 0) >= top1 - 0.12]
        lines = ["[CONTEXTE JURIDIQUE - sources officielles a utiliser en priorite]"]
        for h in hits:
            p = h["payload"]
            # Appartenance complete : code / branche / source / article (exigence de rigueur)
            code = p.get("code", "")
            branche = p.get("branche", "")
            source = p.get("source", p.get("loi", ""))
            appart = " / ".join(x for x in (code, branche, source, p.get("article", "")) if x)
            lines.append(f"- [{appart}] ({p.get('theme','')}) : {p.get('texte','')}")
        lines.append("[FIN CONTEXTE - cite OBLIGATOIREMENT l'appartenance complete de chaque article : code, texte source (loi et date), numero d'article. Format : 'selon l'article X de la <source> (<code>)'. N'utilise QUE les articles ci-dessus.]")
        return "\n".join(lines)
    except Exception as e:
        # RAG non bloquant : si erreur, on continue sans contexte
        return ""


def build_prompt(messages):
    """Aplatit l'historique OpenAI en un prompt unique.

    Le system éventuel est préfixé, mais le cadrage juridique réel vient de
    Le socle SOUL (Qdrant) fait autorite — le system client n'est qu'un complement.
    Un seul tour utilisateur -> on passe le message tel quel.
    Plusieurs tours -> transcript pour garder le contexte.
    """
    rule = (
        "Réponds en texte directement dans la conversation. "
        "Si l'utilisateur demande un document à télécharger (courrier, lettre, "
        "attestation, tableau...), génère-le au format .docx (ou .xlsx pour un tableau) "
        f"dans {AGENT_OUT} en suivant tes procédures (skill courrier), puis termine ta "
        "réponse par son chemin absolu, seul sur la dernière ligne. "
        "NE FABRIQUE JAMAIS de PDF toi-même (pas de reportlab, pas d'écriture de bytes) : "
        "la version PDF est produite automatiquement à partir du .docx. Donne toujours le "
        "chemin du .docx. Sinon, n'écris aucun fichier et ne renvoie aucun chemin. "
        "Si le message mentionne un document joint (chemin de fichier), lis-en le "
        "contenu (read_file, ou extraction via code si le format est binaire) avant de répondre."
    )
    system = "\n".join(m.get("content", "") for m in messages if m.get("role") == "system").strip()
    system = (rule + "\n\n" + system).strip()
    turns = [m for m in messages if m.get("role") in ("user", "assistant")]

    if len([m for m in turns if m.get("role") == "user"]) <= 1:
        body = next((m.get("content", "") for m in reversed(turns) if m.get("role") == "user"), "")
    else:
        lines = []
        for m in turns:
            who = "Utilisateur" if m.get("role") == "user" else "Assistant"
            lines.append(f"{who} : {m.get('content', '')}")
        lines.append("Assistant :")
        body = "\n\n".join(lines)

    return (system + "\n\n" + body).strip()


# ============ MOTEUR SOUVERAIN 2SIN (framework/) ============
# Le relay ne fabrique pas le prompt : il DELEGUE a un moteur de workflow
# declaratif. Aucune dependance a un agent externe.
import sys as _sys
_FW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "framework")
if _FW_DIR not in _sys.path:
    _sys.path.insert(0, _FW_DIR)
from moteur import Moteur as _Moteur
from primitives import REGISTRE as _REGISTRE

_WF_DIR_PUB = os.environ.get("WORKFLOWS_DIR", "")
# GARDE-FOUS DE /v1/executer : ce point d'entree execute un workflow sans passer
# par l'authentification du chat. Deux bornes, declarees a l'exterieur du code :
# un jeton partage, et la liste des workflows appelables. Sans jeton configure,
# l'entree est FERMEE -- une absence de configuration ne doit jamais ouvrir un acces.
EXEC_TOKEN = os.environ.get("EXEC_TOKEN", "").strip()
EXEC_WORKFLOWS = [w.strip() for w in
                  os.environ.get("EXEC_WORKFLOWS", "").split(",") if w.strip()]
_WF_PATH = os.environ.get("WORKFLOW_PATH",
                          os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "framework", "workflows", "juridique.json"))
_MOTEUR = _Moteur(_REGISTRE)
if not _WF_DIR_PUB:
    _WF_DIR_PUB = os.path.dirname(_WF_PATH)


def _charger_workflow():
    """Workflow relu a CHAQUE requete : versionnable a chaud, sans redemarrage."""
    with open(_WF_PATH, encoding="utf-8") as f:
        return json.load(f)


def executer_workflow(nom, params, session_id, profil=None):
    """Execute un workflow NOMME avec ses parametres, hors conversation.
    Voie d'appel pour tout ce qui sollicite 2SIN sans passer par le chat :
    planificateur, connecteur, API cabinet. Le workflow porte l'ordre ; ce point
    d'entree ne fait que le designer et l'alimenter.
    -> {"ok": bool, "sortie": {...}} ou {"ok": False, "erreur": str}
    """
    chemin = os.path.join(_WF_DIR_PUB, "%s.json" % nom) if not nom.endswith(".json") \
             else os.path.join(_WF_DIR_PUB, nom)
    if not os.path.isfile(chemin):
        return {"ok": False, "erreur": "workflow introuvable : %s" % nom}
    try:
        with open(chemin, encoding="utf-8") as fh:
            wf = json.load(fh)
    except Exception as e:
        return {"ok": False, "erreur": "lecture workflow : %s" % str(e)[:150]}
    base = {"session": session_id,
            "profil": profil or RAG_PROFIL or "residentiel",
            "complexite": "simple"}
    base.update(params or {})
    try:
        ctx = _MOTEUR.executer(wf, base)
    except Exception as e:
        return {"ok": False, "erreur": "execution : %s" % str(e)[:250]}
    # On ne renvoie que ce que le workflow DECLARE exposer ; a defaut, un resume.
    expose = wf.get("expose")
    if expose:
        sortie = {k: ctx.get(k) for k in expose if k in ctx}
    else:
        sortie = {k: v for k, v in ctx.items() if not k.startswith("_")}
    ctx["_workflow_nom"] = nom
    try:
        from primitives.journal import journaliser as _journaliser
        _journaliser(None, ctx)
    except Exception:
        pass
    return {"ok": True, "workflow": nom, "sortie": sortie,
            "arrete_par": ctx.get("_arrete_par")}


def traiter_via_moteur(question, session_id, base_url="", profil=None):
    """Execute le workflow et adapte la sortie au format attendu par l'UI."""
    # PROFIL EFFECTIF : header X-Profil (user authentifie) prioritaire,
    # puis RAG_PROFIL (env global), puis defaut. Cloisonne collections + memoire.
    profil_actif = profil or RAG_PROFIL or "residentiel"
    wf = _charger_workflow()

    # --- CHEMIN D'INDICES : navigation episodique sur demande ---
    question_moteur = question
    naviguer_chemin = enregistrer_chemin = None
    try:
        from primitives.memoire import (naviguer_chemin, enregistrer_chemin,
                                         detecter_rappel, rappeler_chemin_long,
                                         archiver_chemin_long, longueur_chemin,
                                         dernier_tour)
        from primitives.svo import archiver_svo
        rappel = naviguer_chemin(session_id, question)
        if rappel:
            # La commande de rappel ("reviens a ma premiere question") n'est PAS
            # une question : c'est une navigation. Une fois la cible retrouvee,
            # on REJOUE la question cible telle quelle. Garder la formule de
            # rappel parasitait l'embed et le modele repondait a la meta-phrase.
            question_moteur = rappel
        elif detecter_rappel(question) is not None:
            # RECOURS CHEMIN LONG : un rappel est demande MAIS le
            # chemin Redis est vide (court terme expire). On descend au froid :
            # recherche par theme, cross-session, filtree par profil. Le froid
            # PROUVE l'historique (theme + date) sans en RESTITUER le contenu.
            empreintes = rappeler_chemin_long(profil_actif, question,
                                              session=session_id)
            if empreintes:
                e = empreintes[0]
                import datetime as _dt
                quand = _dt.datetime.fromtimestamp(e.get("ts", 0)).strftime("%d/%m/%Y")
                question_moteur = ("%s (rappel : ce theme -- %s -- a ete aborde le %s ; "
                                   "le detail n'est plus en memoire courte)"
                                   % (question, e.get("sujet", ""), quand))
    except Exception:
        naviguer_chemin = enregistrer_chemin = None

    ctx = _MOTEUR.executer(wf, {"question": question_moteur,
                                "session": session_id,
                                "profil": profil_actif,
                                "complexite": "simple"})
    # SECONDE PASSE -- la demande ne se decide pas SEULE, mais un tour precedent
    # existe. On rejoue le workflow ENTIER sur la question concatenee, comme si
    # l'utilisateur avait tout ecrit d'un coup : firewall, domaine, droits, RAG.
    # Constate le 28/07 : « cela fait partie de quel article », posee apres une
    # question de legitime defense, recevait un corpus de copropriete. La meme
    # demande ecrite en UN tour rend hors_droits -- le bon comportement.
    # UNE SEULE reprise : si le resultat reste imprecis, on demande.
    if ctx.get("rag_statut") == "imprecise":
        try:
            _prec = dernier_tour(session_id)
        except Exception:
            _prec = None
        if _prec and _prec.strip().lower() != question_moteur.strip().lower():
            ctx = _MOTEUR.executer(wf, {"question": _prec + " " + question_moteur,
                                        "session": session_id,
                                        "profil": profil_actif,
                                        "complexite": "simple"})
            ctx["_reprise_enrichie"] = True
    ctx["_workflow_nom"] = os.path.basename(_WF_PATH).replace(".json", "")
    try:
        from primitives.journal import journaliser as _journaliser
        _journaliser(None, ctx)
    except Exception:
        pass

    try:
        if enregistrer_chemin:
            enregistrer_chemin(session_id, question)
        # ARCHIVAGE CHEMIN LONG : verser une EMPREINTE du tour
        # dans Qdrant (preuve + theme, SANS contenu). Seulement pour un vrai
        # tour (pas une navigation). Non bloquant.
        if archiver_chemin_long and detecter_rappel(question) is None and not ctx.get("_arrete_par"):
            intention = ctx.get("intention") or {}
            sujet = intention.get("sujet") or ""
            domaine = intention.get("domaine") or ""
            if sujet:
                ordre = longueur_chemin(session_id)
                archiver_chemin_long(profil_actif, session_id, ordre, sujet, domaine)
            # ARCHIVAGE SVO : triplet de travail moyen terme, deterministe.
            if 'archiver_svo' in dir():
                archiver_svo(profil_actif, session_id, question,
                             ctx.get("intention") or {})
    except Exception:
        pass

    # Firewall : flux stoppe par une garde -> reponse du core, le modele n'a pas ete appele.
    if ctx.get("_arrete_par"):
        return ctx.get("_arret_message") or "Demande non traitee."

    verif = ctx.get("verif") or {}
    texte = verif.get("texte") or ctx.get("brouillon") or ""
    # REDACTION : la sortie de generer_document PRIME sur le brouillon. Sans cela,
    # une demande de confirmation ou un champ manquant reste invisible : le
    # gestionnaire voit un texte juridique et aucun document, sans savoir pourquoi
    # (constate 18/07). Le core doit dire ce qu'il attend.
    _doc = ctx.get("doc") or {}
    # Acte PRODUIT : on annonce le document, on ne deverse pas le texte juridique
    # qui a servi a l'etablir (il est dans le courrier, pas dans la conversation).
    if isinstance(_doc, dict) and _doc.get("chemin"):
        _v = _doc.get("variables") or {}
        _obj = _v.get("objet") or "courrier"
        _dest = _v.get("nom_destinataire") or ""
        texte = ("Courrier etabli : %s%s." % (_obj, (" - " + _dest) if _dest else ""))
    if isinstance(_doc, dict) and not _doc.get("chemin"):
        if _doc.get("a_confirmer") or _doc.get("manquants") or _doc.get("erreur"):
            _msg = _doc.get("texte") or ""
            _manq = _doc.get("manquants") or []
            if _manq and not _doc.get("a_confirmer"):
                _msg = ("Je ne peux pas etablir cet acte : il me manque "
                        + ", ".join(_manq) +
                        ". Pouvez-vous me preciser ces elements ?")
            if _msg:
                texte = _msg

    fichiers = ctx.get("fichiers") or {}
    liens = []
    for cle in ("docx", "pdf", "md"):
        url = fichiers.get(cle)
        if url:
            nom = url.rsplit("/", 1)[-1]
            liens.append("[\U0001F4CE %s](%s%s)" % (nom, base_url, url))
    if liens:
        texte = (texte + "\n\n" + "  \u00b7  ".join(liens)).strip()
    elif fichiers.get("erreur") and not (isinstance(_doc, dict) and
                                         (_doc.get("manquants") or _doc.get("a_confirmer"))):
        texte = (texte + "\n\n\u26a0\ufe0f " + str(fichiers["erreur"])).strip()

    return texte or "Reponse vide."


def completion_json(text):
    return {
        "id": "chatcmpl-" + uuid.uuid4().hex[:24],
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL_ID,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def chunk_json(delta=None, finish=None):
    return {
        "id": "chatcmpl-" + uuid.uuid4().hex[:24],
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": MODEL_ID,
        "choices": [{"index": 0, "delta": ({"content": delta} if delta is not None else {}), "finish_reason": finish}],
    }


# signatures (magic bytes) attendues par extension — un fichier valide commence par l'une d'elles
_SIGNATURES = {
    ".docx": [b"PK\x03\x04"], ".xlsx": [b"PK\x03\x04"], ".pptx": [b"PK\x03\x04"],
    ".odt": [b"PK\x03\x04"], ".doc": [b"\xd0\xcf\x11\xe0"], ".pdf": [b"%PDF"],
    ".csv": None,  # texte : pas de signature à exiger
}
_MIN_SIZE = 256  # un livrable Office/PDF valide fait au moins quelques centaines d'octets


def _valid_file(path, ext):
    """Vérifie qu'un fichier livrable est bien formé (taille + signature). 
    Retourne True si on peut le servir en confiance."""
    try:
        if os.path.getsize(path) < _MIN_SIZE:
            return False
        sigs = _SIGNATURES.get(ext, [])
        if sigs is None:        # type texte (csv) : pas de signature à contrôler
            return True
        if not sigs:
            return True
        with open(path, "rb") as f:
            head = f.read(8)
        return any(head.startswith(s) for s in sigs)
    except Exception:
        return False


def push_upload(host_path, name, token):
    """Depose le fichier televerse dans la zone du relay.

    Le fichier reste dans la zone du relay : aucun rapatriement vers un
    conteneur tiers, donc aucun socket Docker requis.

    Le fichier est desormais DEPOSE, pas traite : ce qu'on en fait relevera d'une
    primitive a concevoir (lire un bail, extraire les donnees d'un etat des
    lieux). Deposer sans traiter vaut mieux qu'amputer.
    Retourne le chemin du depot, ou None.
    """
    dest_dir = UP_CONTAINER
    dest = os.path.join(dest_dir, token + "_" + name)
    try:
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copy(host_path, dest)
        return dest
    except Exception:
        return None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # silencieux
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _json(self, code, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _serve_web(self):
        try:
            with open(WEB_FILE, "rb") as f:
                data = f.read()
        except Exception:
            self._json(404, {"error": {"message": "page introuvable : " + WEB_FILE}})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self._cors()
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass
        self.close_connection = True

    def _serve_download(self, path):
        # /files/<token>/<nom> — token hex + basename, jamais de chemin arbitraire
        parts = path.split("/")  # ['', 'files', token, nom...]
        if len(parts) != 4 or not re.fullmatch(r"[0-9a-f]{32}", parts[2]):
            self._json(404, {"error": {"message": "not found"}})
            return
        token = parts[2]
        name = os.path.basename(unquote(parts[3]))  # neutralise tout ../
        ext = os.path.splitext(name)[1].lower()
        full = os.path.realpath(os.path.join(FILES_DIR, token, name))
        root = os.path.realpath(FILES_DIR)
        if ext not in ALLOWED_EXT or not full.startswith(root + os.sep) or not os.path.isfile(full):
            self._json(404, {"error": {"message": "not found"}})
            return
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", _MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(name))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self._cors()
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass
        self.close_connection = True

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")
        if path.startswith("/files/"):
            self._serve_download(self.path.split("?")[0])
        elif path.endswith("/models"):
            self._json(200, {"object": "list", "data": [
                {"id": MODEL_ID, "object": "model", "created": int(time.time()), "owned_by": "webotic-2sin"}]})
        elif path == "/health":
            self._json(200, {"status": "ok", "modele": MODEL_ID,
                             "workflow": os.path.basename(os.environ.get("WORKFLOW_PATH", ""))})
        elif path in ("", "/index.html", "/2sin-chat.html"):
            self._serve_web()
        else:
            self._json(404, {"error": {"message": "not found"}})

    def _handle_upload(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_UPLOAD * 2:  # base64 ~+33%, marge large
                self._json(413, {"error": {"message": "Fichier trop volumineux."}})
                return
            req = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._json(400, {"error": {"message": "JSON invalide"}})
            return
        name = os.path.basename(str(req.get("name", ""))).strip()
        ext = os.path.splitext(name)[1].lower()
        data_b64 = str(req.get("data", ""))
        if "," in data_b64 and data_b64.strip().startswith("data:"):
            data_b64 = data_b64.split(",", 1)[1]
        if not name or ext not in UP_EXT:
            self._json(400, {"error": {"message": "Type de fichier non autorisé."}})
            return
        try:
            raw = base64.b64decode(data_b64, validate=False)
        except Exception:
            self._json(400, {"error": {"message": "Contenu illisible."}})
            return
        if len(raw) > MAX_UPLOAD:
            self._json(413, {"error": {"message": "Fichier trop volumineux."}})
            return
        token = uuid.uuid4().hex
        host_dir = os.path.join(UP_HOST, token)
        try:
            os.makedirs(host_dir, exist_ok=True)
            host_path = os.path.join(host_dir, name)
            with open(host_path, "wb") as f:
                f.write(raw)
        except Exception as e:
            self._json(500, {"error": {"message": "Écriture impossible : " + str(e)}})
            return
        agent_path = push_upload(host_path, name, token)
        if not agent_path:
            self._json(502, {"error": {"message": "Transfert vers l'agent échoué."}})
            return
        self._json(200, {"ok": True, "path": agent_path, "name": name})

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/")
        if path.endswith("/upload"):
            self._handle_upload()
            return
        if path.endswith("/executer"):
            self._handle_executer()
            return
        if not path.endswith("/chat/completions"):
            self._json(404, {"error": {"message": "not found"}})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._json(400, {"error": {"message": "JSON invalide"}})
            return

        messages = req.get("messages", [])
        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user = m.get("content", "")
                break
        if not last_user:
            self._json(400, {"error": {"message": "Aucun message utilisateur."}})
            return

        stream = bool(req.get("stream"))
        # IDENTITE : X-User / X-Profil fournis par le backend de session
        # (Node/JWT). L'agent recoit un user DEJA authentifie. Fallback IP sinon.
        xuser = self.headers.get("X-User")
        xprofil = self.headers.get("X-Profil")
        if xuser:
            sid = "user-" + str(xuser).replace(" ", "_")
        else:
            sid = "web-" + str(self.client_address[0]).replace(".", "-")
        host = self.headers.get("Host") or ""
        # L'hote d'origine prime : derriere le proxy d'authentification, "Host"
        # vaut "relay:8787" (nom interne Docker) et le lien serait mort depuis
        # le navigateur.
        host = self.headers.get("X-Forwarded-Host") or host
        base_url = ("http://" + host) if host else ""

        try:
            text = traiter_via_moteur(last_user, sid, base_url=base_url, profil=xprofil)
        except Exception as e:
            err = "Erreur moteur 2SIN : " + str(e)[:300]
            if stream:
                self._stream(["\u26a0\ufe0f " + err])
            else:
                self._json(502, {"error": {"message": err}})
            return

        if stream:
            self._stream([text])
        else:
            self._json(200, completion_json(text))

    def _handle_executer(self):
        """POST /v1/executer {workflow, params, session, profil}
        Execution d'un workflow nomme, hors conversation."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._json(400, {"error": {"message": "JSON invalide"}})
            return
        if not EXEC_TOKEN:
            self._json(403, {"error": {"message": "execution directe non activee"}})
            return
        _jeton = (self.headers.get("X-Exec-Token") or "").strip()
        if _jeton != EXEC_TOKEN:
            self._json(401, {"error": {"message": "jeton d'execution invalide"}})
            return
        nom = req.get("workflow")
        if not nom:
            self._json(400, {"error": {"message": "champ 'workflow' requis"}})
            return
        if EXEC_WORKFLOWS and nom not in EXEC_WORKFLOWS:
            self._json(403, {"error": {"message": "workflow non autorise a l'appel direct"}})
            return
        sid = (self.headers.get("X-User") or req.get("session")
               or "appel-" + str(self.client_address[0]).replace(".", "-"))
        profil = self.headers.get("X-Profil") or req.get("profil")
        res = executer_workflow(nom, req.get("params") or {}, sid, profil=profil)
        self._json(200 if res.get("ok") else 400, res)

    def _stream(self, parts):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self._cors()
        self.end_headers()
        try:
            for p in parts:
                self.wfile.write(b"data: " + json.dumps(chunk_json(delta=p)).encode("utf-8") + b"\n\n")
            self.wfile.write(b"data: " + json.dumps(chunk_json(finish="stop")).encode("utf-8") + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        self.close_connection = True


if __name__ == "__main__":
    print(f"2sin-relay -> ecoute http://{HOST}:{PORT}  (modele={MODEL_ID})")
    print(f"  endpoint chat : http://{HOST}:{PORT}/v1/chat/completions")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
