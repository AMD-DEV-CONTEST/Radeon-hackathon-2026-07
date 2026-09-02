# Example outputs

Real artifacts from actual MeshSmith runs — not mockups. Open the `.glb` in any
glTF viewer (or drag onto https://gltf-viewer.donmccurdy.com). Each `report.md`
is the printability analysis MeshSmith generated for that same mesh.

Print STLs are not committed (tens of MB); regenerate any of these with:

```bash
python -m meshsmith.cli "a low-poly fox figurine" --quality draft --seed 1234
```

| File | Size |
|---|---:|
| `amphora_a-greek-amphora-vase-with-two-handles.glb` | 0.7 MB |
| `amphora_report.json` | 0.0 MB |
| `amphora_report.md` | 0.0 MB |
| `fox_a-low-poly-fox-figurine.glb` | 0.7 MB |
| `fox_report.json` | 0.0 MB |
| `fox_report.md` | 0.0 MB |
| `knob_a-replacement-drawer-knob-fluted-cylinde.glb` | 0.8 MB |
| `knob_report.json` | 0.0 MB |
| `knob_report.md` | 0.0 MB |
