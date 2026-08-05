# Upstream MetaDrive Issue Draft

This document is a draft for a real upstream issue. Confirm the exact final
traceback and upstream issue template before posting. Do not present the draft
itself as an upstream contribution.

## Suggested title

```text
[Bug] Offscreen RGBCamera effect setup fails without an X server and silent bypass changes observations
```

## Issue body

### Summary

MetaDrive 0.4.3 can fail while constructing an offscreen `RGBCamera` on a Linux
cloud instance with no X server, even when interactive rendering is disabled.
The failure occurs during SimplePBR/camera-effect setup because a required quad
is `None` before `set_shader` is called.

A process-local workaround that skips `Pipeline._setup_tonemapping` and
`RGBCamera._setup_effect` allows the environment to run, but it materially
changes RGB observations. Running the same configuration through Xvfb without
the workaround succeeds and preserves the expected observation distribution.

This matters for reproducible sensor-learning benchmarks: silently bypassing
the failed effects can produce valid-looking arrays while introducing a severe
camera-domain shift.

### Environment

```text
OS: Ubuntu/Linux 6.8 x86_64
Python: 3.12.3
MetaDrive: 0.4.3
GPU: AMD Radeon Graphics, gfx1100
ROCm/HIP: 7.2
PyTorch: 2.9.1+rocm7.2.1
Display: no physical X server; Xvfb is available
```

### Minimal reproducer

Run this from a terminal with no `DISPLAY`:

```python
from metadrive import MetaDriveEnv
from metadrive.component.sensors.rgb_camera import RGBCamera

env = MetaDriveEnv(
    {
        "use_render": False,
        "render_pipeline": False,
        "image_observation": True,
        "stack_size": 1,
        "sensors": {"rgb_camera": (RGBCamera, 84, 84)},
        "vehicle_config": {"image_source": "rgb_camera"},
        "num_scenarios": 1,
        "start_seed": 7,
        "map": "S",
    }
)

try:
    observation, info = env.reset()
    print(observation.shape)
finally:
    env.close()
```

Command:

```bash
unset DISPLAY
python reproduce_offscreen_rgb.py
```

### Observed behavior

Environment construction fails during camera/SimplePBR effect setup with the
essential error:

```text
AttributeError: 'NoneType' object has no attribute 'set_shader'
```

Before posting, replace this abbreviated excerpt with the complete original
traceback and exact file/line information from a clean reproduction.

### Expected behavior

One of the following would be preferable:

1. Offscreen RGB observations initialize correctly without a physical X server;
2. unsupported post-processing is disabled through a documented configuration
   path that preserves a defined observation contract; or
3. MetaDrive raises an early, actionable error explaining that an X server or
   Xvfb is required, instead of failing on a `None` quad.

### Validated workaround

The environment runs successfully when the same command is executed through
Xvfb, without monkey-patching MetaDrive:

```bash
xvfb-run -a python reproduce_offscreen_rgb.py
```

### Why skipping the effects is unsafe for data compatibility

We tested a raw-headless fallback that applies:

```python
from metadrive.component.sensors.rgb_camera import RGBCamera
from metadrive.third_party.simplepbr import Pipeline

Pipeline._setup_tonemapping = lambda self: None
RGBCamera._setup_effect = lambda self: None
```

The environment runs, but feature shifts relative to the validated training
stream are severe:

```text
camera_mean shift:            23.608 standard deviations
camera_std shift:             21.113 standard deviations
camera_temporal_delta shift:  37.511 standard deviations
```

LiDAR, speed, and packet-timing features remain unchanged, isolating the shift
to the camera rendering path.

With Xvfb and no effect bypass, a three-seed probe matches the original
15-dimensional training features exactly:

```text
mean_abs_diff = 0
shift_sd = 0
```

### Proposed improvement

I would be happy to submit one of the following after maintainer guidance:

- a guard that checks effect/tonemapping resources before shader assignment and
  raises an actionable initialization error;
- a documented, supported offscreen configuration for `image_observation=True`
  in display-less environments; and/or
- a documentation note recommending Xvfb when the validated camera-effect path
  is required for dataset compatibility.

### Additional context

The issue was found while developing ChronoSafe-Drive, an open Physical AI
sensor-degradation benchmark on AMD ROCm. Formal closed-loop results use Xvfb
without the raw-headless fallback. The invalid bypass measurements are reported
only to demonstrate why an explicit upstream behavior contract would be useful.

## Before posting

- [ ] Re-run the minimal reproducer without Xvfb.
- [ ] Save the complete traceback and replace the abbreviated error.
- [ ] Re-run the same script with Xvfb and record success.
- [ ] Confirm the exact MetaDrive/Panda3D/SimplePBR versions.
- [ ] Search existing upstream issues for duplicates.
- [ ] Remove any cloud hostname, token, or private path.
- [ ] Link the public ChronoSafe-Drive repository only after it is available.
