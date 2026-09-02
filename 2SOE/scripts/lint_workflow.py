#!/usr/bin/env python3
"""Linter de workflow 2SIN — vérifie un JSON de workflow AVANT de le lancer.

Attrape ce qui échoue SILENCIEUSEMENT à l'exécution :
  - primitive inconnue        → le moteur l'ignore, trace ("ERR", ...)
  - $chemin mal orthographié  → résolu à None, la primitive reçoit None
  - littéral entre guillemets → condition toujours fausse
  - producteur après consommateur
  - id dupliqué
  - comparaison de flottant, valeur avec espace

Ce que ce linter NE PEUT PAS vérifier :
  - l'exclusivité réelle des conditions (dépend des valeurs runtime)
  - la forme d'entrée attendue par chaque primitive (str vs liste)
  - quelle primitive peut rendre _arret

Usage :
    lint_workflow.py <fichier.json> [fichier2.json ...]
    lint_workflow.py --tous            tous les workflows du dossier

Sortie : 0 si aucune erreur, 1 sinon. Les avertissements ne changent pas le code.
"""
import json
import os
import re
import sys

_ICI = os.path.dirname(os.path.abspath(__file__))
WF_DIR = os.environ.get(
    "WORKFLOWS_DIR", os.path.join(_ICI, "..", "relay", "framework", "workflows"))
PRIM_DIR = os.environ.get(
    "PRIMITIVES_DIR", os.path.join(_ICI, "..", "relay", "framework", "primitives"))

# Clés écrites HORS CONTRAT par les primitives ou le moteur.
# Elles n'apparaissent dans aucune "sortie" : un chemin qui les vise est légitime.
HORS_CONTRAT = {
    "rag_statut",        # rechercher_corpus
    "_rag_diag",         # rechercher_corpus
    "svo_confiance",     # amplifier_svo
    "svo_pistes",        # amplifier_svo
    "_arrete_par",       # moteur, sur garde
    "_arret_message",    # moteur, sur garde
    "_passe",            # moteur, à chaque passe
    "_trace",            # moteur, en fin d'exécution
    "_skill_profondeur", # executer_skill
    "_reprise_enrichie", # relay, seconde passe
}

# Posées par le relay dans le contexte initial.
CTX_INITIAL = {"question", "session", "profil", "complexite"}

# Un SKILL hérite d'une COPIE du contexte parent (executer_skill : ctx_enfant =
# dict(ctx)). Tout ce que le workflow parent a produit avant l'appel lui est
# donc accessible -- un skill analysé isolément semblerait lire des clés
# inexistantes. Liste des sorties du parent, à tenir à jour si juridique.json
# change.
CTX_HERITE_SKILL = {
    "garde", "contexte", "meta", "intention", "situation", "libre",
    "route", "svo_res", "officiel", "rag", "precision", "abstention",
    "brouillon", "verif", "doc", "fichiers", "tache_close", "memo",
    "corpus_servi",
}

# Sorties TERMINALES : la primitive produit le texte de la réponse, récupéré
# par le relay hors du workflow. Ne jamais les signaler comme mortes.
SORTIES_TERMINALES = {
    "meta", "libre", "precision", "abstention", "verif", "fichiers",
    "memo", "tache_close", "tache_ouverte", "skill_res",
}

# Littéraux Python : à écrire SANS guillemets — la comparaison est textuelle.
LITTERAUX = {"None", "True", "False"}

_RE_COND = re.compile(r"^\s*([\w\.]+)\s*(==|!=)\s*(\S+)\s*$")
_RE_FLOTTANT = re.compile(r"^-?\d+\.\d+$")


def _registre():
    """Les primitives réellement enregistrées, lues depuis primitives/__init__.py.
    Repli : les noms de fonctions fn(entree, ctx) trouvés dans les modules."""
    init = os.path.join(PRIM_DIR, "__init__.py")
    noms = set()
    if os.path.isfile(init):
        with open(init, encoding="utf-8") as f:
            src = f.read()
        noms |= set(re.findall(r'["\'](\w+)["\']\s*:', src))
    if not noms and os.path.isdir(PRIM_DIR):
        for f in os.listdir(PRIM_DIR):
            if not f.endswith(".py"):
                continue
            with open(os.path.join(PRIM_DIR, f), encoding="utf-8") as fh:
                noms |= set(re.findall(r"^def (\w+)\(entree, ctx\)", fh.read(), re.M))
    return noms


def _decouper(expr, sep):
    """Découpe au niveau 0 de parenthèse — même logique que le moteur."""
    parties, courant, prof, i = [], "", 0, 0
    while i < len(expr):
        ch = expr[i]
        if ch == "(":
            prof += 1
        elif ch == ")":
            prof -= 1
        if prof == 0 and expr[i:i + len(sep)] == sep:
            parties.append(courant.strip())
            courant = ""
            i += len(sep)
            continue
        courant += ch
        i += 1
    parties.append(courant.strip())
    return [p for p in parties if p]


def _comparaisons(expr):
    """Rend la liste des comparaisons simples d'une condition.

    MEME ORDRE QUE LE MOTEUR : on deballe le groupe qui enveloppe TOUTE
    l'expression, puis on decoupe au niveau 0 de parenthese. Deballer d'abord
    sans verifier l'enveloppement casse « (A) || (B && C) » -- le premier
    caractere est « ( » et le dernier « ) », mais ce ne sont pas les memes.
    """
    expr = expr.strip()
    if not expr:
        return []
    # Le groupe enveloppe-t-il TOUTE l'expression ?
    while expr.startswith("(") and expr.endswith(")") and _equilibre(expr[1:-1]):
        expr = expr[1:-1].strip()
    for sep in ("||", "&&"):
        parties = _decouper(expr, sep)
        if len(parties) > 1:
            out = []
            for p in parties:
                out.extend(_comparaisons(p))
            return out
    return [expr]


def _equilibre(s):
    n = 0
    for ch in s:
        n += (ch == "(") - (ch == ")")
        if n < 0:
            return False
    return n == 0


def _racine(chemin):
    return chemin.split(".")[0]


def verifier(path, registre):
    """-> (erreurs, avertissements)"""
    err, avert = [], []
    est_skill = os.path.basename(path).startswith("skill_")

    try:
        with open(path, encoding="utf-8") as f:
            wf = json.load(f)
    except Exception as e:
        return (["JSON illisible : %s" % str(e)[:120]], [])

    if not isinstance(wf.get("etapes"), list):
        return (['clé "etapes" absente ou non-liste'], [])

    if "expose" not in wf and not est_skill:
        avert.append(
            'pas de "expose" : un appel /v1/executer renverra TOUT le contexte, '
            "y compris les données de dossier")

    connues = set(CTX_INITIAL) | set(HORS_CONTRAT)
    if est_skill:
        connues |= set(CTX_HERITE_SKILL)
    ids = {}

    for i, e in enumerate(wf["etapes"], start=1):
        eid = e.get("id") or "(sans id)"
        pos = "étape %d [%s]" % (i, eid)

        if not e.get("id"):
            err.append("%s : pas d'\"id\"" % pos)
        elif eid in ids:
            err.append("%s : id dupliqué (déjà vu étape %d)" % (pos, ids[eid]))
        else:
            ids[eid] = i

        prim = e.get("primitive")
        if not prim:
            err.append('%s : pas de "primitive"' % pos)
        elif registre and prim not in registre:
            err.append('%s : primitive inconnue "%s" — le moteur IGNORERA '
                       "l'étape sans erreur" % (pos, prim))

        # --- entrées : $chemins ---
        entree = e.get("entree")
        cibles = entree if isinstance(entree, list) else [entree]
        for v in cibles:
            if not isinstance(v, str) or not v.startswith("$"):
                continue
            r = _racine(v[1:])
            if r not in connues:
                err.append('%s : "%s" — "%s" n\'est produit par aucune étape '
                           "antérieure (résolu à None, en silence)" % (pos, v, r))

        # --- condition ---
        cond = e.get("condition")
        if cond:
            if not _equilibre(cond):
                err.append("%s : parenthèses déséquilibrées" % pos)
            for c in _comparaisons(cond):
                m = _RE_COND.match(c)
                if not m:
                    err.append('%s : comparaison non parsable « %s » — le moteur '
                               "la considère VRAIE (return True)" % (pos, c[:50]))
                    continue
                chemin, _op, attendu = m.groups()
                r = _racine(chemin)
                if r not in connues:
                    err.append('%s : condition sur "%s" — jamais produit '
                               "avant cette étape" % (pos, chemin))
                if attendu.startswith(('"', "'")) or attendu.endswith(('"', "'")):
                    nu = attendu.strip("\"'")
                    err.append('%s : « %s » entre guillemets — la comparaison est '
                               "TEXTUELLE, écrire %s == %s"
                               % (pos, attendu, chemin, nu))
                if attendu.lower() in ("null", "none") and attendu != "None":
                    err.append('%s : « %s » — écrire None (majuscule, sans '
                               "guillemets)" % (pos, attendu))
                if attendu.lower() in ("true", "false") and attendu not in LITTERAUX:
                    err.append('%s : « %s » — écrire %s (majuscule initiale)'
                               % (pos, attendu, attendu.capitalize()))
                if _RE_FLOTTANT.match(attendu):
                    err.append('%s : comparaison de flottant « %s » — str(0.6) est '
                               "fragile, tester le seuil DANS la primitive"
                               % (pos, attendu))
                reste = c[m.end(3):].strip()
                if reste:
                    err.append('%s : « %s » ignoré — la valeur attendue s\'arrête '
                               "au premier espace" % (pos, reste[:30]))

        # --- sortie ---
        s = e.get("sortie")
        if s:
            connues.add(s)

    # --- sorties déclarées mais jamais lues ---
    lues = set()
    for e in wf["etapes"]:
        entree = e.get("entree")
        for v in (entree if isinstance(entree, list) else [entree]):
            if isinstance(v, str) and v.startswith("$"):
                lues.add(_racine(v[1:]))
        if e.get("condition"):
            for c in _comparaisons(e["condition"]):
                m = _RE_COND.match(c)
                if m:
                    lues.add(_racine(m.group(1)))
    for k in (wf.get("expose") or []):
        lues.add(_racine(k))
    for e in wf["etapes"]:
        s = e.get("sortie")
        if s and s not in lues and s not in SORTIES_TERMINALES:
            avert.append('étape [%s] : sortie "%s" jamais lue et non terminale — '
                         "la primitive communique par effet de bord, ou c'est du "
                         "bruit" % (e.get("id"), s))

    # --- conditions dupliquées ---
    vues = {}
    for e in wf["etapes"]:
        c = (e.get("condition") or "").strip()
        if len(c) > 40:
            vues.setdefault(c, []).append(e.get("id"))
    for c, ids_ in vues.items():
        if len(ids_) > 1:
            avert.append("conditions identiques sur %s (%d clauses) — conditionner "
                         "à la SORTIE de l'étape dont on dépend"
                         % (", ".join(ids_), c.count("&&") + c.count("||") + 1))

    return err, avert


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--tous" in sys.argv or not args:
        if not os.path.isdir(WF_DIR):
            print("dossier introuvable : %s" % WF_DIR)
            return 1
        args = sorted(os.path.join(WF_DIR, f)
                      for f in os.listdir(WF_DIR) if f.endswith(".json"))

    registre = _registre()
    print("registre : %d primitives" % len(registre) if registre
          else "⚠ registre vide — vérification des primitives DÉSACTIVÉE")
    print()

    total_err = 0
    for path in args:
        err, avert = verifier(path, registre)
        total_err += len(err)
        nom = os.path.basename(path)
        if not err and not avert:
            print("  ✅ %-32s aucun problème" % nom)
            continue
        print("  %s %s" % ("❌" if err else "⚠ ", nom))
        for e in err:
            print("       ERREUR  %s" % e)
        for a in avert:
            print("       avert.  %s" % a)
        print()

    print()
    print("%d erreur(s)." % total_err if total_err else "Aucune erreur.")
    return 1 if total_err else 0


if __name__ == "__main__":
    sys.exit(main())
