"""Align local SO-101 MJCF with the working ggand0/pick-101 grasp model.

Source of truth for these edits:
  https://github.com/ggand0/pick-101 (models/so101/so101_new_calib.xml)
  https://ggando.com/blog/so101-rl-lift/

Differences vs stock TheRobotStudio SO101 that break grasping in practice:
  * collision default missing contype/conaffinity
  * gripperframe TCP not centered between fingers
  * no fingertip box pads (mesh-mesh contacts are unstable)
  * gripper actuator forcerange too weak (±3.35 vs pick-101 ±10)
"""

from __future__ import annotations

from pathlib import Path

_STATIC_PAD = (
    '                <geom name="static_finger_pad" type="box" '
    'size="0.00125 0.00125 0.00125" pos="-0.008875 0.0 -0.100" '
    'rgba="1 0.5 0.5 0.8" contype="1" conaffinity="1" '
    'friction="1 0.005 0.0001"/>\n'
)
_MOVING_PAD = (
    '                  <geom name="moving_finger_pad" type="box" '
    'size="0.00125 0.00125 0.00125" pos="-0.01136 -0.076 0.019" '
    'rgba="0.5 0.5 1 0.8" contype="1" conaffinity="1" '
    'friction="1 0.005 0.0001"/>\n'
)


def _apply_pick101_alignments(text: str) -> str:
    """Apply all pick-101 grasp-critical MJCF edits (idempotent string replaces)."""
    # 1) Collision geoms must participate in contact.
    text = text.replace(
        """      <default class="collision">
        <geom group="3"/>
      </default>""",
        """      <default class="collision">
        <geom contype="1" conaffinity="1" group="3"/>
      </default>""",
    )

    # 2) Center TCP (pick-101 comment: "centered between fingers").
    text = text.replace(
        'name="gripperframe" pos="-0.0079 -0.000218121 -0.0981274"',
        'name="gripperframe" pos="0.0 0.0 -0.0981274"',
    )

    # 3) Stronger jaw actuator (pick-101 uses ±10 on the gripper only).
    text = text.replace(
        '<position class="sts3215" name="gripper" joint="gripper" '
        'forcerange="-3.35 3.35" ctrlrange="-0.17453 1.74533"/>',
        '<position class="sts3215" name="gripper" joint="gripper" '
        'forcerange="-10 10" ctrlrange="-0.17453 1.74533"/>',
    )

    # 4) Inject / upgrade fingertip pads.
    if "static_finger_pad" not in text and 'name="gripperframe"' in text:
        idx = text.find('name="gripperframe"')
        line_end = text.find("\n", idx)
        text = text[: line_end + 1] + _STATIC_PAD + text[line_end + 1 :]
    else:
        # Upgrade older pad lines that lack contype.
        text = text.replace(
            '<geom name="static_finger_pad" type="box" size="0.00125 0.00125 0.00125" '
            'pos="-0.008875 0.0 -0.100" rgba="1 0.5 0.5 0.8" friction="1 0.05 0.001"/>',
            _STATIC_PAD.rstrip("\n"),
        )

    if "moving_finger_pad" not in text and "moving_jaw_so101_v1" in text:
        marker = 'mesh="moving_jaw_so101_v1"'
        idx = text.find(marker)
        idx2 = text.find(marker, idx + 1) if idx >= 0 else -1
        use = idx2 if idx2 >= 0 else idx
        if use >= 0:
            line_end = text.find("\n", use)
            text = text[: line_end + 1] + _MOVING_PAD + text[line_end + 1 :]
    else:
        text = text.replace(
            '<geom name="moving_finger_pad" type="box" size="0.00125 0.00125 0.00125" '
            'pos="-0.01136 -0.076 0.019" rgba="0.5 0.5 1 0.8" friction="1 0.05 0.001"/>',
            _MOVING_PAD.rstrip("\n"),
        )

    # 5) Disable moving-jaw *mesh* collision; pads provide contact (MuJoCo guidance
    #    cited in the pick-101 blog for unstable mesh-mesh grasps).
    old_jaw_col = (
        '<geom type="mesh" class="collision" pos="-5.55112e-17 -5.55112e-17 0.0189" '
        'quat="1 -0 3.00524e-16 -2.00834e-17" mesh="moving_jaw_so101_v1" '
        'material="moving_jaw_so101_v1_material"/>'
    )
    new_jaw_col = (
        '<geom type="mesh" class="collision" pos="-5.55112e-17 -5.55112e-17 0.0189" '
        'quat="1 -0 3.00524e-16 -2.00834e-17" mesh="moving_jaw_so101_v1" '
        'material="moving_jaw_so101_v1_material" contype="0" conaffinity="0"/>'
    )
    text = text.replace(old_jaw_col, new_jaw_col)
    return text


def patch_so101_grasp_geoms(so101_dir: Path) -> list[Path]:
    """Apply pick-101 grasp alignments to every MJCF under ``so101_dir``."""
    patched: list[Path] = []
    if not so101_dir.is_dir():
        return patched
    for path in so101_dir.rglob("*.xml"):
        # Skip pure scene wrappers without the robot tree.
        original = path.read_text(encoding="utf-8")
        if "gripperframe" not in original and "shoulder_pan" not in original:
            continue
        updated = _apply_pick101_alignments(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            patched.append(path)
    return patched
