# Third-Party Notices

The following open-source projects are runtime dependencies. Their source is
downloaded at the locked revisions by the bootstrap and Docker build; it is not
vendored in this repository.

| Project | Locked revision | License | Intended use |
| --- | --- | --- | --- |
| Genesis World | `ec0efcc0daf9b9932920e6b73f5f810961330997` | Apache-2.0 | ROCm physics, sensors, rendering, robot control |
| Bi-Franka MJCF | Included in locked Genesis World; header credits `vikashplus/franka_sim` | Apache-2.0 | Runtime source for the generated wheeled dual-arm embodiment |
| LeRobot | `73dbb6f43a5088583706c91fb73c6957bca5f806` | Apache-2.0 | Dataset format, ACT, Diffusion, and SmolVLA policy paths |
| SmolVLM2-500M-Video-Instruct | `7b375e1b73b11138ff12fe22c8f2822d8fe03467` | Apache-2.0 | Vision-language initialization for the locally trained SmolVLA checkpoint |
| PyTorch | Cloud image version | BSD-style | ROCm model training and inference |

No third-party source is committed in this project. Sources downloaded under
`third_party/` remain excluded from Git and retain their upstream notices.

`scripts/smoke_genesis.py` is an original integration smoke test based on API
usage demonstrated by these Apache-2.0 Genesis World examples:

- `examples/rigid/franka_cube.py`
- `examples/tutorials/control_your_robot.py`
- `examples/sensors/depth_camera_custom_vverts.py`
