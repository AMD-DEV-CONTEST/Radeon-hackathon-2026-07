# WorldForge v0.9.4.1 - Seamless Explorer Resume Patch

In `apps/web/src/components/worldforge/WorldForgeScene.tsx`, replace your current `toggleMode` function with:

```tsx
const toggleMode = () => {
  if (mode === "explorer") {
    playerState.current.position.y = Math.max(
      playerState.current.position.y,
      PLAYER_HEIGHT
    );
    document.exitPointerLock?.();
    setMode("world");
    return;
  }

  // IMPORTANT:
  // Request pointer lock synchronously while this function is still executing
  // inside the user's M-key press or button-click gesture.
  const canvas = document.querySelector("canvas");

  if (hasEntered && canvas) {
    try {
      canvas.requestPointerLock();
    } catch (error) {
      console.warn("Could not immediately restore pointer lock:", error);
    }
  }

  setMode("explorer");
};
```

Then DELETE this state:

```tsx
const [resumeRequested, setResumeRequested] = useState(0);
```

Remove the `resumeRequested` prop from `<World />`:

```tsx
<World
  mode={mode}
  onLockChange={setLocked}
  playerState={playerState}
/>
```

Update the `World` function signature to:

```tsx
function World({
  mode,
  onLockChange,
  playerState,
}: {
  mode: Mode;
  onLockChange: (locked: boolean) => void;
  playerState: React.MutableRefObject<PlayerState>;
}) {
```

Update `<ExplorerController />` inside `World` to:

```tsx
<ExplorerController
  enabled={mode === "explorer"}
  onLockChange={onLockChange}
  playerState={playerState}
/>
```

Update the `ExplorerController` function signature to:

```tsx
function ExplorerController({
  enabled,
  onLockChange,
  playerState,
}: {
  enabled: boolean;
  onLockChange: (locked: boolean) => void;
  playerState: React.MutableRefObject<PlayerState>;
}) {
```

DELETE the entire effect that contains:

```tsx
gl.domElement.requestPointerLock?.();
```

and remove `gl` from:

```tsx
const { camera, gl } = useThree();
```

so it becomes:

```tsx
const { camera } = useThree();
```

The existing Resume Explorer button should remain. It will now be used only when pointer lock is manually released, such as by pressing Escape.

Expected flow:

Explorer -> M -> World View -> M -> Explorer immediately

No Resume Explorer click should be needed during normal mode switching.
