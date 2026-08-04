# Notes for anyone reproducing this

Read [`README.md §5`](README.md#5-installation-and-usage) first — the install
order matters and several steps fail silently if skipped.

Two things worth doing before you trust any result:

```bash
python -m config                                   # paths, GPU, scene xml
python diagnostics/diag_perfect.py <motion.npz>    # all six rewards must be 1.0000
```

The second one is the important one. It sets the state exactly to a reference
frame, where a perfect tracker must score 1.0000 on every term. Anything else
means a frame, reference-point or unit convention is wrong — and no policy can
score in that environment. We lost days to this before adding the check.

The pitfalls that produce **no error message** are collected in
[`docs/踩坑清单-Docker打包必读.md`](docs/zh/踩坑清单-Docker打包必读.md).
