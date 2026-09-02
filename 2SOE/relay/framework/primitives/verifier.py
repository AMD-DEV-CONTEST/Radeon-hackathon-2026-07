#!/usr/bin/env python3
"""Primitive verifier_citations 2SIN - GARDE-FOU DETERMINISTE DE FIDELITE.
Le modele peut citer ; le CORE verifie chaque citation contre la source servie.
Toute divergence est SIGNALEE (drapeau visible) : l'humain tranche, le core ne masque pas.
Fondement : la fidelite au caractere pres n'est PAS delegable au modele.
Contrat : fn(entree, ctx) -> {"texte","conforme","divergences","controlees"}
"""
import re
from difflib import SequenceMatcher

SEUIL_IDENTIQUE = 0.97     # au-dela : variante typographique, PAS une deformation
SEUIL_PROCHE = 0.55      # au-dela : on considere que le modele visait ce passage
MIN_LONGUEUR = 25        # on ne verifie pas les citations trop courtes (bruit)


def _normaliser(s):
    """Normalise la FORME sans toucher au FOND (chiffres et mots intacts)."""
    s = s.lower()
    s = s.replace("\u2019", "'").replace("\u2018", "'")
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
    s = s.replace("\u00a0", " ").replace("\u202f", " ")
    s = s.replace("\u2026", "...")          # points de suspension typographiques
    s = re.sub(r"[\s]+", " ", s)
    s = re.sub(r"[\.,;:!\?\u2026]+$", "", s)
    return s.strip()


def _decouper_alineas(citation):
    """Decoupe une citation-article en alineas (unite de sens juridique).
    Marqueurs : 1° 2° ... , a) b) , ou sauts de ligne. Retourne [citation]
    si aucun marqueur (citation simple, non decomposable)."""
    # Marqueurs d'alineas numerotes (1° 2° 3° bis...) ou lettres (a) b))
    parts = re.split(r'(?=\b\d+\u00b0(?:\s*bis|\s*ter)?\b)|(?<=[\.;])\s*(?=\d+\u00b0)', citation)
    parts = [p.strip() for p in parts if len(p.strip()) >= MIN_LONGUEUR]
    return parts if len(parts) >= 2 else [citation]


def _extraire_citations(texte):
    """Segments presentes comme litteraux : guillemets francais, droits, courbes."""
    cits = []
    for pat in [r'\u00ab\s*(.+?)\s*\u00bb',      # « ... »
                r'\u201c\s*(.+?)\s*\u201d',      # “ ... ”
                r'"([^"]{%d,})"' % MIN_LONGUEUR]:  # " ... "
        for m in re.finditer(pat, texte, re.DOTALL):
            c = m.group(1).strip()
            if len(c) >= MIN_LONGUEUR:
                cits.append(c)
    # dedoublonnage en conservant l'ordre
    vus, out = set(), []
    for c in cits:
        if c not in vus:
            vus.add(c); out.append(c)
    return out


def _phrases_source(rag):
    """Decoupe la source en phrases candidates pour la comparaison."""
    corps = "\n".join(l for l in rag.split("\n") if not l.startswith("["))
    corps = re.sub(r'^- \[[^\]]*\] \([^\)]*\) : ', '', corps, flags=re.MULTILINE)
    return [p.strip() for p in re.split(r'(?<=[\.\;])\s+', corps) if len(p.strip()) >= MIN_LONGUEUR]


def verifier_citations(entree, ctx):
    """entree = [texte_genere, rag]. Verifie chaque citation contre la source."""
    if isinstance(entree, list):
        texte = entree[0] if len(entree) > 0 else ""
        rag   = entree[1] if len(entree) > 1 else ""
    else:
        texte, rag = str(entree), ctx.get("rag", "")

    if not texte:
        return {"texte": texte, "conforme": True, "divergences": [], "controlees": 0}

    citations = _extraire_citations(texte)
    if not citations:
        return {"texte": texte, "conforme": True, "divergences": [], "controlees": 0}

    if not rag:
        # Cite alors qu'AUCUNE source n'a ete servie : divergence par construction.
        div = [{"citee": c, "source": None, "motif": "aucune source servie"} for c in citations]
        return {"texte": _annoter(texte, div), "conforme": False,
                "divergences": div, "controlees": len(citations)}

    rag_norm = _normaliser(rag)
    phrases = _phrases_source(rag)
    divergences = []

    for c in citations:
        # DECOMPOSITION PAR ALINEA : une citation-article (multi-alineas) se
        # verifie alinea par alinea (unite de sens juridique), pas en bloc.
        # Un bloc entier ne matche jamais une phrase isolee de la source.
        fragments = _decouper_alineas(c)
        multi = len(fragments) > 1
        for i, frag in enumerate(fragments):
            tronquee = bool(re.search(r'(\u2026|\.\.\.)\s*$', frag.strip()))
            cn = _normaliser(frag)
            if not cn:
                continue
            if cn in rag_norm:
                continue  # alinea LITTERALEMENT present dans la source -> conforme
            # Troncature legitime : debut de phrase puis "..." present tel quel.
            if tronquee and len(cn) >= MIN_LONGUEUR and cn in rag_norm:
                continue
            # Non trouve : on cherche le passage que le modele visait.
            best, ratio = None, 0.0
            for p in phrases:
                r = SequenceMatcher(None, cn, _normaliser(p)).ratio()
                if r > ratio:
                    best, ratio = p, r
            if ratio >= SEUIL_IDENTIQUE:
                continue   # variante typographique : conforme
            # Localisation du probleme : alinea precis si citation-article.
            ou = (" (alinea %d)" % (i + 1)) if multi else ""
            if ratio >= SEUIL_PROCHE:
                divergences.append({"citee": frag, "source": best.strip(),
                                    "motif": "citation DEFORMEE%s (%.0f%% de proximite)" % (ou, ratio * 100)})
            else:
                divergences.append({"citee": frag, "source": None,
                                    "motif": "citation INTROUVABLE dans la source servie%s" % ou})

    return {"texte": _annoter(texte, divergences) if divergences else texte,
            "conforme": not divergences,
            "divergences": divergences,
            "controlees": len(citations)}


def _annoter(texte, divergences):
    """Drapeau visible : le core ne corrige pas en silence, il SIGNALE. L'humain tranche."""
    out = texte
    for d in divergences:
        out = out.replace(d["citee"], d["citee"] + " [!! CITATION NON CONFORME]", 1)
    bloc = ["", "", "=" * 68,
            "!! CONTROLE DE FIDELITE DES SOURCES - %d divergence(s) detectee(s)" % len(divergences),
            "=" * 68]
    for i, d in enumerate(divergences, 1):
        bloc.append("")
        bloc.append("%d. %s" % (i, d["motif"]))
        bloc.append("   CITE PAR L'ASSISTANT : \u00ab %s \u00bb" % d["citee"][:220])
        if d["source"]:
            bloc.append("   TEXTE OFFICIEL      : \u00ab %s \u00bb" % d["source"][:220])
        else:
            bloc.append("   TEXTE OFFICIEL      : aucun passage correspondant dans la source servie")
    bloc.append("")
    bloc.append("Le controle est automatique et deterministe. La citation ci-dessus n'est PAS")
    bloc.append("conforme au texte officiel servi. Verification humaine requise avant tout usage.")
    bloc.append("=" * 68)
    return out + "\n".join(bloc)
