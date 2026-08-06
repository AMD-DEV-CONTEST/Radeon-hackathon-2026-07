# WorldForge v0.9.4.1

Replace:
`apps/web/src/components/worldforge/WorldForgeScene.tsx`

This complete replacement preserves v0.9.4 and changes World View -> Explorer switching to request pointer lock directly from the M-key/button user gesture.

Test:
1. Enter WorldForge.
2. Walk somewhere.
3. Press M for World View.
4. Rotate/zoom.
5. Press M again.
6. Explorer should resume without the normal extra Resume Explorer click.
7. Press Esc manually; Resume Explorer should still be available.

Commit after validation:

```bash
git add .
git commit -m "fix(worldforge): enable seamless return to explorer mode"
git push
```
