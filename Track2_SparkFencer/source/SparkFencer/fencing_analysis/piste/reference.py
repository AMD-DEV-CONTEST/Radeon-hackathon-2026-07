"""Standard fencing piste reference model.

Piste coordinate system used across the project:
  x: along the piste in meters, 0 at the left end (as seen by the camera),
     increasing to the right.
  y: across the piste in meters, 0 at the far edge (image top), increasing
     toward the camera.

The camera is assumed to shoot the piste from the side, so the two fencers
appear as "left" and "right".
"""

PISTE_LENGTH = 14.0
PISTE_WIDTH = 1.5
CENTER_LINE = PISTE_LENGTH / 2.0
# En-garde lines sit 2 m either side of the center line.
EN_GARDE_OFFSET = 2.0
# Warning lines sit 2 m from each end of the piste.
WARNING_LINE_FROM_END = 2.0


def piste_marks(piste_length=PISTE_LENGTH):
    """Return the x positions of the standard piste lines for a strip of
    *piste_length* meters (scaled proportionally when the annotated strip is
    shorter than a full piste)."""
    scale = piste_length / PISTE_LENGTH
    center = piste_length / 2.0
    return {
        "center": center,
        "en_garde_left": center - EN_GARDE_OFFSET * scale,
        "en_garde_right": center + EN_GARDE_OFFSET * scale,
        "warning_left": WARNING_LINE_FROM_END * scale,
        "warning_right": piste_length - WARNING_LINE_FROM_END * scale,
    }
