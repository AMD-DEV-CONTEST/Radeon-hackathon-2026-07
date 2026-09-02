#!/usr/bin/env python3
"""Primitive generer_document 2SIN - generation DETERMINISTE.
le modele renseigne les VARIABLES metier, le code
impose la FORME (template, structure, formats). Le modele ne touche jamais au docx.
Contrat : fn(entree, ctx) -> {"texte":..., "chemin":..., "erreur":...}
"""
import os, json, subprocess, time

GEN_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "generateurs", "courrier-cabinet")
GEN_PY    = os.path.abspath(os.path.join(GEN_DIR, "generate.py"))
AGENT_OUT = os.environ.get("AGENT_OUT", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "out"))
GEN_TIMEOUT = int(os.environ.get("GEN_TIMEOUT", "120"))

def generer_document(entree, ctx):
    """entree = [contenu_redige, question] ou str."""
    if isinstance(entree, list):
        contenu  = entree[0] if len(entree) > 0 else ""
        question = entree[1] if len(entree) > 1 else ""
        # Le CORPUS servi, distinct du contenu redige : le fondement se verifie
        # contre les sources, pas contre le brouillon du modele.
        corpus   = entree[2] if len(entree) > 2 else ""
    else:
        contenu, question, corpus = str(entree), ctx.get("question", ""), ctx.get("rag", "")

    # 0. REPRISE D'UN ACTE EN ATTENTE : si le tour est un accord et qu'un acte
    #    attend confirmation, on genere AVEC LES VALEURS VALIDEES, sans nouvelle
    #    extraction et sans consulter la memoire. L'etat est consomme (une fois).
    try:
        from memoire import detecter_accord
        from tache import lire_tache, rattacher, fermer_tache
    except ImportError:
        from primitives.memoire import detecter_accord
        from primitives.tache import lire_tache, rattacher, fermer_tache
    _sid = ctx.get("session") or "anonyme"
    _repris = None
    if detecter_accord(question):
        _t = lire_tache(_sid)
        _repris = ({"gabarit": _t.get("nature"), "valeurs": _t.get("elements") or {},
                    "question": (_t.get("sujet") or question)} if _t else None)
        pass
        if not _repris:
            return {"texte": "Je n'ai pas d'acte en attente de confirmation. "
                             "Pouvez-vous reformuler votre demande ?",
                    "chemin": None, "erreur": None}

    # TRAVAIL EXPIRE : un tour d'apport arrive sans tache. Le dire, plutot que de
    # laisser le tour partir dans le vide -- une expiration silencieuse est du
    # meme ordre qu'une garde qui echoue sans le signaler.
    if not _repris and not lire_tache(_sid) \
            and (ctx.get("intention") or {}).get("intention") != "redaction":
        return {"texte": ("Le courrier en cours a expire : je n'ai plus les "
                          "elements que vous m'aviez donnes.\n"
                          "Reprenez depuis le debut en precisant l'acte souhaite."),
                "chemin": None, "erreur": None, "raison": "tache expiree"}

    # 1. QUALIFICATION — skill d'APPLICATION : invoque par son NOM,
    #    pas route semantiquement. Il enchaine selection du gabarit, extraction
    #    des variables et assemblage du motif. Le modele n'intervient que pour
    #    renseigner des valeurs ; le texte de l'acte vient du gabarit.
    try:
        from skill import executer_skill
    except ImportError:
        from primitives.skill import executer_skill
    ctx_q = dict(ctx)
    ctx_q["question"] = question
    ctx_q["contenu_acte"] = contenu
    ctx_q["corpus_servi"] = corpus or ctx.get("rag", "")
    ctx_q["situation"] = ctx.get("situation") or {}
    if _repris:
        # Valeurs deja validees par un humain : on saute la qualification.
        from gabarit import _charger as _charger_gabarits
        _g = (_charger_gabarits() or {}).get(_repris.get("gabarit") or "", {})
        sortie = {"gabarit": {"nom": _repris.get("gabarit"), "gabarit": _g},
                  "motif": {"motif": (_g.get("motif") or "").format(**_repris["valeurs"])
                            if _g.get("motif") else None, "manquants": []}}
        question = _repris.get("question") or question
    else:
        sortie = executer_skill("qualifier_acte", ctx_q) or {}
        # Les traces du skill sont accumulees dans la COPIE du contexte : on les
        # remonte au contexte reel, sans quoi le journal ne voit rien du skill.
        if ctx_q.get("_traces_skills"):
            ctx["_traces_skills"] = (ctx.get("_traces_skills") or []) \
                                    + ctx_q["_traces_skills"]
    motif = (sortie.get("motif") or {}) if isinstance(sortie, dict) else {}
    # ACTE EN COURS DE CONSTITUTION : les valeurs du tour s'ajoutent a
    # celles deja reunies. Un element apporte a n'importe quel tour reste acquis ;
    # le tour courant fait autorite sur ce qu'il apporte. On ne conclut au manque
    # qu'APRES fusion -- c'est l'usage legitime de la memoire : accumuler un dossier.
    _a_fermer = False
    if not _repris:
        _ext = sortie.get("extraction") or {}
        _sel = sortie.get("gabarit") or {}
        _gab_nom = _sel.get("nom")
        # UN ACTE EN COURS PRIME sur une nouvelle qualification : un tour qui
        # n'apporte que des elements ("pour M. TOTO, avril 2026, 599 euros") ne
        # contient plus le sujet et serait requalifie a tort (constate 18/07 :
        # relance de loyer requalifiee en charges de copropriete).
        _encours = lire_tache(_sid) or {}
        if _encours.get("nature") and _encours["nature"] != _gab_nom:
            try:
                from gabarit import _charger as _charger_gab
            except ImportError:
                from primitives.gabarit import _charger as _charger_gab
            _g_enc = (_charger_gab() or {}).get(_encours["nature"])
            if _g_enc:
                _gab_nom = _encours["nature"]
                _sel = {"nom": _gab_nom, "gabarit": _g_enc}
                sortie["gabarit"] = _sel
        if _gab_nom:
            # Le rattachement est une ETAPE du skill : ici on LIT
            # seulement l'etat qui en resulte.
            _t = (sortie.get("tache_courante") or {}).get("tache") or lire_tache(_sid) or {}
            _cumul = _t.get("elements") or {}
            _g = _sel.get("gabarit") or {}
            # UNION variables + requis : un acte n'existe pas sans destinataire ni
            # signataire, meme si le motif ne les mentionne pas.
            try:
                from gabarit import _champs_acte
            except ImportError:
                from primitives.gabarit import _champs_acte
            _reste = [k for k in _champs_acte(_g)
                      if not str(_cumul.get(k, "")).strip()]
            if not _reste and _g.get("motif"):
                try:
                    _vm = {k: _cumul.get(k, "") for k in (_g.get("variables") or [])}
                    motif = {"motif": _g["motif"].format(**_vm), "manquants": []}
                    _a_fermer = True                  # fermeture APRES construction
                except Exception:
                    pass
            elif _reste:
                motif = {"motif": None, "manquants": _reste}

    # FONDEMENT NON VERIFIE : l'acte se fonde sur un article que le corpus servi
    # ne contient pas. Un courrier opposable ne peut pas citer une reference que
    # le core n'a pas pu confirmer -- c'est le sens meme du controle de fidelite.
    # On ne l'etablit pas en silence : on le dit.
    _ext_v = (sortie.get("extraction") or {}).get("valeurs") or {}
    _verdict = str(_ext_v.get("fondement_verifie")
                   or (lire_tache(_sid) or {}).get("elements", {}).get("fondement_verifie", ""))
    if _verdict == "non":
        return {"texte": ("Je ne peux pas etablir cet acte : son fondement "
                          "(%s) n'a pas ete retrouve dans le corpus verifie. "
                          "Une verification humaine est requise."
                          % _ext_v.get("fondement", "reference declaree")),
                "chemin": None, "erreur": "fondement non verifie"}

    manquants = motif.get("manquants") or []
    if manquants:
        # Une valeur manque : on ne comble JAMAIS. Le workflow demandera la precision.
        return {"texte": contenu, "chemin": None, "manquants": manquants,
                "erreur": "variables manquantes : " + ", ".join(manquants)}
    a_confirmer = motif.get("a_confirmer") or []
    if a_confirmer:
        # Valeurs issues d'un echange precedent : on demande confirmation avant de
        # les engager dans un acte. Aucune donnee heritee n'entre sans accord.
        _ext = (sortie.get("extraction") or {})
        return {"texte": ("Ces informations proviennent de nos echanges precedents : "
                          + motif.get("proposition", "") +
                          ". Confirmez-vous qu'il s'agit bien du meme dossier ?"),
                "chemin": None, "a_confirmer": a_confirmer,
                "proposition": motif.get("proposition", "")}


    # 2. METADONNEES du courrier (expediteur, destinataire, objet, signataire)
    try:
        from variables_courrier import extraire_variables_courrier
    except ImportError:
        from primitives.variables_courrier import extraire_variables_courrier
    variables = extraire_variables_courrier([contenu, question], ctx)
    if "erreur" in variables:
        return {"texte": contenu, "chemin": None, "erreur": variables["erreur"]}
    # Le motif du gabarit prime sur le corps redige (determinisme de l'acte).
    if motif.get("motif"):
        variables["corps"] = motif["motif"]
        variables["_gabarit"] = (sortie.get("gabarit") or {}).get("nom")

    # 2. DETERMINISTE : le core impose la forme via le template
    os.makedirs(AGENT_OUT, exist_ok=True)
    base = os.path.join(AGENT_OUT, "courrier_%d" % int(time.time()))
    data_path, docx_path = base + ".json", base + ".docx"
    pdf_path = base + ".pdf"
    md_path = base + ".md"

    # FORMATS : les deux par defaut. Un acte peut en imposer un seul -- une mise
    # en demeure se transmet en PDF (non modifiable), un projet de courrier en
    # docx (retouchable par le gestionnaire). Le gabarit le declare ; a defaut,
    # FORMATS_ACTE vaut pour l'installation.
    _fmt = ((sortie.get("gabarit") or {}).get("gabarit") or {}).get("formats") \
        or [x.strip() for x in os.environ.get("FORMATS_ACTE", "docx,pdf").split(",")
            if x.strip()]
    _veut_docx, _veut_pdf = ("docx" in _fmt), ("pdf" in _fmt)
    _veut_md = "md" in _fmt
    if not (_veut_docx or _veut_pdf or _veut_md):
        _veut_docx = True

    try:
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(variables, f, ensure_ascii=False)
        # generate.py produit le PDF a partir du docx bien forme -- jamais a la
        # main. Demander le PDF produit donc les deux ; demander le docx
        # seul evite le passage par LibreOffice.
        _cible = pdf_path if _veut_pdf else (docx_path if _veut_docx else md_path)
        p = subprocess.run(["python3", GEN_PY, data_path, _cible],
                           capture_output=True, text=True, timeout=GEN_TIMEOUT)
        # Le Markdown ne derive pas du docx : il se rend directement depuis les
        # variables, sans LibreOffice ni docxtpl. Un second appel, donc.
        if _veut_md and _cible != md_path:
            subprocess.run(["python3", GEN_PY, data_path, md_path],
                           capture_output=True, text=True, timeout=GEN_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"texte": contenu, "chemin": None,
                "erreur": "generation document : delai depasse (%ds)" % GEN_TIMEOUT}
    except Exception as e:
        return {"texte": contenu, "chemin": None, "erreur": "generation : %s" % str(e)[:200]}

    _produits = [x for x in (docx_path, pdf_path, md_path) if os.path.exists(x)]
    if p.returncode != 0 or not _produits:
        err = (p.stderr or p.stdout or "").strip()[-400:]
        return {"texte": contenu, "chemin": None, "erreur": "generate.py a echoue : %s" % err}
    # Le docx intermediaire est retire si seul le PDF est demande.
    if _veut_pdf and not _veut_docx and os.path.exists(docx_path):
        try:
            os.remove(docx_path)
            _produits = [x for x in _produits if x != docx_path]
        except Exception:
            pass

    # La tache n'est fermee QU'APRES construction complete : les metadonnees
    # (objet declare par le gabarit) la lisent encore juste avant.
    # La fermeture est une ETAPE du workflow (etape 'cloture'), plus un effet
    # de bord de la generation : une modification d'etat doit etre visible.
    return {"texte": contenu, "chemin": _produits[0],
            "fichiers": _produits, "formats": _fmt, "erreur": None,
            "variables": variables}
