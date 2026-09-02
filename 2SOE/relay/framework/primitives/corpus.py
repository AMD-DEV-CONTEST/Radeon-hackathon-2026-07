#!/usr/bin/env python3
"""Primitive rechercher_corpus 2SIN - RAG Qdrant pilote par le DOMAINE mesure.
Contrat : fn(entree, ctx) -> str (bloc contexte formate, ou "" si abstention).
Deux apports vs le relay (profil statique) :
  1. le DOMAINE (mesure par la tete) selectionne les collections
  2. la REFERENCE citee filtre sur article ET source (pas d'homonymie inter-lois)
"""
import os
_RACINE = os.environ.get("SEED_ROOT", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "data-seed"))

import json, os, re
import urllib.request as _urlreq

TEI_URL        = os.environ.get("TEI_URL", "http://localhost:8080/embed")
QDRANT_URL     = os.environ.get("QDRANT_URL", "http://localhost:6333")
RAG_COLLECTION = os.environ.get("RAG_COLLECTION", "juridique_code_civil")
RAG_TOPK       = int(os.environ.get("RAG_TOPK", "3"))
RAG_MIN_SCORE  = float(os.environ.get("RAG_MIN_SCORE", "0.60"))
PROFILS_PATH   = os.environ.get("PROFILS_PATH",
                                os.path.join(_RACINE, "profils.json"))
RAG_PROFIL     = os.environ.get("RAG_PROFIL", "")

# Le DOMAINE mesure par la tete determine le perimetre de recherche.
# (complexite et perimetre sont deduits du domaine)
DOMAINE_COLLECTIONS = {
    "baux_habitation":  ["juridique_code_civil", "juridique_jurisprudence"],
    "baux_commerciaux": ["juridique_code_de_commerce", "juridique_code_civil",
                         "juridique_jurisprudence"],
    "copropriete":      ["juridique_code_civil", "juridique_jurisprudence"],
    "penal":            ["juridique_code_penal", "juridique_jurisprudence"],
    "urbanisme":        ["juridique_code_de_l_urbanisme",
                         "juridique_code_de_la_construction_et_de_l_habitation"],
    "hors_domaine":     [],
}


# --- CONTROLE DE COUVERTURE LEXICALE (critere de core, deterministe) ---
# Demonstration empirique : le SEUIL DE SIMILARITE est structurellement
# inapte a decider de la couverture — les populations in-corpus et hors-corpus se
# RECOUVRENT (in: 0.501-0.692 / hors: 0.510-0.575). Le score penalise les questions
# COURTES sans que la pertinence baisse : la geometrie met toujours le bon article
# en tete (rang correct dans 5/5 cas), c'est le seuil absolu qui abstient a tort.
# => La geometrie CLASSE (rang), le CORE VERIFIE (l'article parle-t-il du sujet ?).
COUVERTURE_MIN = float(os.environ.get("RAG_COUVERTURE_MIN", "0.40"))
# En-deca de ce nombre de termes porteurs, la question est jugee INDECIDABLE
# (on demande une precision au lieu d'abstenir a tort).
TERMES_MIN_DECIDABLE = int(os.environ.get("RAG_TERMES_MIN", "3"))
RAG_WINDOW = float(os.environ.get("RAG_WINDOW", "0.12"))  # fenetre d'acceptation autour de top1

_STOPWORDS = set(
    "le la les de des du un une et ou au aux en dans sur pour par est sont il elle "
    "quel quelle quels quelles est-ce que qui quoi comment combien peut peuvent doit "
    "doivent sans avec ce cette ces son sa ses leur leurs je tu vous nous on mon ma mes "
    "faire fait puis-je dois-je etre avoir cas lors alors donc mais "
    "cela ceci celui celle ceux partie parle propos sujet chose truc "
    "dire dis dit savoir sais sait pouvez pouvons voici voila".split()
)


def _termes_porteurs(question):
    """Mots porteurs de sens (>=4 car., hors mots-outils)."""
    mots = re.findall(r"[a-zA-Z\u00e0\u00e2\u00e4\u00e9\u00e8\u00ea\u00eb\u00ee\u00ef\u00f4\u00f6\u00f9\u00fb\u00fc\u00e7]{4,}", question.lower())
    return [m for m in mots if m not in _STOPWORDS]


def _couverture(question, payload):
    """Part des termes porteurs de la question qui figurent dans le texte servi.
    Comparaison sur racine 6 caracteres (tolere les flexions : preavis/preavis)."""
    termes = _termes_porteurs(question)
    if not termes:
        return 0.0
    corpus = ((payload.get("texte", "") or "") + " " +
              (payload.get("theme", "") or "") + " " +
              (payload.get("branche", "") or "")).lower()
    trouves = sum(1 for t in termes if t[:6] in corpus)
    return trouves / len(termes)


def _post_json(url, payload, timeout=30):
    data = json.dumps(payload).encode("utf-8")
    req = _urlreq.Request(url, data=data, headers={"Content-Type": "application/json"})
    with _urlreq.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _collections_profil(profil_ctx=None):
    """Fallback : collections du profil actif (config vivante) si pas de domaine mesure.
    profil_ctx (header X-Profil, user authentifie) prioritaire sur RAG_PROFIL global."""
    try:
        with open(PROFILS_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        profil = profil_ctx or RAG_PROFIL or cfg.get("profil_defaut", "residentiel")
        p = cfg.get("profils", {}).get(profil)
        if p and p.get("collections"):
            return p["collections"]
    except Exception:
        pass
    return [RAG_COLLECTION]


def _collections_pour(ctx):
    """Le domaine mesure pilote le perimetre, MAIS le profil du user le BORNE.
    Permission control : un user n'accede JAMAIS a des collections
    hors de son profil, meme si le domaine mesure pointe ailleurs. Le profil
    est un plafond de droits, pas un simple fallback."""
    autorisees = _collections_profil(ctx.get("profil"))  # plafond de droits du user
    dom = (ctx.get("intention") or {}).get("domaine")
    if dom in DOMAINE_COLLECTIONS:
        voulues = DOMAINE_COLLECTIONS[dom]
        # COLLECTION CARACTERISTIQUE : la premiere declaree est celle
        # SANS LAQUELLE le domaine ne peut pas etre traite. Si le profil la
        # refuse, le repli sur les collections communes fait REPONDRE A COTE --
        # constate : en profil residentiel, une question de bail commercial
        # recevait l'article 11 de la loi 89, et le modele completait de memoire.
        # Repondre a cote est pire qu'abstenir : le user croit etre renseigne.
        if voulues and voulues[0] not in autorisees:
            return []
        # INTERSECTION : ce que le domaine veut ∩ ce que le profil autorise.
        inter = [col for col in voulues if col in autorisees]
        return inter  # peut etre vide -> abstention (le user n'a pas les droits)
    return autorisees


def detecter_references(question):
    """Detecte articles/lois cites explicitement (core deterministe)."""
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


def _existe_ailleurs(ctx):
    """La collection caracteristique du domaine est-elle detenue par UN AUTRE
    profil ? Si oui, le refus est une question de DROITS ; sinon le texte
    n'existe nulle part et le refus est un HORS CORPUS."""
    dom = (ctx.get("intention") or {}).get("domaine")
    voulues = DOMAINE_COLLECTIONS.get(dom) or []
    if not voulues:
        return False
    caracteristique = voulues[0]
    try:
        with open(PROFILS_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        for p in (cfg.get("profils") or {}).values():
            if caracteristique in (p.get("collections") or []):
                return True
    except Exception:
        pass
    return False


def rechercher_corpus(entree, ctx):
    """entree = question (str). ctx['intention']['domaine'] pilote les collections."""
    question = entree if isinstance(entree, str) else str(entree)
    collections = _collections_pour(ctx)
    if not collections:
        # HORS DROITS ou HORS CORPUS ? Les deux se recouvrent quand aucune
        # collection n'est accessible. La distinction suit ce qui est VRAI POUR
        # L'UTILISATEUR : « demandez un acces » n'a de sens que si un autre
        # profil possede le texte. Sinon personne ne l'a -- c'est hors corpus,
        # et l'avis d'un professionnel s'impose.
        ctx["rag_statut"] = ("hors_droits" if _existe_ailleurs(ctx)
                             else "hors_corpus")
        return ""   # abstention par construction, aucun appel Qdrant

    try:
        refs = detecter_references(question)
        ref_nums = re.findall(r'article\s+((?:[LRD])?\d+(?:-\d+)*)', refs)
        ref_lois = re.findall(r'loi\s+(\d{2}-\d{3})', refs)
        # L'annee est cherchee dans la QUESTION : « la loi de 1948 » n'entre pas
        # dans le motif des references normalisees.
        ref_annees = re.findall(r'\b(1[89]\d{2}|20\d{2})\b', question)

        # ENRICHISSEMENT PAR L'HISTORIQUE (demontre le 11/07) : le RAG embedait la
        # question SEULE et ignorait le contexte. Une question courte ou elliptique
        # ("et le delai ?") est alors indecidable. Le contexte technique (Redis) la
        # densifie et la DESAMBIGUISE ("duree du bail" -> loi 89 ou L145 selon le bail).
        # Gains mesures : +0.183 sur question courte ; bascule de collection correcte.
        memo = ctx.get("contexte") or {}
        prefixe = ""
        if memo:
            bribes = [str(memo.get(k)) for k in ("domaine", "sujet") if memo.get(k)]
            if bribes:
                prefixe = ", ".join(bribes).replace("_", " ") + ". "
        # AMPLIFICATION SVO : la memoire de travail moyen terme oriente
        # l'embed. Les amplificateurs (objets/termes des SVO passes proches) sont
        # ajoutes au prefixe. Le SVO ORIENTE (amplificateur), il ne source rien.
        ampl = ctx.get("amplificateurs") or []
        if ampl:
            prefixe = prefixe + ", ".join(str(a) for a in ampl).replace("_", " ") + ". "
        # SUJET MESURE DU TOUR COURANT : sur une demande de REDACTION, la
        # question brute est noyee par les donnees du dossier (noms propres, montants,
        # adresses) et l'embed rate le signal juridique. Le sujet mesure par
        # mesurer_intention le condense ("lettre de relance pour loyer impaye") :
        # on l'ajoute au prefixe. Deterministe, issu du core, jamais du modele.
        _intent = ctx.get("intention") or {}
        _sujet = str(_intent.get("sujet") or "").strip()
        # TERMES DE RECHERCHE DECLARES PAR L'ACTE : un tour d'apport ne
        # porte plus le sujet ; l'embedder tel quel fait deriver le RAG (relance de
        # loyer -> charges de copropriete). Chaque gabarit declare les termes sur
        # lesquels chercher : c'est une propriete de l'acte, pas une regle du code.
        _termes_acte = ""
        try:
            from tache import lire_tache as _lt
            from gabarit import _charger as _cg
        except ImportError:
            from primitives.tache import lire_tache as _lt
            from primitives.gabarit import _charger as _cg
        _tk = _lt(ctx.get("session") or "") or {}
        if _tk.get("nature"):
            _termes_acte = ((_cg() or {}).get(_tk["nature"]) or {}).get("termes_rag", "")
        _texte_embed = question
        if _intent.get("intention") == "redaction" and _sujet:
            # LISTE BLANCHE. Le sujet extrait embarque les donnees du dossier
            # (noms, adresses, montants, dates) : l'embed retombe hors corpus. Plutot que
            # de purger du bruit imprevisible, on ne GARDE que le vocabulaire juridique.
            # Deterministe : un nom propre ou un montant ne peut pas passer.
            _LEX = ("loyer impaye charges bail location locataire bailleur conge preavis "
                    "resiliation clause resolutoire commandement payer relance mise demeure "
                    "quittance depot garantie caution travaux reparation trouble jouissance "
                    "copropriete syndic assemblee charges expulsion indemnite occupation "
                    "renouvellement revision indexation solidarite congé impayé résolutoire").split()
            _mots = re.findall(r"[a-zàâçéèêëîïôûùüÿñæœ]+", _sujet.lower())
            _garde = [m for m in _mots if m in _LEX]
            _texte_embed = (_termes_acte or
                            (" ".join(dict.fromkeys(_garde)) if _garde
                             else _sujet.replace("_", " ")))
            # Le prefixe (contexte memoire + amplificateurs SVO) recopie le sujet
            # BRUT et reinjecte les donnees du dossier devant l'embed : mesure du
            # 18/07, 0.655 seul contre 0.538 avec prefixe. En redaction le signal
            # juridique est deja isole par la liste blanche : on neutralise le prefixe.
            if _garde:
                prefixe = ""
        elif _sujet and _sujet.lower() not in prefixe.lower():
            prefixe = prefixe + _sujet.replace("_", " ") + ". "
        _embed_txt = "Question juridique immobiliere : " + prefixe + _texte_embed + " ?"
        ctx["_rag_embed"] = _embed_txt
        vec = _post_json(TEI_URL, {"inputs": _embed_txt})[0]

        merged = []
        for coll in collections:
            try:
                r = _post_json(
                    QDRANT_URL + "/collections/" + coll + "/points/search",
                    {"vector": vec, "limit": RAG_TOPK, "with_payload": True},
                )
                merged.extend(r.get("result", []))
            except Exception:
                continue

        # Reference citee : filtre deterministe article + SOURCE (anti-homonymie).
        ref_hit = False
        if ref_nums:
            for coll in collections:
                for num in ref_nums:
                    try:
                        r = _post_json(
                            QDRANT_URL + "/collections/" + coll + "/points/scroll",
                            {"filter": {"must": [{"key": "article", "match": {"text": num}}]},
                             "limit": 5, "with_payload": True},
                        )
                        for p in r.get("result", {}).get("points", []):
                            pay = p.get("payload", {})
                            art = pay.get("article", "")
                            if num.lower() not in art.lower().replace(" ", ""):
                                continue
                            # ANNEE CITEE : « l'article 3-1 de la loi de 1948 »
                            # servait l'article 3-1 de la loi de 1989 -- meme numero,
                            # autre texte, presente comme « source officielle ».
                            # L'annee est un discriminant sur : chaque source porte
                            # la sienne. Servir un texte abroge ou etranger a la
                            # demande est la faute maximale pour un cabinet.
                            if ref_annees:
                                _src_a = (pay.get("source") or pay.get("loi") or "")
                                if not any(a in _src_a for a in ref_annees):
                                    continue
                            # Si une loi est citee, l'article doit venir de CETTE loi.
                            if ref_lois:
                                src = (pay.get("source") or pay.get("loi") or "")
                                if not any(l in src for l in ref_lois):
                                    continue   # article homonyme d'une autre loi : ecarte
                            p["score"] = 0.99
                            merged.append(p)
                            ref_hit = True
                    except Exception:
                        continue

        results = sorted(merged, key=lambda h: h.get("score", 0), reverse=True)
        if not results:
            return ""

        top1 = results[0].get("score", 0)
        top2 = results[1].get("score", 0) if len(results) > 1 else 0.0
        couv = _couverture(question, results[0].get("payload", {}))

        # Union de criteres : chacun rattrape la faiblesse de l'autre.
        #  - reference citee  -> deterministe (le core sert l'article cite)
        #  - score franc      -> vocabulaire different mais semantique proche
        #  - couverture       -> question courte (score bas) mais termes bien dans le texte
        # REFERENCE CITEE ET NON TROUVEE : pas de repli semantique. L'utilisateur
        # demandait un TEXTE, pas un texte approchant -- servir l'article 17 pour
        # une demande portant sur l'article 3-1 de 1948, c'est repondre a cote en
        # se presentant comme « source officielle ».
        if (ref_nums or ref_annees) and not ref_hit:
            ctx["rag_statut"] = "hors_corpus"
            ctx["_rag_diag"] = {"ref_demandee": True, "ref_hit": False,
                                "statut": "hors_corpus"}
            return ""
        accept = ref_hit or (top1 >= RAG_MIN_SCORE) or (couv >= COUVERTURE_MIN)

        # TROIS ISSUES, pas deux.
        # Non couvert + question RICHE   -> hors-corpus reel      -> ABSTENIR
        # Non couvert + question PAUVRE  -> demande indecidable   -> DEMANDER
        # (le contexte a deja ete injecte dans l'embed : s'il n'a pas suffi,
        #  c'est que l'historique lui-meme ne porte pas le sujet)
        n_termes = len(_termes_porteurs(question))
        # DECIDABILITE D'ABORD : une question qui ne porte pas assez de sens
        # ne se decide pas, quel que soit ce que le vecteur a trouve (28/07).
        # ref_hit EXEMPTE du plancher de decidabilite : une reference citee est
        # un FAIT objectif, elle n'a pas a etre mesuree (c16 : « Que dit
        # l'article 24 de la loi du 6 juillet 1989 ? » ne porte que 2 termes
        # porteurs, mais elle nomme sa source).
        if not ref_hit and n_termes < TERMES_MIN_DECIDABLE:
            statut = "imprecise"
        elif accept:
            statut = "servi"
        else:
            statut = "hors_corpus"
        ctx["rag_statut"] = statut
        ctx["_rag_diag"] = {"top1": round(top1, 3), "top2": round(top2, 3),
                            "couverture": round(couv, 2), "ref_hit": ref_hit,
                            "termes": n_termes, "statut": statut}
        if not accept:
            return ""

        hits = [h for h in results if h.get("score", 0) >= top1 - RAG_WINDOW]
        lines = ["[CONTEXTE JURIDIQUE - sources officielles a utiliser en priorite]"]
        for h in hits:
            p = h["payload"]
            # CITATION IMPOSEE PAR LE CORE. Le modele assemblait auparavant
            # "Code civil" + "Article 24" -> "article 24 du Code civil", qui existe
            # et traite de la NATIONALITE FRANCAISE. Une loi non codifiee (89-462,
            # 65-557) ne doit JAMAIS etre citee comme un code : le core fournit
            # la formule exacte, le modele la recopie.
            art  = p.get("article", "")
            code = p.get("code", "")
            src_txt = p.get("texte_source") or p.get("source") or p.get("loi") or ""
            if code:
                citation = art + " du " + code
            elif src_txt:
                citation = art + " de la " + src_txt
            else:
                citation = art
            branche = p.get("branche", "")
            entete = citation + (" | " + branche if branche else "")
            lines.append("- " + citation + " (" + entete + ") : "
                         + p.get("texte", ""))
        lines.append("[REGLES : Appuie-toi UNIQUEMENT sur les articles ci-dessus. "
                     "Donne la reference exacte (numero + loi ou code) et explique le contenu "
                     "avec tes mots ; ne recopie pas de longs passages entre guillemets. "
                     "N'invente jamais l'appartenance a un code : une loi non codifiee "
                     "(loi n\u00b0 89-462, loi n\u00b0 65-557) se cite 'article X de la loi n\u00b0 ... "
                     "du ...'. Si une information ne figure pas ci-dessus, dis 'non precise "
                     "dans la source' au lieu de l'inventer.]")
        return "\n".join(lines)
    except Exception:
        return ""
