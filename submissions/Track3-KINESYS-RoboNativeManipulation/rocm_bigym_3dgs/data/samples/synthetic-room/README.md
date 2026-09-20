# Synthetic room fixture

The repository intentionally does not check in a DL3DV-derived PLY. CI creates
a tiny Apache-2.0 Gaussian room with:

- floor at `z=0`;
- ceiling at `z=3`;
- four perimeter walls;
- twelve synthetic camera poses;
- identity Gaussian-to-MuJoCo alignment.

Generate and export it with:

```bash
make smoke-reconstruction
```

This proves the binary PLY parser, spatial layer split, Sim(3) contract,
central-workspace exclusion, artifact hashes and physics-isolation metadata. It
does **not** prove GPU rendering or visual quality.
