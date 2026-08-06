# BotClaw Verb Taxonomy v0.9

BotClaw skills use a verb-first taxonomy: a skill says what the robot does,
while runtime adapters decide how a specific robot performs it.

## v0.9 Standard Verbs

| Verb | Layer | Meaning | Current Status |
| --- | --- | --- | --- |
| `teleop` | control | Human-operated control loop, usually leader/follower | Implemented for SO-101 |
| `record` | data | Record robot state, camera frames, and task metadata | Implemented for SO-101 |
| `inference` | deploy | Run a trained policy on a runtime | Implemented for SO-101 path |
| `pick` | manipulation | Acquire an object from the scene | Draft |
| `place` | manipulation | Put a held object at a target pose/location | Draft |
| `grasp` | manipulation | Close gripper / establish object contact | Draft |
| `release` | manipulation | Release held object | Draft |
| `push` | manipulation | Push an object along a surface | Draft |
| `pull` | manipulation | Pull an object toward a target | Draft |
| `pour` | manipulation | Pour from one container to another | Draft |
| `wave` | expression | Gesture or expressive motion | Implemented for Reachy Mini |
| `scan` | perception | Move sensors to inspect an area/object | Draft |
| `navigate` | locomotion | Move a mobile base or embodied platform | Future |
| `home` | safety | Return runtime to known safe pose | Runtime-level primitive |

## Rules

1. Use verbs for robot capabilities, not hardware names.
2. Put object/target details in `params`, not in the verb.
3. Keep runtime-specific constraints in `compatible_types` and future
   compatibility metadata.
4. Composite tasks can be named with `_and_` only when they orchestrate multiple
   standard verbs, e.g. `pick_and_place`.

## Current vs Later

v0.9 ratifies `teleop`, `record`, `inference`, and `wave` because they already
have concrete registry entries. The remaining verbs are vocabulary anchors for
Skill authors and BotClaw v1.0 compatibility work.
