#!/usr/bin/env python3
"""Primitive demander_precision 2SIN - la TROISIEME issue du quadrant.
Le systeme ne repond pas toujours, et ne s'abstient pas toujours : il peut DEMANDER.
Cas d'usage : question trop pauvre pour etre decidable, et l'historique n'a pas suffi
a la densifier. Abstenir serait une FAUTE (le sujet est peut-etre au corpus) ;
repondre serait un RISQUE (on ne sait pas de quoi il s'agit).
Le core ARRETE le flux et rend la main a l'humain. Aucun appel au modele.
Contrat : fn(entree, ctx) -> {"message", "_arret": True}
"""

PISTES = {
    "baux_habitation":  "un cong\u00e9, un pr\u00e9avis, un loyer impay\u00e9, un d\u00e9p\u00f4t de garantie",
    "baux_commerciaux": "la dur\u00e9e du bail, le renouvellement, le loyer, le d\u00e9plafonnement",
    "copropriete":      "une assembl\u00e9e g\u00e9n\u00e9rale, des charges, une majorit\u00e9 de vote",
    "penal":            "une infraction, une plainte, une occupation sans droit",
}


def demander_precision(entree, ctx):
    """entree = question (str). Formule une demande de precision orientee par le domaine."""
    question = entree if isinstance(entree, str) else str(entree)
    domaine = (ctx.get("intention") or {}).get("domaine") or ""
    memo = ctx.get("contexte") or {}

    lignes = ["Votre demande est trop br\u00e8ve pour que je puisse identifier avec certitude "
              "le texte applicable."]
    if memo.get("sujet"):
        lignes.append("Le dernier sujet abord\u00e9 \u00e9tait \u00ab %s \u00bb, mais il ne suffit pas "
                      "\u00e0 trancher votre question." % memo["sujet"])
    piste = PISTES.get(domaine)
    if piste:
        lignes.append("Pouvez-vous pr\u00e9ciser s'il s'agit de : %s ?" % piste)
    else:
        lignes.append("Pouvez-vous pr\u00e9ciser le contexte (bail d'habitation, bail commercial, "
                      "copropri\u00e9t\u00e9\u2026) et l'objet exact de votre question ?")
    lignes.append("")
    lignes.append("Je pr\u00e9f\u00e8re vous demander une pr\u00e9cision plut\u00f4t que de r\u00e9pondre "
                  "\u00e0 c\u00f4t\u00e9 ou d'inventer une r\u00e9f\u00e9rence.")

    return {"message": "\n".join(lignes), "_arret": True, "motif": "demande_indecidable"}
