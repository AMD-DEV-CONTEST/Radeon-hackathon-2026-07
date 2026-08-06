# Live reconstruction examples

These folders contain the six five-view groups exposed by the Gradio demo. The
images are copied from the local PlantDreamer and PLANesT-3D datasets; camera
metadata is neither bundled nor used by the reconstruction path.

- PlantDreamer Bean 4 images retain their original 1080 px resolution.
- PLANesT-3D images are auto-oriented and resized to a maximum dimension of
  1600 px using JPEG quality 92. The model frontend resizes them further during
  inference.
- `configs/gradio_examples.toml` is the authoritative group manifest.

Verify the upstream dataset redistribution terms before publishing these image
copies outside the hackathon submission.
