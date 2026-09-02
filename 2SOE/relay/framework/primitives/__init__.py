"""Registre des primitives 2SIN : nom -> fonction. Import decouple."""
from .moderation import moderer
from .memoire import repondre_rappel, rappeler_contexte, memoriser
from .mesurer import mesurer_intention
from .source import rechercher_source
from .corpus import rechercher_corpus
from .clarifier import demander_precision
from .llm import appeler_llm
from .verifier import verifier_citations
from .document import generer_document
from .gabarit import selectionner_gabarit, extraire_variables, assembler_motif
from .tache import (situer_tache, appliquer_tache, ouvrir_tache,
                    rattacher, lire_tache, fermer_tache)
from .journal import journaliser
from .abstenir import abstenir
from .converser import converser
from .fichiers import servir_fichiers
from .skill import executer_skill
from .routeur import router_skill
from .svo import amplifier_svo

REGISTRE = {
    "moderer": moderer,
    "rappeler_contexte": rappeler_contexte,
    "memoriser": memoriser,
    "mesurer_intention": mesurer_intention,
    "rechercher_source": rechercher_source,
    "rechercher_corpus": rechercher_corpus,
    "demander_precision": demander_precision,
    "appeler_llm": appeler_llm,
    "verifier_citations": verifier_citations,
    "generer_document": generer_document,
    "selectionner_gabarit": selectionner_gabarit,
    "extraire_variables": extraire_variables,
    "assembler_motif": assembler_motif,
    "situer_tache": situer_tache,
    "appliquer_tache": appliquer_tache,
    "journaliser": journaliser,
    "repondre_rappel": repondre_rappel,
    "abstenir": abstenir,
    "converser": converser,
    "servir_fichiers": servir_fichiers,
    "executer_skill": executer_skill,
    "router_skill": router_skill,
    "amplifier_svo": amplifier_svo,
}
