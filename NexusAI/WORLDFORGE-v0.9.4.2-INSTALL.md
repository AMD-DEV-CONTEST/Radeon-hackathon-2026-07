# WorldForge v0.9.4.2 - Pointer Lock Transition Fix

Replace:

`apps/web/src/components/worldforge/WorldForgeScene.tsx`

## What changed

The World View -> Explorer transition now:

1. Receives the M-key or Explorer Mode button user gesture.
2. Requests pointer lock immediately while World View is still mounted.
3. Waits for the browser's `pointerlockchange` confirmation.
4. Only after pointer lock succeeds does React switch to Explorer Mode.
5. PointerLockControls then takes over the already-locked canvas.

This avoids the previous state where React switched controls first and the browser
created a pointer lock that PointerLockControls did not correctly own.

## Test

1. Enter WorldForge once.
2. Walk away from the spawn point.
3. Press M.
4. Rotate and zoom World View.
5. Press M.
6. Do NOT press Escape.
7. Move the mouse and press W immediately.

Expected: first-person Explorer control resumes at the saved player position.

Manual Escape while exploring should still expose the Resume Explorer control.

## Commit after validation

```bash
git add apps/web/src/components/worldforge/WorldForgeScene.tsx
git commit -m "fix(worldforge): synchronize pointer lock during view transitions"
git push
```
