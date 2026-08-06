# BiGym 3DGS runtime overlay

The pinned `eust-w/amd-bigym-3dgs-rocm` interface patch imports
`bigym.utils.visual_shell` and `bigym.utils.visual_shell_assets`, but does not
include those modules in its BiGym patch. This directory carries the exact
runtime modules used by the verified AMD evaluation so a new checkout does not
depend on files left in an existing machine image.

`scripts/install_bigym_amd_overlay.sh` installs these modules after applying the
pinned upstream interface patch, then applies the repository's explicit ROCm
accelerator check. Scene PLY files and profiles are not included.
