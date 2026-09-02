#!/usr/bin/env python3
"""Primitive servir_fichiers 2SIN - publie les livrables produits par le relay.
Chaine : docx (cote conteneur) -> PDF (LibreOffice) -> copie hote -> validation -> URL servie.
Le PDF n'est JAMAIS fabrique a la main : il derive du docx bien forme (mise en page + accents).
Contrat : fn(entree, ctx) -> {"docx": url|None, "pdf": url|None, "erreur": str|None}
"""
import os, shutil, subprocess, uuid

FILES_DIR      = os.environ.get("FILES_DIR", "/opt/2sin/files")

_SIGNATURES = {
    ".docx": [b"PK\x03\x04"], ".xlsx": [b"PK\x03\x04"], ".pptx": [b"PK\x03\x04"],
    ".odt": [b"PK\x03\x04"], ".doc": [b"\xd0\xcf\x11\xe0"], ".pdf": [b"%PDF"],
    ".csv": None,
}
_MIN_SIZE = 256


def _valid_file(path, ext):
    """Fichier livrable bien forme : taille minimale + signature (magic bytes)."""
    try:
        if os.path.getsize(path) < _MIN_SIZE:
            return False
        sigs = _SIGNATURES.get(ext, [])
        if sigs is None or not sigs:
            return True
        with open(path, "rb") as f:
            head = f.read(8)
        return any(head.startswith(s) for s in sigs)
    except Exception:
        return False


def _fetch_file(chemin, dest):
    """Copie le livrable vers la zone servie. Les fichiers sont produits DANS le
    relay : aucun rapatriement par docker cp, donc aucun socket Docker
    requis -- le relay ne pilote aucun conteneur."""
    try:
        if not os.path.isfile(chemin):
            return False
        shutil.copy(chemin, dest)
        return os.path.isfile(dest)
    except Exception:
        return False

def _publier(container_path):
    """Rapatrie + valide + publie sous /files/<uuid>/<nom>. -> chemin relatif servi ou None."""
    if not container_path:
        return None
    nom = os.path.basename(container_path)
    ext = os.path.splitext(nom)[1].lower()
    jeton = uuid.uuid4().hex
    dossier = os.path.join(FILES_DIR, jeton)
    try:
        os.makedirs(dossier, exist_ok=True)
    except Exception:
        return None
    dest = os.path.join(dossier, nom)
    if not _fetch_file(container_path, dest):
        return None
    if not _valid_file(dest, ext):
        try: os.remove(dest)
        except Exception: pass
        return None
    return "/files/" + jeton + "/" + nom


def servir_fichiers(entree, ctx):
    """entree = sortie de generer_document. Publie les fichiers DEJA produits.

    La conversion PDF est faite par generate.py dans le relay, en meme
    temps que le docx : ici on ne fait que PUBLIER.
    -> {"docx": url|None, "pdf": url|None, "md": url|None, "erreur": str|None}
    """
    vide = {"docx": None, "pdf": None, "md": None}
    if isinstance(entree, dict):
        fichiers = entree.get("fichiers") or [entree.get("chemin")]
        err_amont = entree.get("erreur")
    else:
        fichiers = [entree] if isinstance(entree, str) else []
        err_amont = None
    fichiers = [f for f in fichiers if f]
    if err_amont:
        return {**vide, "erreur": err_amont}
    if not fichiers:
        return {**vide, "erreur": "aucun document produit"}

    urls, manques = dict(vide), []
    for chemin in fichiers:
        ext = os.path.splitext(chemin)[1].lower().lstrip(".")
        url = _publier(chemin)
        if url:
            urls[ext] = url
        else:
            manques.append(os.path.basename(chemin))
    if not any(urls.values()):
        return {**vide, "erreur": "document introuvable ou mal forme : "
                                  + ", ".join(manques)}
    return {**urls,
            "erreur": ("non servi : " + ", ".join(manques)) if manques else None}
