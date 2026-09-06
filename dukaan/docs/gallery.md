# Gallery

Every image below came out of one `dukaan pack` run against a Radeon PRO
(gfx1100, 48 GB) through ROCm, generated at **1536x1536** with the refine
pass on, so the stills are downscaled into their formats rather than
stretched up. Each row is a single GPU pass: one clip, and
three stills lifted from three different moments of it.

The input photographs are CC0 museum object shots, credited in
[../examples/CREDITS.md](../examples/CREDITS.md). Nothing in the product itself
is generated: the model lights a scene around a cutout it is told not to change,
and the type is composited afterwards.

---

## Every product, every style

Twelve packs: each product run under each look. One photograph in four styles
shows the styles work; this shows they work across the catalogue rather than on
one lucky input.

![style matrix](gallery/style-matrix.png)

Look at the bangles on the festive ground: the marigolds show *through* the ring
interiors. That is the cutout correctly treating an enclosed pocket of backdrop
as backdrop, which an earlier version got wrong by filling it and turning two
rings into two discs.

**The styles do not all relight to the same degree, and the grid shows it.**
Studio, festive and midnight keep the flat catalogue view they were given.
Daylight, whose plate backdrop sits furthest from a plain sweep, sometimes
re-stages instead: the silver bracelet comes back standing on the wooden surface
with real depth rather than lying flat. Its identity is intact, the dragon heads,
the engraving, the open gap and the border pattern all match the photograph, but
the model has inferred volume that the flat input did not contain. That is worth
knowing before choosing a style for a product whose exact shape matters.

The blue-and-white porcelain vase is deliberately absent. Its photograph carries
a vignette behind the object that the backdrop fit cannot see, and the patch it
leaves is fused to the vase, so it comes out with a streak beside it. Several
ways of removing it were measured and none paid for itself; the numbers are in
[profile.md](profile.md), section 4.2. Showing it here as though it were good
output would be the dishonest choice.

---

## The product survives the generation

`strength=0.7` on the image-to-video conditioning means the model is genuinely
allowed to alter the product, so this is a claim to be checked rather than
asserted. Each row is one pack: the plate the model was handed, then the frames
the pack actually selected.

![product survives](gallery/product-survives.png)

The corrosion marks on the bangles, the engraving and pitting on the ewer, and
the dragon heads on the bracelet all carry through unchanged while the scene
around them is rebuilt completely. The brass ewer row is the clearest: a flat
maroon wash becomes full festive bokeh, and the object does not move.

This is shown rather than scored on purpose. A pixel metric against the plate
measures the camera, not the product: the motion prompt pushes the camera in, so
by the later frames the object is legitimately larger and in a different place,
and a mask taken from the plate lands on the wrong pixels. Aligning that away
was attempted several times and kept disagreeing with what the crops plainly
show, so the crops are the evidence.

---

## One photo, four looks

The same photograph under every style Dukaan ships. Only the style name changed
between these four runs; the ewer is identical in all of them, which is the
point. A seller cannot post a picture of a thing they will not ship.

![four styles](gallery/one-photo-four-styles.png)

---

## Handmade brass ewer, festive

Plate the model was given, then the three creatives.

<img src="gallery/brass-ewer-plate.png" width="260">

| square, frame 16 | story, frame 20 | banner, frame 48 |
|---|---|---|
| <img src="gallery/brass-ewer-square.png" width="240"> | <img src="gallery/brass-ewer-story.png" width="135"> | <img src="gallery/brass-ewer-banner.png" width="300"> |

![clip](gallery/brass-ewer-clip.gif)

65.3 s of GPU time. The banner is the case that drove the reflection fix:
stretching the edge column instead drew the bokeh into horizontal streaks.

---

## Hand-worked silver bangle, studio

<img src="gallery/silver-bracelet-plate.png" width="260">

| square, frame 13 | story, frame 21 | banner, frame 48 |
|---|---|---|
| <img src="gallery/silver-bracelet-square.png" width="240"> | <img src="gallery/silver-bracelet-story.png" width="135"> | <img src="gallery/silver-bracelet-banner.png" width="300"> |

![clip](gallery/silver-bracelet-clip.gif)

72.6 s of GPU time. The bangle's engraving survives the pass intact, which is
the thing that matters: a seller cannot ship a creative where the model has
redesigned the product.

---

## What the numbers were

| product | style | GPU | wall clock | frames | stills from |
|---|---|---|---|---|---|
| brass ewer | festive | 65.3 s | 2 m 20 s | 49 | 16, 20, 48 |
| silver bangle | studio | 72.6 s | 2 m 19 s | 49 | 13, 21, 48 |

Wall clock includes the plate upload, both model loads and pulling 49 frames
plus a wav back over the tunnel. Before frames were fetched as one tar it was
3 m 34 s.
