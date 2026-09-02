#!/usr/bin/env python3
"""Banc de mesure 2SIN - rejoue un jeu de cas et compare depuis le journal.

Le core est JUGE AUTOMATIQUE : il produit deja les signaux (statut RAG, verdict
de fondement, citations non conformes, champs manquants, abstention). Aucune
annotation humaine n'est requise -- on compare ce que le systeme a constate.

Sert trois besoins : choisir un modele, mesurer l'effet d'un affutage (LoRA),
et prouver la STABILITE (meme cas, meme resultat).

Usage :
  benchmark.py lancer [SERIE]     execute le jeu de cas
  benchmark.py comparer           agrege le journal par modele
"""
import json, os, re, sys, time, hashlib
import urllib.request as u

RELAY      = os.environ.get("RELAY_EXEC", "http://localhost:8787/v1/executer")
EXEC_TOKEN = os.environ.get("EXEC_TOKEN", "")
# Ancre sur l'emplacement du script : le banc suit le depot, il ne depend
# pas d'un chemin d'installation particulier.
CAS_PATH   = os.environ.get("BENCH_CAS", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data-seed", "benchmark_cas.json"))
PG = {"host": os.environ.get("PG_HOST", "localhost"),
      "port": os.environ.get("PG_PORT", "5432"),
      "user": os.environ.get("PG_USER", "2sin"),
      "password": os.environ.get("PG_PASSWORD", ""),
      "dbname": os.environ.get("PG_DATABASE", "2sin")}


def _cas():
    with open(CAS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _appel(question, session, profil="residentiel"):
    corps = json.dumps({"workflow": "juridique",
                        "params": {"question": question},
                        "session": session, "profil": profil}).encode()
    req = u.Request(RELAY, data=corps,
                    headers={"Content-Type": "application/json",
                             "X-Exec-Token": EXEC_TOKEN})
    t0 = time.time()
    try:
        rep = json.loads(u.urlopen(req, timeout=600).read().decode())
        return rep, time.time() - t0
    except Exception as e:
        return {"ok": False, "erreur": str(e)[:200]}, time.time() - t0


# Valeurs et delais : ce qui ne peut pas varier sans que l'une des deux
# reponses soit fausse.
_RE_DELAI = re.compile(r"\b(un|deux|trois|quatre|cinq|six|neuf|douze|\d+)\s+"
                       r"(jours?|semaines?|mois|ans?|annees?)\b", re.I)
_RE_MONTANT = re.compile(r"(\d[\d\s.,]*)\s*(?:€|euros?)\b", re.I)


def _faits(rep):
    """Ce que la reponse ENGAGE, distinct de la maniere dont elle le dit."""
    s = (rep.get("sortie") or {})
    intention = s.get("intention") or {}
    doc = s.get("doc") or {}
    verif = s.get("verif") or {}
    texte = str(verif.get("texte") or "")
    return {
        # NOYAU STRICT : varier ici, c'est se contredire
        "rag_statut": s.get("rag_statut"),
        # L'abstention est un FAIT du systeme, pas une tournure de phrase : la
        # chercher dans le texte echouait des que les messages changeaient
        # (six voies distinctes depuis le 19/07). Le core la signale : flux
        # arrete, ou aucun corpus servi sans acte produit.
        # ARRETER LE FLUX N'EST PAS S'ABSTENIR : la voie libre repond puis
        # s'arrete, faute d'etapes utiles ensuite. L'abstention est un REFUS de
        # repondre -- elle se lit a la raison de l'arret, pas a l'arret lui-meme.
        "abstention": ((s.get("_arret_raison") or s.get("raison")) in
                       ("hors_corpus", "hors_droits", "hors_domaine")
                       or bool(s.get("_arrete_par") in ("firewall", "abstenir"))
                       or (s.get("rag_statut") in ("hors_corpus", "hors_droits")
                           and not doc.get("chemin")
                           and s.get("_arrete_par") != "converser")),
        "acte": bool(doc.get("chemin")),
        "arrete": bool(s.get("_arrete_par") or rep.get("arrete_par")),
        # Le delai PRINCIPAL (premier enonce) engage ; les suivants developpent
        # des exceptions et peuvent varier sans qu'aucune reponse soit fausse.
        "delai_principal": (lambda m: "%s %s" % (m[0].lower(), m[1].lower())
                            if m else None)(
            (_RE_DELAI.findall(texte) or [None])[0]),
        "delais": sorted(set("%s %s" % (m[0].lower(), m[1].lower())
                             for m in _RE_DELAI.findall(texte))),
        "montants": sorted(set(re.sub(r"\s+", "", m)
                               for m in _RE_MONTANT.findall(texte))),
        # TOLERE PAR INCLUSION : une reponse moins complete n'est pas fausse
        "articles": sorted(set(re.findall(
            r"[Aa]rticle\s+((?:[LRD]\.?\s?)?[\d-]+)", texte))),
        # contexte, non comparé
        "domaine": intention.get("domaine"),
        "intention": intention.get("intention"),
        "manquants": sorted(doc.get("manquants") or []),
    }


_STRICT = ("rag_statut", "abstention", "acte", "arrete",
           "delai_principal", "montants")


def _arbitrer(liste_faits):
    # QUAND UN ACTE EST PRODUIT, C'EST LUI QUI ENGAGE. Le texte qui l'accompagne
    # est un commentaire : qu'il mentionne ou non un delai ne contredit rien, le
    # courrier etant identique au caractere pres (motif issu du gabarit).
    if all(f.get("acte") for f in liste_faits):
        for f in liste_faits:
            f["delai_principal"] = None
            f["delais"] = []
    """VARIABILITE NON FAUSSE.

    On ne cherche pas l'identite mais la NON-CONTRADICTION. Deux reponses qui
    citent l'une {15, 17} et l'autre {17} ne se contredisent pas : la seconde est
    moins complete. Deux reponses qui disent trois mois et six mois, si.

    -> "identique" | "compatible" | "CONTRADICTOIRE"
    """
    if len(liste_faits) < 2:
        return "identique", []
    ecarts = []
    ref = liste_faits[0]
    for f in liste_faits[1:]:
        for k in _STRICT:
            if f.get(k) != ref.get(k):
                ecarts.append(k)
    if ecarts:
        return "CONTRADICTOIRE", sorted(set(ecarts))
    # articles ET delais secondaires : tolerance par inclusion. Une reponse qui
    # developpe des exceptions n'en contredit pas une qui s'arrete au principe ;
    # un element ETRANGER a l'ensemble le plus large reste une faute.
    ens = [set(f.get("articles") or []) | set(f.get("delais") or [])
           for f in liste_faits]
    union, inter = set().union(*ens), set.intersection(*ens)
    if union == inter:
        return "identique", []
    plus_grand = max(ens, key=len)
    if all(e <= plus_grand for e in ens):
        return "compatible", sorted(union - inter)
    return "CONTRADICTOIRE", sorted(union - inter)



def _pertinence(cas, faits):
    """Confronte les FAITS observes a l'ATTENDU declare par le cas.

    La coherence dit si le systeme se contredit ; elle ne dit pas s'il a raison.
    Un cas parfaitement stable peut etre systematiquement faux -- c'est cette
    mesure-la qui manquait.
    -> (satisfaits, total, [manques])
    """
    att = cas.get("attendu") or {}
    ok, total, manques = 0, 0, []
    for cle, voulu in att.items():
        total += 1
        if cle == "article":
            arts = [a.replace(" ", "").replace(".", "").upper()
                    for a in (faits.get("articles") or [])]
            if str(voulu).replace(" ", "").replace(".", "").upper() in arts:
                ok += 1
            else:
                manques.append("article %s absent" % voulu)
        elif cle == "abstention":
            if bool(faits.get("abstention")) == bool(voulu):
                ok += 1
            else:
                manques.append("abstention=%s attendu %s"
                               % (faits.get("abstention"), voulu))
        elif cle == "acte_produit":
            if bool(faits.get("acte")) == bool(voulu):
                ok += 1
            else:
                manques.append("acte=%s attendu %s" % (faits.get("acte"), voulu))
        elif cle == "champs_manquants_non_vide":
            if bool(faits.get("manquants")) == bool(voulu):
                ok += 1
            else:
                manques.append("manquants=%s" % (faits.get("manquants") or []))
        elif cle in ("rag_statut", "domaine", "intention"):
            if str(faits.get(cle)) == str(voulu):
                ok += 1
            else:
                manques.append("%s=%s attendu %s" % (cle, faits.get(cle), voulu))
        else:
            total -= 1        # attendu non mesurable ici (gabarit, fondement...)
    return ok, total, manques


def lancer(serie, parallele=None):
    """Deux modes, deux objets.

    SEQUENTIEL (defaut) : mesure la JUSTESSE. Sous charge, les temps deviennent
    incomparables et le traitement par lots de vLLM peut modifier les resultats.

    PARALLELE : eprouve la CONCURRENCE et le CLOISONNEMENT. Les fuites de memoire
    entre utilisateurs ne se manifestent que sous concurrence -- le sequentiel ne
    les voit pas. vLLM annonce onze requetes simultanees au pire cas, une
    quarantaine en usage reel.
    """
    jeu = _cas()
    n = int(jeu.get("executions_par_cas", 1))
    if parallele is None:
        parallele = int(jeu.get("parallele", 0))
    print("serie '%s' - %d cas x %d executions\n" % (serie, len(jeu["cas"]), n))
    resultats = []
    if parallele:
        from concurrent.futures import ThreadPoolExecutor
        print("mode PARALLELE : %d executions simultanees\n" % parallele)

        def _un_cas(cas):
            obs, durees = [], []
            for i in range(n):
                sess = "bench-%s-%s-%d" % (serie, cas["id"], i)
                rep, dt = _appel(cas["question"], sess,
                                 profil=cas.get("profil", "residentiel"))
                obs.append(_faits(rep))
                durees.append(dt)
            verdict, ecarts = _arbitrer(obs)
            ok, tot, manques = _pertinence(cas, obs[-1])
            return {"id": cas["id"], "famille": cas["famille"],
                    "verdict": verdict, "ecarts": ecarts,
                    "pertinence": round(100.0 * ok / tot) if tot else None,
                    "manques": manques, "faits": obs[-1],
                    "duree_moy": round(sum(durees) / len(durees), 2)}

        with ThreadPoolExecutor(max_workers=parallele) as pool:
            for r in pool.map(_un_cas, jeu["cas"]):
                resultats.append(r)
                print("  %-30s %-13s %-14s %4s%% %5.1fs %s"
                      % (r["id"], r["famille"], r["verdict"],
                         r["pertinence"] if r["pertinence"] is not None else "  -",
                         r["duree_moy"],
                         ("| " + " ; ".join(r["manques"])) if r["manques"] else ""))
        _synthese(resultats, serie)
        return

    for c in jeu["cas"]:
        obs, durees = [], []
        for i in range(n):
            # SESSION PROPRE par execution : la regle de la tache vierge vaut
            # aussi pour la mesure -- aucune contamination entre cas.
            sess = "bench-%s-%s-%d" % (serie, c["id"], i)
            rep, dt = _appel(c["question"], sess,
                             profil=c.get("profil", "residentiel"))
            obs.append(_faits(rep))
            durees.append(dt)
        verdict, ecarts = _arbitrer(obs)
        _ok, _tot, _manques = _pertinence(c, obs[-1])
        _pert = round(100.0 * _ok / _tot) if _tot else None
        moy = round(sum(durees) / len(durees), 2)
        resultats.append({"id": c["id"], "famille": c["famille"],
                          "verdict": verdict, "ecarts": ecarts,
                          "pertinence": _pert, "manques": _manques,
                          "faits": obs[-1], "duree_moy": moy})
        print("  %-30s %-13s %-14s %4s%% %5.1fs %s"
              % (c["id"], c["famille"], verdict,
                 _pert if _pert is not None else "  -", moy,
                 ("| " + " ; ".join(_manques)) if _manques else ""))
    _synthese(resultats, serie)


def _synthese(resultats, serie):
    chemin = "/tmp/bench-%s.json" % serie
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump({"serie": serie, "quand": time.time(),
                   "resultats": resultats}, f, ensure_ascii=False, indent=2)
    contradictoires = [r["id"] for r in resultats if r["verdict"] == "CONTRADICTOIRE"]
    compatibles = [r["id"] for r in resultats if r["verdict"] == "compatible"]
    print("\nidentiques    : %d/%d" % (len(resultats) - len(contradictoires)
                                      - len(compatibles), len(resultats)))
    print("compatibles   : %d  (variabilite non fausse)" % len(compatibles))
    print("CONTRADICTOIRES : %d" % len(contradictoires))
    _p = [r["pertinence"] for r in resultats if r.get("pertinence") is not None]
    if _p:
        print("PERTINENCE      : %d%% (moyenne), %d cas parfaits sur %d"
              % (round(sum(_p) / len(_p)), sum(1 for x in _p if x == 100), len(_p)))
    if contradictoires:
        print("  -> " + ", ".join(contradictoires))
    print("-> %s" % chemin)


def comparer():
    import psycopg
    with psycopg.connect(**PG, connect_timeout=5) as cnx:
        with cnx.cursor() as cur:
            cur.execute("""
                SELECT modele,
                       count(*),
                       count(*) FILTER (WHERE rag_statut = 'servi'),
                       count(*) FILTER (WHERE rag_statut = 'hors_corpus'),
                       count(*) FILTER (WHERE arrete_par IS NOT NULL),
                       coalesce(sum(citations_non_conformes), 0),
                       count(*) FILTER (WHERE acte_produit),
                       round(avg(duree_ms)::numeric, 0),
                       round(avg(rag_top1)::numeric, 3)
                FROM journal_decisions
                GROUP BY modele ORDER BY 2 DESC""")
            lignes = cur.fetchall()
    print("%-34s %5s %6s %6s %7s %6s %5s %8s %6s"
          % ("modele", "n", "servi", "hors", "arrete", "cit_nc", "acte", "ms", "top1"))
    for l in lignes:
        print("%-34s %5d %6d %6d %7d %6d %5d %8s %6s"
              % (str(l[0])[:34], l[1], l[2], l[3], l[4], l[5], l[6], l[7], l[8]))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "lancer"
    if cmd == "lancer":
        _serie = sys.argv[2] if len(sys.argv) > 2 else time.strftime("%m%d-%H%M")
        _par = int(sys.argv[3]) if len(sys.argv) > 3 else None
        lancer(_serie, parallele=_par)
    elif cmd == "comparer":
        comparer()
    else:
        print(__doc__)
