#!/usr/bin/env python3
"""Primitive journaliser 2SIN — journal des DECISIONS.

Ce journal porte de quoi JUGER une decision, jamais son contenu : ni nom de
locataire, ni montant, ni adresse. Un acte s'audite sans exposer un dossier.
Le contenu appartient a l'acte produit ; le journal dit sur quoi il s'est fonde.

Trois usages d'une meme trace :
  - AUDIT      pour le cabinet : sur quelle source, a quel score, quel verdict
  - BENCHMARK  entre modeles : rejouer un jeu de cas et comparer
  - CORPUS     d'entrainement : les executions saines font des paires exemplaires

Contrat : fn(entree, ctx) -> {"journalise": bool, "id": int|None}
Ecriture DECLAREE : c'est une etape du workflow, pas un effet de bord.
"""
import os, json, hashlib, datetime

PG = {"host": os.environ.get("PG_HOST", "postgres"),
      "port": os.environ.get("PG_PORT", "5432"),
      "user": os.environ.get("PG_USER", "2sin"),
      "password": os.environ.get("PG_PASSWORD", ""),
      "dbname": os.environ.get("PG_DATABASE", "2sin")}
SEL = os.environ.get("JOURNAL_SEL", "2sin")          # sel du hachage de session
ACTIF = os.environ.get("JOURNAL_ACTIF", "1") not in ("0", "false", "")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS journal_decisions (
    id            BIGSERIAL PRIMARY KEY,
    quand         TIMESTAMPTZ NOT NULL DEFAULT now(),
    session_hash  TEXT,
    workflow      TEXT,
    modele        TEXT,
    profil        TEXT,
    domaine       TEXT,
    intention     TEXT,
    rag_statut    TEXT,
    rag_top1      REAL,
    rag_top2      REAL,
    rag_couv      REAL,
    rag_ref_hit   BOOLEAN,
    collections   TEXT,
    gabarit       TEXT,
    champs_manquants TEXT,
    fondement_verifie TEXT,
    citations_non_conformes INTEGER,
    acte_produit  BOOLEAN,
    arrete_par    TEXT,
    duree_ms      INTEGER,
    etapes        JSONB
);
CREATE INDEX IF NOT EXISTS idx_journal_quand   ON journal_decisions (quand DESC);
CREATE INDEX IF NOT EXISTS idx_journal_modele  ON journal_decisions (modele);
CREATE INDEX IF NOT EXISTS idx_journal_statut  ON journal_decisions (rag_statut);
"""

_pret = False


def _connexion():
    import psycopg
    return psycopg.connect(**PG, connect_timeout=5)


def _assurer_schema(cur):
    global _pret
    if not _pret:
        cur.execute(_SCHEMA)
        _pret = True


def _hash_session(sid):
    """La session rattache les tours d'un meme travail ; elle n'a pas a designer
    un utilisateur. Empreinte stable, non reversible."""
    if not sid:
        return None
    return hashlib.sha256((SEL + str(sid)).encode()).hexdigest()[:16]


def _resume_etapes(trace, skill=None, profondeur=0):
    """Une ligne par etape : identifiant, issue, duree. Pas de contenu.
    Une etape de SKILL porte son origine et sa profondeur -- sans quoi la
    qualification d'acte reste une boite noire dans le journal."""
    out = []
    for t in (trace or []):
        if not isinstance(t, (list, tuple)) or not t:
            continue
        issue = t[0]
        etape = t[1] if len(t) > 1 else None
        duree = t[3] if len(t) > 3 else None
        ligne = {"etape": etape, "issue": issue, "duree": duree,
                 "type": "skill" if skill else "primitive"}
        if skill:
            ligne["skill"] = skill
            ligne["profondeur"] = profondeur
        out.append(ligne)
    return out


def journaliser(entree, ctx):
    """entree ignoree : la primitive lit le contexte d'execution et n'en retient
    que les elements de JUGEMENT."""
    if not ACTIF:
        return {"journalise": False, "id": None}

    diag = ctx.get("_rag_diag") or {}
    intention = ctx.get("intention") or {}
    doc = ctx.get("doc") or {}
    verif = ctx.get("verif") or {}
    # Le gabarit retenu est porte par le document produit : la cle "gabarit" du
    # skill enfant n'est pas visible ici (le journal constate au niveau du relay).
    gab = (ctx.get("gabarit") or {})
    _gab_doc = ((doc.get("variables") or {}).get("_gabarit")
                if isinstance(doc, dict) else None)
    trace = _resume_etapes(ctx.get("_trace"))
    for _sk in (ctx.get("_traces_skills") or []):
        trace.extend(_resume_etapes(_sk.get("trace"), skill=_sk.get("skill"),
                                    profondeur=_sk.get("profondeur", 1)))
    duree = sum(int(float(str(e.get("duree", "0")).rstrip("s")) * 1000)
                for e in trace if e.get("duree")) if trace else None

    ligne = {
        "session_hash": _hash_session(ctx.get("session")),
        "workflow": ctx.get("_workflow_nom"),
        "modele": os.environ.get("VLLM_MODEL"),
        "profil": ctx.get("profil"),
        "domaine": intention.get("domaine"),
        "intention": intention.get("intention"),
        "rag_statut": ctx.get("rag_statut"),
        "rag_top1": diag.get("top1"),
        "rag_top2": diag.get("top2"),
        "rag_couv": diag.get("couverture"),
        "rag_ref_hit": diag.get("ref_hit"),
        "collections": ",".join(ctx.get("_rag_collections") or []) or None,
        "gabarit": _gab_doc or (gab.get("nom") if isinstance(gab, dict) else None),
        "champs_manquants": ",".join(doc.get("manquants") or []) or None,
        "fondement_verifie": ((ctx.get("extraction") or {}).get("valeurs") or {}
                              ).get("fondement_verifie"),
        "citations_non_conformes": len(verif.get("divergences") or [])
                                   if isinstance(verif, dict) else None,
        "acte_produit": bool(doc.get("chemin")),
        "arrete_par": ctx.get("_arrete_par"),
        "duree_ms": duree,
        "etapes": json.dumps(trace, ensure_ascii=False),
    }
    cols = ", ".join(ligne.keys())
    marks = ", ".join(["%s"] * len(ligne))
    try:
        with _connexion() as cnx:
            with cnx.cursor() as cur:
                _assurer_schema(cur)
                cur.execute("INSERT INTO journal_decisions (%s) VALUES (%s) RETURNING id"
                            % (cols, marks), list(ligne.values()))
                rid = cur.fetchone()[0]
            cnx.commit()
        return {"journalise": True, "id": rid}
    except Exception as e:
        # Le journal ne doit JAMAIS empecher une reponse : il constate, il ne
        # gouverne pas. L'echec est signale, le flux continue.
        return {"journalise": False, "id": None, "erreur": str(e)[:200]}
