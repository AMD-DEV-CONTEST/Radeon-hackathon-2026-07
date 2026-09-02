"""Primitive executer_skill 2SIN - composition recursive bornee.

Charge un workflow ENFANT (skill_*.json) et l'execute via le MEME moteur.
Reutilise le registre existant. Import differe du moteur pour eviter le
circulaire (moteur <- primitives). Garde-fou de profondeur.

Contrat : executer_skill(entree, ctx) -> sortie
  entree : nom du skill (str) OU ["nom_skill"] (liste resolue)
  ctx    : contexte courant ; le sous-workflow herite d'une COPIE
  sortie : le contexte de sortie du sous-workflow (dict) ou {"erreur": ...}
"""
import os, json

# Racine des workflows (skills). Meme dossier que juridique.json.
_WF_DIR = os.environ.get(
    "WORKFLOWS_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workflows"),
)

# Garde-fou : profondeur maximale de composition (evite recursion infinie).
PROFONDEUR_MAX = int(os.environ.get("SKILL_PROFONDEUR_MAX", "3"))


def executer_skill(entree, ctx):
    # Resolution de l'entree : "nom" ou ["nom"]
    nom = entree[0] if isinstance(entree, (list, tuple)) and entree else entree
    if not nom or not isinstance(nom, str):
        return {"erreur": "executer_skill : nom de skill manquant"}

    # Garde-fou de profondeur (compteur dans le ctx, propage aux enfants)
    profondeur = int(ctx.get("_skill_profondeur", 0)) + 1
    if profondeur > PROFONDEUR_MAX:
        return {"erreur": "executer_skill : profondeur max (%d) depassee" % PROFONDEUR_MAX}

    # Charger le skill (fichier skill_<nom>.json ou <nom>.json)
    candidats = ["skill_%s.json" % nom, "%s.json" % nom]
    chemin = None
    for c in candidats:
        p = os.path.join(_WF_DIR, c)
        if os.path.exists(p):
            chemin = p
            break
    if not chemin:
        return {"erreur": "executer_skill : skill introuvable (%s)" % nom}

    try:
        skill_wf = json.load(open(chemin, encoding="utf-8"))
    except Exception as e:
        return {"erreur": "executer_skill : lecture %s : %s" % (nom, str(e)[:120])}

    # Import DIFFERE du moteur (evite le circulaire moteur <- primitives)
    from moteur import Moteur
    from primitives import REGISTRE

    # Le sous-workflow herite d'une COPIE du ctx + le compteur de profondeur
    ctx_enfant = dict(ctx)
    ctx_enfant["_skill_profondeur"] = profondeur

    moteur = Moteur(REGISTRE)
    ctx_sortie = moteur.executer(skill_wf, ctx_enfant)

    # Remonter les cles utiles DANS le ctx parent (pour que la suite du
    # workflow parent -- document, publier, memoire -- les trouve comme
    # apres le flux normal). Effet de bord assume : un skill NOURRIT le parent.
    # Cles remontees par defaut (flux juridique) + celles que le skill DECLARE
    # exposer via "expose" dans son fichier. Un nouveau skill n'oblige plus a
    # modifier cette primitive : il declare son contrat de sortie. Les valeurs exposees sont aussi RETOURNEES a
    # l'appelant, pour une invocation directe (skill d'APPLICATION).
    _defaut = ("verif", "brouillon", "rag", "rag_statut", "fichiers", "doc")
    _expose = tuple(skill_wf.get("expose") or ())
    # Les etapes d'un skill etaient invisibles au journal : la qualification
    # d'acte -- ou se joue l'essentiel -- restait une boite noire. On accumule les
    # traces enfants dans le contexte parent, marquees de leur skill d'origine.
    _tr_enfant = ctx_sortie.get("_trace", [])
    _accu = ctx.get("_traces_skills")
    if not isinstance(_accu, list):
        _accu = []
    _accu.append({"skill": nom, "profondeur": profondeur, "trace": _tr_enfant})
    ctx["_traces_skills"] = _accu
    sortie = {"skill": nom, "ok": True, "_trace_skill": _tr_enfant}
    for cle in _defaut + _expose:
        if cle in ctx_sortie:
            ctx[cle] = ctx_sortie[cle]
            if cle in _expose:
                sortie[cle] = ctx_sortie[cle]
    return sortie
