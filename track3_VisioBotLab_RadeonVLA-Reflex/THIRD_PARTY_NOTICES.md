# Third-Party Notices

RadeonVLA-Reflex depends on or references the following upstream projects:

| Project | Purpose | Source |
|---|---|---|
| Genesis World | Physics simulation | Apache-2.0 · https://github.com/Genesis-Embodied-AI/Genesis |
| LeRobot | Dataset, policy training, and SmolVLA | https://github.com/huggingface/lerobot |
| SmolVLA | Vision-language-action base model | No license metadata declared at frozen revision · https://huggingface.co/lerobot/smolvla_base |
| Franka Fruit-Pick Demo | Track 3 workflow reference | https://github.com/wangxunx/franka_fruit_pick_demo |
| YCB Object Set | Candidate simulation assets | https://www.ycbbenchmarks.com/object-models/ |

Each dependency and asset remains subject to its own license and attribution
requirements.

The Franka Fruit-Pick Demo is used only as a workflow reference for Genesis + LeRobot
on ROCm and is not vendored as source code in this tree.

### Bundled simulation assets under `assets/`

| Asset | Bundled path | Upstream |
|---|---|---|
| Franka Emika Panda MJCF | `assets/robots/franka/` | Apache-2.0 · Genesis World package assets |
| YCB banana / apple / lemon / orange / plum / bowl | `assets/ycb/<id>/` | CC BY 4.0 · [YCB Object and Model Set](https://www.ycbbenchmarks.com/object-models/) |

YCB project pages:

- https://www.ycbbenchmarks.com/object-models/
- http://ycb-benchmarks.s3-website-us-east-1.amazonaws.com/

The official YCB data portal identifies the dataset license as
[Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/).
RadeonVLA-Reflex uses the textured meshes and derived collision geometry in simulation;
blue bowl color is applied at runtime. Cite the YCB papers and link the license when
redistributing the meshes or rendered Physical-1K dataset.

Integrity: `assets/SHA256SUMS` and `python -m radeonvla.setup_assets --verify`.
Blue bowl appearance is applied in scene code (entity surface color), not by editing
the upstream YCB texture files.
