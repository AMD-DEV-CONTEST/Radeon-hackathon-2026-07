# Open pixel-conversion tooling survey

Research date: 2026-08-03. This survey uses project repositories and official
documentation as primary sources. It separates true-pixel recovery from editing
and production features because they solve different stages of the asset
pipeline.

## Practical user-facing workflow

For this project, the useful product is not another detector dashboard. It is a
small sprite workshop with four visible stages:

`import -> make transparent -> repair pixels -> split/compose/export`

The following functions are higher priority than adding another recovery
algorithm.

### One-click transparent background

The default pixel-art path should be deterministic rather than neural:

- sample the four corners and border to propose background colors;
- remove only similar-color regions connected to the canvas border, so white
  eyes or clothing inside the sprite are not accidentally erased;
- expose an eyedropper for adding/removing background colors and a tolerance
  slider with a live checkerboard preview;
- offer hard alpha, one-pixel feather, remove color fringe, close holes, remove
  tiny islands, and restore/erase mask brushes;
- process a folder or every frame with the same settings.

[Pixel Extractor](https://github.com/univeous/Pixel-Extractor) already combines
automatic/manual background-color removal with multi-sprite detection and
island cleanup. For painterly or photographic backgrounds, an optional
[rembg](https://github.com/danielgatis/rembg) backend can return a mask, apply
alpha matting, accept foreground/background points, and batch a folder. Neural
cutouts must be snapped back to hard or palette-aware alpha before pixel export.

### Manual true-pixel repair

The editor should operate on the recovered 1x grid even when displayed at 8x or
16x. The essential tools are:

- one-cell pencil and eraser;
- color picker and palette-locked drawing;
- bucket modes for contiguous region or every occurrence of a color;
- filled rectangle, line, selection, move, copy/paste, flip and mirror;
- transparent checkerboard, optional grid, before/after toggle and onion skin;
- unlimited or sufficiently deep undo/redo and autosaved project sessions;
- apply an edit to the current frame, selected frames, or all frames.

Two MIT projects provide most of the foundation. [Comfy Canvas](https://github.com/Zlata-Salyukova/Comfy-Canvas)
already supplies a persistent ComfyUI overlay with layers, masks, brush,
eraser, eyedropper, bucket, selection, transforms, undo/redo and autosave.
[Dotting](https://github.com/hunkim98/dotting) is a smaller embeddable React
pixel-grid editor with pen, eraser, fill, selection, line, rectangle and ellipse
tools. Extending one of these is substantially more practical than writing a
general canvas editor inside the snapper node.

### Multiple 2D images: split, align, compose and pack

"Combine 2D images" should cover three different user jobs:

1. **Split:** open an existing sheet, detect transparent components or a regular
   grid, adjust slice lines manually, name/reorder frames, and export individual
   PNG files.
2. **Compose:** place images as layers, snap them by center, feet line or a
   manual anchor, then merge body/clothes/hair/weapon sheets frame-for-frame.
   Single overlays can be repeated over every frame; matched sheets can be
   combined cell by cell.
3. **Pack:** arrange independent frames horizontally, vertically, in fixed
   rows/columns, or as a compact atlas. Support fixed cell size, transparent
   padding, edge extrusion, trim, duplicate removal, maximum atlas size and
   multi-page output.

Every operation needs animation preview, FPS control, frame duration, stable
pivot/anchor coordinates and a warning when frame dimensions or palettes do not
match. [Free Texture Packer](https://github.com/odrick/free-tex-packer) is an MIT
reference for rotation, trimming, duplicate detection, multipacking, sheet
splitting and Godot/Phaser/Cocos/Pixi/JSON exports. [EzSpriteSheet](https://github.com/z64me/EzSpriteSheet)
adds automatic pivot detection and animated GIF/WebP input, but its GPL-3.0
license makes it a feature reference rather than code to copy into this MIT
module.

### Export that is actually ready for a game

One export action should be able to produce:

- transparent 1x PNG files and nearest-neighbour preview PNGs;
- horizontal/vertical/grid/packed sprite sheets;
- GIF or animated WebP previews;
- a ZIP of named frames;
- atlas JSON containing frame rectangles, source size, trim offset, pivot,
  duration, animation tag and palette identifier;
- presets for Godot, Unity, RPG Maker and a plain portable JSON format.

The project session must remain non-destructive: original image, recovered 1x
image, transparency mask, manual pixel edits, layers, slices, anchors and export
settings should all be saved independently rather than flattened after every
step.

## Recommended practical delivery order

### First usable release

1. Border-connected background removal plus eyedropper/tolerance and mask brush.
2. A pixel-locked manual repair overlay with pencil, eraser, picker, bucket,
   selection and undo/redo.
3. Automatic/manual sprite splitting, frame reorder and fixed-grid stitching.
4. Per-frame auto-trim, common canvas normalization, feet/center/manual anchor,
   animation preview and PNG/ZIP/JSON export.

### Second release

1. Layered frame-for-frame composition for clothes, hair, weapons and effects.
2. Shared-palette enforcement, global color replacement and edits applied to
   selected/all frames.
3. Compact atlas packing, duplicate detection, multi-page atlases and engine
   presets.
4. Optional `rembg` for complex backgrounds, followed by pixel-aware alpha
   cleanup.

### Later polish

- outline/inset outline, shadow and palette ramp tools;
- frame-to-frame flicker and anchor-drift warnings;
- onion skin, tags, per-frame timing and batch naming templates;
- reusable export profiles for character sprites, icons, tiles and cards.

## Closest open-source recovery projects

| Project | License | Recovery approach | Additional functions worth noting |
|---|---|---|---|
| [Retro Diffusion Pixel Art Fixer](https://github.com/Retro-Diffusion/pixel-art-fixer) | MIT | Multiple phase-invariant detectors, consensus and arbitration; handles fractional/non-square cells, drift, warp, blur and JPEG interference | Confidence/decision metadata, fast/full modes, grid overlay, folder batch + JSON, alpha-majority reconstruction, Python reference and matching Rust binary, open 4,300-case distortion benchmark |
| [Pixel Extractor](https://github.com/univeous/Pixel-Extractor) | MIT | Edge detection and grid fitting derived from `ai-pixelart-extractor` | Non-square cells, automatic multi-sprite splitting, histogram or K-Means color cleanup, automatic/manual background removal, before/after slider, persistent history, offline PWA |
| [AI Pixel-Art Extractor](https://github.com/Donitzo/ai-pixelart-extractor) | MIT | Scientific-image-processing pipeline for badly aligned generated art | Batch path patterns, sprite splitting distance, extraction summary plots; detects virtual pixels down to roughly two source pixels |
| [Astropulse Pixel Detector](https://github.com/Astropulse/pixeldetector) | MIT | Restores resized or JPEG-damaged pixel art and predicts the downscale | Optional predicted palette reduction, simple CLI, Pillow/NumPy/SciPy reference |
| [ComfyUI Unfake Pixels](https://github.com/tauraloke/ComfyUI-Unfake-Pixels) | MIT | Edge-aware automatic scale estimation | Direct ComfyUI node; intentionally small feature surface |
| [Pixel Art Fixer thesis project](https://github.com/raresbit/pixelfixer) | Source available; repository does not state a standard license | Detects and corrects pixel-art craft defects rather than recovering a source grid | Interactive correction of banding and pillow shading; useful as a post-conversion lint/correction reference |

The most important architectural idea is Pixel Art Fixer's separation of grid
detection from reconstruction. It combines autocorrelation, run-length combs,
shift self-similarity, spectral/phase evidence, within-cell variance, and a
round-trip distillability score. Reconstruction uses a temporary adaptive
palette for structural voting but derives final colors from unquantized source
pixels, preserving rare highlights better than palette-clamped output.

## Palette, dithering and format converters

| Project | License | Functions beyond basic pixelation |
|---|---|---|
| [Image-to-Pixel](https://github.com/Tezumie/Image-to-Pixel) | MIT library; Apache-2.0 app | Floyd-Steinberg, Atkinson, ordered, clustered and Bayer dithers with strength control; Lospec/custom palettes; palette JSON import/export/cache; original-resolution or true-pixel export; browser editor and JavaScript API |
| [ComfyUI PixelArt Detector](https://github.com/dimtoneff/ComfyUI-PixelArt-Detector) | MIT | Six ComfyUI nodes; palette extraction/loading/preview/swapping; multiple quantizers including PIL, OpenCV K-Means and K-Medians; rare-color cleanup; prepared or mask-defined dithering; contain/fit/stretch geometry; WebP workflow embedding |
| [Dithertron](https://github.com/sehugg/dithertron) | GPL-3.0 | Hardware-accurate palettes and per-block color limits for C64, NES, ZX Spectrum, Game Boy and many other systems; crop/resize/dither; PNG, native binary and viewer-code export |
| [image_to_pixel_art_wasm](https://github.com/gametorch/image_to_pixel_art_wasm) | MIT | Rust/WASM browser library; learned or caller-supplied palette; alpha preservation; aspect-preserving fixed-grid conversion; returns PNG bytes plus palette |
| [2D Image Filter](https://github.com/Hawkynt/2dimagefilter) | LGPL-3.0 | Large family of pixel-art upscalers (Eagle, Scale, HQ, XBR/XBRz), reverse-AA, CRT/scanline effects, arbitrary resamplers, similarity thresholds, GUI/library/Paint.NET/CLI surfaces |

These projects suggest treating palette handling as a first-class object rather
than only a `k_colors` integer: import, lock, generate, preview, remap, sort,
dither, serialize and reuse palettes across every frame of a character.

## Editing, animation and game-ready export

| Project | License/status | Production functions |
|---|---|---|
| [Pixelorama](https://github.com/Orama-Interactive/Pixelorama) | MIT, free/open source | Layers, indexed color, non-destructive effects, palette management, timeline/onion skin/audio/frame tags, pixel-specific rotation/scaling, rectangular/isometric/hex tilemaps, spritesheet export and an extensible JSON-based project format |
| [LibreSprite](https://github.com/LibreSprite/LibreSprite) | GPL-2.0 | Layers and frames, live animation preview, onion skin, tiled drawing, palette tools, precise drawing/shading tools and multi-format animation export |
| [PixelOver](https://docs.pixelover.io/manual/introduction/) | Cross-platform commercial application; not an open-source dependency candidate | Non-destructive indexation/dithering/pixel-perfect lines, keyframes, bones, IK, mesh deformation, 2D/3D import, shaders, particles, color cycling, automatic rotation and spritesheet export |
| [SpriteBrew](https://github.com/GAlbanese09/spritebrew) | AGPL-3.0 shell; generation uses an external API | Upload/slice, pixel editor, animation preview, 4/8-direction and walk/idle/VFX generation workflows, exports for Unity/Godot/GameMaker/RPG Maker |

PixelOver is included as a feature benchmark only. Its documentation exposes a
particularly useful production target: animate transforms, drawings and shader
parameters without leaving the pixel-aware environment, then export image
sequences, GIFs or spritesheets.

## Recommended roadmap for this repository

The following additions have the highest value without compromising the two
existing algorithm contracts:

1. Add a third, explicitly non-compatible `consensus` detector modeled on the
   multi-detector idea: per-axis step candidates, confidence, harmonic rejection,
   JPEG-notch handling and a diagnostic grid overlay.
2. Decouple reconstruction from palette quantization. Use quantized labels to
   decide cell structure, but sample final RGB/alpha from the original image.
3. Add a palette value object and nodes for extraction, locking, Lospec import,
   remapping, rare-color cleanup, preview and JSON serialization.
4. Add optional dithering after true-pixel recovery, with Floyd-Steinberg,
   Atkinson and Bayer/ordered patterns. Never dither before grid detection by
   default because it can obscure the true period.
5. Add alpha/background processing: automatic and sampled-key removal, fringe
   cleanup, transparent-cell majority, and premultiplied-alpha-safe color votes.
6. Add spritesheet tools: component detection, automatic slicing, padding/crop,
   per-frame alignment, shared-palette enforcement and atlas JSON metadata.
7. Add animation consistency checks across a batch: stable grid and origin,
   shared palette, flicker/rare-color reports, onion-skin comparison and frame
   tags/durations in the export manifest.
8. Add game-asset transforms and exports: pixel-safe rotation, outlines,
   horizontal/vertical/grid/packed sheets, and Unity/Godot/RPG Maker metadata.
9. Build a distortion benchmark containing native sprites damaged by fractional
   scaling, axis asymmetry, blur, JPEG, noise, drift and broken alpha. Score
   native-size recovery, grid alignment, RGB/alpha error and runtime separately.

The proposed features should enter as deep modules behind the existing
`snap_images` seam or as separate palette/spritesheet interfaces. They should
not add conditionals to `legacy_exact`; that mode remains a frozen compatibility
contract.
