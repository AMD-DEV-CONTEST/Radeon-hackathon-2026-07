#!/usr/bin/env python3
"""Primitives de GABARIT D'ACTE 2SIN.
Decoupe en trois capacites atomiques, composables par un skill :
  selectionner_gabarit : demande -> gabarit (lexical, DETERMINISTE, sans modele)
  extraire_variables   : champs declares -> valeurs (SEULE etape avec modele)
  assembler_motif      : gabarit + valeurs -> motif, ou champs manquants (sans modele)
Le degre de determinisme d'un acte se lit dans SON gabarit : motif declare = strict.
"""
import os
_RACINE = os.environ.get("SEED_ROOT", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "data-seed"))

import os, re, json
import urllib.request as u

GABARITS_PATH = os.environ.get("GABARITS_PATH",
                               os.path.join(_RACINE, "gabarits_motif.json"))
VLLM_URL   = os.environ.get("VLLM_URL", "http://localhost:8000/v1/chat/completions")
VLLM_MODEL = os.environ.get("VLLM_MODEL", "mistralai/Mistral-7B-Instruct-v0.3")


def _normaliser(s):
    s = (s or "").lower()
    for a, b in (("é","e"),("è","e"),("ê","e"),("à","a"),("â","a"),("î","i"),
                 ("ô","o"),("û","u"),("ù","u"),("ç","c"),("°","")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", " ", s)


def _ancre(valeur, source_norm):
    """Ancree si ses jetons porteurs (nombres, mots > 3 lettres) sont dans la source."""
    jetons = [j for j in _normaliser(valeur).split() if len(j) > 3 or j.isdigit()]
    return all(j in source_norm for j in jetons) if jetons else True


_RE_MARQUEUR = re.compile(
    r"^\s*(x+\s*[€$]?|\[.*\]|[.]{2,}|montant|periode|votre\s+\w+|"
    r"nom\s+du\s+\w+|adresse\s+du\s+\w+|a completer)\s*$", re.I)

_MOIS = ("janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|"
         "octobre|novembre|d[ée]cembre")

def _lire_directement(texte):
    """Ce qui est RECONNAISSABLE dans la demande est lu par le core, pas devine.
    Periode (mois + annee) et montant (nombre + unite) suivent des motifs stables."""
    out = {}
    m = re.search(r"\b(%s)\s+(\d{4})\b" % _MOIS, texte or "", re.I)
    if m:
        out["periode"] = "%s %s" % (m.group(1).lower(), m.group(2))
    # Le montant colle a son unite : sans frontiere, "avril 2026, 599 euros"
    # donnait "2026,599 euros" (l'annee absorbee dans le montant).
    m = re.search(r"(?<![\d,.])(\d{1,3}(?:[ .]\d{3})*(?:[.,]\d{1,2})?)\s*(?:€|euros?|EUR)\b",
                  texte or "", re.I)
    if m:
        out["montant"] = "%s euros" % re.sub(r"\s+", "", m.group(1)).rstrip(".,")
    return out


def _champs_acte(g):
    """Tous les champs sans lesquels l'acte ne peut exister : les trous du motif
    (variables) ET ce que l'acte exige par nature (requis : destinataire,
    signataire...). Le controle porte sur l'UNION -- un courrier sans destinataire
    ne doit pas s'etablir (constate 18/07)."""
    vus, out = set(), []
    for k in list(g.get("variables") or []) + list(g.get("requis") or []):
        if k not in vus:
            vus.add(k); out.append(k)
    return out


def _charger():
    """Relu a chaque appel : ajouter un acte = editer un JSON, pas du code."""
    try:
        with open(GABARITS_PATH, encoding="utf-8") as fh:
            return json.load(fh).get("gabarits", {})
    except Exception:
        return {}


# --------------------------------------------------------------------------
def selectionner_gabarit(entree, ctx):
    """LECTURE SEULE : quel acte ce tour concerne-t-il ?
    N'ouvre ni ne modifie la tache -- elle rend sa DECISION, une primitive
    d'ecriture l'applique ensuite.
    -> {"nom":.., "gabarit":{..}, "variables":[..], "decision": ouvrir|rattacher|None}
    """
    q = entree[0] if isinstance(entree, (list, tuple)) and entree else entree
    _intent = ctx.get("intention") or {}
    # UN GABARIT NE VAUT QUE POUR UNE REDACTION. « Quel preavis pour un CONGE
    # donne par le locataire ? » est une consultation : le mot designe le SUJET,
    # pas le travail a produire. Sans ce garde, la question reclamait la date
    # d'effet du conge a rediger.
    # Le garde cede si une TACHE est en cours : un tour d'apport a l'intention
    # « recherche » (il ne porte que des noms et des chiffres) mais il complete
    # un acte -- le juger isolement le rendait sterile.
    try:
        from tache import lire_tache as _lt0
    except ImportError:
        from primitives.tache import lire_tache as _lt0
    _en_cours = (_lt0(ctx.get("session") or "") or {}).get("nature")
    if _intent.get("intention") not in ("redaction", None, "") and not _en_cours:
        return {"nom": None, "gabarit": None, "variables": [], "decision": None}
    sujet = _intent.get("sujet", "")
    txt = ((q or "") + " " + (sujet or "")).lower()
    try:
        from tache import lire_tache
    except ImportError:
        from primitives.tache import lire_tache
    _encours = lire_tache(ctx.get("session") or "") or {}

    # Un declencheur nomme l'acte : ouverture si la nature change, sinon on
    # poursuit le travail en cours.
    # LE DECLENCHEUR LE PLUS SPECIFIQUE GAGNE : « redige une mise en
    # demeure pour loyer impaye » contient « impaye », declencheur de
    # relance_loyer -- qui l'emportait par simple ordre de declaration. Un
    # declencheur long est plus discriminant qu'un mot isole.
    _candidats = []
    for nom, g in _charger().items():
        for d in g.get("declencheurs", []):
            if d.lower() in txt:
                _candidats.append((len(d), nom, g))
                break
    _candidats.sort(reverse=True)
    for _, nom, g in _candidats[:1]:
        if True:
                decision = "rattacher" if _encours.get("nature") == nom else "ouvrir"
                return {"nom": nom, "gabarit": g, "variables": _champs_acte(g),
                        "decision": decision, "sujet": sujet or q}

    # AUCUN DECLENCHEUR : un tour qui n'apporte que des elements ("pour M. TOTO,
    # avril 2026, 599 euros") ne porte plus le sujet. La tache en cours donne la
    # nature du travail : le complement s'y rattache.
    if _encours.get("nature"):
        _g = _charger().get(_encours["nature"])
        if _g:
            return {"nom": _encours["nature"], "gabarit": _g,
                    "variables": _champs_acte(_g), "decision": "rattacher",
                    "sujet": _encours.get("sujet", "")}

    return {"nom": None, "gabarit": None, "variables": [], "decision": None}
# --------------------------------------------------------------------------
_REGLE = (
    "Tu extrais des donnees metier pour un acte de cabinet immobilier.\n"
    "Tu ne rediges AUCUNE phrase : le texte de l'acte est impose par un gabarit.\n\n"
    "Reponds par un objet JSON STRICT, sans texte avant ni apres, avec exactement "
    "ces cles : %s\n\n"
    "REGLES ABSOLUES :\n"
    "- N'INVENTE JAMAIS une valeur absente de la demande ou du contexte juridique.\n"
    "- Si une valeur n'est pas donnee, mets une chaine vide. JAMAIS de marqueur de\n"
    "  remplacement (pas de 'Votre Nom', '[adresse]', 'XXX', 'a completer').\n"
    "- Recopie les valeurs TELLES QU'ELLES apparaissent, sans les reformuler.\n\n"
    "SENS DES CLES :\n"
    "- periode : le mois concerne, ex 'juin 2026'.\n"
    "- montant : la somme due, ex '850 euros'.\n"
    "- date_effet : date en francais lisible, ex '30 septembre 2026'.\n"
    "- fondement : la reference juridique seule, ex \"l'article 24 de la loi\n"
    "  n 89-462 du 6 juillet 1989\". Jamais le texte de l'article, jamais d'enumeration.\n"
    "- nom_destinataire : le locataire ou la personne a qui le courrier s'adresse.\n"
    "- adresse_destinataire : son adresse postale.\n"
    "- nom_cabinet : le cabinet ou l'agence qui envoie le courrier.\n"
    "- adresse_cabinet : l'adresse du cabinet.\n"
    "- signataire : la personne qui signe le courrier.\n"
    "- fonction_signataire : sa fonction, ex 'gestionnaire'.\n"
)

# Budget de generation : un modele A RAISONNEMENT depense d'abord des tokens
# a delibérer, puis repond. Un budget calibre sur un modele qui repond
# directement le coupe AVANT sa reponse -- content vide, extraction perdue,
# et rien ne le signale (finish_reason = length).
_EXTRACT_MAX = int(os.environ.get("EXTRACT_MAX_TOKENS", "900"))

def _llm(sys_prompt, q, maxt=None):
    maxt = maxt or _EXTRACT_MAX
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
    # content est la REPONSE, reasoning le BROUILLON. Les concatener revient a
    # parser le raisonnement comme s'il engageait : un modele a raisonnement y
    # ecrit des ebauches d'objets, du texte libre et des guillemets non apparies.
    # On ne lit le brouillon qu'a defaut de reponse.
    contenu = (m.get("content") or "").strip()
    return contenu if contenu else (m.get("reasoning") or "")

_JSON_MAX = 20000   # au-dela, ce n'est plus un objet de variables

def _json_de(txt):
    """Extrait le premier objet JSON exploitable, par BALAYAGE LINEAIRE.

    Une regex a alternatives imbriquees explose en backtracking des que le texte
    contient une accolade non fermee : un modele a raisonnement (champ reasoning
    en texte libre) suffit a la faire tourner sans fin, GIL tenu, relay paralyse.
    Le balayage ci-dessous est lineaire par construction : il ne peut pas boucler.
    """
    txt = (txt or "")[:_JSON_MAX]
    n = len(txt)
    i = 0
    while i < n:
        if txt[i] != "{":
            i += 1
            continue
        prof, j, dans_chaine, echap = 0, i, False, False
        while j < n:
            c = txt[j]
            if dans_chaine:
                if echap:
                    echap = False
                elif c == "\\":
                    echap = True
                elif c == '"':
                    dans_chaine = False
            elif c == '"':
                dans_chaine = True
            elif c == "{":
                prof += 1
            elif c == "}":
                prof -= 1
                if prof == 0:
                    try:
                        d = json.loads(txt[i:j + 1])
                        if isinstance(d, dict) and d:
                            return d
                    except Exception:
                        pass
                    break
            j += 1
        i += 1
    return None

def extraire_variables(entree, ctx):
    """entree = [champs, contenu_verifie, question]. SEULE etape faisant appel au
    modele -- et seulement pour ce qui n'est pas reconnaissable autrement.

    ORDRE (chaque etape peut ecraser la precedente, du moins sur au plus sur) :
      1. le MODELE propose des valeurs pour les champs demandes
      2. le CORE lit directement ce qui est reconnaissable (periode, montant)
      3. TRI PAR ORIGINE : ancree dans la demande -> gardee ; connue de la memoire
         seule -> a confirmer ; ni l'un ni l'autre -> inventee, ecartee
      4. les ACQUIS de la tache comblent ce qui reste vide : ils ont deja passe ce
         controle quand ils sont entres, ils ne le repassent pas. Sur un tour qui
         ne se rattache PAS a la tache, ils sont proposes et non appliques.
    -> {"valeurs": {...}, "manquants": [...], "a_confirmer": [...]}
    """
    champs    = entree[0] if len(entree) > 0 else []
    contenu   = entree[1] if len(entree) > 1 else ""
    question  = entree[2] if len(entree) > 2 else ctx.get("question", "")
    if isinstance(champs, dict):
        champs = champs.get("variables", [])
    if not champs:
        return {"valeurs": {}, "manquants": [], "a_confirmer": []}

    # 1. Proposition du modele
    try:
        brut = _llm(_REGLE % ", ".join(champs),
                    "[DEMANDE]\n" + str(question) +
                    "\n\n[CONTEXTE JURIDIQUE]\n" + str(contenu))
    except Exception as e:
        return {"valeurs": {k: "" for k in champs}, "manquants": list(champs),
                "a_confirmer": [], "erreur": "extraction : %s" % str(e)[:150]}
    d = _json_de(brut) or {}
    vals = {k: str(d.get(k, "") or "").strip() for k in champs}

    # 2. Ce qui est RECONNAISSABLE appartient au core : il prime sur le modele,
    #    qui avait halluciné "juin 2026" sur une demande portant "avril 2026".
    for k, v in _lire_directement(str(question)).items():
        if k in vals and v:
            vals[k] = v

    # FONDEMENT PROTEGE COMME UN ACQUIS : il est etabli sur le corpus servi
    # au tour qui OUVRE l'acte, puis conserve. Sans cela il est recalcule a chaque
    # tour et suit le RAG du moment : une relance de loyer se retrouvait fondee sur
    # la loi de 1965 relative a la copropriete. Le lien au corpus verifie est garde
    # (il n'est pas declare dans le gabarit), mais il ne se contredit plus en cours
    # de constitution.
    try:
        from tache import lire_tache as _lt_f
    except ImportError:
        from primitives.tache import lire_tache as _lt_f
    _f_acquis = ((_lt_f(ctx.get("session") or "") or {}).get("elements") or {}).get("fondement")
    if "fondement" in vals and str(_f_acquis or "").strip():
        vals["fondement"] = _f_acquis

    # FONDEMENT BORNE PAR L'ACTE : le RAG peut deriver et fonder une
    # relance de bail d'habitation sur le code de commerce (L145-1) ou la
    # copropriete. Le gabarit declare le texte attendu : un fondement qui n'en
    # releve pas est ECARTE, il ne sera pas servi a moitie juste.
    _tache_courante = _lt_f(ctx.get("session") or "") or {}
    _acquis_tache = _tache_courante.get("elements") or {}
    _gab_courant = _charger().get(_tache_courante.get("nature") or "") or {}
    _attendu = _gab_courant.get("fondement_attendu")
    if _attendu and "fondement" in vals:
        # Le fondement DECLARE prime : le RAG derivait d'un article a l'autre
        # (24 puis 20-1) et d'un code a l'autre. On le sert tel quel, apres
        # verification qu'il figure bien dans le corpus servi (tracabilite).
        vals["fondement"] = "l'" + _attendu
        # Le VERDICT de verification est une valeur comme une autre : etabli au
        # tour ou le corpus servi est celui du sujet, puis acquis.
        _num = re.search(r"article\s+([LRD]?\.?\s?[\d-]+)", _attendu, re.I)
        # TROIS ETATS, pas deux : un corpus vide ne prouve pas qu'un article est
        # absent, il prouve qu'on n'a rien pu verifier. Un verdict "oui" est acquis
        # definitivement ; "indetermine" laisse la verification a un tour ulterieur.
        _verdict = _acquis_tache.get("fondement_verifie")
        if _verdict != "oui":
            if not str(contenu).strip():
                _verdict = "indetermine"
            elif _num and _normaliser(_num.group(1)) in _normaliser(str(contenu)):
                _verdict = "oui"
            else:
                _verdict = "non"
        vals["fondement_verifie"] = _verdict

    # Normalisation de la reference juridique ("loi n 89-462" -> "loi n° 89-462")
    if vals.get("fondement"):
        vals["fondement"] = re.sub(r"\bn\s*[°o]?\s*(?=\d)", "n° ", vals["fondement"])
        vals["fondement"] = re.sub(r"\s{2,}", " ", vals["fondement"]).strip()

    # 3. TRI PAR ORIGINE. Les DONNEES DE DOSSIER ne peuvent etre ancrees que dans
    #    la DEMANDE : le corpus porte des delais legaux ("six semaines") que le
    #    modele prenait pour une periode de loyer. Le fondement vient du corpus.
    _DOSSIER = ("periode", "montant", "date_effet", "montant_du",
                "nom_destinataire", "adresse_destinataire",
                "nom_cabinet", "adresse_cabinet", "signataire", "fonction_signataire")
    _src_demande = _normaliser(str(question))
    _src = _normaliser(str(question) + " " + str(contenu))
    _memo = _normaliser(" ".join(str(v) for v in (ctx.get("contexte") or {}).values())
                        + " " + " ".join(str(x) for x in (ctx.get("amplificateurs") or [])))
    a_confirmer = []
    for k, v in list(vals.items()):
        if not v or k == "fondement":
            continue
        if _RE_MARQUEUR.match(v):
            vals[k] = ""
            continue
        _ref = _src_demande if k in _DOSSIER else _src
        if _ancre(v, _ref):
            continue
        if _memo.strip() and _ancre(v, _memo):
            a_confirmer.append(k)
        else:
            vals[k] = ""

    # 4. ACQUIS DE LA TACHE, en dernier : ils comblent sans repasser le controle.
    #    Sur un tour PORTEUR (qui rouvre un travail sans reprendre aucun element),
    #    ils sont PROPOSES : un courrier ne doit pas heriter en silence de la
    #    periode d'un autre dossier (constate 18/07, destinataire vide de surcroit).
    try:
        from tache import lire_tache as _lt
    except ImportError:
        from primitives.tache import lire_tache as _lt
    _acquis = (_lt(ctx.get("session") or "") or {}).get("elements") or {}
    # (Le drapeau d'apport n'a plus d'objet : depuis qu'une tache s'ouvre VIERGE,
    # un acquis appartient par construction au travail courant -- il n'y a plus
    # d'heritage a soumettre a confirmation.)
    for k in champs:
        _a = str(_acquis.get(k, "")).strip()
        if not _a:
            continue
        # UN ACQUIS PRIME : au tour "de la part du Cabinet X, signe
        # Thierry ROLLAND", le modele proposait ROLLAND comme DESTINATAIRE -- une
        # valeur bien ancree dans la demande, donc admise par le tri, qui ecrasait
        # l'acquis "Monsieur TOTO". Le modele ne sait pas qu'un champ n'est pas
        # concerne par le tour ; le core, si : ce qui est acquis reste.
        vals[k] = _a

    manquants = [k for k, v in vals.items() if not str(v).strip()]
    return {"valeurs": vals, "manquants": manquants,
            "a_confirmer": sorted(set(a_confirmer))}


# --------------------------------------------------------------------------
def assembler_motif(entree, ctx):
    """entree = [gabarit_ou_selection, extraction]. AUCUN modele : pur formatage.
    Une valeur manquante ne se comble JAMAIS : on rend les manquants au workflow.
    -> {"motif": str|None, "manquants": [...]}
    """
    sel = entree[0] if len(entree) > 0 else {}
    ext = entree[1] if len(entree) > 1 else {}
    gab = sel.get("gabarit") if isinstance(sel, dict) else None
    if not gab or not gab.get("motif"):
        return {"motif": None, "manquants": [], "raison": "aucun gabarit"}
    manquants = list(ext.get("manquants") or [])
    if manquants:
        return {"motif": None, "manquants": manquants}
    # VALEURS HERITEES DE LA MEMOIRE : le core ne les engage pas dans un acte sans
    # accord explicite. Il propose, le gestionnaire tranche.
    a_conf = list(ext.get("a_confirmer") or [])
    if a_conf:
        vals = ext.get("valeurs") or {}
        return {"motif": None, "manquants": [], "a_confirmer": a_conf,
                "proposition": ", ".join("%s : %s" % (k, vals.get(k, "")) for k in a_conf)}
    try:
        return {"motif": gab["motif"].format(**(ext.get("valeurs") or {})),
                "manquants": []}
    except Exception as e:
        return {"motif": None, "manquants": [],
                "raison": "assemblage : %s" % str(e)[:120]}
