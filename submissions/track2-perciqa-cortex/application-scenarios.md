# Application Scenarios — Perciqa Cortex

> **AMD AI DevMaster Hackathon 2026, Track 2 (Radeon/ROCm)**
> Reference deployment: two-SOC cybersecurity fabric at `cortex.perciqa.com`

---

## 1. The scenario space

Cortex is a protocol for cross-organization agent memory with cryptographic provenance. The general shape is always the same: two or more organizations run sovereign nodes on their own AMD GPUs; a lightweight broker routes signed, scoped memory articles between them; and each organization can ask the fabric "what is known about X?" without exposing raw data, probe placement, or analyst identities.

The reference deployment exercises this with a **two-SOC threat-intel fabric**:

| Tenant | Org DID | Domain | Agent |
|---|---|---|---|
| SOC Alpha | `did:percq:org:soc-alpha` | APT / espionage | `alpha-demo-bot` |
| SOC Beta | `did:percq:org:soc-beta` | Ransomware / cybercrime | `beta-demo-bot` |

Each SOC publishes MITRE ATT&CK findings and LLM-synthesized insights. A pipeline feeds the fabric fresh content every ~30 minutes, so the console always shows live, real data — nothing staged.

---

## 2. SOC Alpha — APT / espionage

Scenario bank (one is selected at random per cycle):

| Threat actor | Technique | Tactic | Query used by agent |
|---|---|---|---|
| APT29 | T1059.001 PowerShell Execution | Execution | `T1059.001 PowerShell APT29 indicators` |
| APT41 | T1053.005 Scheduled Task | Execution | `T1053.005 scheduled task APT41 supply chain` |
| Lazarus Group | T1566.001 Spearphishing Attachment | Initial Access | `T1566.001 phishing Lazarus cryptocurrency` |
| Turla | T1082 System Discovery | Discovery | `T1082 system discovery Turla satellite infrastructure` |

Example findings Alpha publishes (APT29 cycle):
- Encoded PowerShell cradle downloading a second-stage implant from a compromised CDN node
- PowerShell enumeration module exfiltrating AD objects via DNS-over-HTTPS
- PowerShell remoting pivoting from initial workstation to domain controller within 4 hours

---

## 3. SOC Beta — ransomware / cybercrime

| Threat actor | Technique | Tactic | Query used by agent |
|---|---|---|---|
| LockBit 3.0 | T1486 Data Encrypted for Impact | Impact | `T1486 data encryption LockBit double extortion` |
| REvil | T1190 Exploit Public-Facing Application | Initial Access | `T1190 exploit public-facing REvil Kaseya` |
| BlackCat | T1530 Data from Cloud Storage | Collection | `T1530 cloud storage BlackCat ALPHV` |
| Cl0p | T1195 Supply Chain Compromise | Initial Access | `T1195 supply chain Cl0p MOVEit` |

Example findings Beta publishes (BlackCat cycle):
- Stolen Azure AD credentials accessing blob storage, exfiltrating 2 TB via AzCopy
- Rust-based ransomware variant skipping VM disks to maximize encryption speed
- Ransomware-as-a-Service operation with an 80/20 affiliate revenue split

---

## 4. The three fabric operations, in scenario terms

### 4.1 Publish — Alpha detects a new campaign
SOC Alpha's agent detects APT29 using obfuscated PowerShell for lateral movement. The node signs the article with Ed25519, computes the embedding on the Radeon GPU via ROCm, and broadcasts it to subscribed peers. The console shows the article appear in the feed and the ATT&CK matrix technique light up in real time.

### 4.2 Cross-org query — Beta asks about credential access
SOC Beta's agent asks: "what's known about credential access techniques?" It has never seen Alpha's data. The query fans out through the broker to peer nodes; five results come back, ranked by a hybrid of cosine similarity and trust score. Each result carries full provenance — which organization produced it, when, and the SHA-256 commitment of the source data. Neither SOC exposed raw data, probe placement, or analyst identities.

### 4.3 Derive — Alpha composes an insight across both organizations
Alpha's agent composes a new insight from the top retrieved findings — a synthesis across both organizations' knowledge. The provenance graph grows; the new article inherits trust from its citations (high-trust sources lift it, low-trust citations penalize it). The console shows the citation graph expanding.

---

## 5. Beyond cybersecurity

The protocol is domain-agnostic. Same publish → query → derive cycle, same provenance, same trust:

- **Healthcare:** a hospital's clinical agent retrieves findings from a research lab's literature agent. Patient data never leaves the hospital; research methods never leave the lab.
- **Finance:** fraud-detection signals shared across banks without sharing transaction data.
- **Research consortia:** laboratory results shared with provenance between institutions, each keeping sovereign control of its raw data.
- **Supply chain:** vulnerability findings shared between suppliers and buyers with scoped access.

The fabric supports `private`, `partner:<org>`, and `public` scopes, so an org can keep articles fully local, share them with a named partner, or broadcast them — the same protocol handles all three.
