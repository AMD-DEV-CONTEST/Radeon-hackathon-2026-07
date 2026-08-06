# SO-101 Grasp Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent scripted SO-101 lifts unless the measured fingertip target has converged and both fingers contact the cube, while emitting diagnostics that identify IK, joint tracking, TCP, and contact failures.

**Architecture:** Add a Genesis-independent grasp-control utility module for TCP transforms, convergence state, and contact classification. Keep Genesis IK and the existing velocity-limited joint path, but gate each grasp phase on measured TCP convergence and replace the direct close hold with a gradual, bilateral-contact-aware close routine.

**Tech Stack:** Python 3.10+, NumPy, Genesis World 1.1.x, standard-library `unittest`, Git.

---

## File Structure

- Create `simulation/grasp_control.py`: pure geometry, convergence, and contact-classification primitives with no Genesis import.
- Modify `simulation/scripted_pick.py`: measured TCP, structured motion result, convergence gate, gradual bilateral-contact close, and structured logs.
- Create `tests/test_grasp_control.py`: unit tests for every pure control primitive.
- Create `tests/test_scripted_pick.py`: simulator-free orchestration tests using a stub `simulation.genesis_env` module and small fake robot/bundle objects.

### Task 1: TCP Geometry and Stable Convergence

**Files:**
- Create: `tests/test_grasp_control.py`
- Create: `simulation/grasp_control.py`

- [ ] **Step 1: Write failing TCP and convergence tests**

Create tests that define the public API before production code exists:

```python
import unittest

import numpy as np

from simulation.grasp_control import ConvergenceWindow, local_point_world


class TcpGeometryTests(unittest.TestCase):
    def test_local_point_is_rotated_before_translation(self):
        half = np.sqrt(0.5)
        actual = local_point_world(
            link_pos=[1.0, 2.0, 3.0],
            link_quat_wxyz=[half, 0.0, half, 0.0],
            local_point=[0.0, 0.0, -0.1],
        )
        np.testing.assert_allclose(actual, [0.9, 2.0, 3.0], atol=1e-9)


class ConvergenceWindowTests(unittest.TestCase):
    def test_requires_consecutive_samples_and_resets_on_miss(self):
        window = ConvergenceWindow(tolerance=0.005, required_samples=3)
        self.assertFalse(window.update(0.004))
        self.assertFalse(window.update(0.003))
        self.assertFalse(window.update(0.006))
        self.assertFalse(window.update(0.002))
        self.assertFalse(window.update(0.002))
        self.assertTrue(window.update(0.001))
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_grasp_control -v
```

Expected: import failure for missing `simulation.grasp_control`.

- [ ] **Step 3: Implement the minimal pure geometry and convergence API**

Create `simulation/grasp_control.py` with:

```python
from dataclasses import dataclass

import numpy as np


def quat_rotate_wxyz(quat, vector):
    q = np.asarray(quat, dtype=np.float64).reshape(4)
    v = np.asarray(vector, dtype=np.float64).reshape(3)
    q = q / np.linalg.norm(q)
    w, x, y, z = q
    qv = np.array([x, y, z])
    return v + 2.0 * np.cross(qv, np.cross(qv, v) + w * v)


def local_point_world(link_pos, link_quat_wxyz, local_point):
    return np.asarray(link_pos, dtype=np.float64).reshape(3) + quat_rotate_wxyz(
        link_quat_wxyz, local_point
    )


@dataclass
class ConvergenceWindow:
    tolerance: float
    required_samples: int
    streak: int = 0

    def update(self, error: float) -> bool:
        self.streak = self.streak + 1 if error <= self.tolerance else 0
        return self.streak >= self.required_samples
```

- [ ] **Step 4: Run the tests and verify GREEN**

Run `python3 -m unittest tests.test_grasp_control -v`.

Expected: both tests pass.

- [ ] **Step 5: Commit the geometry/convergence unit**

```bash
git add simulation/grasp_control.py tests/test_grasp_control.py
git commit -m "test: define SO-101 grasp convergence primitives"
```

### Task 2: Finger Contact Classification

**Files:**
- Modify: `tests/test_grasp_control.py`
- Modify: `simulation/grasp_control.py`

- [ ] **Step 1: Write failing bilateral/unilateral contact tests**

Add tests using NumPy arrays shaped like Genesis `get_contacts()` output:

```python
from simulation.grasp_control import classify_finger_contacts


class ContactClassificationTests(unittest.TestCase):
    def test_detects_bilateral_contacts_and_force(self):
        contacts = {
            "link_a": np.array([10, 30, 20]),
            "link_b": np.array([30, 10, 30]),
            "force_a": np.array([[3.0, 4.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 6.0]]),
            "force_b": np.zeros((3, 3)),
        }
        summary = classify_finger_contacts(contacts, fixed_link_idx=10, moving_link_idx=20)
        self.assertTrue(summary.fixed)
        self.assertTrue(summary.moving)
        self.assertTrue(summary.bilateral)
        self.assertEqual(summary.count, 3)
        self.assertEqual(summary.max_force, 6.0)

    def test_ignores_invalid_and_unrelated_contacts(self):
        contacts = {
            "link_a": np.array([10, 20, 40]),
            "link_b": np.array([30, 30, 30]),
            "force_a": np.ones((3, 3)),
            "force_b": -np.ones((3, 3)),
            "valid_mask": np.array([True, False, True]),
        }
        summary = classify_finger_contacts(contacts, fixed_link_idx=10, moving_link_idx=20)
        self.assertTrue(summary.fixed)
        self.assertFalse(summary.moving)
        self.assertFalse(summary.bilateral)
        self.assertEqual(summary.count, 2)

    def test_empty_contacts_are_not_a_grasp(self):
        summary = classify_finger_contacts({}, fixed_link_idx=10, moving_link_idx=20)
        self.assertFalse(summary.bilateral)
        self.assertEqual(summary.count, 0)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python3 -m unittest tests.test_grasp_control.ContactClassificationTests -v
```

Expected: import failure for missing `classify_finger_contacts`.

- [ ] **Step 3: Implement contact normalization and classification**

Add a frozen `ContactSummary(fixed, moving, count, max_force)` dataclass and a
`classify_finger_contacts` function. Normalize Torch-like inputs by applying
`detach()`, `cpu()`, and `numpy()` when present, apply `valid_mask`, treat either
side of a pair as the robot link, and compute the maximum norm across both
`force_a` and `force_b`. Empty or malformed optional force arrays yield
`max_force=0.0`; absent link arrays yield an all-false, zero-count summary.

```python
@dataclass(frozen=True)
class ContactSummary:
    fixed: bool = False
    moving: bool = False
    count: int = 0
    max_force: float = 0.0

    @property
    def bilateral(self) -> bool:
        return self.fixed and self.moving


def _as_numpy(value):
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    return np.asarray(value)


def classify_finger_contacts(contacts, *, fixed_link_idx, moving_link_idx):
    if not contacts or "link_a" not in contacts or "link_b" not in contacts:
        return ContactSummary()
    link_a = _as_numpy(contacts["link_a"]).reshape(-1)
    link_b = _as_numpy(contacts["link_b"]).reshape(-1)
    valid = np.ones(link_a.shape, dtype=bool)
    if "valid_mask" in contacts:
        valid = _as_numpy(contacts["valid_mask"]).astype(bool).reshape(-1)
    link_a, link_b = link_a[valid], link_b[valid]
    fixed = bool(np.any((link_a == fixed_link_idx) | (link_b == fixed_link_idx)))
    moving = bool(np.any((link_a == moving_link_idx) | (link_b == moving_link_idx)))
    maxima = []
    for key in ("force_a", "force_b"):
        if key in contacts:
            force = _as_numpy(contacts[key]).reshape(-1, 3)[valid]
            if force.size:
                maxima.append(float(np.max(np.linalg.norm(force, axis=1))))
    return ContactSummary(fixed, moving, int(valid.sum()), max(maxima, default=0.0))
```

- [ ] **Step 4: Run all grasp-control tests and verify GREEN**

Run `python3 -m unittest tests.test_grasp_control -v`.

Expected: all geometry, convergence, and contact tests pass.

- [ ] **Step 5: Commit contact classification**

```bash
git add simulation/grasp_control.py tests/test_grasp_control.py
git commit -m "feat: classify bilateral Genesis finger contacts"
```

### Task 3: Measured TCP and Motion Convergence Gate

**Files:**
- Create: `tests/test_scripted_pick.py`
- Modify: `simulation/scripted_pick.py:20-231`

- [ ] **Step 1: Write failing motion-gate orchestration tests**

Before importing `simulation.scripted_pick`, register a `ModuleType` stub for
`simulation.genesis_env` containing `BASKET_HOME`, `BASKET_SIZE`, `CUBE_SIZE`,
and `TABLE_TOP_Z`. Test these externally visible behaviors:

```python
def test_run_aborts_before_close_when_grasp_motion_does_not_converge(self):
    picker = make_picker()
    picker._move_to = Mock(side_effect=[motion_ok(), motion_failed()])
    picker._close_until_contact = Mock()

    self.assertFalse(picker.run("red"))
    picker._close_until_contact.assert_not_called()


def test_tip_position_rotates_local_offset(self):
    picker = make_picker()
    picker.ee_link.get_pos.return_value = np.array([1.0, 2.0, 3.0])
    half = np.sqrt(0.5)
    picker.ee_link.get_quat.return_value = np.array([half, 0.0, half, 0.0])

    np.testing.assert_allclose(picker._tip_pos(), [0.902, 2.0, 3.0], atol=1e-6)


def test_motion_log_contains_solver_tracking_and_tcp_fields(self):
    picker = make_picker()
    output = io.StringIO()
    with redirect_stdout(output):
        picker._move_to(np.array([0.2, 0.0, 0.77]), phase="grasp", gripper=1.7)
    message = output.getvalue()
    for field in (
        "phase=grasp", "target_tip=", "actual_tip=", "error_vec=", "tcp_err=",
        "ik_err=", "joint_err=", "settle_steps=", "converged=",
    ):
        self.assertIn(field, message)
```

`make_picker()` supplies a real `ScriptedPickPlace` instance with small fake
cube, robot, link, scene, and bundle objects; `motion_ok()` and
`motion_failed()` create the planned `MotionResult` dataclass values.

- [ ] **Step 2: Run the focused tests and verify RED**

Run `python3 -m unittest tests.test_scripted_pick -v`.

Expected: failures for missing `MotionResult`, `_tip_pos`, and convergence gate.

- [ ] **Step 3: Implement measured motion results and exact TCP**

In `simulation/scripted_pick.py`:

- add `MotionResult` with `converged`, `arm_goal`, `target_tip`, `actual_tip`,
  `error_vector`, `tcp_error`, `ik_error`, `joint_error`, `interp_steps`, and
  `settle_steps`;
- resolve and log the Genesis IK API variant once;
- request `return_error=True` when supported and retain the position residual;
- calculate `_tip_pos()` using `ee_link.get_pos()`, `ee_link.get_quat()`, and
  `local_point_world(..., [0, 0, -EE_TIP_OFFSET])`;
- replace the fixed 12-step settle with at most `MOVE_SETTLE_MAX_STEPS = 120`;
- require `MOVE_STABLE_STEPS = 5` consecutive samples within
  `TCP_POS_TOL = 0.006` m;
- emit one motion summary line containing phase, target/actual TCP, error vector,
  TCP norm, IK norm, joint norm, step counts, and convergence status;
- make `_move_to(..., phase=...)` return `MotionResult`;
- have `run()` abort with the gripper open after failed pre-grasp or grasp
  convergence.

Use these exact data structures and TCP method:

```python
@dataclass(frozen=True)
class MotionResult:
    converged: bool
    arm_goal: np.ndarray
    target_tip: np.ndarray
    actual_tip: np.ndarray
    error_vector: np.ndarray
    tcp_error: float
    ik_error: float
    joint_error: float
    interp_steps: int
    settle_steps: int


def _tip_pos(self) -> np.ndarray:
    return local_point_world(
        _to_np(self.ee_link.get_pos())[:3],
        _to_np(self.ee_link.get_quat())[:4],
        [0.0, 0.0, -so101.EE_TIP_OFFSET],
    )
```

The convergence tail must follow this complete control rule after joint
interpolation:

```python
window = ConvergenceWindow(TCP_POS_TOL, MOVE_STABLE_STEPS)
actual_tip = self._tip_pos()
settle_steps = 0
converged = False
for settle_steps in range(1, MOVE_SETTLE_MAX_STEPS + 1):
    self._cmd(arm_goal, gripper, recorder=recorder)
    actual_tip = self._tip_pos()
    tcp_error = float(np.linalg.norm(actual_tip - target_tip))
    if window.update(tcp_error):
        converged = True
        break
measured_arm = _to_np(self.robot.get_dofs_position(so101.ARM_DOF))[:5]
error_vector = actual_tip - target_tip
result = MotionResult(
    converged=converged,
    arm_goal=arm_goal.copy(),
    target_tip=target_tip.copy(),
    actual_tip=actual_tip.copy(),
    error_vector=error_vector.copy(),
    tcp_error=float(np.linalg.norm(error_vector)),
    ik_error=ik_error,
    joint_error=float(np.max(np.abs(measured_arm - arm_goal))),
    interp_steps=n,
    settle_steps=settle_steps,
)
print(
    f"[pick] motion phase={phase} target_tip={result.target_tip.round(4).tolist()} "
    f"actual_tip={result.actual_tip.round(4).tolist()} "
    f"error_vec={result.error_vector.round(4).tolist()} tcp_err={result.tcp_error:.4f} "
    f"ik_err={result.ik_error:.4f} joint_err={result.joint_error:.4f} "
    f"interp_steps={result.interp_steps} settle_steps={result.settle_steps} "
    f"converged={result.converged}"
)
return result
```

- [ ] **Step 4: Run scripted-pick and utility tests and verify GREEN**

Run:

```bash
python3 -m unittest tests.test_grasp_control tests.test_scripted_pick -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit measured motion gating**

```bash
git add simulation/scripted_pick.py tests/test_scripted_pick.py
git commit -m "fix: gate SO-101 grasp on measured TCP convergence"
```

### Task 4: Gradual Bilateral-Contact Close

**Files:**
- Modify: `tests/test_scripted_pick.py`
- Modify: `simulation/scripted_pick.py:63-231`

- [ ] **Step 1: Write failing close and lift-gating tests**

Add fake contact sequences and assert:

```python
def test_close_succeeds_only_after_bilateral_contact(self):
    picker = make_picker(contact_sequence=[fixed_only(), bilateral(), bilateral()])
    self.assertTrue(picker._close_until_contact(
        picker.bundle.cubes["red"], np.zeros(5), np.zeros(3)
    ))


def test_close_fails_when_range_exhausts_without_bilateral_contact(self):
    picker = make_picker(contact_sequence=[fixed_only()] * CLOSE_RAMP_STEPS)
    self.assertFalse(picker._close_until_contact(
        picker.bundle.cubes["red"], np.zeros(5), np.zeros(3)
    ))


def test_run_does_not_lift_after_contact_failure(self):
    picker = make_picker()
    picker._move_to = Mock(side_effect=[motion_ok(), motion_ok()])
    picker._close_until_contact = Mock(return_value=False)

    self.assertFalse(picker.run("red"))
    self.assertEqual(picker._move_to.call_count, 2)


def test_close_log_contains_per_finger_contact_and_force(self):
    picker = make_picker(contact_sequence=[fixed_only()] * CLOSE_RAMP_STEPS)
    output = io.StringIO()
    with redirect_stdout(output):
        picker._close_until_contact(picker.bundle.cubes["red"], np.zeros(5), np.zeros(3))
    message = output.getvalue()
    for field in (
        "fixed_contact=", "moving_contact=", "contacts=", "max_force=",
        "gripper_cmd=", "gripper_q=",
    ):
        self.assertIn(field, message)
```

- [ ] **Step 2: Run close tests and verify RED**

Run `python3 -m unittest tests.test_scripted_pick -v`.

Expected: failures because `_close_until_contact` and contact-based lift gating
do not exist.

- [ ] **Step 3: Implement contact-aware closing**

In `ScriptedPickPlace.__init__`, resolve required links named `gripper` and
`moving_jaw_so101_v1`. Implement `_finger_contacts(cube)` with
`robot.get_contacts(with_entity=cube)` and `classify_finger_contacts`.

Implement `_close_until_contact` with:

- `CLOSE_RAMP_STEPS = 250` from measured open position to `GRIPPER_CLOSE`;
- arm goal held on every step;
- contact logging every 25 steps and at contact transitions;
- first bilateral contact recorded with command, measured jaw, TCP residual,
  contact count, and maximum force;
- `CONTACT_TIGHTEN = 0.35` rad applied over `TIGHTEN_STEPS = 80`;
- at most five consecutive lost-contact samples during tightening;
- success only when tightening finishes with bilateral contact.

The ramp and contact transition use this control shape:

```python
start_q = self._gripper_q()
for step in range(1, CLOSE_RAMP_STEPS + 1):
    alpha = step / CLOSE_RAMP_STEPS
    gripper_cmd = start_q + (so101.GRIPPER_CLOSE - start_q) * alpha
    self._cmd(arm_goal, gripper_cmd, recorder=recorder)
    contact = self._finger_contacts(cube)
    if step % CLOSE_LOG_INTERVAL == 0 or contact.bilateral:
        print(
            f"[pick] close step={step} gripper_cmd={gripper_cmd:.4f} "
            f"gripper_q={self._gripper_q():.4f} fixed_contact={contact.fixed} "
            f"moving_contact={contact.moving} contacts={contact.count} "
            f"max_force={contact.max_force:.3f} tcp_err="
            f"{np.linalg.norm(self._tip_pos() - target_tip):.4f}"
        )
    if contact.bilateral:
        contact_cmd = gripper_cmd
        break
else:
    self._close_failure_reason = "no_bilateral_contact"
    return False

tight_target = max(so101.GRIPPER_CLOSE, contact_cmd - CONTACT_TIGHTEN)
lost_streak = 0
for step in range(1, TIGHTEN_STEPS + 1):
    alpha = step / TIGHTEN_STEPS
    gripper_cmd = contact_cmd + (tight_target - contact_cmd) * alpha
    self._cmd(arm_goal, gripper_cmd, recorder=recorder)
    contact = self._finger_contacts(cube)
    lost_streak = 0 if contact.bilateral else lost_streak + 1
    if lost_streak > CONTACT_LOST_MAX_STEPS:
        self._close_failure_reason = "contact_lost"
        return False
return contact.bilateral
```

Replace `_hold(CLOSE_HOLD_STEPS, ...)` in `run()` with this method. On failure,
open for 30 control steps, print `reason=no_bilateral_contact` or
`reason=contact_lost`, and return before lift.

- [ ] **Step 4: Run all unit tests and verify GREEN**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests pass with no errors.

- [ ] **Step 5: Commit contact-aware closing**

```bash
git add simulation/scripted_pick.py tests/test_scripted_pick.py
git commit -m "fix: require bilateral contact before SO-101 lift"
```

### Task 5: Final Verification

**Files:**
- None

- [ ] **Step 1: Run fresh full verification**

Run each command and require exit code zero:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q simulation scripts tests
git diff --check
git status --short
```

Confirm only planned source, tests, and documentation are changed; leave
`.codegraph/` and `.cursor/` untouched.

- [ ] **Step 2: Document the unavailable integration check**

Record in the final handoff that local verification cannot run Genesis because
the local environment raises `ModuleNotFoundError: genesis`. Provide this exact
Radeon acceptance command:

```bash
python scripts/record_dataset.py --episodes 5 --max-attempts 5 --seed 0 \
  --save-debug-dir /tmp/so101_grasp_verify --overwrite
```

Expected on Radeon: each close begins only after TCP convergence; every lift
has bilateral contact; successful cubes rise by at least 20 mm. Any failure has
an explicit phase and residual/contact diagnostics.

### Task 6: Push the Verified Branch

**Files:** none

- [ ] **Step 1: Inspect final commits and remote target**

Run:

```bash
git status --short
git log -6 --oneline --decorate
git remote -v
git branch -vv
```

Expected: planned commits are on `main`, only the pre-existing `.codegraph/`
and `.cursor/` remain untracked, and `main` has an `origin/main` upstream.

- [ ] **Step 2: Push the current branch**

Run:

```bash
git push origin main
```

Expected: remote `origin/main` advances to the final verified commit.

- [ ] **Step 3: Verify the remote-tracking state**

Run:

```bash
git status -sb
git log -1 --oneline --decorate
```

Expected: local `main` and `origin/main` point at the same final commit.
