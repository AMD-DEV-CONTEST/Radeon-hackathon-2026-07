# Canonical visual evidence

The images in this directory correspond only to the canonical DL3DV commercial
kitchen scene `90e70328f9196bc78c7e6c695c1e8cbb55a3c961cccf34c566966a5e2d8d8947`
at revision `e035bc5efd8dc5b2fa1e704cb2b1086fd9ec2c5c`.

- `canonical-source-contact-sheet.jpg`: selected authorized source trajectory
  views;
- `bigym-3dgs-runtime-demo.gif`: six-second, 900-pixel-wide, 8 fps inline
  preview of the user-supplied four-view BiGym + 3DGS runtime video; clicking
  it in either README opens the full-resolution MP4.
- `cutlery-cam-high-preview.gif`: a six-second, 640-pixel-wide excerpt starting
  at 330 seconds in the merged canonical `cam_high` H.264 stream; generated at
  10 fps with a 128-color palette for GitHub README playback.
- `amd-rocm-heldout-vs-reference.png`: left is the withheld canonical source
  frame; right is the full-resolution render produced after 15,000 OpenSplat
  HIP steps on AMD Radeon PRO W7900D. The combined image is `3840x1080`, SHA-256
  `f332b18cae3208fb769f481f65eb9a770ec631210477ae5a6d25c58e7720542b`.

These are review aids, not proof of all head/wrist camera frames. The Radeon
image supports the reconstruction gate only; the 32-episode three-camera
package remains a separate reference awaiting visual approval. Images are
subject to the applicable upstream and DL3DV dataset terms.
