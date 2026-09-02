#!/usr/bin/env python3
"""Planificateur souverain 2SIN.

Aucun plancher de contexte n'est impose : les modeles legers restent
eligibles, conformement a la souverainete par distribution.

Il ne fait AUCUN metier : il declenche un WORKFLOW nomme sur un relay, a l'heure
dite, et depose le resultat. L'ordre est dans le workflow, la planification ne
fait que designer quoi executer, ou, et quand.

API locale :
  GET    /planifications          liste
  POST   /planifications          depose  {nom, schedule, workflow, params,
                                           relay, profil, actif}
  DELETE /planifications/<nom>    retire
  GET    /resultats/<nom>         dernier resultat depose
"""
import json, os, threading, time, urllib.request as u
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import redis

REDIS_HOST  = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT  = int(os.environ.get("REDIS_PORT", "6379"))
PORT        = int(os.environ.get("SCHEDULER_PORT", "8788"))
EXEC_TOKEN  = os.environ.get("EXEC_TOKEN", "")
RELAY_DEF   = os.environ.get("RELAY_URL", "http://relay:8787/v1/executer")
TICK        = int(os.environ.get("SCHEDULER_TICK", "30"))
TTL_RESULT  = int(os.environ.get("SCHEDULER_TTL_RESULT", "86400"))

R = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
_K_PLAN = "plan:%s"
_K_RES  = "plan:resultat:%s"


# --------------------------------------------------------------------------
# Planification : stockee en Redis, elle survit au redemarrage du conteneur.
def lister():
    out = []
    for cle in R.scan_iter(match="plan:*"):
        if cle.startswith("plan:resultat:"):
            continue
        try:
            out.append(json.loads(R.get(cle)))
        except Exception:
            continue
    return sorted(out, key=lambda p: p.get("nom", ""))


def deposer(p):
    p.setdefault("actif", True)
    p.setdefault("params", {})
    p.setdefault("relay", RELAY_DEF)
    p.setdefault("derniere", None)
    R.set(_K_PLAN % p["nom"], json.dumps(p, ensure_ascii=False))
    return p


def retirer(nom):
    return bool(R.delete(_K_PLAN % nom))


# --------------------------------------------------------------------------
# Echeance : expression cron a cinq champs (min heure jour mois jour_semaine).
def _champ_ok(expr, valeur):
    if expr == "*":
        return True
    for part in expr.split(","):
        if part.startswith("*/"):
            pas = int(part[2:])
            if pas and valeur % pas == 0:
                return True
        elif "-" in part:
            a, b = part.split("-", 1)
            if int(a) <= valeur <= int(b):
                return True
        elif part.isdigit() and int(part) == valeur:
            return True
    return False


def echu(expr, maintenant):
    champs = (expr or "").split()
    if len(champs) != 5:
        return False
    jsem = maintenant.weekday() + 1          # lundi = 1 … dimanche = 7
    return all([
        _champ_ok(champs[0], maintenant.minute),
        _champ_ok(champs[1], maintenant.hour),
        _champ_ok(champs[2], maintenant.day),
        _champ_ok(champs[3], maintenant.month),
        _champ_ok(champs[4], jsem % 7),      # dimanche accepte en 0
    ])


# --------------------------------------------------------------------------
def declencher(p):
    """Appelle le relay designe. Le resultat est DEPOSE, jamais livre : le
    transport (Discord, courriel) est un chemin distinct, avec ses propres
    exigences."""
    corps = json.dumps({"workflow": p.get("workflow"),
                        "params": p.get("params") or {},
                        "session": "plan-" + p.get("nom", "?"),
                        "profil": p.get("profil")}, ensure_ascii=False).encode()
    req = u.Request(p.get("relay") or RELAY_DEF, data=corps,
                    headers={"Content-Type": "application/json",
                             "X-Exec-Token": EXEC_TOKEN})
    try:
        rep = json.loads(u.urlopen(req, timeout=300).read().decode())
        res = {"ok": bool(rep.get("ok")), "sortie": rep.get("sortie"),
               "erreur": rep.get("erreur")}
    except Exception as e:
        res = {"ok": False, "sortie": None, "erreur": str(e)[:250]}
    res["quand"] = datetime.now().isoformat(timespec="seconds")
    R.set(_K_RES % p["nom"], json.dumps(res, ensure_ascii=False), ex=TTL_RESULT)
    p["derniere"] = res["quand"]
    R.set(_K_PLAN % p["nom"], json.dumps(p, ensure_ascii=False))
    print("[plan] %s -> %s" % (p["nom"], "ok" if res["ok"] else res["erreur"]),
          flush=True)


def boucle():
    """Un reveil par minute suffit : la granularite d'un cron est la minute."""
    vu = set()
    while True:
        maintenant = datetime.now()
        marque = maintenant.strftime("%Y-%m-%dT%H:%M")
        for p in lister():
            if not p.get("actif") or not p.get("workflow"):
                continue
            if (p["nom"], marque) in vu:
                continue
            if echu((p.get("schedule") or ""), maintenant):
                vu.add((p["nom"], marque))
                declencher(p)
        if len(vu) > 500:
            vu = set()
        time.sleep(TICK)


# --------------------------------------------------------------------------
class API(BaseHTTPRequestHandler):
    def _rep(self, code, obj):
        corps = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def log_message(self, *a):
        pass

    def do_GET(self):
        chemin = self.path.split("?")[0].rstrip("/")
        if chemin == "/planifications":
            return self._rep(200, {"planifications": lister()})
        if chemin.startswith("/resultats/"):
            brut = R.get(_K_RES % chemin.rsplit("/", 1)[-1])
            return self._rep(200 if brut else 404,
                             json.loads(brut) if brut else {"erreur": "aucun resultat"})
        if chemin == "/sante":
            return self._rep(200, {"ok": True, "planifications": len(lister())})
        self._rep(404, {"erreur": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/planifications":
            return self._rep(404, {"erreur": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            p = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._rep(400, {"erreur": "JSON invalide"})
        manque = [k for k in ("nom", "schedule", "workflow") if not p.get(k)]
        if manque:
            return self._rep(400, {"erreur": "champs requis : " + ", ".join(manque)})
        self._rep(200, {"ok": True, "planification": deposer(p)})

    def do_DELETE(self):
        chemin = self.path.rstrip("/")
        if not chemin.startswith("/planifications/"):
            return self._rep(404, {"erreur": "not found"})
        nom = chemin.rsplit("/", 1)[-1]
        self._rep(200, {"ok": retirer(nom), "nom": nom})


if __name__ == "__main__":
    threading.Thread(target=boucle, daemon=True).start()
    print("[plan] planificateur 2SIN sur :%d -> %s" % (PORT, RELAY_DEF), flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), API).serve_forever()
