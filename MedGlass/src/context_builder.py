"""Prompt construction and PHI sanitization for the SOAP-note LLM."""

from __future__ import annotations

import re

from config import CONFIG

SYSTEM_PROMPT = """You are MedGlass, a clinical documentation assistant. You receive a transcript of a doctor-patient conversation and optional visual findings. Your task is to generate a structured Patient Note (SOAP format).

**Subjective (S):** The patient's reported symptoms, history, and concerns, in their own words where possible. Include the patient's stated name in the S section.
**Objective (O):** Measurable findings — vital signs, physical exam observations, visual findings (from camera), lab results mentioned.
**Assessment (A):** The clinician's diagnosis, differential, or clinical impression.
**Plan (P):** Treatment plan, prescriptions, follow-up instructions, referrals.

Rules:
- Use standard medical abbreviations where appropriate.
- Mark uncertain or missing information with "[ ]" brackets.
- Do NOT fabricate information not present in the transcript.
- Keep the note concise and clinically useful.
- Format each section clearly with headers.
"""

FEW_SHOT_EXAMPLE = """Transcript:
Doctor: "Hi Sarah, what brings you in today?"
Patient: "I've had this sore throat for about 4 days now. It hurts to swallow. Also feeling a bit feverish."
Doctor: "Any cough or runny nose?"
Patient: "A little cough, no runny nose."
Doctor: "Let me check your throat. Say 'ahh'... I see some redness and swelling. No white patches."
Doctor: "Temperature is 100.2. I think it's likely viral pharyngitis. I'll recommend rest, fluids, and ibuprofen for pain. If it doesn't improve in 3 days, come back."
Visual: No medication labels detected.

Patient Note:
S: Patient reports sore throat x 4 days, odynophagia, subjective fever, mild cough. Denies rhinorrhea.
O: Vitals: Temp 100.2F. Pharynx: erythema and edema, no exudates. Visual: no medications detected.
A: Viral pharyngitis.
P: Supportive care — rest, hydration, ibuprofen prn pain. Return to clinic if no improvement in 3 days."""

# Names, dates, phone numbers, SSNs, MRNs, ages, address-like strings.
_PHI_PATTERNS = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),                      # SSN
    re.compile(r"\b\d{3}\)?[ -.]\d{3}[ -.]\d{4}\b"),          # phone
    re.compile(r"\b\d{1,3} [A-Z][A-Za-z]+ (St|Ave|Rd|Blvd|Dr|Ln|Ct|Way|Pkwy|Cir|Pl|Ter)\b"),
    re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b"),
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"),               # birthdate (MM/DD/YYYY)
    re.compile(r"\bMRN\s*[:#]?\s*\d{4,}\b", re.IGNORECASE),
    re.compile(r"\bDOB\s*[:#]?\s*\d{1,2}/\d{1,2}/\d{2,4}\b", re.IGNORECASE),
    re.compile(r"\b\d{1,3}[- ](?:year|yr|yo|mo|month)[- ]?(?:old)?\b", re.IGNORECASE),  # age
    re.compile(r"\b\d{5}(?:-\d{4})?\b"),                      # ZIP code
    re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"),               # email
    re.compile(r"\b(?:ACCT|CHART|PATIENT|PAT)\s*[:#]?\s*\d{4,}\b", re.IGNORECASE),  # chart IDs
]

# Heuristic first/last name detector: "Dr. Smith" or "Dr Smith".
_DOCTOR_TITLE = re.compile(r"\b(?:Dr|Doctor|Nurse|NP|PA)\s*[.]?\s*([A-Z][a-zA-Z]+)\b")


def sanitize_phi(text: str) -> str:
    """Replace likely PHI tokens with redaction markers.

    This is deliberately conservative: it is a privacy helper, NOT a
    substitute for clinician review. Run it before any local storage.
    """
    if not text:
        return text
    for pattern in _PHI_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    text = _DOCTOR_TITLE.sub(r"\1 [REDACTED]", text)
    return text


def _format_visual(visual_findings: list[dict] | None) -> str:
    if not visual_findings:
        return "Visual: No photos or detections captured."
    lines = []
    for v in visual_findings:
        kind = v.get("kind", "observation")
        detail = v.get("detail", "")
        lines.append(f"- {kind}: {detail}")
    return "Visual findings:\n" + "\n".join(lines)

def build_prompt(transcript: str,
                 visual_findings: list[dict] | None = None,
                 patient_name: str | None = None) -> str:
    """Assemble system prompt + few-shot + transcript + visual context.

    ``patient_name`` (authoritative, e.g. from the EMR / session) is injected as
    a directive so the model uses it verbatim instead of hallucinating a name
    from an ASR transcription that mis-transcribed the proper noun.
    """
    transcript = transcript.strip()
    visual = _format_visual(visual_findings)
    name_block = (f"\nPatient name: {patient_name}\n\n"
                  if patient_name else "")
    return (
        SYSTEM_PROMPT
        + name_block
        + "\n---\n"
        + FEW_SHOT_EXAMPLE
        + "\n---\n"
        + "Transcript:\n"
        + transcript
        + "\n\n"
        + visual
        + "\n\n"
        + "Patient Note:\n"
    )


def build_chat_messages(transcript: str,
                        visual_findings: list[dict] | None = None,
                        patient_name: str | None = None) -> list[dict]:
    """Same content as build_prompt but as OpenAI-style chat messages.

    Useful for llama.cpp --jinja or a server backend.
    """
    name_block = (f"\nPatient name: {patient_name}\n" if patient_name else "")
    user_content = (
        "Transcript:\n" + transcript.strip() + name_block + "\n\n"
        + _format_visual(visual_findings)
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT + "\n" + FEW_SHOT_EXAMPLE},
        {"role": "user", "content": user_content},
    ]
