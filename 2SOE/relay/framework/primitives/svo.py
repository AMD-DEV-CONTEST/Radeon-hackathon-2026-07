"""Primitive SVO 2SIN - memoire de travail moyen terme.

Le SVO est un AMPLIFICATEUR : il oriente la requete, il n'est JAMAIS cite.
Triplet HYBRIDE deterministe (core pur, zero appel LLM) :
  - squelette : intention.{domaine, sujet, intention} (deja mesure)
  - enrichi   : regex cibles sur le prompt (nombres, articles, termes juridiques)

Deux fonctions :
  - amplifier_svo(entree, ctx) : PRIMITIVE du workflow. Cherche les SVO passes
    proches, enrichit l'embed RAG a venir (passif, a chaque tour).
  - archiver_svo(...) : ecrit le triplet du tour dans Qdrant (appelee apres le moteur).

Datation + nettoyage : SVO_TTL (moyen terme). Portee cross-session par profil.
"""
import re, os, json, time, re, urllib.request as _u

_TEI_URL    = os.environ.get("TEI_URL", "http://localhost:8080/embed")
_QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
_SVO_COLL   = os.environ.get("SVO_COLLECTION", "memoire_svo")
_SVO_TTL    = int(os.environ.get("SVO_TTL", "604800"))      # 7 jours par defaut
_SVO_TOPK   = int(os.environ.get("SVO_TOPK", "3"))
_SVO_MIN    = float(os.environ.get("SVO_MIN_SCORE", "0.50"))
_SVO_GAP    = float(os.environ.get("SVO_GAP", "0.08"))  # ecart top1-top2 : net vs ambigu

# Termes juridiques saillants a capter par regex (enrichissement).
_RE_TERMES = re.compile(
    r"\b(pr[eé]avis|cong[eé]|d[eé]p[oô]t|garantie|r[eé]siliation|loyer|charges|"
    r"bail|clause|r[eé]solutoire|impay[eé]|expulsion|indemnit[eé]|caution|"
    r"vacance|dur[eé]e|renouvellement|c[eé]dant|preneur|bailleur|locataire)\b", re.I)
_RE_ARTICLE = re.compile(r"\b((?:L\.?\s?)?\d{1,4}(?:-\d{1,3})+|article\s+\d+)\b", re.I)
_RE_NOMBRE  = re.compile(r"\b(\d+\s?(?:mois|ans?|jours?|semaines?|%|euros?|€))\b", re.I)


def _post(url, payload, timeout=15):
    req = _u.Request(url, data=json.dumps(payload).encode(),
                     headers={"Content-Type": "application/json"})
    with _u.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def _embed(texte):
    try:
        return _post(_TEI_URL, {"inputs": texte})[0]
    except Exception:
        return None

def _assure_collection(dim):
    try:
        _u.urlopen(_u.Request(_QDRANT_URL + "/collections/" + _SVO_COLL, method="GET"), timeout=5)
        return
    except Exception:
        pass
    try:
        _u.urlopen(_u.Request(_QDRANT_URL + "/collections/" + _SVO_COLL,
                   data=json.dumps({"vectors": {"size": dim, "distance": "Cosine"}}).encode(),
                   headers={"Content-Type": "application/json"}, method="PUT"), timeout=10)
    except Exception:
        pass

def _termes_cles(prompt):
    """Regex cibles : termes juridiques + articles + nombres. Deterministe."""
    if not prompt:
        return []
    t = set()
    for m in _RE_TERMES.findall(prompt): t.add(m.lower())
    for m in _RE_ARTICLE.findall(prompt): t.add(m.strip())
    for m in _RE_NOMBRE.findall(prompt):  t.add(m.strip())
    return sorted(t)

def _texte_vecteur(domaine, objet, termes):
    """Texte vectorise : cadre + objet + termes saillants."""
    return " ".join(filter(None, [domaine or "", objet or "", " ".join(termes or [])]))


def archiver_svo(profil, session, prompt, intention):
    """Ecrit le triplet SVO du tour dans Qdrant (deterministe, non bloquant).
    intention = {domaine, sujet, intention}. Enrichi par regex sur le prompt."""
    domaine = (intention or {}).get("domaine", "")
    objet   = (intention or {}).get("sujet", "")
    acte    = (intention or {}).get("intention", "")
    if not (domaine or objet):
        return False
    termes = _termes_cles(prompt)
    vec = _embed(_texte_vecteur(domaine, objet, termes))
    if vec is None:
        return False
    _assure_collection(len(vec))
    pid = abs(hash("%s|%s|%s" % (profil, session, time.time()))) % (10**15)
    point = {"id": pid, "vector": vec, "payload": {
        "profil": profil or "default", "session": session or "",
        "ts": int(time.time()), "domaine": domaine, "objet": objet,
        "acte": acte, "termes_cles": termes}}
    try:
        _u.urlopen(_u.Request(_QDRANT_URL + "/collections/" + _SVO_COLL + "/points",
                   data=json.dumps({"points": [point]}).encode(),
                   headers={"Content-Type": "application/json"}, method="PUT"), timeout=10)
        return True
    except Exception:
        return False


def amplifier_svo(entree, ctx):
    """PRIMITIVE : cherche les SVO passes proches, retourne les termes amplificateurs.
    Passif : a chaque tour. Filtre profil + fenetre temporelle (SVO_TTL).
    Le SVO ORIENTE (amplificateur), il ne source rien : on retourne des termes
    a ajouter a l'embed RAG, jamais du contenu cite."""
    q = entree[0] if isinstance(entree, (list, tuple)) and entree else entree
    if not q or not isinstance(q, str):
        q = ctx.get("question", "")
    profil = ctx.get("profil") or os.environ.get("RAG_PROFIL", "") or "residentiel"

    vec = _embed(q)
    if vec is None:
        return {"amplificateurs": [], "svo_utilise": False}

    borne = int(time.time()) - _SVO_TTL
    # limit >= 2 pour disposer de top1 ET top2 (mesure de nettete geometrique).
    # CLOISONNEMENT PAR SESSION : la session etait ARCHIVEE mais jamais
    # filtree -- deux gestionnaires d'un meme cabinet partageaient donc leur
    # memoire de travail, ce que l'un venait de traiter orientant l'embed de
    # l'autre. Le profil borne les DROITS, la session borne le TRAVAIL.
    _sess = ctx.get("session") or ""
    _must = [{"key": "profil", "match": {"value": profil}},
             {"key": "ts", "range": {"gte": borne}}]
    if _sess:
        _must.append({"key": "session", "match": {"value": _sess}})
    body = {"vector": vec, "limit": max(_SVO_TOPK, 2), "with_payload": True,
            "filter": {"must": _must}}
    try:
        res = _post(_QDRANT_URL + "/collections/" + _SVO_COLL + "/points/search", body)
        hits = res.get("result", [])
    except Exception:
        return {"amplificateurs": [], "svo_utilise": False}

    # Filtrer au seuil de resonance.
    pertinents = [h for h in hits if h.get("score", 0.0) >= _SVO_MIN]
    if not pertinents:
        ctx["svo_confiance"] = "aucune"
        return {"amplificateurs": [], "svo_utilise": False, "svo_confiance": "aucune"}

    top1 = pertinents[0]
    top2 = pertinents[1] if len(pertinents) > 1 else None
    s1 = top1.get("score", 0.0)
    s2 = top2.get("score", 0.0) if top2 else 0.0

    # DECISION top1/top2 : net (detache) vs ambigu (proches).
    # Le CORE mesure la nettete (fait geometrique) ; le FLUIDE en tiendra compte.
    ambigu = (top2 is not None) and ((s1 - s2) < _SVO_GAP)
    confiance = "ambigue" if ambigu else "nette"

    def _termes_de(h):
        p = h.get("payload", {})
        out = []
        if p.get("objet"): out.append(p["objet"])
        out.extend(p.get("termes_cles", []))
        return out

    if ambigu:
        # AMBIGU : on amplifie QUAND MEME (les deux pistes), et on marque les
        # PISTES pour challenger le LLM (X ou Y). Union prudente top1+top2.
        ampl = _termes_de(top1) + _termes_de(top2)
        ctx["svo_pistes"] = [ (top1.get("payload") or {}).get("objet",""),
                              (top2.get("payload") or {}).get("objet","") ]
    else:
        # NET : le top1 oriente franchement.
        ampl = _termes_de(top1)

    # FILTRE DONNEES DE DOSSIER. Un amplificateur ORIENTE l'embed, il ne
    # TRANSPORTE pas de contenu. Constat : "850 euros" stocke comme terme SVO
    # ressortait dans l'acte d'un AUTRE locataire (courrier adresse a Mme MARTIN
    # portant le loyer de M. DUPONT). Un montant, une date, un nom propre sont des
    # donnees de dossier : ils n'orientent rien et ne doivent jamais ressortir.
    def _est_donnee(t):
        s = str(t).strip()
        if re.search(r"\d", s):                      # montant, date, numero
            return True
        if re.match(r"^(M\.|Mme|Monsieur|Madame)\b", s, re.I):
            return True
        mots = [m for m in re.findall(r"[A-Za-zÀ-ÿ]+", s) if len(m) > 2]
        if mots and all(m.isupper() for m in mots):   # NOM EN CAPITALES
            return True
        return False

    seen, uniq = set(), []
    for a in ampl:
        if a and a not in seen and not _est_donnee(a):
            seen.add(a); uniq.append(a)
    ampl_final = uniq[:6]
    ctx["amplificateurs"] = ampl_final       # corpus.py le lit
    ctx["svo_confiance"] = confiance          # appeler_llm le lit (challenge si ambigu)
    return {"amplificateurs": ampl_final, "svo_utilise": bool(ampl_final),
            "svo_confiance": confiance, "top1": round(s1,3), "top2": round(s2,3)}
