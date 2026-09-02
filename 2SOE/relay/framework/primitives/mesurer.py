#!/usr/bin/env python3
"""Primitive mesurer_intention 2SIN - tete neuronale (embedding + arbitrage motive).
Domaine : embedding TEI + distance, arbitrage motive LLM sur ambiguite.
Contrat : fn(entree, ctx) -> {"domaine","intention","sujet"}.
"""
import json, re, math, os
import urllib.request as u

TEI_URL=os.environ.get("TEI_URL","http://localhost:8080/embed")
VLLM_URL=os.environ.get("VLLM_URL","http://localhost:8000/v1/chat/completions")
VLLM_MODEL=os.environ.get("VLLM_MODEL","openai/gpt-oss-20b")
SEUIL_AMBIGU=float(os.environ.get("INTENT_SEUIL_AMBIGU","0.04"))
SEUIL_DOMAINE=float(os.environ.get("INTENT_SEUIL_DOMAINE","0.52"))  # resonance minimale pour reconnaitre un domaine  # ecart top1-top2 sous lequel on arbitre

DOMAINES={
 "baux_habitation":"bail d'habitation location logement loyer preavis conge locataire bailleur depot de garantie impaye resiliation clause resolutoire",
 "baux_commerciaux":"bail commercial local commercial fonds de commerce loyer commercial renouvellement duree ferme",
 "copropriete":"copropriete assemblee generale syndic charges lot reglement majorite vote immeuble tantiemes",
 "penal":"infraction penale delit peine vol abus garde a vue poursuite plainte violation domicile squat squatteur effraction",
 "hors_domaine":"cuisine recette meteo sport loisir sans rapport avec le droit",
}
INTENTIONS=["recherche","redaction","arbitrage","recherche_jurisprudence","na"]
# VERBE D'ACTION = FAIT LEXICAL. Sur une demande longue portant les donnees
# du dossier, le modele classait "Redige un courrier..." en "recherche". Un verbe de
# production est objectif : le core tranche, le modele n'a pas a en decider.
_RE_REDACTION = re.compile(
    r"\b(r[ée]dige[rz]?|[ée]cris|[ée]crire|r[ée]diger|pr[ée]pare[rz]?|"
    r"g[ée]n[èe]re[rz]?|produis|produire|fais[- ]moi\s+(un|une)\s+(courrier|lettre|"
    r"mise en demeure|relance|quittance|conge)|"
    r"(courrier|lettre|mise en demeure|relance|quittance)\s+(de|pour|a)\b)", re.I)

_dom_labels=list(DOMAINES.keys())
_dom_vecs=None

def _embed(texts):
    req=u.Request(TEI_URL,data=json.dumps({"inputs":texts}).encode(),headers={"Content-Type":"application/json"})
    return json.loads(u.urlopen(req,timeout=60).read().decode())

def _cos(a,b):
    d=sum(x*y for x,y in zip(a,b)); na=math.sqrt(sum(x*x for x in a)); nb=math.sqrt(sum(y*y for y in b))
    return d/(na*nb) if na and nb else 0

def _init_vecs():
    global _dom_vecs
    if _dom_vecs is None:
        _dom_vecs=_embed([DOMAINES[k] for k in _dom_labels])

def _extract_json(txt):
    if not txt: return None
    for pat in [r'\{(?:[^{}]|"[^"]*")*?"domaine"(?:[^{}]|"[^"]*")*?\}', r'\{[^{}]*?"intention"\s*:\s*"[^"]*"[^{}]*?\}']:
        for m in re.finditer(pat, txt):
            try: return json.loads(m.group(0))
            except Exception: continue
    return None

def _llm(sys,q,maxt=350):
    payload={"model":VLLM_MODEL,"messages":[{"role":"system","content":sys},{"role":"user","content":q}],"temperature":0.0,"max_tokens":maxt}
    _hdr={"Content-Type":"application/json"}
    _k=os.environ.get("MISTRAL_API_KEY","")
    if _k and "api.mistral.ai" in VLLM_URL: _hdr["Authorization"]="Bearer "+_k
    req=u.Request(VLLM_URL,data=json.dumps(payload).encode(),headers=_hdr)
    r=json.loads(u.urlopen(req,timeout=90).read().decode())
    m=r["choices"][0]["message"]
    return (m.get("content") or "")+" "+(m.get("reasoning") or "")

def _elliptique(question):
    """Une demande est elliptique si elle ne porte pas son sujet : trop peu de
    termes signifiants pour se suffire. Meme mesure que la decidabilite RAG."""
    try:
        from corpus import _termes_porteurs as _tp
    except Exception:
        try:
            from primitives.corpus import _termes_porteurs as _tp
        except Exception:
            return False
    try:
        return len(_tp(question or "")) < int(os.environ.get("RAG_TERMES_MIN", "3"))
    except Exception:
        return False


def mesurer_intention(entree, ctx):
    """entree = question (str). Contexte technique dans ctx['contexte'] pour heritage elliptique."""
    _init_vecs()
    # entree = [question, garde] -- la garde est RECUE du workflow
    if isinstance(entree, (list, tuple)):
        q = entree[0] if entree else ""
        _garde = entree[1] if len(entree) > 1 else {}
    else:
        q, _garde = str(entree), {}
    contexte = ctx.get("contexte") or {}

    # --- DOMAINE : embedding + distance ---
    qv=_embed(["Question juridique immobiliere : "+q])[0]
    scores=sorted(((_cos(qv,v),lbl) for v,lbl in zip(_dom_vecs,_dom_labels)),reverse=True)
    top1,top2=scores[0],scores[1]
    ambigu = (top1[0]-top2[0]) < SEUIL_AMBIGU
    domaine=top1[1]
    # PLANCHER DE RESONANCE : sans plancher, le domaine le MOINS MAUVAIS
    # gagne toujours -- une question de divorce ou une recette de tarte etaient
    # classees 'baux_habitation' a 0.45. Le systeme cherchait alors un texte qui
    # n'existe pas, ne trouvait rien, et le modele comblait de memoire.
    # Sous le plancher, aucun domaine n'est reconnu : c'est HORS DOMAINE.
    # UNE REFERENCE CITEE EST UN FAIT, pas une proximite semantique. « Que dit
    # l'article 24 de la loi du 6 juillet 1989 ? » resonne a 0.41 -- sous le
    # plancher -- alors que c'est la question la PLUS precise qu'on puisse poser.
    # Le plancher ne s'applique donc pas quand une reference est detectee.
    _ref = False
    try:
        from corpus import detecter_references as _dr
    except ImportError:
        try:
            from primitives.corpus import detecter_references as _dr
        except ImportError:
            _dr = None
    if _dr:
        try:
            _ref = bool((_dr(q) or "").strip())
        except Exception:
            _ref = False
    # LE FIREWALL A DEJA TRANCHE. S'il a reconnu le domaine metier (action
    # "corpus"), c'est un FAIT deterministe -- une detection par mots-cles, pas
    # une proximite semantique. Le plancher ne doit pas le contredire : il sert
    # a choisir ENTRE domaines metier, pas a re-juger l'appartenance au metier.
    # Sans cela, deux organes du meme core rendent des verdicts opposes sur la
    # meme question : « regularisation annuelle des charges » (mot-cle "charges",
    # firewall = metier) resonnait a 0.496 et repartait en hors_domaine, alors
    # que le corpus avait l'article 23 a 0.7086.
    _garde_metier = str((_garde or {}).get("action", "")) == "corpus"
    if top1[0] < SEUIL_DOMAINE and not _ref and not _garde_metier:
        domaine = "hors_domaine"
        ambigu = False
    motivation=""

    # --- ARBITRAGE MOTIVE si ambiguite ---
    if ambigu and domaine != "hors_domaine":
        sys=("Deux domaines sont proches pour cette demande : %s et %s.\n"
             "Tranche en MOTIVANT ton choix (le chemin de raisonnement).\n"
             'Reponds : {"domaine":"'+top1[1]+'" ou "'+top2[1]+'","motivation":"..."}'
             ) % (top1[1],top2[1])
        r=_extract_json(_llm(sys,q))
        if r and r.get("domaine") in _dom_labels:
            domaine=r["domaine"]; motivation=r.get("motivation","")

    # --- INTENTION : LLM local, encadre par le contexte + motivation ---
    # INJECTION CONDITIONNEE. Le contexte n'est montre au modele que si la
    # demande est ELLIPTIQUE. Sinon il le RECOPIAIT : mesure du 29/07, « quel
    # est le montant du depot de garantie » heritait du sujet « delai de
    # preavis » du tour precedent, et ce sujet perime se propageait ensuite a
    # tous les tours (il est ecrit en memoire, donc reinjecte au suivant).
    # Le caractere elliptique se MESURE ; il n'a pas a etre juge par le modele.
    ctx_txt = ("Contexte : "+", ".join("%s=%s"%(k,v) for k,v in contexte.items())+"\n") \
              if (contexte and _elliptique(q)) else ""
    mot_txt = ("Arbitrage : "+motivation+"\n") if motivation else ""
    sys_int=(ctx_txt+mot_txt+
        "Tache : classer l'intention d'une demande juridique (domaine deja identifie: %s).\n"%domaine+
        "Reponds par un objet JSON compact sur une seule ligne, RIEN d'autre, aucune reflexion.\n"
        "intention doit valoir exactement l'une de : "+str(INTENTIONS)+".\n"
        "Si la demande est elliptique (et pour..., rediges ca, ce sujet), reprends le sujet du contexte.\n"
        'Exemple de format attendu : {"intention":"recherche","sujet":"clause resolutoire"}')
    # L'appel au modele n'extrait qu'un SUJET. Il est inutile quand le tour
    # n'ira pas plus loin : une garde du firewall l'a deja arrete, ou aucun
    # domaine n'est reconnu. 184 executions sur 706 etaient dans ce cas, a
    # 1,07 s chacune.
    _garde = _garde or {}
    _inutile = (domaine == "hors_domaine"
                or bool(_garde.get("_arret"))
                or _garde.get("action") in ("refus_redirection", "refus_strict"))
    ri = {} if _inutile else (_extract_json(_llm(sys_int,q)) or {})

    return {
        "domaine": domaine,
        "intention": ("redaction" if _RE_REDACTION.search(q) else ri.get("intention","na")),
        # HERITAGE ELLIPTIQUE CONDITIONNE. Le repli sur le sujet du contexte
        # etait INCONDITIONNEL : voyant un contexte, le modele n'en renvoyait
        # plus, et le sujet du PREMIER tour se propageait a tous les suivants
        # (mesure 29/07 : « quel est le montant du depot de garantie » heritait
        # de « delai de preavis »). Le caractere elliptique se MESURE -- il n'a
        # pas a etre laisse au modele.
        "sujet": ri.get("sujet") or (contexte.get("sujet","") if _elliptique(q) else ""),
        "_ambigu": ambigu,
        "_motivation": motivation,
        "_top": [[round(top1[0],3),top1[1]],[round(top2[0],3),top2[1]]],
    }
