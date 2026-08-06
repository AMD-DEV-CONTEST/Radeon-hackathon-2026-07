import re
from nexus.extraction.models import CandidateEntity, CandidateRelationship, ExtractionResult

PATTERNS = [
    (
        r"(?P<a>[A-Z][A-Za-z. ]*?) lives in (?P<b>[A-Z][A-Za-z ]*?)(?=[.,]|$)",
        "person",
        "place",
        "LIVES_IN",
    ),
    (
        r"(?P<a>[A-Z][A-Za-z. ]*?) works with (?:a [A-Za-z ]+ named )?(?P<b>[A-Z][A-Za-z. ]*?)(?=[.,]|$)",
        "person",
        "person",
        "WORKS_WITH",
    ),
    (
        r"(?P<a>[A-Z][A-Za-z. ]*?) visited (?:the )?(?P<b>[A-Z][A-Za-z ]*?)(?: in [A-Z][A-Za-z ]+)?(?=[.,]|$)",
        "person",
        "place",
        "VISITED",
    ),
    (
        r"(?P<a>[A-Z][A-Za-z. ]*?) maintains (?:the )?(?P<b>[A-Z][A-Za-z]+)(?: backend| project)?(?=[.,]|$)",
        "person",
        "project",
        "MAINTAINS",
    ),
    (
        r"(?P<a>[A-Z][A-Za-z. ]*?) advises (?:the )?(?P<b>[A-Z][A-Za-z]+)(?: project)?(?=[.,]|$)",
        "person",
        "project",
        "ADVISES",
    ),
    (
        r"(?P<a>[A-Z][A-Za-z ]*?) is located in (?P<b>[A-Z][A-Za-z ]*?)(?=[.,]|$)",
        "place",
        "place",
        "LOCATED_IN",
    ),
    (
        r"(?P<a>[A-Z][A-Za-z]+) is connected to (?P<b>[A-Z][A-Za-z]+)(?=[.,]|$)",
        "system",
        "project",
        "CONNECTED_TO",
    ),
]
def clean_name(value: str) -> str:
    return " ".join(value.strip().split()).removeprefix("Dr. ").strip()

def extract(text: str) -> ExtractionResult:
    result = ExtractionResult()

    entities: dict[str, CandidateEntity] = {}
    seen_relationships = set()

    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", text)
        if sentence.strip()
    ]

    for sentence in sentences:
        for pattern, source_type, target_type, relation_type in PATTERNS:
            for match in re.finditer(pattern, sentence):

                source = clean_name(match.group("a"))
                target = clean_name(match.group("b"))

                if not source or not target:
                    continue

                entities.setdefault(
                    source.lower(),
                    CandidateEntity(source, source_type),
                )

                entities.setdefault(
                    target.lower(),
                    CandidateEntity(target, target_type),
                )

                key = (
                    source.lower(),
                    target.lower(),
                    relation_type,
                )

                if key not in seen_relationships:
                    result.relationships.append(
                        CandidateRelationship(
                            source,
                            target,
                            relation_type,
                        )
                    )

                    seen_relationships.add(key)

    known = {
        "NexusAI": "project",
        "MemoryWeaver": "system",
        "WorldForge": "system",
        "Aurora": "system",
        "Nexus Research Lab": "place",
        "Kochi": "place",
        "Bengaluru": "place",
    }

    for name, entity_type in known.items():
        if name in text:
            entities.setdefault(
                name.lower(),
                CandidateEntity(name, entity_type),
            )

    result.entities = list(entities.values())

    result.observations = sentences

    return result