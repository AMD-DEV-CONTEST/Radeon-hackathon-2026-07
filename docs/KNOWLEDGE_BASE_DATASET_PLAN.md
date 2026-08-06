# XiangLens Knowledge and Image Dataset Plan — Hackathon Edition

> Document status: P0 seed implemented
> Updated: July 25, 2026
> Time budget: 12-day hackathon
> Product language: English only
> Runtime database: Milvus Lite

## 1. Goal

The XiangLens knowledge base exists to demonstrate three things:

1. The local agent can retrieve relevant context instead of injecting one large prompt;
2. The response can cite a visible source;
3. Different Lens Packs can be enabled for different tasks.

It is not intended to be a production cultural-knowledge dataset during the hackathon.

The Track 2 requirements evaluate whether local RAG works as part of a complete agent; they do not specify a minimum corpus size, a gold set, or a dataset-review workflow. Retrieval behavior and visible citations are therefore the acceptance signal, not card count beyond the small P0 floor.

The correct target is a small corpus that is easy to understand, quick to edit, and stable in the demo. The application, agent workflow, privacy tools, memory, AMD deployment, benchmark, documentation, and video are more important than building a large dataset.

## 2. Hard Scope Limit

### 2.1 Hackathon Target

| Lens Pack | Content | P0 | Stretch |
|---|---|---:|---:|
| `profile_basics` | Avatar clarity, crop, and composition | 8 | 12 |
| `privacy_safety` | EXIF, QR, badge, screen, and text-disclosure risks | 8 | 10 |
| `global_professional_context` | Platform behavior and copyright provenance | 12 | 18 |
| `open_chinese_symbolism` | A few documented plants, animals, and motifs | 6 | 10 |
| **Total** |  | **34 cards** | **50 cards** |

Build **34 cards first**. Stop when the nine smoke queries pass. Expand toward 50 only after the agent workflow, tools, memory, UI, AMD benchmark, documentation, and video are complete.

### 2.2 Post-Hackathon Target

The earlier 180–290-card target is moved to a future milestone. It is not an acceptance criterion for the competition submission.

### 2.3 Explicitly Out of Scope

- No automated Met, Smithsonian, Europeana, or Wikidata ingestion pipeline;
- No 20-field card schema;
- No source snapshots or revision tracking beyond a URL and retrieval date;
- No multi-reviewer workflow;
- No automated license linter;
- No semantic-duplicate detector;
- No reranker;
- No sparse or hybrid retrieval requirement;
- No 40-query gold set;
- No dataset release engineering;
- No attempt to cover every cultural interpretation.

### 2.4 Implemented Image Fixture Target

The project uses two deliberately separate dataset layers:

| Layer | Count | Runtime Role |
|---|---:|---|
| Knowledge cards | 34 | Embedded into Milvus Lite for source-backed RAG |
| Image fixtures | 120 | Exercised by the VLM and deterministic image, privacy, OCR, QR, and EXIF tools |
| **Primary test records** | **154** | Text retrieval plus visual/tool evaluation |

The image layer is implemented from **24 existing open-license Wikimedia Commons images**: 16 event portraits and 8 cultural images covering bat, lotus, dragon, and bamboo motifs. One additional public-domain QR image is used only as an overlay source. No AI-generated image is included.

The builder creates controlled 512-by-512 variants so the same source can test clean input and one measurable change. The resulting pack contains:

- 80 portrait fixtures covering clean input, tight crop, small subject, low contrast, QR, fake badge, fake screen, fake location sign, small text, multiple subjects, GPS EXIF, and device EXIF;
- 40 cultural fixtures covering clean input, circular preview, small subject, low contrast, and busy background.

These are 120 actual JPEG files, not 120 manually researched cards. Provenance, author, source page, license, and SHA-256 hashes are generated into manifests. Inserted names, addresses, identifiers, email domains, tokens, and timestamps are fictional test values.

## 3. Minimal Card Format

Each card has exactly four author-written fields:

```yaml
- text: "GitHub avatars appear across collaboration surfaces. The subject should remain recognizable after a small circular crop."
  pack: profile_basics
  source: github_profile_reference
  tags: [github, crop, small-size]
```

That is the complete authoring format.

The build script automatically generates:

- `id`, using a stable hash;
- embedding vector;
- source title;
- source URL;
- license label;
- ingestion timestamp.

### 3.1 Field Rules

#### `text`

- One or two short sentences;
- One useful idea;
- Written in English;
- Directly usable as retrieved context;
- No personality, health, wealth, crime, relationship, or destiny inference.

#### `pack`

One of:

```text
profile_basics
privacy_safety
global_professional_context
open_chinese_symbolism
```

#### `source`

A key from `sources.yaml`. Project-original rules use `xianglens_original`.

#### `tags`

Three to six simple retrieval hints. Do not build a formal taxonomy during the hackathon.

## 4. Minimal Source Registry

Sources are written once in `sources.yaml` and referenced by key from every card.

```yaml
github_profile_reference:
  title: GitHub Profile Reference
  url: https://docs.github.com/en/account-and-profile/reference/profile-reference
  license: CC-BY-4.0

linkedin_photo_guidelines:
  title: LinkedIn Profile Photo Guidelines
  url: https://www.linkedin.com/help/linkedin/answer/a1377087?lang=en
  license: summary-and-link

xianglens_original:
  title: XiangLens Project-Authored Heuristics
  url: https://github.com/PROJECT_REPOSITORY
  license: project-license
```

The registry needs only:

- title;
- URL;
- license or `summary-and-link` label.

Optional `retrieved_at` may be added automatically by the build script.

## 5. Files

```text
data/
├── knowledge/
│   ├── cards.yaml
│   ├── sources.yaml
│   └── LICENSE.dataset
├── evaluation/
│   └── rag_smoke_queries.yaml
└── fixtures/
    ├── source_catalog.yaml
    ├── source_manifest.yaml
    ├── manifest.yaml
    ├── LICENSE.images
    ├── README.md
    ├── sources/
    └── images/

scripts/
├── build_image_fixtures.py
└── build_knowledge_db.py
```

`cards.yaml` is the editable knowledge source of truth. `source_catalog.yaml` is the short, human-maintained image selection list. The Milvus Lite file and both image manifests are generated.

## 6. Lens Pack Boundaries

### `profile_basics`

Platform-independent and measurable image behavior:

- small-size clarity;
- circular crop survival;
- square crop survival;
- subject size;
- edge clipping;
- competing subjects;
- text legibility;
- background separation;
- logo visibility.

Platform documentation may supply realistic dimensions, but official platform policy belongs in `global_professional_context`.

### `privacy_safety`

Privacy findings and mitigations:

- EXIF and GPS;
- QR codes;
- visible email or phone number;
- work badges;
- screens and documents;
- street or location text;
- temporary retention;
- safe derivative export.

The detector is code. The card explains why the detected item may matter.

### `global_professional_context`

Platform-specific facts:

- GitHub file and display behavior;
- LinkedIn likeness and photo policy;
- Discord avatar formats and per-server profiles;
- visible differences between professional, open-source, and community contexts.

“Community consensus” is not treated as an official source. Useful advice is marked through `source: xianglens_original` and phrased as a project heuristic.

### `open_chinese_symbolism`

A deliberately small set of historically documented associations:

- bat;
- peach;
- crane;
- lotus;
- peony;
- bamboo;
- dragon;
- phoenix;
- fish;
- cloud pattern;
- red or gold in a specific documented context.

Each card must say that it describes a documented context, not every modern viewer.

Gestures are omitted from the hackathon seed unless a strong source is immediately available.

## 7. Source List

### 7.1 Platform Sources

| Key | Source | Use |
|---|---|---|
| `github_profile_reference` | GitHub Profile Reference | File requirements, image dimensions, profile visibility |
| `github_personalize_profile` | Personalize Your GitHub Profile | Where the avatar appears and upload cropping |
| `linkedin_photo_guidelines` | LinkedIn Profile Photo Guidelines | Likeness and image policy |
| `linkedin_photo_management` | LinkedIn Profile Photo Management | Crop and visibility behavior |
| `discord_custom_profiles` | Discord Custom Profiles | Avatar formats and customization |
| `discord_per_server_profiles` | Discord Per-Server Profiles | Context-specific avatars, formats, size, and cropping |

GitHub documentation may be attributed under CC BY 4.0. LinkedIn and Discord cards use short project-authored summaries and links rather than copied help-center text.

### 7.2 Privacy Sources

| Key | Source | Use |
|---|---|---|
| `nist_privacy_framework` | NIST Privacy Framework | Data minimization, deletion, and user control |
| `nist_sp_800_122` | NIST SP 800-122 | PII confidentiality principles |
| `exiftool_gps_tags` | ExifTool GPS Tag Reference | Latitude, longitude, altitude, and related GPS metadata |
| `exiftool_exif_tags` | ExifTool EXIF Tag Reference | Device, time, and software metadata |
| `xianglens_original` | XiangLens threat model | QR, badge, OCR, and screen-risk explanations |

NIST is used for general privacy principles. It is not cited as if it defines avatar QR or badge detection.

### 7.3 Chinese Symbolism Sources

Do not research individual collection objects during the hackathon. Use two authoritative thematic pages that already summarize several motifs:

| Key | Source | Cards it can support |
|---|---|---|
| `smithsonian_cloisonne_symbols` | Smithsonian National Museum of Asian Art, *Symbolism in Cloisonné* teaching guide | Bat, crane, dragon, and other motifs covered by the guide |
| `met_longevity_chinese_art` | The Met, *Longevity in Chinese Art* | Bat, peach, crane, deer, and longevity combinations |

Write short project-authored summaries and link to the thematic page. Label these sources `summary-and-link`; do not copy paragraphs or redistribute page images.

Multiple cards may cite the same page. The demo does not need object IDs, image downloads, API calls, or object-level provenance. A card only needs enough source support for a reviewer to open the page and understand the stated association.

Wikipedia is an optional fallback, not the default. If its text is adapted, record the article URL and comply with its CC BY-SA attribution and ShareAlike requirements.

## 8. P0 Card Allocation

### 8.1 `profile_basics`: 8 Cards

1. Circular crop removes corners;
2. Fine text fails at small avatar sizes;
3. Multiple subjects compete at small sizes;
4. A very small central subject loses recognition;
5. Busy backgrounds reduce separation;
6. Low subject/background contrast reduces clarity;
7. A subject touching the edge is crop-sensitive;
8. Previewing at target size is more reliable than judging the source image alone.

### 8.2 `privacy_safety`: 8 Cards

1. GPS EXIF may disclose location;
2. Device metadata may disclose capture context;
3. QR codes may expose links or identifiers;
4. Badges may expose name or employer;
5. Screens and documents may expose contact or project information;
6. Street signs may expose location;
7. Session-only retention reduces unnecessary storage;
8. A metadata-stripped derivative reduces hidden-data exposure.

### 8.3 `global_professional_context`: 10 Cards

Suggested split:

- four GitHub cards;
- three LinkedIn cards;
- three Discord cards.

Do not create ten nearly identical “look professional” recommendations.

### 8.4 `open_chinese_symbolism`: 6 Cards

Select six motifs from the Smithsonian teaching guide. The exact list is less important than reliable citations and careful wording.

Example:

```yaml
- text: "A museum record documents the bat motif in a specific Chinese decorative tradition as an auspicious visual association. This does not predict how every modern viewer interprets a bat image."
  pack: open_chinese_symbolism
  source: smithsonian_cloisonne_symbols
  tags: [bat, motif, chinese-art, documented-context]
```

### 8.5 Copyright-Provenance Extension: 2 Cards

Two WIPO-backed cards support the explicit memory demo for users who prefer cartoon-style avatars
while wanting copyright uncertainty considered. The cards recommend independently created,
commissioned-with-rights, licensed, or public-domain artwork. They deliberately do not make an
infringement determination from visual similarity.

### 8.6 Total

```text
 8 profile cards
 8 privacy cards
12 professional-context cards
 6 cultural cards
----------------------------
34 cards total
```

Stop at 34 when all nine smoke queries pass. More cards are optional.

## 9. Build Script

`build_knowledge_db.py` performs only the following steps:

1. Load `sources.yaml`;
2. Load `cards.yaml`;
3. Confirm that each card contains `text`, `pack`, `source`, and `tags`;
4. Confirm that the source key exists;
5. Generate a stable card ID;
6. Generate a local embedding;
7. Insert the record into Milvus Lite;
8. Print card counts by pack.

Generated Milvus fields:

| Field | Source |
|---|---|
| `id` | Stable hash of pack, source, and text |
| `text` | Card |
| `vector` | Embedding model |
| `pack` | Card |
| `source_key` | Card |
| `source_title` | Source registry |
| `source_url` | Source registry |
| `license` | Source registry |
| `tags` | Card |

No separate chunking pipeline is required because every card is already short.

## 10. Retrieval

Use the simplest possible retrieval flow:

```text
user goal + platform + observed image tags
  -> filter enabled packs
  -> dense search in Milvus Lite
  -> top 4 cards
  -> include text and source link in the model context
```

No reranking is required for the hackathon. If retrieval is weak, improve the card text and tags before adding infrastructure.

## 11. Smoke Evaluation

Create nine queries: two per Lens Pack plus one copyright-provenance query for professional context.

```yaml
- query: "Will the logo survive a circular crop at a small avatar size?"
  expected_tags: [crop, small-size]

- query: "Could this image expose where it was taken?"
  expected_tags: [exif, gps, location]
```

Manual pass condition:

- at least one relevant card appears in the top four;
- its source link is visible;
- the final response uses the retrieved card correctly;
- no unrelated sensitive inference appears.

This is a smoke test, not a benchmark paper. Eight queries are sufficient for the hackathon demo.

## 12. Review

One final read-through is enough:

- remove duplicates;
- verify every source link opens;
- check that every cultural card includes a limitation;
- check that no card contains sensitive inference;
- check that platform summaries do not claim to be official quotations;
- check that the private course appears nowhere.

The review does not require per-card reviewer fields, timestamps, or approval states.

## 13. Time Budget

| Task | Budget |
|---|---:|
| Create `sources.yaml` | 1 hour |
| Write 8 profile cards | 1 hour |
| Write 8 privacy cards | 1 hour |
| Write 10 platform cards | 2 hours |
| Write 6 cultural cards from one thematic guide | 1.5 hours |
| Build Milvus script | 2 hours |
| Run nine smoke queries and fix cards | 1 hour |
| Final read-through | 0.5 hour |
| **Total** | **10 hours** |

This is approximately one focused workday plus contingency, not a multi-week dataset project.

The image pack is built separately by one deterministic script. Its 120 outputs do not require 120 manual authoring passes: source selection is maintained once, and mechanical variants, hashes, attribution fields, and manifests are generated automatically.

## 14. Acceptance Criteria

- [ ] `cards.yaml` contains at least 34 useful cards;
- [ ] Every card has exactly the four required author-written fields;
- [ ] Every source key resolves in `sources.yaml`;
- [ ] No private-course content is included;
- [ ] No card makes a sensitive inference;
- [ ] Every cultural card includes a scope limitation in its text;
- [ ] Milvus Lite builds from scratch with one command;
- [ ] The application retrieves four cards or fewer per run;
- [ ] The UI displays source title and link;
- [ ] Eight smoke queries pass manually;
- [ ] Runtime analysis requires no network access.
- [x] The fixture pack contains 120 actual 512-by-512 JPEG files;
- [x] No AI-generated image is included in the fixture pack;
- [x] Every fixture resolves through the manifests to a source page, author or credit, license, and SHA-256 hash;
- [x] Fixture licenses are restricted to CC0, public domain, CC BY, or CC BY-SA entries accepted by the builder;
- [x] Two GPS EXIF fixtures and two device EXIF fixtures contain machine-readable test metadata;
- [x] All inserted privacy-risk values are explicitly fictional test data.

## 15. Future Work, Not Hackathon Work

After submission, the dataset may add:

- 180–290 reviewed cards;
- museum API ingestion;
- richer rights metadata;
- multi-reviewer cultural review;
- automated policy linting;
- duplicate detection;
- larger retrieval evaluation;
- hybrid search and reranking;
- versioned public dataset releases.

None of these items should block the competition build.

## 16. References

### Platform Sources

- [GitHub Profile Reference](https://docs.github.com/en/account-and-profile/reference/profile-reference)
- [Personalize Your GitHub Profile](https://docs.github.com/en/account-and-profile/tutorials/personalize-your-profile)
- [GitHub Docs Repository and License](https://github.com/github/docs)
- [LinkedIn Profile Photo Guidelines](https://www.linkedin.com/help/linkedin/answer/a1377087?lang=en)
- [LinkedIn Profile Photo Management](https://www.linkedin.com/help/linkedin/answer/a541850?lang=en)
- [Discord Custom Profiles](https://support.discord.com/hc/en-us/articles/4403147417623-Custom-Profiles)
- [Discord Per-Server Profiles](https://support.discord.com/hc/en-us/articles/4409388345495-Per-Server-Profiles)
- [Discord Profile Privacy](https://support.discord.com/hc/en-us/articles/38859942749463-Profile-Privacy-Setting-on-Discord)

### Privacy Sources

- [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)
- [OWASP Input Validation Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html)
- [NIST Privacy Framework](https://www.nist.gov/privacy-framework/privacy-framework)
- [NIST SP 800-122](https://csrc.nist.gov/pubs/sp/800/122/final)
- [ExifTool Geolocation Documentation](https://exiftool.org/geolocation.html)

### Optional Cultural Sources

- [Smithsonian National Museum of Asian Art: Symbolism in Cloisonné](https://asia-archive.si.edu/wp-content/uploads/2020/06/LP23WS1-Symbolism-in-Cloisonne-FA3.pdf)
- [The Met: Longevity in Chinese Art](https://www.metmuseum.org/essays/longevity-in-chinese-art)
- [Wikipedia Licensing Overview](https://wikimediafoundation.org/what-we-do/wikimedia-projects/wikipedia/)
