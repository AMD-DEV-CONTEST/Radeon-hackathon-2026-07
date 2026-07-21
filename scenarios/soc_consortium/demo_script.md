# Perciqa Cortex — Demo Walkthrough Script

> **Duration:** 3-5 minutes
> **Scenario:** F1 Cybersecurity SOC Consortium
> **Actors:** SOC Alpha (publisher), SOC Beta (querier), Fabric Broker, Console UI

---

## Segment 1: Setup & Context (0:00–0:45)

**Visual:** Console opens showing two-column tenant layout: "SOC Alpha" (left) and "SOC Beta" (right).

**Narrator:**
"Today, every SOC is an island. Threat intel sharing happens via CSV dumps, PDF reports, and trust built on phone calls — no provenance, no machine-verifiable trust.

Perciqa Cortex is a decentralized agent memory fabric. Two sovereign SOCs can share findings without exposing raw data, without trusting a central vendor — every article carries cryptographic provenance."

**Action:** Point to the two tenant panels. Highlight the "scope" indicators showing `partner` ACL.

---

## Segment 2: SOC Alpha Publishes a Finding (0:45–1:30)

**Visual:** Terminal or Console showing SOC Alpha's agent console.

**Narrator:**
"SOC Alpha's agent has detected a credential-harvesting campaign — PowerShell encoded commands matching MITRE T1059.001, attributed to APT29.

The agent publishes this as a signed MemoryArticle — a `finding` type with full provenance: which agent, which org, a hash of the source telemetry, and an Ed25519 signature."

**Action:** The article card appears on the SOC Alpha side of the Console with type tag `FINDING` (red), trust score ring spinning up. An animated dotted line flows from SOC Alpha to the broker (center) and then to SOC Beta's side.

**Narrator:**
"The article embeds on the local Radeon GPU in ~7 milliseconds, gets signed with the org's Ed25519 key, and routes through the broker to SOC Beta — but only because the article's scope is `partner:org:soc-beta`."

---

## Segment 3: SOC Beta Queries the Fabric (1:30–2:30)

**Visual:** SOC Beta's agent panel, query input visible.

**Narrator:**
"SOC Beta's agent is monitoring the same threat actor. It queries the fabric: 'what's new on APT29 T1059.001?'

The query embeds on Beta's local GPU, runs semantic similarity over their fabric partition — which now includes Alpha's finding — and returns ranked results."

**Action:** Query results appear in SOC Beta's panel. The top result is Alpha's finding with hybrid score (0.5 × cosine + 0.5 × trust). Click to expand.

**Narrator:**
"Notice the hybrid ranking: trust score and cosine similarity are blended. Trust isn't just a number in the UI — it shapes what agents actually see.

The provenance panel shows the full chain: produced by SOC Alpha's agent, source data hash, signatures verified — green checkmarks on both agent and org signatures."

**Action:** Point to the green checkmarks in the Article Detail view. Show the provenance tree expanding.

---

## Segment 4: SOC Beta Derives New Insight (2:30–3:15)

**Visual:** SOC Beta's agent composing a derived insight.

**Narrator:**
"SOC Beta's agent has its own corroborating telemetry. It composes a new `insight` article: 'Three independent telemetry sources suggest a coordinated APT29 campaign starting mid-July.'

This new article cites Alpha's finding as a source. The provenance graph extends — you can see the edge forming in real time. Trust propagates: Beta's insight inherits trust from Alpha's high-reputation finding."

**Action:** Provenance Graph view in Console. Show the new node (INSIGHT, blue) appearing with an edge to the original FINDING node. Trust score updates on the new article.

---

## Segment 5: The ATT&CK Matrix Comes Alive (3:15–4:00)

**Visual:** Switch to the ATT&CK Matrix view. 14×15 grid of MITRE techniques.

**Narrator:**
"The Console includes a live MITRE ATT&CK matrix. Every finding is mapped to its technique ID.

Watch: Alpha's finding lights up T1059.001 in orange. When Beta's insight corroborates the same technique, it shifts to bright red — indicating ≥3 articles citing this technique.

At a glance, a SOC analyst can see which techniques are being discussed across the consortium."

**Action:** T1059.001 cell lights up orange → shifts to red. Click the cell to see the list of articles.

---

## Segment 6: Benchmark Panel (4:00–4:30)

**Visual:** Bench Panel overlay showing live bar charts.

**Narrator:**
"Every node runs a benchmark sidecar measuring Radeon vs CPU throughput. The embed pipeline: 1,004 embeddings per second on Radeon, versus 245 on CPU — a 4× improvement.

The AMD Radeon GPU is load-bearing, not decorative. Sovereign local inference is the only way this architecture works without trusting a central vendor."

**Action:** Bar charts animate with live metrics. Highlight the Radeon vs CPU comparison.

---

## Segment 7: Wrap & Generality Proof (4:30–5:00)

**Visual:** Quick cut to healthcare montage scenario.

**Narrator:**
"Cortex is domain-agnostic. The same fabric works for hospital-research lab collaboration — where patient data never leaves the hospital, and research methods never leave the lab.

Same protocol. Same cryptographic guarantees. Different domain.

Imagine a 2028 where agents have verifiable, provenance-tracked memory across organizational boundaries. Perciqa Cortex is the first step."

**Action:** Show the healthcare article flow briefly (montage). Fade to title card with repo URL and "Thank you."
