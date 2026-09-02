#!/usr/bin/env python3
"""Primitive memoire 2SIN - mémoire conversationnelle catégorisée sur Redis.
Contrat : fn(entree, ctx) -> sortie. Categorisation technique/sensible + TTL differencie.
"""
import os, redis, re
R = redis.Redis(host=os.environ.get("REDIS_HOST", "localhost"), port=int(os.environ.get("REDIS_PORT", "6379")), decode_responses=True)
TTL_TECH = int(os.environ.get("TTL_TECH", "3600"))
TTL_SENS = int(os.environ.get("TTL_SENS", "300"))
TTL_CHEMIN = int(os.environ.get("TTL_CHEMIN", "3600"))
MAX_CHEMIN = 20   # profondeur max du fil conserve

# --- CHEMIN D'INDICES : sequence ordonnee des prompts bruts ---
# Le chemin est la MEMOIRE EPISODIQUE : navigable par position.
# Il ne SOURCE rien (jamais cite) ; il ORIENTE la requete sur demande.

# Declencheurs de RAPPEL (regex, deterministe = core). Presence -> navigation.
_RE_PREMIER   = re.compile(r"\b(premi[eè]re?|tout(?:e)? premi[eè]re?|1[eè]re?)\b", re.I)
_RE_RETOUR    = re.compile(r"\b(reviens?|revenons|retour(?:ne)?|comme (?:tout )?[àa] l'heure|pr[eé]c[eé]demment|tout [àa] l'heure)\b", re.I)
_RE_PRECEDENT = re.compile(r"\b(pr[eé]c[eé]dent(?:e)?|d'avant|juste avant)\b", re.I)
# CONTINUATION : poursuit le dernier tour (n'est PAS un rappel, ne rejoue pas).
_RE_CONTINUATION = re.compile(r"^\s*(et\s*(donc|apr[eè]s|ensuite|alors|quoi|puis)?|ensuite|donc|d'accord et|ok et)\s*[\?\.,\!]*\s*$", re.I)

def _kc(sid): return "chemin:%s" % sid

def enregistrer_chemin(sid, prompt):
    """Append du prompt brut en fin de sequence (RPUSH), borne a MAX_CHEMIN.
    Un prompt de NAVIGATION pure (rappel) n'entre pas dans le chemin :
    il ne fait que pointer vers un tour, il n'est pas un tour lui-meme."""
    if not prompt: return
    if detecter_rappel(prompt) is not None:
        return  # commande de navigation, pas un vrai tour
    R.rpush(_kc(sid), prompt)
    R.ltrim(_kc(sid), -MAX_CHEMIN, -1)
    R.expire(_kc(sid), TTL_CHEMIN)

def detecter_rappel(q):
    """Retourne l'index cible dans le chemin, ou None si pas de rappel demande.
    0 = premier ; -2 = precedent (avant le courant) ; None = aucun."""
    if not q: return None
    if _RE_PREMIER.search(q):   return 0     # la premiere question
    if _RE_PRECEDENT.search(q): return -1    # l'avant-dernier (le precedent)
    if _RE_RETOUR.search(q):    return 0     # "reviens" seul -> debut du fil
    return None

def detecter_continuation(q):
    """True si la question est une continuation vague ('et donc ?', 'ensuite').
    Distinct du rappel : on n'REJOUE pas un tour, on POURSUIT le dernier."""
    if not q: return False
    return bool(_RE_CONTINUATION.match(q))

def dernier_tour(sid):
    """Le dernier tour reel du chemin (sujet a poursuivre). None si vide."""
    try:
        chemin = R.lrange(_kc(sid), 0, -1)
        return chemin[-1] if chemin else None
    except Exception:
        return None

def naviguer_chemin(sid, q):
    """Si un rappel est detecte, retourne le prompt cible du chemin. Sinon None.
    Le prompt COURANT n'est pas encore dans le chemin au moment de l'appel."""
    idx = detecter_rappel(q)
    if idx is None: return None
    chemin = R.lrange(_kc(sid), 0, -1)
    if not chemin: return None
    try:
        return chemin[idx]
    except IndexError:
        return chemin[0] if chemin else None

def _k(sid, cat): return "sess:%s:%s" % (sid, cat)


def oublier_contexte(sid):
    """Efface le contexte technique et sensible d'une session.
    Un abandon efface le TRAVAIL et son CONTEXTE : sans cela l'intention
    « redaction » survivait et la question suivante, pourtant une consultation,
    etait traitee comme un acte a rediger."""
    try:
        R.delete(_k(sid, "technique"), _k(sid, "sensible"))
        return True
    except Exception:
        return False

def detecte_sensible(q):
    return bool(re.search(r'\d[\d\s]*€|\d+\s*euros', q or "")) or bool(re.search(r'\bM\.|\bMme|\bMonsieur|\bMadame', q or ""))

def rappeler_contexte(entree, ctx):
    """entree = session_id ; rend le contexte technique ET le chemin des tours.

    Le chemin etait lu ailleurs, jamais expose au workflow : la voie libre s'en
    trouvait sans memoire. Meme mémoire, meme moment, une seule lecture.
    -> {"domaine":.., "intention":.., "sujet":.., "chemin":[..]}
    """
    sid = entree
    t = dict(R.hgetall(_k(sid, "technique")) or {})
    try:
        t["chemin"] = R.lrange(_kc(sid), -8, -1) or []
    except Exception:
        t["chemin"] = []
    return t

def memoriser(entree, ctx):
    """entree = session_id ; lit ctx['intention'] et ctx['question'] pour ecrire technique + sensible."""
    sid = entree
    intent = ctx.get("intention") or {}
    q = ctx.get("question", "")
    # technique (se propage)
    if intent.get("domaine"):    R.hset(_k(sid,"technique"), "domaine", intent["domaine"])
    if intent.get("intention"):  R.hset(_k(sid,"technique"), "intention", intent["intention"])
    if intent.get("sujet"):      R.hset(_k(sid,"technique"), "sujet", intent["sujet"])
    R.expire(_k(sid,"technique"), TTL_TECH)
    # sensible (isole, TTL court)
    sensible = detecte_sensible(q)
    if sensible:
        R.hset(_k(sid,"sensible"), "donnees", q)
        R.expire(_k(sid,"sensible"), TTL_SENS)
    return {"memorise": True, "sensible": sensible}


# ============================================================================
# CHEMIN PERSISTANT LONG TERME (Qdrant)
# ----------------------------------------------------------------------------
# Le chemin Redis (ci-dessus) est GLISSANT (TTL court). Ici, le chemin LONG :
# une EMPREINTE par tour (profil, session, ordre, ts, sujet, domaine) versee
# dans Qdrant. PREUVE d'historique + theme, JAMAIS le contenu (doctrine :
# "preuve sans contenu"). Vectorise sur le SUJET -> retrouvable par theme.
#
# SOLLICITATION : LU seulement en RECOURS (rappel demande + chemin Redis vide).
# Ecrit a chaque tour reel (empreinte legere). Portee : cross-session par PROFIL.
# ============================================================================
import json, time, urllib.request as _u

_TEI_URL    = os.environ.get("TEI_URL", "http://localhost:8080/embed")
_QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
_MEM_COLL   = os.environ.get("MEM_CHEMIN_COLLECTION", "memoire_chemin")

def _post_json(url, payload, timeout=15):
    req = _u.Request(url, data=json.dumps(payload).encode(),
                     headers={"Content-Type": "application/json"})
    with _u.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def _embed(texte):
    """Embedding via TEI (BGE-M3). Retourne le vecteur ou None si echec."""
    try:
        return _post_json(_TEI_URL, {"inputs": texte})[0]
    except Exception:
        return None

def _mem_assure_collection(dim):
    """Cree la collection memoire_chemin si absente (idempotent)."""
    try:
        req = _u.Request(_QDRANT_URL + "/collections/" + _MEM_COLL, method="GET")
        _u.urlopen(req, timeout=5)
        return  # existe deja
    except Exception:
        pass
    try:
        req = _u.Request(_QDRANT_URL + "/collections/" + _MEM_COLL,
                         data=json.dumps({"vectors": {"size": dim, "distance": "Cosine"}}).encode(),
                         headers={"Content-Type": "application/json"}, method="PUT")
        _u.urlopen(req, timeout=10)
    except Exception:
        pass

def archiver_chemin_long(profil, session, ordre, sujet, domaine):
    """Verse une EMPREINTE du tour dans Qdrant (preuve + theme, sans contenu).
    Vectorise sur le sujet. Silencieux en cas d'echec (non bloquant)."""
    if not sujet:
        return False
    vec = _embed(sujet)
    if vec is None:
        return False
    _mem_assure_collection(len(vec))
    # id deterministe : profil+session+ordre (evite les doublons au rejeu)
    pid = abs(hash("%s|%s|%s" % (profil, session, ordre))) % (10**15)
    point = {
        "id": pid, "vector": vec,
        "payload": {
            "profil": profil or "default", "session": session or "",
            "ordre": ordre, "ts": int(time.time()),
            "sujet": sujet, "domaine": domaine or "",
        },
    }
    try:
        req = _u.Request(_QDRANT_URL + "/collections/" + _MEM_COLL + "/points",
                         data=json.dumps({"points": [point]}).encode(),
                         headers={"Content-Type": "application/json"}, method="PUT")
        _u.urlopen(req, timeout=10)
        return True
    except Exception:
        return False

def rappeler_chemin_long(profil, q, limite=3, session=None):
    """RECOURS : cherche par theme dans le chemin long. A n'appeler QUE si le
    chemin Redis est sans objet ET un rappel est demande.

    CLOISONNEMENT : ce recours etait « cross-session, filtre profil » --
    cross-session et cross-UTILISATEUR avaient ete confondus. Le profil borne les
    DROITS, il ne borne pas les personnes : un gestionnaire pouvait s'entendre
    dire qu'un theme avait ete aborde, alors qu'il l'avait ete par un collegue.
    On filtre desormais sur la session (identite du travailleur) ; retrouver ses
    propres echanges anterieurs reste possible, ceux d'autrui non.
    """
    vec = _embed(q)
    if vec is None:
        return []
    _must = [{"key": "profil", "match": {"value": profil or "default"}}]
    if session:
        _must.append({"key": "session", "match": {"value": session}})
    body = {"vector": vec, "limit": limite, "with_payload": True,
            "filter": {"must": _must}}
    try:
        res = _post_json(_QDRANT_URL + "/collections/" + _MEM_COLL + "/points/search", body)
        hits = res.get("result", [])
    except Exception:
        return []
    return [h.get("payload", {}) for h in hits]


def longueur_chemin(sid):
    """Nombre de tours dans le chemin Redis d'une session (= n° du tour courant)."""
    try:
        return R.llen(_kc(sid))
    except Exception:
        return 0

# ---------------------------------------------------------------------------
# ACTE EN ATTENTE DE CONFIRMATION
# Etat COURT et CONSOMME, distinct de la memoire conversationnelle. Quand des
# valeurs proviennent d'un echange precedent, le core ne les engage pas dans un
# acte : il les propose et attend un accord. Cet etat porte les valeurs exactes
# proposees ; au tour suivant, un accord genere AVEC ELLES, sans reextraction et
# sans consulter la memoire (le canal qui avait fait partir le courrier d'un
# locataire a un autre). Il est detruit des qu'il a servi, ou expire seul.
# ---------------------------------------------------------------------------
TTL_ACTE = int(os.environ.get("TTL_ACTE", "300"))     # 5 min : le temps d'un accord

def _ka(sid): return "acte:%s" % sid

def fusionner_acte(sid, gabarit, valeurs, question):
    """ACTE EN COURS DE CONSTITUTION. L'acte s'ENRICHIT de tour en tour :
    les valeurs du tour courant ECRASENT les anciennes, celles qui ne sont pas
    contredites sont CONSERVEES. C'est l'usage legitime de la memoire : accumuler
    un dossier. Un tour ne repart jamais de zero, mais il fait toujours autorite
    sur ce qu'il apporte."""
    ancien = lire_acte_attente(sid) or {}
    if ancien.get("gabarit") and gabarit and ancien["gabarit"] != gabarit:
        ancien = {}                       # changement d'acte : on repart propre
    fusion = dict(ancien.get("valeurs") or {})
    for k, v in (valeurs or {}).items():
        if str(v or "").strip():
            fusion[k] = v                 # le tour courant fait autorite
    return poser_acte_attente(sid, gabarit or ancien.get("gabarit"), fusion, question)


def poser_acte_attente(sid, gabarit, valeurs, question):
    """Ecrit l'etat tel quel (usage interne : fusionner_acte passe par ici)."""
    try:
        R.setex(_ka(sid), TTL_ACTE, json.dumps(
            {"gabarit": gabarit, "valeurs": valeurs, "question": question},
            ensure_ascii=False))
        return True
    except Exception:
        return False

def lire_acte_attente(sid):
    """L'acte en attente, ou None. Lecture seule : ne consomme pas."""
    try:
        brut = R.get(_ka(sid))
        return json.loads(brut) if brut else None
    except Exception:
        return None

def consommer_acte_attente(sid):
    """Rend l'acte ET le detruit : un accord ne vaut qu'une fois."""
    a = lire_acte_attente(sid)
    try:
        R.delete(_ka(sid))
    except Exception:
        pass
    return a

_RE_ACCORD = re.compile(r"^\s*(oui|ok|d'accord|daccord|c'est (ca|cela)|exact|"
                        r"confirme|je confirme|tout a fait|affirmatif)\s*[.!]*\s*$", re.I)

def detecter_accord(q):
    """True si le tour est un acquiescement pur (pas une nouvelle demande)."""
    return bool(_RE_ACCORD.match(q or ""))

# ---------------------------------------------------------------------------
# MEMOIRE DE LA VOIE LIBRE
# Espace DISTINCT du chemin metier. Le chemin ne porte que les questions, jamais
# les reponses : la voie libre s'en trouvait sans continuite -- « et en
# javascript ? » repondait en Python, « quelle etait ma premiere question ? »
# redonnait l'exemple au lieu de la citer.
#
# Ici on stocke l'ECHANGE COMPLET, ce qui serait discutable pour le metier
# (volume, conseil engageant, second depot a auditer) mais ne l'est pas ici : le
# firewall a deja ecarte le sensible et le domaine a ecarte le metier. Ce qui
# reste est anodin par construction.
# ---------------------------------------------------------------------------
TTL_LIBRE = int(os.environ.get("TTL_LIBRE", "3600"))
MAX_LIBRE = int(os.environ.get("MAX_LIBRE", "12"))     # 6 echanges


def _kl(sid): return "libre:%s" % sid


def echange_libre(sid, question, reponse):
    """Consigne un tour de la voie libre. Silencieux en cas d'echec : cette
    memoire enrichit, elle ne gouverne pas."""
    try:
        R.rpush(_kl(sid), json.dumps({"r": "user", "c": question}, ensure_ascii=False))
        R.rpush(_kl(sid), json.dumps({"r": "assistant", "c": reponse}, ensure_ascii=False))
        R.ltrim(_kl(sid), -MAX_LIBRE, -1)
        R.expire(_kl(sid), TTL_LIBRE)
        return True
    except Exception:
        return False


def rappeler_libre(sid, limite=None):
    """Rend les tours precedents au format du modele : [{"role","content"}]."""
    try:
        brut = R.lrange(_kl(sid), -(limite or MAX_LIBRE), -1) or []
    except Exception:
        return []
    out = []
    for b in brut:
        try:
            d = json.loads(b)
            out.append({"role": d["r"], "content": d["c"]})
        except Exception:
            continue
    return out

def repondre_rappel(entree, ctx):
    """PRIMITIVE : une meta-question sur la conversation se repond SANS MODELE.

    « Quelle etait ma premiere question ? » echouait identiquement sur le 7B
    local, sur mistral-small et sur mistral-large : le modele recoit un
    historique et une question, sans rien qui indique qu'on l'interroge SUR cet
    historique plutot que dans son prolongement. Ce n'est pas une limite de
    capacite, c'est un defaut de conception -- et la reponse est deterministe :
    le chemin est en Redis.

    entree = question (str). -> {"texte", "_arret"} ou {"rappel": False}
    """
    q = entree[0] if isinstance(entree, (list, tuple)) and entree else entree
    idx = detecter_rappel(str(q or ""))
    if idx is None:
        return {"rappel": False}
    sid = ctx.get("session") or ""
    try:
        tours = R.lrange(_kc(sid), 0, -1) or []
    except Exception:
        tours = []
    # le tour courant est deja enregistre : on l'exclut
    tours = [t for t in tours if t.strip() and t.strip() != str(q).strip()]
    if not tours:
        txt = "Je n'ai pas encore d'echange enregistre dans cette conversation."
    else:
        cible = tours[0] if idx == 0 else tours[idx]
        quoi = "premiere demande" if idx == 0 else "demande precedente"
        txt = "Votre %s etait : « %s »" % (quoi, cible.strip())
    return {"texte": txt, "message": txt, "_arret": True,
            "rappel": True, "index": idx}
