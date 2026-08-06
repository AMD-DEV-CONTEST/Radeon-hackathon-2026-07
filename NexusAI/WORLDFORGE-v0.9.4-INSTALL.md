# NexusAI WorldForge v0.9.4

Replace:
`apps/web/src/components/worldforge/WorldForgeScene.tsx`

No route changes are required if your `[world]/page.tsx` already returns only `<WorldForgeScene />` for `worldforge`.

## v0.9.4 changes
- Spacebar jump with gravity and ground detection
- WASD movement and Shift sprint retained
- varied building positions and rotations
- less rigid city layout while preserving navigable streets
- interactive World View using OrbitControls
- drag to rotate
- right-drag to pan
- scroll to zoom
- player position and orientation preserved between modes
- M switches Explorer -> World View -> Explorer
- returning from World View attempts to resume pointer lock automatically
- Enter WorldForge appears only on initial entry
- if the user manually presses Esc, a smaller Resume Explorer prompt appears

## Controls
Explorer:
- WASD: move
- Mouse: look
- Shift: sprint
- Space: jump
- M: World View
- Esc: release mouse

World View:
- Left drag: rotate
- Right drag: pan
- Scroll: zoom
- M: return to Explorer

## Run
From `apps/web`:
```bash
npm run dev
```

## Commit after validation
```bash
git add .
git commit -m "feat(worldforge): add jump interactive world view and varied city layout"
git push
```
