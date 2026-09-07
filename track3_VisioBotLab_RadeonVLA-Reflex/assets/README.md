# Assets

Simulation meshes required by the Franka dual-bowl scene ship **inside this
repository** under `assets/`. A normal `git clone` is sufficient for reproduction;
no private mirror is required.

## Layout

```text
assets/
  SHA256SUMS
  robots/franka/panda.xml   # Franka Emika Panda MJCF (+ meshes)
  ycb/
    011_banana/
    013_apple/
    014_lemon/
    017_orange/
    018_plum/
    024_bowl/               # mesh reused by four bowl entities (two painted blue)
```

Each YCB folder contains at least `textured.obj` and `collision.ply` (plus textures).

## Verify integrity

```bash
python -m radeonvla.setup_assets --verify
# or:
sha256sum -c assets/SHA256SUMS
```

## If assets are missing (sparse checkout / accidental delete)

```bash
python -m radeonvla.setup_assets
# optional network fallback for YCB packs:
python -m radeonvla.setup_assets --download
```

Fallback order implemented in `radeonvla.setup_assets`:

1. files already under `assets/` (project tree);
2. local development mirrors (optional);
3. Franka model from the installed `genesis-world` package;
4. with `--download`, optional YCB archive URLs listed in `setup_assets.py`.

## Sources and attribution

| Asset | Upstream |
|---|---|
| Franka Panda MJCF | Genesis World bundled assets |
| YCB banana / apple / lemon / orange / plum / bowl | [YCB Object and Model Set](https://www.ycbbenchmarks.com/object-models/) (meshes redistributed for simulation; also commonly packaged via ManiSkill) |

Public project pages:

- YCB Object and Model Set: https://www.ycbbenchmarks.com/object-models/
- YCB data portal: http://ycb-benchmarks.s3-website-us-east-1.amazonaws.com/
- Genesis World: https://github.com/Genesis-Embodied-AI/Genesis

See `THIRD_PARTY_NOTICES.md` for license notes. Blue bowl colors are applied at scene
build time in code (not baked into the YCB texture).
