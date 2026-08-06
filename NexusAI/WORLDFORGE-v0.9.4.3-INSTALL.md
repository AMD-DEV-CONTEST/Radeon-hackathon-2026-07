# WorldForge v0.9.4.3 - PointerLockControls Ownership Fix

Replace:
`apps/web/src/components/worldforge/WorldForgeScene.tsx`

## Fix
When returning from World View, React first mounts Explorer Mode and its
PointerLockControls component. The controller then calls its own `lock()` method
instead of directly calling `canvas.requestPointerLock()`.

This is intended to synchronize:
- pointer lock
- PointerLockControls internal state
- mouse-look listeners
- WASD movement
- saved player position/orientation

## Test
1. Enter WorldForge.
2. Walk and look around.
3. Press M.
4. Rotate/zoom/pan World View.
5. Press M.
6. Without pressing Esc or clicking Resume:
   - move mouse: camera should look around
   - press WASD: player should move

Esc should still intentionally release Explorer and show Resume Explorer.

## Commit after validation
```bash
git add apps/web/src/components/worldforge/WorldForgeScene.tsx
git commit -m "fix(worldforge): restore mouse look after world view transition"
git push
```
