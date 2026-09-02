#!/usr/bin/env python3
"""Lanceur du banc 2SIN — paramètres explicites, sortie rangée, comparaison.

Le banc écrit dans /tmp/bench-<serie>.json (chemin codé en dur). /tmp ne survit
ni à un redémarrage, ni à la destruction d'une instance. Ce lanceur exécute le
banc, RAPATRIE le JSON dans un dossier durable, et compare au run précédent.

Usage :
    run_bench.py seq                        séquentiel, nom horodaté
    run_bench.py mul 6                      6 exécutions simultanées
    run_bench.py seq --nom avant-patch      nom explicite
    run_bench.py seq --sortie ~/mesures     dossier de destination
    run_bench.py seq --repeter 3            trois runs d'affilée
    run_bench.py --lister                   les runs déjà enregistrés
    run_bench.py --comparer a.json b.json   deux runs, cas par cas

Sortie : 0 si la justesse est à 100 %, 1 sinon.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

_ICI = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.join(_ICI, "benchmark.py")
SORTIE_DEFAUT = os.environ.get(
    "BENCH_SORTIE", os.path.join(os.path.expanduser("~"), "mesures-2sin"))


def _verifier_env():
    manque = []
    if not os.environ.get("EXEC_TOKEN"):
        manque.append("EXEC_TOKEN")
    if manque:
        print("⚠ variable(s) absente(s) : %s" % ", ".join(manque))
        print("  export EXEC_TOKEN=$(grep '^EXEC_TOKEN=' .env | cut -d= -f2)")
        return False
    return True


def _charger(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _resume(d):
    res = d.get("resultats") or []
    p = [r.get("pertinence") for r in res if r.get("pertinence") is not None]
    return {
        "cas": len(res),
        "identiques": sum(1 for r in res if r.get("verdict") == "identique"),
        "compatibles": sum(1 for r in res if r.get("verdict") == "compatible"),
        "contradictoires": sum(1 for r in res if r.get("verdict") == "CONTRADICTOIRE"),
        "justesse": round(sum(p) / len(p)) if p else None,
        "parfaits": sum(1 for x in p if x == 100),
    }


def lancer(mode, simultanees, nom, dossier, repeter):
    if not _verifier_env():
        return 1

    os.makedirs(dossier, exist_ok=True)
    par = 0 if mode == "seq" else simultanees
    codes = []

    for n in range(1, repeter + 1):
        serie = nom if repeter == 1 else "%s-%d" % (nom, n)
        suffixe = "seq" if par == 0 else "par%d" % par
        horod = time.strftime("%Y%m%d-%H%M%S")
        final = os.path.join(dossier, "%s_%s_%s.json" % (horod, suffixe, serie))
        log = final[:-5] + ".log"

        print("=" * 70)
        print("  run %d/%d — %s — série « %s »"
              % (n, repeter, "séquentiel" if par == 0 else "%d simultanées" % par,
                 serie))
        print("=" * 70)

        t0 = time.time()
        cmd = [sys.executable, "-u", BENCH, "lancer", serie, str(par)]
        with open(log, "w", encoding="utf-8") as fl:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True)
            for ligne in proc.stdout:
                sys.stdout.write(ligne)
                fl.write(ligne)
            proc.wait()
        duree = time.time() - t0

        src = "/tmp/bench-%s.json" % serie
        if not os.path.isfile(src):
            print("\n❌ le banc n'a produit aucun JSON (%s)" % src)
            codes.append(1)
            continue

        shutil.move(src, final)
        d = _charger(final)
        d["_duree_s"] = round(duree, 1)
        d["_mode"] = "sequentiel" if par == 0 else "parallele-%d" % par
        with open(final, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)

        r = _resume(d)
        print("\n  → %s" % final)
        print("    %s  |  justesse %s%%  |  %d/%d parfaits  |  %s"
              % (d["_mode"], r["justesse"], r["parfaits"], r["cas"],
                 time.strftime("%Mm%Ss", time.gmtime(duree))))
        codes.append(0 if r["justesse"] == 100 else 1)

        precedent = _precedent(dossier, final)
        if precedent:
            print()
            comparer(precedent, final, bref=True)

    return max(codes) if codes else 1


def _precedent(dossier, courant):
    """Le run enregistré juste avant celui-ci, même dossier."""
    fichiers = sorted(f for f in os.listdir(dossier) if f.endswith(".json"))
    nom = os.path.basename(courant)
    if nom in fichiers:
        i = fichiers.index(nom)
        if i > 0:
            return os.path.join(dossier, fichiers[i - 1])
    return None


def comparer(a, b, bref=False):
    da, db = _charger(a), _charger(b)
    ra, rb = _resume(da), _resume(db)

    print("  %-46s %-16s %s"
          % ("", os.path.basename(a)[:16], os.path.basename(b)[:16]))
    for cle, lib in (("justesse", "justesse %"), ("parfaits", "cas parfaits"),
                     ("identiques", "identiques"), ("compatibles", "compatibles"),
                     ("contradictoires", "CONTRADICTOIRES")):
        va, vb = ra.get(cle), rb.get(cle)
        fleche = "  " if va == vb else ("↑ " if (vb or 0) > (va or 0) else "↓ ")
        print("  %-46s %-16s %s%s" % (lib, va, fleche, vb))

    if bref:
        return

    ia = {r["id"]: r for r in (da.get("resultats") or [])}
    ib = {r["id"]: r for r in (db.get("resultats") or [])}
    change = [k for k in sorted(set(ia) | set(ib))
              if (ia.get(k, {}).get("verdict"), ia.get(k, {}).get("pertinence"))
              != (ib.get(k, {}).get("verdict"), ib.get(k, {}).get("pertinence"))]
    if not change:
        print("\n  aucun cas n'a changé de verdict.")
        return
    print("\n  cas modifiés :")
    for k in change:
        va, vb = ia.get(k, {}), ib.get(k, {})
        print("    %-32s %-14s %3s%%   →   %-14s %3s%%"
              % (k, va.get("verdict", "—"), va.get("pertinence", "—"),
                 vb.get("verdict", "—"), vb.get("pertinence", "—")))


def lister(dossier):
    if not os.path.isdir(dossier):
        print("aucun run enregistré (%s)" % dossier)
        return 0
    fichiers = sorted(f for f in os.listdir(dossier) if f.endswith(".json"))
    if not fichiers:
        print("aucun run enregistré (%s)" % dossier)
        return 0
    print("%-42s %-14s %-9s %s" % ("fichier", "mode", "justesse", "parfaits"))
    print("-" * 78)
    for f in fichiers:
        try:
            d = _charger(os.path.join(dossier, f))
            r = _resume(d)
            print("%-42s %-14s %-9s %d/%d"
                  % (f[:42], d.get("_mode", "?"), "%s%%" % r["justesse"],
                     r["parfaits"], r["cas"]))
        except Exception:
            print("%-42s (illisible)" % f[:42])
    return 0


def main():
    p = argparse.ArgumentParser(
        description="Lanceur du banc 2SIN — sortie rangée et comparée.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Usage :")[1] if "Usage :" in __doc__ else "")
    p.add_argument("mode", nargs="?", choices=["seq", "mul"],
                   help="seq = séquentiel, mul = simultané")
    p.add_argument("simultanees", nargs="?", type=int, default=6,
                   help="nombre d'exécutions simultanées (défaut 6)")
    p.add_argument("--nom", help="nom de série (défaut : horodaté)")
    p.add_argument("--sortie", default=SORTIE_DEFAUT, help="dossier de destination")
    p.add_argument("--repeter", type=int, default=1,
                   help="enchaîner N runs (la forme varie, la justesse non)")
    p.add_argument("--lister", action="store_true")
    p.add_argument("--comparer", nargs=2, metavar=("A", "B"))
    a = p.parse_args()

    if a.lister:
        return lister(a.sortie)
    if a.comparer:
        comparer(a.comparer[0], a.comparer[1])
        return 0
    if not a.mode:
        p.print_help()
        return 1

    nom = a.nom or time.strftime("%m%d-%H%M")
    return lancer(a.mode, a.simultanees, nom, os.path.expanduser(a.sortie),
                  a.repeter)


if __name__ == "__main__":
    sys.exit(main())
