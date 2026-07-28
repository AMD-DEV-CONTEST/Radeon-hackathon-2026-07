# CDNA kernel templates

Empty for now. Reserved for CDNA (Instinct/MI, wave64) kernel variants, should
that portability investigation happen. Every kernel currently in `../rdna/`
was written and tuned for RDNA2/RDNA3's wave32 execution model and has never
been validated on real CDNA hardware; some (wave-level reductions using
`warpSize` dynamically) may port with no changes, others may need a real
wave64 rewrite. See [docs/LIMITATIONS.md](../../../../docs/LIMITATIONS.md#hardware-portability)
for what's already known about the RDNA-only assumptions baked into the
current kernel set.

`CodegenEngine.templates_dir` resolves to `templates/rdna/` directly today;
adding real architecture-family selection (picking `rdna/` vs `cdna/` based
on the detected GPU) is future work, not implemented yet.
