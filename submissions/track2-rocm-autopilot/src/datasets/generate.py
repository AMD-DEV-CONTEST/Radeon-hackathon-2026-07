"""Generate the confidential-drafting benchmark suite (30 prompts).

Three document classes that can never leave local infrastructure:
patent claims (pre-filing disclosure), medical reports (privilege),
anonymized investigative articles (source protection). Each class has
two base scenarios x five parameter variations = 10 prompts, 300-800
input tokens each, structured long-form output expected.

Synthetic and templated by design: committed alongside its output so
the benchmark is fully reproducible.
"""

import json
import itertools

PATENT_BASES = [
    (
        "thermal management of stacked memory",
        "an invention disclosure describing a microfluidic cold plate bonded "
        "directly to a 3D-stacked HBM package. Coolant channels are etched at "
        "45 degrees to the die edge, with flow rate modulated per-bank by "
        "thermal telemetry sampled every 2 ms from on-die sensors. A predictive "
        "controller anticipates bank activation from the memory controller's "
        "command queue and pre-cools regions 500 microseconds before access "
        "bursts. Prototype results: 14 C peak reduction at iso-power, 9 percent "
        "higher sustained bandwidth, no throttling events across 72-hour runs",
    ),
    (
        "adaptive radio resource scheduling",
        "an invention disclosure for a scheduler that allocates uplink resource "
        "blocks using a learned model of per-device channel coherence time. "
        "Devices with stable channels receive longer grants with sparse pilots; "
        "fast-fading devices receive short interleaved grants with dense "
        "pilots. The model runs on the base station, retrains nightly from "
        "HARQ feedback statistics, and falls back to proportional-fair when "
        "confidence drops below a threshold. Field trial: 23 percent fewer "
        "retransmissions and 11 percent cell-edge throughput gain",
    ),
]

MEDICAL_BASES = [
    (
        "cardiology consultation",
        "raw consultation notes: 58 yo patient, exertional chest tightness x3 "
        "weeks, radiating left arm, relieved by rest in under 5 min. Risk "
        "factors: smoker 20 pack-years, hypertension on ramipril, father MI at "
        "61. Exam: BP 148/92, HR 78 regular, no murmur, lungs clear. ECG: "
        "1 mm ST depression V5-V6 during symptoms, normalizing at rest. "
        "Troponin negative x2. Started bisoprolol 2.5 mg, aspirin 75 mg, "
        "atorvastatin 40 mg. Plan: coronary CT angiogram within 2 weeks, "
        "stress echo if inconclusive, safety-netting advice given",
    ),
    (
        "post-operative follow-up",
        "raw notes: day 5 after laparoscopic cholecystectomy, 44 yo patient. "
        "Reports mild right shoulder tip pain resolving, tolerating full diet, "
        "bowels open day 3. Wounds: four ports dry, no erythema, steri-strips "
        "intact. Temp 36.8, obs stable. Bloods: WCC 8.2 normalized from 11.4, "
        "CRP 22 falling from 96, LFTs normal. Histology: chronic cholecystitis, "
        "no dysplasia. Plan: remove strips day 10 by practice nurse, resume "
        "driving when emergency stop comfortable, sick note 2 weeks, no "
        "routine follow-up unless symptoms recur",
    ),
]

ARTICLE_BASES = [
    (
        "procurement irregularities",
        "verified source notes for an investigative piece: three municipal "
        "contracts for road resurfacing awarded 2024-2025 to the same "
        "contractor despite bids 18 to 31 percent above the lowest qualified "
        "competitor. Tender committee minutes show two members declared no "
        "conflicts while land registry documents link one member's spouse to "
        "a subcontractor. An internal audit flagged 'insufficient "
        "justification' in all three awards; the audit was not forwarded to "
        "the council. Two sources inside the finance department (protected, "
        "referred to as A and B) provided the payment schedules",
    ),
    (
        "industrial wastewater releases",
        "verified source notes: night-shift logs from a chemical plant show "
        "unpermitted discharge valve openings on 14 dates over six months, "
        "each preceding scheduled regulator inspections by 2 to 4 days. "
        "Downstream sensor data from the water authority shows conductivity "
        "spikes matching 11 of the 14 dates. A former shift supervisor "
        "(protected source C) confirms verbal instructions to 'balance the "
        "basins before visits'. The plant's compliance reports for the period "
        "declare zero exceptional discharges",
    ),
]

VARIANTS = [
    "Prioritize completeness over brevity.",
    "Flag any missing information that a reviewer would request.",
    "Use numbered sections and a formal register.",
    "Include a short risk/limitations paragraph at the end.",
    "Target roughly 600 words of output.",
]

INSTRUCTIONS = {
    "patent": (
        "You are drafting for a confidential pre-filing review (nothing may "
        "leave local infrastructure). From the following disclosure, draft: "
        "(1) a title, (2) one independent claim and three dependent claims in "
        "formal patent language, (3) a 150-word abstract, (4) a brief prior-art "
        "differentiation paragraph. Disclosure: {body}. {variant}"
    ),
    "medical": (
        "You are producing a confidential structured medical report (patient "
        "data must remain on local infrastructure). From the following notes, "
        "produce: (1) structured summary (history, exam, investigations), "
        "(2) assessment, (3) management plan as a numbered list, (4) a "
        "plain-language letter to the patient. Notes on {body}. {variant}"
    ),
    "article": (
        "You are drafting a publishable investigative article from confidential "
        "source notes (source protection: all identifying details must be "
        "anonymized, sources referred to only by their protected labels). "
        "Draft: (1) headline and standfirst, (2) a 500-word article body with "
        "careful attribution, (3) a fact-check list of every claim and its "
        "supporting evidence. Notes on {body}. {variant}"
    ),
}


def main() -> None:
    rows = []
    for kind, bases in (
        ("patent", PATENT_BASES),
        ("medical", MEDICAL_BASES),
        ("article", ARTICLE_BASES),
    ):
        for (topic, body), variant in itertools.product(bases, VARIANTS):
            prompt = INSTRUCTIONS[kind].format(body=f"{topic}: {body}", variant=variant)
            rows.append({"prompt": prompt, "max_tokens": 512, "class": kind})
    with open("datasets/confidential_drafting.jsonl", "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    print(f"wrote {len(rows)} prompts")


if __name__ == "__main__":
    main()
