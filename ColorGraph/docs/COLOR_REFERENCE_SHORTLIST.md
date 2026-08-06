# Color Reference and Backup Demo Shortlist

Research freeze: **2026-08-02**

This shortlist selects professionally finished reference material and public
backup footage for ColorGraph. It does not resume the final demo-video edit.
No source video from this list has been added to Git, and no new asset should
enter the reproducible downloader until its exact object, license copy, checksum,
and attribution have been frozen.

## Selection

| Priority | Candidate | Source-to-grade evidence | Public use | Frozen role |
| --- | --- | --- | --- | --- |
| P0 | **Netflix `Sparks`** | Sony F55 RAW, non-graded ACES master, graded ACES master, display master, and finished encodes | Yes, with CC BY 4.0 attribution | Primary professional look reference and paired calibration benchmark |
| P1 | **Blender `Tears of Steel`** | Original Sony F65 footage/EXR material and a finished 4K re-grade | Yes, with CC BY 3.0 attribution and separate audio care | Live-action source-to-finish backup |
| P1 | **Netflix / Blender `Cosmos Laundromat`** | Original open movie plus a professional Dolby Vision HDR re-grade | Yes, with CC BY attribution | Stylized palette and HDR creative-look backup |
| P1 | **Blackmagic Design Colorist Guide 20** | Camera media, authored exercises, node work, and completed/solved timelines | Local study only unless separate permission is confirmed | Best professional imitation-learning curriculum |
| P2 | **Netflix `Meridian`** | Professionally mastered SDR/HDR deliverables, but no compact ungraded pair | Yes, with CC BY 4.0 attribution | HDR/output-transform and playback regression |

The first implementation target should be `Sparks`. It is the only shortlisted
title that combines a named professional grade, aligned non-graded and graded
ACES masters, a finished viewing encode, explicit open licensing, and the same
high-highlight / deep-shadow conditions that ColorGraph is designed to protect.

## P0 — Netflix `Sparks`

Official sources:

- [Netflix Open Content](https://opencontent.netflix.com/home)
- [Engineers Making Movies](https://netflixtechblog.com/engineers-making-movies-aka-open-source-test-content-f21363ea3781)
- [Current CC BY 4.0 license copy](https://download.opencontent.netflix.com.s3.amazonaws.com/sparks/creative-commons-attribution-4-intl-public-license.txt)
- [Legacy asset manifest and download instructions](https://download.opencontent.netflix.com.s3.amazonaws.com/TechblogAssets/README.txt)

Netflix documents this production chain:

```text
Sony F55 16-bit RAW SQ
  -> Non-Graded Archival Master (NAM), ACES linear
  -> Graded Archival Master (GAM), ACES linear
  -> 4000-nit P3-D65/PQ Video Display Master (VDM)
  -> Dolby Vision / HDR10 / SDR deliverables
```

The master grade was refined at Dolby on a 4000-nit Pulsar display. The reviewed
SDR encode credits **Matthew Donato** as colorist and **Shane Mario Ruggieri** as
high-dynamic-range colorist.

### Why it fits ColorGraph

- welding arcs and showers of sparks test highlight reconstruction and roll-off;
- dark steel, backlit workers, and open sky create extreme simultaneous contrast;
- orange sparks against green/blue daylight expose hue-separation decisions;
- helmets, clothing, faces, red fabric, and puddle reflections are useful mask
  and subject-protection targets;
- the aligned NAM/GAM/VDM frames allow measurement against an actual final grade,
  rather than judging only by taste.

### Audited viewing asset

- SDR preview: `Sparks_4096x2160_5994fps_SDR.mp4`
- 4096 × 2160, 60000/1001 fps, 229.888 seconds, H.264/AAC
- 419,744,507 bytes (400.30 MiB)
- direct object: <https://download.opencontent.netflix.com.s3.amazonaws.com/TechblogAssets/Sparks/encodes/Sparks_4096x2160_5994fps_SDR.mp4>

Remote random-access frame inspection established two useful windows:

- **96–123 s — primary hero:** close and wide welding shots, airborne sparks,
  dark structural steel, green daylight, and puddle reflections;
- **146–162 s — continuity/skin secondary:** hard hats, faces, dark workwear,
  saturated red clothing, blue sky, and green landscape.

For a lightweight paired benchmark, start with timestamps **98 s, 108 s, and
118 s**. Download only the matching NAM and GAM frames first. Each EXR is about
50.66 MiB, so the three two-way pairs are about 304 MiB; adding the three VDM
frames raises the set to about 456 MiB. Verify frame alignment visually before
freezing exact frame numbers and SHA-256 values.

Do **not** mirror the complete material:

- NAM: approximately 681.6 GB;
- GAM: approximately 681.6 GB;
- VDM: approximately 681.6 GB;
- three published Sony RAW camera clips: approximately 57.1 GB total.

Recommended use: show a credited `Sparks` frame as the professional reference,
apply its measurable tonal and palette principles to a different open source
clip, and use the NAM/GAM samples only for engineering calibration.

## P1 — Blender `Tears of Steel`

Official sources:

- [Project and license](https://mango.blender.org/about/)
- [Original 4K sample frames](https://mango.blender.org/production/first-original-footage-frames-in-4k/)
- [4K re-graded release on Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Tears_of_Steel_in_4k_-_Official_Blender_Foundation_release.webm)

This is the strongest live-action public backup because the Blender Foundation
released the film, original footage, and studio-created production material as
open content. The finished 4K release is 3840 × 1714, 24 fps, 734.055 seconds,
and 958,806,974 bytes (914.39 MiB). It combines faces, mixed lighting, sky,
greenscreen plates, VFX integration, and strong narrative color continuity.

The complete source archive is measured in hundreds of gigabytes to terabytes,
so use the official five-frame 4K sample pack or a single scene-level EXR subset.
Do not attempt to fetch the full raw archive for the hackathon.

The soundtrack has separate CC BY-ND constraints described by the project. A
ColorGraph excerpt should therefore be silent or use independently cleared audio
unless the exact audio use is reviewed. The visual hero timestamp remains
unfrozen until a local proxy can be audited without stressing Wikimedia's public
servers.

## P1 — Netflix / Blender `Cosmos Laundromat`

Official sources:

- [Netflix Open Content re-grade](https://opencontent.netflix.com/home)
- [Current CC BY 4.0 license copy](https://download.opencontent.netflix.com.s3.amazonaws.com/CosmosLaundromat/creative-commons-attribution-4-intl-public-license.txt)
- [Original Blender open movie](https://video.blender.org/w/wfW3bDTkUhQKRnEfT9Wpeq)

Netflix partnered with Blender Foundation and FotoKem's Keep Me Posted to
re-grade this film in Dolby Vision HDR. That makes it a rare openly usable,
professionally re-graded comparison source.

The audited Netflix SDR preview is 2048 × 858, 24 fps, 730.069 seconds, and
491,245,034 bytes (468.49 MiB). The 2K P3/PQ HDR MP4 is about 0.68 GiB. Visual
inspection favors:

- **200–220 s:** warm red hair and skin-like facial materials against a cool blue
  environment;
- **290–315 s:** dark fur, saturated foreground color, and controlled separation;
- the later laundromat sequence for intense multi-hue and emissive-light tests.

Use it for palette reasoning, HDR gamut mapping, and deliberately stylized
`amplified` / `counterpoint` proposals. Do not use it as evidence for real-camera
noise, natural human skin, or camera-log reconstruction.

## P1 — Blackmagic Design Colorist Guide 20

Official sources:

- [Blackmagic Design training page](https://www.blackmagicdesign.com/products/davinciresolve/training)
- [The Colorist Guide to DaVinci Resolve 20](https://documents.blackmagicdesign.com/UserManuals/DaVinci-Resolve-20-Colorist-Guide.pdf)

The guide is authored by professional colorist **Daria Fissoun, CSI**. Its three
downloadable lesson projects include media and completed timelines intended for
comparison and troubleshooting:

1. documentary balancing, shot matching, continuity, windows, and tracking;
2. REDWideGamutRGB/Log3G10 narrative material, creative looks, and grade transfer;
3. a commercial workflow using groups, film emulation, masks, keyframes, and
   noise treatment.

This is the best curriculum for learning *why* a professional makes a decision
and how a node structure supports it. Translate those decisions into ColorGraph's
typed operations and protections; do not copy a node tree blindly.

No explicit public-redistribution or machine-training license for the lesson
media was identified in this review. Keep all lesson files local, do not place
them in Git or a public demo package, and do not use them to train model weights
without separate written permission. They may be used as private human study and
manual regression references under the supplied training workflow.

## P2 — Netflix `Meridian`

`Meridian` is a professionally mastered narrative test title available through
[Netflix Open Content](https://opencontent.netflix.com/home). The compact HDR
P3/PQ MP4 is about 0.79 GiB; an SDR 3840 × 2160, 59.94 fps preview is about
1.21 GiB. It is useful for checking HDR-to-SDR transforms, playback, subtitles,
and final-delivery behavior.

The current asset directory includes a
[CC BY 4.0 license copy](https://download.opencontent.netflix.com.s3.amazonaws.com/Meridian/creative-commons-attribution-4-intl-public-license.txt).

It is not a first-choice imitation benchmark because no compact aligned
ungraded/graded pair is published. Use it after `Sparks`, not instead of it.

## Candidates intentionally not selected

- **Netflix `Nocturne`:** strong night and grain stress material, but the
  published film-grain MOV files are about 88–91 GB and no compact source/grade
  pair is exposed.
- **Netflix `Chimera`:** useful low-light dinner imagery, but its smallest listed
  HDR MP4 is about 2.36 GiB and it adds less learning value than `Sparks`.
- **Unlicensed YouTube/Vimeo colorist reels:** useful for private visual study,
  but unsuitable as a reproducible or redistributable hackathon dependency.
- **Paid practice libraries:** potentially useful later, but a purchase and its
  exact portfolio/publication license should be approved separately.

## Safe imitation-learning protocol

The goal is to learn repeatable decisions, not copy an opaque LUT or reproduce a
finished frame pixel for pixel.

1. Normalize the source and reference through declared input/display transforms.
2. Measure global exposure, contrast pivot, highlight shoulder, saturation, and
   hue-family relationships.
3. Identify protected subjects and spatial decisions such as faces, sky, sparks,
   dark workwear, and reflective surfaces.
4. Express the result as typed, bounded Grade Graph operations with a written
   intent and protected-region contract.
5. Render `faithful`, `amplified`, and `counterpoint` variations on a different
   open source clip; never replace the source with the reference image.
6. Evaluate highlight clipping, legal gamut, skin/subject drift, temporal
   consistency, and distance from both neutral and the professional reference.
7. Preserve title, creator/rightsholder, source URL, license URL, and a clear
   modification notice in every published derivative.

This protocol is suitable for reference-conditioned evaluation and human-guided
look development. Any later dataset construction or model-weight training needs
a separate rights and provenance review.

## Next bounded action

When asset work resumes, create a small `reference-pack-v1` rather than fetching
entire productions:

1. Netflix license file and `Sparks` 400.30 MiB SDR preview;
2. three aligned `Sparks` NAM/GAM frame pairs at 98/108/118 seconds;
3. one silent `Tears of Steel` scene or the official five-frame source pack;
4. the `Cosmos Laundromat` SDR preview only if stylized HDR comparison is needed;
5. immutable SHA-256 values, media metadata, exact credit strings, and contact
   sheets generated locally under ignored directories.

No final demo video is part of this action.
