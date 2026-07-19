# RDNA kernel templates

Every `.hip.template` file used in production today: written and tuned for
RDNA2/RDNA3's wave32 execution model, targeting `gfx1030`-`gfx1034` (RDNA2)
and `gfx1100`/`gfx1101`/`gfx1102` (RDNA3). `CodegenEngine.templates_dir`
resolves here directly. See [../cdna/README.md](../cdna/README.md) for the
sibling folder reserved for a future CDNA port.
