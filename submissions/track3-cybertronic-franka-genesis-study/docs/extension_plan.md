# Extension Plan: Vision-Guided Franka Fruit Tracking

## Recommended Direction

Use the camera to estimate the fruit target instead of directly reading the preset 3D target coordinates.

This direction is the best fit for the current project because the existing demo already has:

- A Franka Panda robot arm
- A moving red fruit target
- An offscreen camera
- Inverse kinematics control
- Tracking-error metrics
- MP4 recording output

Compared with grasping, collision/contact simulation, LeRobot dataset generation, imitation learning, or VLA training, vision-guided tracking is easier to implement in a short competition cycle while still producing a clear upgrade in technical depth and demo quality.

## Competition Story

Current baseline:

The robot follows a target using its known simulation coordinates.

Planned extension:

The robot follows the target from camera observations. The visual tracker detects the red fruit in rendered camera frames, estimates image-space error, and drives the end effector through a simple visual servoing loop.

This changes the demo from scripted target following into perception-driven closed-loop control.

## Implementation Scope

### Phase 1: Camera-Based Red Target Tracking

Add a lightweight vision module:

- Capture RGB frames from the Genesis camera.
- Segment red pixels using HSV or RGB thresholding.
- Estimate the fruit center in image coordinates.
- Record detection confidence, bounding box, and center position.

Expected files:

```text
src/vision_tracking.py
configs/franka_vision_tracking.json
```

### Phase 2: Visual Servoing Control

Use image-space error to adjust the end-effector target:

- Keep a nominal 3D tracking target near the working area.
- Use the detected fruit center to compute horizontal and vertical image error.
- Convert image error into small Y/Z target corrections.
- Continue using Genesis inverse kinematics and PD joint control.

This avoids fragile full 3D reconstruction while still showing camera-driven closed-loop behavior.

Expected files:

```text
src/franka_vision_servo.py
scripts/franka_vision_servo.py
```

### Phase 3: Better Demo Output

Improve evaluation and presentation:

- Save per-frame visual tracking metrics.
- Save robot tracking metrics.
- Render an annotated video with detection center, target center, and tracking status.
- Compare baseline coordinate-following vs vision-guided following.

Expected outputs:

```text
outputs/videos/franka_vision_servo.mp4
outputs/metrics/franka_vision_servo.json
results/franka_vision_servo_summary.json
```

Only lightweight summary files should be committed. Generated MP4 files remain ignored by Git.

## Success Metrics

The extended demo should report:

- Fruit detection success rate
- Mean image-space tracking error in pixels
- Mean end-effector tracking error in millimeters
- Mean IK latency
- Runtime and GPU/backend information

Target competition-ready goals:

- Detection success rate above 95%
- Mean end-effector tracking error below 20 mm
- Stable 300-frame video generation
- Clear annotated video showing perception and control

## Why Not Other Directions First

### Real Grasping

Grasping would look impressive, but it requires stable contact, friction tuning, gripper control, object dynamics, and success/failure handling. It has a higher risk of unstable behavior under deadline pressure.

### Collision, Contact, and Friction

This is useful for realism, but by itself it is less visually distinctive than perception-driven tracking. It can be added later once the visual tracking loop is stable.

### LeRobot Dataset

Dataset export is relatively feasible, but it is less compelling as the main demo unless paired with a learning pipeline. It is better as an optional second extension after vision tracking works.

### Imitation Learning or VLA

These are strong research directions but likely too heavy for a short competition iteration. They require data collection, training, evaluation, and fallback behavior.

## Recommended Roadmap

1. Implement red fruit detection from rendered camera frames.
2. Add a `--control-mode coordinate|vision` switch.
3. Implement image-space visual servo corrections.
4. Add annotated video overlays.
5. Add metrics comparison between baseline and vision mode.
6. Update README with the new demo command, results table, and video link.

## Minimal Deliverable

The minimal competition deliverable should include:

```text
src/vision_tracking.py
src/franka_vision_servo.py
scripts/franka_vision_servo.py
configs/franka_vision_tracking.json
results/franka_vision_servo_summary.json
docs/extension_plan.md
```

The original baseline command should continue to work:

```bash
python scripts/franka_fruit_follow.py
```

The new extension command should be:

```bash
python scripts/franka_vision_servo.py
```
