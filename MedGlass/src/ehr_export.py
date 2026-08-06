"""Export saved notes for download or direct EHR import.

Formats
-------
* ``txt``   - plain-text patient note
* ``md``    - markdown patient note with metadata header
* ``json``  - the full MedGlass record
* ``fhir``  - HL7 FHIR R4 Bundle containing a ``Composition``
              (LOINC 28633-4 "Physician encounter Note") with SOAP sections
* ``ccda``  - minimal Consolidated CDA XML (document body with SOAP sections)

The FHIR export is a standard, importable document for most modern EHRs
(Epic, Cerner, etc. accept a FHIR ``Composition``/``Bundle``); the CDA export
is provided for the classic XDS / CCDA route.
"""

from __future__ import annotations

import html
from datetime import datetime
from urllib.parse import quote

LOINC_SOAP = {
    "S": {"code": "10164-2", "display": "History of present illness"},
    "O": {"code": "8716-3", "display": "Vital signs"},
    "A": {"code": "11450-4", "display": "Problem list - Reported"},
    "P": {"code": "18776-5", "display": "Plan of care"},
}

SECTION_TITLES = {"S": "Subjective", "O": "Objective", "A": "Assessment",
                  "P": "Plan"}


def _fmt_date(iso: str) -> str:
    """'2026-08-04T16:07:29+00:00' -> '2026-08-04 16:07:29 UTC'."""
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d %H:%M:%S %Z") if dt.tzinfo else iso
    except ValueError:
        return iso


def _escape_xml(text: str) -> str:
    return (html.escape(text or "")
            .replace('"', "&quot;").replace("'", "&apos;"))


# ---------------------------------------------------------------------------
# Text / Markdown / JSON
# ---------------------------------------------------------------------------

def to_text(record: dict) -> str:
    return record.get("note", "")


def to_markdown(record: dict) -> str:
    lines = [
        "# MedGlass Patient Note",
        "",
        f"- **ID**: {record['id']}",
        f"- **Created**: {_fmt_date(record['created_at'])}",
        f"- **Source**: {record.get('source', 'api')}",
        f"- **Session**: {record.get('session_id', '')}",
    ]
    if record.get("patient_id"):
        lines.append(f"- **Patient**: {record['patient_id']}")
    if record.get("provider"):
        lines.append(f"- **Provider**: {record['provider']}")
    sections = record.get("sections") or {}
    if sections:
        lines.append("")
        lines.append("## Sections")
        lines.append("")
        for key, title in SECTION_TITLES.items():
            if sections.get(key):
                lines.append(f"### {title}")
                lines.append("")
                lines.append(sections[key])
                lines.append("")
    lines.append("---")
    lines.append("## Full note")
    lines.append("")
    lines.append(record.get("note", ""))
    if record.get("photos"):
        lines.append("")
        lines.append("## Photos")
        lines.append("")
        for photo in record["photos"]:
            lines.append(f"- [{photo.get('id', 'photo')}]({photo.get('original', '')})")
    if record.get("transcript"):
        lines.append("")
        lines.append("## Transcript (source)")
        lines.append("")
        lines.append(record["transcript"])
    return "\n".join(lines)


def to_json(record: dict) -> dict:
    return dict(record)


# ---------------------------------------------------------------------------
# HL7 FHIR R4
# ---------------------------------------------------------------------------

def _text_to_div(text: str) -> str:
    """XHTML narrative for a FHIR Narrative / CDA text node."""
    return "<div xmlns=\"http://www.w3.org/1999/xhtml\"><p>{}</p></div>".format(
        _escape_xml(text).replace("\n", "<br/>"))


def to_fhir_bundle(record: dict) -> dict:
    """Build a FHIR R4 Bundle with one Composition (SOAP note)."""
    now = datetime.now().isoformat()
    sections = record.get("sections") or {}
    note_id = record["id"]
    created = record["created_at"]
    source = record.get("source", "api")

    section_resources = []
    for key in ("S", "O", "A", "P"):
        body = sections.get(key)
        if not body:
            continue
        coding = LOINC_SOAP.get(key, {"code": "55109-3", "display": "Summary"})
        section_resources.append({
            "title": SECTION_TITLES.get(key, key),
            "code": {
                "coding": [{
                    "system": "http://loinc.org",
                    "code": coding["code"],
                    "display": coding["display"],
                }],
            },
            "text": {
                "status": "generated",
                "div": _text_to_div(body),
            },
        })

    composition = {
        "resourceType": "Composition",
        "id": note_id,
        "status": "final",
        "type": {
            "coding": [{
                "system": "http://loinc.org",
                "code": "28633-4",
                "display": "Physician encounter Note",
            }],
            "text": "SOAP Note",
        },
        "subject": {
            "reference": record.get("patient_id")
            and f"Patient/{record['patient_id']}" or "Patient/unknown",
        },
        "date": created or now,
        "author": [{
            "reference": record.get("provider")
            and f"Practitioner/{record['provider']}" or "Practitioner/medglass",
            "display": record.get("provider") or "MedGlass Ambient Scribe",
        }],
        "title": f"MedGlass SOAP Note ({_fmt_date(created)})",
        "attester": [{
            "mode": "professional",
            "time": created or now,
        }],
        "section": section_resources,
    }

    bundle = {
        "resourceType": "Bundle",
        "id": note_id,
        "type": "collection",
        "identifier": {
            "system": "urn:uuid:medglass",
            "value": note_id,
        },
        "timestamp": now,
        "meta": {
            "profile": [
                "http://hl7.org/fhir/uv/ecr/StructureDefinition/eCR-Bundle",
            ],
            "source": f"https://medglass.local/{quote(note_id)}",
        },
        "entry": [{
            "fullUrl": f"urn:uuid:{note_id}",
            "resource": composition,
        }],
    }
    if record.get("transcript"):
        bundle["entry"].append({
            "resource": {
                "resourceType": "DocumentReference",
                "id": f"{note_id}-src",
                "status": "current",
                "type": {
                    "coding": [{
                        "system": "http://loinc.org",
                        "code": "34816-5",
                        "display": "History of present illness",
                    }],
                },
                "date": created or now,
                "content": [{
                    "attachment": {
                        "contentType": "text/plain",
                        "data": __import__("base64").b64encode(
                            record["transcript"].encode("utf-8")).decode(),
                    },
                }],
            },
        })
    # Clinical photos captured during the encounter.
    for photo in record.get("photos") or []:
        pid = photo.get("id", "")
        if not pid:
            continue
        image_b64 = _photo_b64(f"{pid}.jpg")
        if not image_b64:
            continue
        bundle["entry"].append({
            "resource": {
                "resourceType": "DocumentReference",
                "id": f"{note_id}-photo-{pid[:8]}",
                "status": "current",
                "type": {
                    "coding": [{
                        "system": "http://loinc.org",
                        "code": "72170-4",
                        "display": "Clinical photograph",
                    }],
                    "text": "Clinical photograph",
                },
                "date": created or now,
                "content": [{
                    "attachment": {
                        "contentType": "image/jpeg",
                        "data": image_b64,
                        "title": "Clinical photograph",
                    },
                }],
            },
        })
    return bundle


def _photo_b64(filename: str) -> str | None:
    """Read an image from output/photos and base64-encode it for FHIR."""
    import base64
    from pathlib import Path
    path = Path("output") / "photos" / Path(filename).name
    if not path.exists():
        return None
    return base64.b64encode(path.read_bytes()).decode("ascii")


# ---------------------------------------------------------------------------
# Consolidated CDA
# ---------------------------------------------------------------------------

def to_ccda(record: dict) -> str:
    """Minimal CDA (CCD) XML carrying the SOAP note in the document body."""
    created = _fmt_date(record["created_at"])
    sections = record.get("sections") or {}

    body = []
    for key in ("S", "O", "A", "P"):
        text = sections.get(key)
        if not text:
            continue
        coding = LOINC_SOAP.get(key, {"code": "55109-3", "display": "Summary"})
        body.append(f"""
    <component>
      <section>
        <templateId root="2.16.840.1.113883.10.20.22.2.1.1"/>
        <code code="{coding['code']}" codeSystem="2.16.840.1.113883.6.1"
              codeSystemName="LOINC" displayName="{_escape_xml(coding['display'])}"/>
        <title>{_escape_xml(SECTION_TITLES.get(key, key))}</title>
        <text>{_escape_xml(text)}</text>
      </section>
    </component>""")

    full_note = record.get("note", "")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ClinicalDocument xmlns="urn:hl7-org:v3">
  <typeId root="2.16.840.1.113883.1.3" extension="POCD_HD000040"/>
  <templateId root="2.16.840.1.113883.10.20.22.1.2"/>
  <id root="urn:uuid:medglass" extension="{_escape_xml(record['id'])}"/>
  <code code="34117-2" codeSystem="2.16.840.1.113883.6.1"
        codeSystemName="LOINC" displayName="Patient encounter Note"/>
  <title>MedGlass SOAP Note ({_escape_xml(created)})</title>
  <effectiveTime value="{record['created_at']}"/>
  <confidentialityCode code="N" codeSystem="2.16.840.1.113883.5.25"/>
  <languageCode code="en-US"/>
  <recordTarget>
    <patientRole>
      <id extension="{_escape_xml(record.get('patient_id') or 'unknown')}"/>
    </patientRole>
  </recordTarget>
  <author><time value="{record['created_at']}"/>
    <assignedAuthor>
      <id extension="medglass"/>
      <assignedPerson><name>MedGlass Ambient Scribe</name></assignedPerson>
    </assignedAuthor>
  </author>
  <custodian><assignedCustodian><representedCustodianOrganization>
    <id root="urn:uuid:medglass"/>
    <name>MedGlass</name>
  </representedCustodianOrganization></assignedCustodian></custodian>
  <documentationOf>
    <serviceEvent classCode="PCPR">
      <effectiveTime><low value="{record['created_at']}"/></effectiveTime>
    </serviceEvent>
  </documentationOf>
  <component>
    <structuredBody>{''.join(body)}
      <component>
        <section>
          <templateId root="2.16.840.1.113883.10.20.22.2.5.1"/>
          <code code="34816-5" codeSystem="2.16.840.1.113883.6.1"
                codeSystemName="LOINC" displayName="History of present illness"/>
          <title>Full Note</title>
          <text>{_escape_xml(full_note)}</text>
        </section>
      </component>
    </structuredBody>
  </component>
</ClinicalDocument>
"""


FORMATTERS = {
    "txt": ("text/plain", to_text),
    "md": ("text/markdown", to_markdown),
    "json": ("application/json", to_json),
    "fhir": ("application/fhir+json", to_fhir_bundle),
    "ccda": ("application/xml", to_ccda),
}

EXTENSIONS = {"txt": "txt", "md": "md", "json": "json", "fhir": "json",
              "ccda": "xml"}


def export(record: dict, fmt: str):
    """Return (media_type, filename, content) for a download."""
    fmt = (fmt or "md").lower()
    if fmt not in FORMATTERS:
        raise KeyError(fmt)
    media_type, formatter = FORMATTERS[fmt]
    content = formatter(record)
    if not isinstance(content, str):
        content = __import__("json").dumps(content, indent=2)
    filename = (f"medglass-note-{record['id']}-"
                f"{record['created_at'][:10]}.{EXTENSIONS[fmt]}")
    return media_type, filename, content
