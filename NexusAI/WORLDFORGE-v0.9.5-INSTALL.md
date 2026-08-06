# NexusAI WorldForge v0.9.5 - World View Player Location

Replace:
`apps/web/src/components/worldforge/WorldForgeScene.tsx`

## Adds
- live World View marker at the saved Explorer position
- glowing cyan ground ring
- vertical beacon visible from a distance
- direction arrow based on the Explorer camera orientation
- pulsing marker for visibility
- World View HUD legend

The marker uses the same `playerState` already used to preserve the player's
position and orientation between Explorer and World View.

## Test
1. Enter WorldForge.
2. Walk away from spawn and turn in a recognizable direction.
3. Press M.
4. Locate the cyan vertical beacon and ground ring.
5. Verify the marker is at the location where you stopped.
6. Press M and return to Explorer.
7. Walk elsewhere, press M again, and verify the marker moved.

## Commit after validation
```bash
git add apps/web/src/components/worldforge/WorldForgeScene.tsx
git commit -m "feat(worldforge): add player location marker to world view"
git push
```
