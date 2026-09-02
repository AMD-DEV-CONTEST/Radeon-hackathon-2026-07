#!/usr/bin/env python3
"""Routines d'installation 2SIN — LE CONTRAT (version Python).
Fonctions pures, non-destructives, idempotentes, appelables par argument
depuis le main (install/check/ingest). Specification reimplementee en Go.
"""
import os
import shutil
import subprocess

BASE_DATA_DEFAULT = "/data/2sin"
VOLUMES = ["qdrant", "redis", "tei-cache", "vllm-cache"]
INGESTS = [
    ("decoupe_socle.py",       "decoupe du socle en blocs"),
    ("ingest_socle_qdrant.py", "socle -> Qdrant"),
    ("ingest_soul.py",         "fragments -> Qdrant"),
    ("ingest_corpus.py",       "corpus juridique -> Qdrant"),
]


def _log(msg):
    print("[install] " + msg)


def link_volumes(repo_root, base_data=BASE_DATA_DEFAULT):
    """Etablit ./volumes/<X> : symlink si data existe, mkdir sinon. Idempotent."""
    vol_root = os.path.join(repo_root, "volumes")
    os.makedirs(vol_root, exist_ok=True)
    res = {}
    for v in VOLUMES:
        cible = os.path.join(vol_root, v)
        source = os.path.join(base_data, v)
        if os.path.exists(cible) or os.path.islink(cible):
            res[v] = "exists"; _log("volume " + v + " : deja present")
        elif os.path.isdir(source):
            os.symlink(source, cible); res[v] = "link"
            _log("volume " + v + " : lien -> " + source)
        else:
            os.makedirs(cible, exist_ok=True); res[v] = "created"
            _log("volume " + v + " : cree vierge")
    return res


def setup_secret(repo_root, token=None):
    """Cree secrets/openlegi.env si absent. Source: arg > env > drop-in systemd."""
    sec_dir = os.path.join(repo_root, "secrets")
    os.makedirs(sec_dir, exist_ok=True)
    cible = os.path.join(sec_dir, "openlegi.env")
    if os.path.exists(cible):
        _log("secret : deja present"); return "exists"
    tok = token or os.environ.get("OPENLEGI_TOKEN", "")
    if not tok:
        dropin = "/etc/systemd/system/2sin-relay.service.d/openlegi.conf"
        if os.path.exists(dropin):
            try:
                for l in open(dropin, encoding="utf-8"):
                    if "OPENLEGI_TOKEN=" in l:
                        tok = l.split("OPENLEGI_TOKEN=", 1)[1].strip().strip(chr(34)); break
            except Exception:
                pass
    if not tok:
        _log("secret : AUCUN token trouve, creez secrets/openlegi.env"); return "missing"
    with open(cible, "w", encoding="utf-8") as f:
        f.write("OPENLEGI_TOKEN=" + tok + chr(10))
    os.chmod(cible, 0o600)
    _log("secret : cree (chmod 600)"); return "created"


def setup_env(repo_root):
    """Copie .env.example -> .env si absent. Non-destructif."""
    ex = os.path.join(repo_root, ".env.example")
    ci = os.path.join(repo_root, ".env")
    if os.path.exists(ci):
        _log(".env : deja present"); return "exists"
    if not os.path.exists(ex):
        _log(".env.example introuvable"); return "missing"
    shutil.copy(ex, ci); _log(".env : cree"); return "created"


def check_prereqs(repo_root, base_data=BASE_DATA_DEFAULT):
    """Verifie docker, compose, volumes, GPU. Lecture seule."""
    ok = True
    def _c(cmd):
        try:
            subprocess.run(cmd, capture_output=True, timeout=10, check=False); return True
        except Exception:
            return False
    _log("docker : " + ("present" if _c(["docker","--version"]) else "ABSENT"))
    if not _c(["docker","--version"]): ok = False
    _log("compose : " + ("present" if _c(["docker","compose","version"]) else "ABSENT"))
    if not _c(["docker","compose","version"]): ok = False
    vol_root = os.path.join(repo_root, "volumes")
    for v in VOLUMES:
        c = os.path.join(vol_root, v)
        if os.path.islink(c): _log("volume " + v + " : lien -> " + os.readlink(c))
        elif os.path.isdir(c): _log("volume " + v + " : dossier local")
        else: _log("volume " + v + " : absent")
    _log("GPU AMD : " + ("present" if os.path.exists("/dev/kfd") else "absent (mode API)"))
    _log("prerequis : " + ("OK" if ok else "INCOMPLETS"))
    return ok


def ingest(repo_root):
    """Execute les ingests dans l'ordre. Peuple Qdrant. Apres services healthy."""
    ing = os.path.join(repo_root, "ingest")
    for script, desc in INGESTS:
        p = os.path.join(ing, script)
        if not os.path.exists(p):
            _log("ingest : " + script + " introuvable"); continue
        _log("ingest : " + desc)
        r = subprocess.run(["python3", p], capture_output=True, text=True)
        if r.returncode == 0:
            _log("  OK " + r.stdout.strip()[:80])
        else:
            _log("  ECHEC : " + r.stderr.strip()[:120]); return False
    _log("ingest : termine"); return True


def install(repo_root, base_data=BASE_DATA_DEFAULT, token=None):
    """Orchestration : liens volumes + secret + config. Ne lance pas les conteneurs."""
    _log("=== INSTALLATION 2SIN ===")
    vols = link_volumes(repo_root, base_data)
    sec = setup_secret(repo_root, token)
    env = setup_env(repo_root)
    _log("=== RESUME ===")
    _log("volumes : " + str(vols))
    _log("secret  : " + sec)
    _log("env     : " + env)
    _log("Suivant : docker compose up -d, puis <main> ingest")
    return {"volumes": vols, "secret": sec, "env": env}


def repo_root_default():
    env = os.environ.get("REPO_ROOT")
    if env:
        return env
    ici = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(ici))
