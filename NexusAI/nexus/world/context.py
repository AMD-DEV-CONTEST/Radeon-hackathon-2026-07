from dataclasses import dataclass, field
import re

@dataclass(frozen=True)
class ContextEvidence:
    tokens: set[str]=field(default_factory=set)
    phrases: list[str]=field(default_factory=list)
    text: str=""

def extract_context(text:str)->ContextEvidence:
    normalized=text.lower()
    tokens=set(re.findall(r"[a-z][a-z'-]+", normalized))
    phrases=[]
    for phrase in (
    "sand dunes",
    "pine forest",
    "snow covered",
    "stone walls",
    "high rise",
    "ocean shore",
    "mountain range",
    "city streets",
    "early morning",
    "late afternoon",
    "golden hour",
    "night sky",
    "starry night",
):
            if phrase in normalized: phrases.append(phrase)
    return ContextEvidence(tokens=tokens,phrases=phrases,text=normalized)
