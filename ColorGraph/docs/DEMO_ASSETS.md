# Demo Media and Rights Strategy

This document freezes the media plan for the ColorGraph hackathon submission.
It is an engineering and publication checklist, not legal advice.

## Decision

Use two separate media lanes:

1. **Public reproducibility lane:** Wikimedia Commons clips with explicit
   redistribution rights, immutable URLs, attribution, and checked SHA-256 values.
2. **Premium local showcase lane:** the licensed DJI Mavic 3 Pro Cine D-Log source,
   used only within the actual permission scope. Do not publish its source file or
   an extracted mezzanine clip unless the agreement explicitly grants that right.

Professionally graded references and additional public backup candidates are
frozen separately in the
[Color Reference and Backup Demo Shortlist](COLOR_REFERENCE_SHORTLIST.md). Those
assets have been selected but not yet ingested or added to the downloader.

Commercial-use permission and redistribution permission answer different
questions. Permission to modify and show a finished commercial work may be enough
for a public presentation, while still prohibiting delivery of the source footage
or an extract that substitutes for it.

## Frozen media roles

| Role | Source | Why it works | Public handling |
| --- | --- | --- | --- |
| Creative-direction hero | **Tbilisi life at night**, Mostafameraji, Canon EOS M3 | Blue-hour city detail, a warm illuminated cathedral, traffic highlights, and cool/warm contrast make `faithful`, `amplified`, and `counterpoint` immediately readable. | CC BY-SA 4.0; downloader verifies SHA-256 `2c21780225809981c78b94cf6d9cc0e3aa6449e1ad989215cf8134f2b08600e7`. Attribute every published derivative. |
| End-to-end workflow | **Snowdonia by drone**, Wiebe de Jager, DJI Phantom 2 Vision+ / FC200 | Multiple edits, green terrain, rivers, waterfalls, road, mountain, and architecture exercise scene structure and semantic masks better than one continuous shot. | CC BY-SA 4.0; downloader verifies SHA-256 `e6ff1c365a4e86576678d8b4b2bf13fed25e465c11f6ccb4615131befa6e7309`. Attribute every published derivative. |
| Professional log / ACES proof | **Snow canyon aerial — DJI Mavic 3 Pro Cine D-Log**, user-attested Mediastorm source | 4K 59.94 fps, ProRes 422 HQ 10-bit, D-Log/D-Gamut override, snow highlights, rock texture, and a late warm vehicle anchor stress the professional path. | Private/local. Finished public display only after the actual certificate/terms confirm modification, public display, commercial showcase, territory/term, and attribution. No raw or excerpt redistribution is currently authorized in the intake record. |

Source pages:

- Tbilisi: <https://commons.wikimedia.org/wiki/File:Tbilisi_life_-_Georgia_Travel_-_canon_camera_Eosm11_-_Creative_commons.ogv>
- Snowdonia: <https://commons.wikimedia.org/wiki/File:Snowdonia_by_drone.webm>
- CC BY-SA 4.0: <https://creativecommons.org/licenses/by-sa/4.0/>

## Reproduce the public lane

From the repository root:

```powershell
.\scripts\fetch-demo-assets.ps1 -Asset all
```

The script downloads into the ignored `demo-assets/` directory. It refuses a
file whose SHA-256 differs from the frozen intake value.

Verify already-downloaded files without network access:

```powershell
.\scripts\fetch-demo-assets.ps1 -Asset all -VerifyOnly
```

## Visual direction freeze

The selected Tbilisi frame audit established these bounded creative ranges:

| Direction | Typed operation | Candidate range | Visual purpose |
| --- | --- | ---: | --- |
| `faithful` | scene tone / contrast preserve | nominal `0.00` | Preserve the measured source relationship. |
| `amplified` | scene tone / contrast increase | `+0.30` to `+0.45` | Increase separation and architectural/traffic hierarchy without clipping. |
| `counterpoint` | scene look / saturation decrease | `-0.55` to `-0.40` | Quiet the warm/cool competition while retaining spatial structure. |

A real offline run rendered three samples per direction. All three candidates
passed asset-integrity, graph-schema, finite-value, and legal-output-gamut hard
checks, and the current Grade Graph remained unchanged pending confirmation.
This is engineering evidence, not a substitute for the formal independent expert
review or the frozen `0.15` full-pipeline diversity gate.

## DJI publication checklist

The current record is a user attestation, not the underlying certificate or full
license text. Before a public submission includes DJI-derived finished footage,
archive a redacted copy of the actual authorization and verify:

- exact licensor legal entity and licensee;
- asset/source identification;
- commercial use and modification/derivative rights;
- public display, online publication, and competition/showcase use;
- whether short extracts or source-like deliverables may be redistributed;
- territory, term, platform, and audience restrictions;
- required credit, watermark, or link format;
- music, talent, trademark, location, and other embedded rights;
- any restriction on sublicensing or making the source downloadable.

Until that review is complete:

- keep the 25.68 GB full ProRes source local;
- keep the approximately 1.05 GB five-second ProRes extract local;
- do not add either file to Git or Git LFS;
- use approximately **111.0–123.8 seconds** as the preferred local hero segment;
- publish only the Wikimedia public lane in reproducible examples.

## Size is a separate constraint

Even if redistribution were permitted, the DJI source is unsuitable for an
ordinary Git repository. GitHub Large File Storage can technically represent
large objects, but source video still creates clone, bandwidth, quota, and review
friction. The reproducible downloader plus immutable hash is the preferred public
workflow for the much smaller Commons media as well.

## Paused deliverable

No final demo video is created by this workflow. The 3–5 minute edit remains
explicitly paused; this document only freezes the media and visual plan for later.
