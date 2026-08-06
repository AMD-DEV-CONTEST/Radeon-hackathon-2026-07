"""Generate the demo document: a report redacted the way people actually do it.

Run once before the demo:  python demo/build_demo_pdf.py

This produces `demo/sample.pdf`, which leaks the same identity through four
independent channels so every persona has something real to find:

  1. Redaction underlay  — a black box drawn over live text (Tier M, Forensicist)
  2. Document metadata   — /Author left populated (Tier M, Forensicist)
  3. Quasi-identifiers   — role + site + start date + tenure, which intersect
                           against corpus/meridian/* to a candidate set of 1
                           (Tier C, Data-Broker / Insider / Journalist)
  4. A distinctive quote — reproduced verbatim from a public conference report
                           (Tier C, Journalist via cooccurrence_count)

The point of building the fixture in code rather than shipping a binary: the
judges can read this file and see exactly what the ground truth is, and nobody
has to trust that the demo PDF wasn't hand-tuned to make VEIL look good.
"""
from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth

HERE = Path(__file__).parent
OUT = HERE / "sample.pdf"

LEFT = 72

# The line carrying the covered name, split so the rectangle can be placed by
# measurement rather than by eye. Getting this wrong is the difference between
# recovering "Dr. Amara Osei" and recovering "Amara Osei, on 1".
COVER_BEFORE = "the Chief Executive, "
COVER_TARGET = "Dr. Amara Osei"
COVER_AFTER = ", on 14 March 2019."

BODY_1 = [
    ("Meridian Health Trust", "Helvetica-Bold", 16),
    ("Internal Review: Escalation Handling at the Exeter Site", "Helvetica-Bold", 12),
    ("RESTRICTED — prepared for release under FOI request 2024/0417", "Helvetica-Oblique", 9),
    ("", "Helvetica", 10),
    ("1. Background", "Helvetica-Bold", 11),
    ("", "Helvetica", 10),
    ("This review was commissioned following a serious incident reported at the", "Helvetica", 10),
    ("Exeter site in February 2024. The review was led by the Director of", "Helvetica", 10),
    ("Governance and Risk, who has held the post since March 2019 and is based", "Helvetica", 10),
    ("at the Bristol headquarters.", "Helvetica", 10),
    ("", "Helvetica", 10),
    ("The reviewing director was appointed from a national regulatory body, where", "Helvetica", 10),
    ("they had led inspection policy. The interview panel was chaired by", "Helvetica", 10),
]

BODY_2 = [
    ("2. Findings", "Helvetica-Bold", 11),
    ("", "Helvetica", 10),
    ("The review found that escalation thresholds were applied inconsistently", "Helvetica", 10),
    ("across the four sites. Staff at Exeter reported reluctance to escalate", "Helvetica", 10),
    ("owing to perceived workload consequences.", "Helvetica", 10),
    ("", "Helvetica", 10),
    ("The reviewing director noted, as they have publicly before, that \"if your", "Helvetica", 10),
    ("incident numbers are going down, either you have solved patient safety or", "Helvetica", 10),
    ("people have stopped telling you things.\"", "Helvetica", 10),
    ("", "Helvetica", 10),
    ("3. Declarations", "Helvetica-Bold", 11),
    ("", "Helvetica", 10),
    ("The reviewing director declared a personal connection to a member of the", "Helvetica", 10),
    ("investigating panel and recused themselves from panel selection. A separate", "Helvetica", 10),
    ("declared interest concerning an immediate family member employed by a Trust", "Helvetica", 10),
    ("supplier was recorded in 2022 and is managed by exclusion from procurement.", "Helvetica", 10),
    ("", "Helvetica", 10),
    ("4. Recommendations", "Helvetica-Bold", 11),
    ("", "Helvetica", 10),
    ("Fourteen recommendations are made, of which eleven mirror those accepted", "Helvetica", 10),
    ("following the external review reported to the Board in June 2023.", "Helvetica", 10),
]


def build() -> Path:
    c = canvas.Canvas(str(OUT), pagesize=LETTER)

    # Leak #2: the metadata nobody remembers to strip.
    c.setAuthor("J. Okafor")
    c.setTitle("Exeter Escalation Review - RESTRICTED DRAFT")
    c.setSubject("Internal review, Governance and Risk directorate")
    c.setCreator("Meridian Trust Governance Template v4")

    y = 720
    for text, font, size in BODY_1:
        c.setFont(font, size)
        c.drawString(LEFT, y, text)
        y -= size + 6

    # Leak #1: the DOJ/NHS failure, reproduced exactly. Draw the full line
    # first — including the name — then cover the name with an opaque box. The
    # glyphs remain in the content stream underneath.
    c.setFont("Helvetica", 10)
    c.drawString(LEFT, y, COVER_BEFORE + COVER_TARGET + COVER_AFTER)

    box_x = LEFT + stringWidth(COVER_BEFORE, "Helvetica", 10)
    box_w = stringWidth(COVER_TARGET, "Helvetica", 10)
    c.setFillColorRGB(0, 0, 0)
    # Descender to a little above cap height, so it looks like a real redaction.
    c.rect(box_x - 1, y - 2.5, box_w + 2, 12, fill=1, stroke=0)
    c.setFillColorRGB(0, 0, 0)

    c.showPage()

    y = 720
    for text, font, size in BODY_2:
        c.setFont(font, size)
        c.drawString(LEFT, y, text)
        y -= size + 6

    c.save()
    return OUT


GROUND_TRUTH = {
    "document": "sample.pdf",
    "subject": "J. Okafor, Director of Governance and Risk, Meridian Health Trust",
    "expected_findings": [
        {
            "id": "GT-1",
            "tier": "M",
            "channel": "redaction_underlay",
            "expect": "Dr. Amara Osei",
            "persona": "Layout-Forensicist",
            "note": "Text drawn under an opaque rectangle on page 1.",
        },
        {
            "id": "GT-2",
            "tier": "M",
            "channel": "metadata",
            "expect": "J. Okafor",
            "persona": "Layout-Forensicist",
            "note": "/Author field never cleared. Names the report's subject directly.",
        },
        {
            "id": "GT-3",
            "tier": "C",
            "channel": "quasi_identifier_intersection",
            "expect_candidate_set_size": 1,
            "persona": "Data-Broker",
            "note": (
                "Director of Governance and Risk + Bristol + in post since March 2019. "
                "Corpus states the directorate has had one director since 2019."
            ),
        },
        {
            "id": "GT-4",
            "tier": "C",
            "channel": "verbatim_quote",
            "expect": "if your incident numbers are going down",
            "persona": "Journalist",
            "note": "Reproduced from Health Service Weekly, 14 Sept 2021, where it is attributed.",
        },
        {
            "id": "GT-5",
            "tier": "C",
            "channel": "declared_interest",
            "persona": "Insider",
            "note": (
                "Family-member-at-supplier declaration from 2022 appears in the public "
                "Regulatory Register for exactly one Meridian officer."
            ),
        },
    ],
    "should_not_find": [
        {
            "note": (
                "No Tier M claim may be made about the identity of the Exeter staff "
                "who reported reluctance to escalate — the document gives no "
                "mechanical evidence about them, only an aggregate statement."
            )
        }
    ],
}


if __name__ == "__main__":
    path = build()
    (HERE.parent / "corpus" / "ground_truth.json").write_text(
        json.dumps(GROUND_TRUTH, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {path}")
    print("Wrote corpus/ground_truth.json")

    # Verify the fixture actually leaks before anyone relies on it in a demo.
    # A silently-correct redaction here would mean standing in front of judges
    # with a document that has nothing wrong with it.
    import sys

    sys.path.insert(0, str(HERE.parent))
    from veil.tools.doc_metadata import doc_metadata
    from veil.tools.layout_forensics import extract_underlay

    print("\nSelf-check:")
    spans = extract_underlay(str(path))
    recovered = " ".join(s.text for s in spans)
    if "Amara Osei" in recovered:
        print(f"  OK   underlay leaks: {recovered!r}")
    else:
        print(f"  FAIL underlay recovered {recovered!r}, expected 'Dr. Amara Osei'")
        print("       The redaction box is misplaced — fix before demoing.")
        raise SystemExit(1)

    author = doc_metadata(str(path)).get("identifying_fields", {}).get("Author")
    if author == "J. Okafor":
        print(f"  OK   metadata leaks Author={author!r}")
    else:
        print(f"  FAIL metadata Author={author!r}, expected 'J. Okafor'")
        raise SystemExit(1)

    print("\nFixture is correctly broken. Ready to demo.")
