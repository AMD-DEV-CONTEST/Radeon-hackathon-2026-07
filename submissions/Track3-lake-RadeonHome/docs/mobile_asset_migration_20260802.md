# Safe Migration from Fixed Franka to Mobile Manipulation

## Problem

The upstream Franka asset was designed for a fixed tabletop mount. Adding
planar root joints alone moved the robot, but retained a mounting collision
shell and a work surface that overlapped the mobile root. The resulting scene
could look as if the arm passed through the table, or could reject valid
mobile docking poses.

## Collision migration

RadeonHome now:

1. generates planar `base_x`, `base_y`, and `base_yaw` joints;
2. preserves all seven arm-link, hand, and official fingertip collisions;
3. disables only the fixed-installation `link0_c` shell;
4. adds a ground-level `0.22 m` radius chassis collision proxy, aligned with
   the planner's `0.23 m` robot radius;
5. places the tabletop near edge `0.20 m` in front of the arm root, removing
   the visual overlap; and
6. retains the inflated A* navigation margin around room obstacles.

## Retained regression evidence

| Variant | Physical outcome | Diagnostic observation |
| --- | --- | --- |
| Fixed `link0_c`, initial clearance | Failed | `0.514 m` delivery docking error |
| Fixed `link0_c`, shallow table | Failed | `0.420 m` delivery docking error |
| Root-height collision proxy | Failed | `1.224 m` early stop near room furniture |
| Ground-level chassis proxy | Success | `0.0014 mm` delivery docking error; `15.52 mm` placement error |

The failed and successful structured results are retained under
[`results/mobile_migration_smoke_20260802/`](../results/mobile_migration_smoke_20260802/).

## Collision-corrected multi-object smoke test

All profiles used seed `20260707`, lifted carry, physical contact, the same
room route, and video disabled. This is a one-seed-per-profile engineering
regression, not a population estimate.

| Profile | Mass | Result | Horizontal placement error |
| --- | ---: | ---: | ---: |
| `parcel_small` | 25 g | Success | 16.15 mm |
| `parcel_medium` | 50 g | Success | 9.78 mm |
| `parcel_wide` | 80 g | Success | 13.12 mm |
| `carton_tall` | 120 g | Success | 1.90 mm |
| `package_heavy` | 200 g | Success | 19.73 mm |
| **Total / mean** | **25-200 g** | **5/5** | **12.14 mm** |

The earlier 15/17 campaign predates this collision migration and remains
useful historical evidence, but it is reported separately rather than being
presented as a measurement of the corrected geometry.
