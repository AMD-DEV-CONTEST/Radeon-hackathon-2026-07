export const GLOSSARY = {
  insight: {
    term: "Insight",
    plain: "A conclusion the AI wrote after reading several findings at once. A finding is one clue; an insight is the story those clues seem to add up to.",
    so: 'Start here when triaging — it\'s the machine\'s "so what". Then check its homework in Sources.',
  },
  finding: {
    term: "Finding",
    plain: "One concrete thing actually observed — a command that ran, a file that appeared, a connection made. A single fact, not a verdict.",
    so: "Harmless on its own, often. It matters when it clusters with others around the same actor or technique.",
  },
  unranked: {
    term: "Unranked trust",
    plain: 'Nothing has confirmed or contradicted this yet, so we can\'t score it. The dashed meter means "no signal", not "scored zero".',
    so: 'Unranked ≠ wrong and ≠ low priority. It means "we don\'t know" — which is exactly what a human eye should look at.',
  },
  actor: {
    term: "Actor",
    plain: "The nickname analysts give a group they believe is behind the activity — APT29, Turla, REvil. A working label, not a fingerprint.",
    so: 'Attribution is a best guess. Treat it as a lead to pull on, not a fact to file.',
  },
  technique: {
    term: "Technique (MITRE ATT&CK)",
    plain: "A code from a shared dictionary of *how* adversaries behave — T1059.001 is \"ran PowerShell\", T1082 is \"listed system info\".",
    so: "Two unrelated events that share a technique may be the same playbook. That coincidence is the signal.",
  },
  hash: {
    term: "Hash",
    plain: "A fingerprint of a file or string. Identical content always gives the identical fingerprint, so it's how we say \"this exact thing\" without shipping the thing.",
    so: "Copy it into your other tools. A matching hash anywhere = the same artefact, full stop.",
  },
  org: {
    term: "Organisation",
    plain: "Which team or tenant this item belongs to — SOC Alpha, SOC Beta. A scope label, not a severity.",
    so: "Use it to narrow the view, the way you'd filter an inbox by account.",
  },
  payload: {
    term: "Tool payload",
    plain: "The raw articles and the exact prompt the AI was handed to produce this insight — the unedited inputs.",
    so: 'Engineers\' view. The friendly "Sources" panel above is the same data, translated.',
  },
  severity: {
    term: "Severity",
    plain: "How critical this item is, based on the MITRE ATT&CK severity rating and available trust signals.",
    so: "Critical ≠ confirmed. Use trust + severity together before acting.",
  },
  agent: {
    term: "Agent",
    plain: "An automated reasoning process running in the fabric. Each agent monitors a scope, analyses findings, and publishes insights.",
    so: "An agent that produces many low-trust findings is probably misconfigured, not malicious.",
  },
  computation_ref: {
    term: "ZK-Verified",
    plain: "This computation was cryptographically verified using a zero-knowledge proof. The result is provably correct without revealing the inputs.",
    so: "A green badge = you can trust the maths even if you don't trust the source.",
  },
  provenance: {
    term: "Provenance",
    plain: "The chain of articles and events that led to this item. Think of it as a citation tree — who said what, and what they based it on.",
    so: "Follow it upstream to verify. A short chain with high-trust sources is stronger than a long chain of unranked hops.",
  },
} as const;

export type GlossaryKey = keyof typeof GLOSSARY;
