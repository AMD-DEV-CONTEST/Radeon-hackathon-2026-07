# NexusAI WorldForge v0.9.3

## Adds
- true fullscreen 100vw × 100vh WorldForge
- Explorer Mode as default
- WASD movement
- mouse-look through Pointer Lock
- Shift sprint
- basic building collision
- world-boundary collision
- M key mode switching
- World View camera
- fullscreen HUD
- crosshair
- Return to Nexus overlay

## IMPORTANT: Dynamic route integration

Your project uses `src/app/[world]/page.tsx`.

Do NOT create `src/app/worldforge/page.tsx`.

1. Replace:
`apps/web/src/components/worldforge/WorldForgeScene.tsx`

2. In your existing `apps/web/src/app/[world]/page.tsx`, keep the current conditional WorldForge handling, but make the WorldForge branch return ONLY:

```tsx
if (world === "worldforge") {
  return <WorldForgeScene />;
}
```

Make sure this import remains at the top:

```tsx
import WorldForgeScene from "@/components/worldforge/WorldForgeScene";
```

This removes the old heading/container and allows the scene to occupy the entire viewport.

## Controls

- Click `Enter WorldForge` to capture the mouse.
- W/A/S/D: move
- Mouse: look
- Shift: sprint
- Escape: release mouse
- M: toggle Explorer Mode / World View

## Note

World View in v0.9.3 is a fixed overview camera. Orbit/pan controls will be restored in a later refinement if needed. The priority here is validating fullscreen immersion and reliable first-person movement.

## Commit after validation

```bash
git add .
git commit -m "feat(worldforge): add fullscreen WASD explorer mode"
git push
```
