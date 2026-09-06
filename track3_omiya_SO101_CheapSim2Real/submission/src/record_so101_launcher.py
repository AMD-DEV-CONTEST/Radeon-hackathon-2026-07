"""lerobot-record with the camera TRANSPORT swapped for a plain-cv2 reader.

Everything that defines the recording — the teleop loop, episode/reset timing,
keyboard controls, dataset schema and writing — is lerobot's own
``lerobot_record.main``, untouched. Only the camera I/O class is replaced.

Why: lerobot's ``OpenCVCamera`` validates the device-reported fps, requires the
first frame within ``warmup_s`` and aborts the session on a >500 ms stale frame.
The wrist camera on this rig is a 120fps-locked UVC device whose fps report
flaps with the negotiated resolution (640x480 -> "30", 320x240 -> "120") and
whose first frame regularly takes longer than any warmup we set — through
AVFoundation it failed 6 different ways across two days, while plain ``cv2``
reads never failed once. So the launcher patches camera construction to return
``PlainCamera`` (background thread, newest-frame buffer, never raises after
startup), which exposes the same interface the SO follower calls:
``connect() / read_latest() / disconnect() / is_connected``.

Usage: identical to lerobot-record. The ``fps`` field in --robot.cameras is
accepted but ignored by the transport (the record loop paces itself with
--dataset.fps).

    uv run python -m franka_fruit_pick.record_so101_launcher \
        --robot.type=so101_follower ... --dataset.num_episodes=10 ...

Liveness guard: a UVC device can deliver one frame at connect and then silently
stop — ``cap.read()`` keeps returning ok=True with the same buffer, so the
"never raises" design recorded 10 episodes of a frozen wrist view without a
single error. Being open is not being alive; only pixel change over time is.
So PlainCamera now tracks frame-to-frame change and (a) refuses to connect if
the stream shows no change during startup, (b) raises from ``read_latest`` if
no pixel change for FREEZE_LIMIT_S mid-session — aborting the recording loudly
instead of writing garbage. (This is the true-positive half of lerobot's
staleness check, which the transport swap had removed along with its false
positives.)
"""

from __future__ import annotations

import threading
import time

import numpy as np

# Mean |diff| (0-255 scale) on an 8x-downsampled frame; live sensor noise on a
# static scene measures ~1.2, an actually frozen buffer repeats exactly (0.0).
CHANGE_EPS = 0.2
REOPEN_AFTER_S = 2.0     # no change for this long -> release + reopen the device
FREEZE_LIMIT_S = 10.0    # still no change after reopens -> abort the session
STARTUP_LIVE_S = 6.0     # must see change within this long at connect


class PlainCamera:
    """Minimal threaded UVC reader on raw cv2, shaped like a lerobot camera."""

    def __init__(self, cfg):
        self.index = cfg.index_or_path
        self.width = cfg.width
        self.height = cfg.height
        self.fps = cfg.fps
        self.cap = None
        self._frame = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._prev_small: np.ndarray | None = None
        self._last_change: float | None = None
        self._n_reads = 0
        self.reopen_count = 0

    # -- lerobot camera interface -------------------------------------------
    @property
    def is_connected(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _open_device(self):
        import cv2
        cap = cv2.VideoCapture(self.index)
        if not cap.isOpened():
            raise RuntimeError(f"PlainCamera({self.index}) did not open")
        # Deliberately NO property requests: the wrist device is rock-solid in its
        # native mode (1920x1080@30 — 150 s soak, zero stalls) but freezes every
        # ~9 s when asked for 320x240 (that request selects its 120 fps mode).
        # Capture at whatever the device prefers and resize in _loop instead.
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"[record] PlainCamera({self.index}) native mode {w}x{h} "
              f"-> resizing to {self.width}x{self.height}", flush=True)
        return cap

    def connect(self, warmup: bool = True) -> None:
        self.cap = self._open_device()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        deadline = time.time() + 20.0
        while self._latest_unchecked() is None and time.time() < deadline:
            time.sleep(0.05)
        if self._latest_unchecked() is None:
            raise RuntimeError(f"PlainCamera({self.index}) no frame within 20 s")
        # Liveness gate: one frame is not a stream. Require pixel change before
        # declaring the camera usable, otherwise refuse to start the session.
        deadline = time.time() + STARTUP_LIVE_S
        while self._last_change is None and time.time() < deadline:
            time.sleep(0.1)
        if self._last_change is None:
            raise RuntimeError(
                f"PlainCamera({self.index}) FROZEN at startup: frames arrive but "
                f"pixels never change ({STARTUP_LIVE_S:.0f} s). Re-seat the USB "
                f"cable / avoid the hub, then retry.")
        print(f"[record] PlainCamera({self.index}) up @ {self.width}x{self.height} (LIVE)")

    def _loop(self) -> None:
        import cv2
        last_reopen = 0.0
        while not self._stop.is_set():
            ok, frame = self.cap.read()
            if ok and frame is not None:
                if frame.shape[1] != self.width or frame.shape[0] != self.height:
                    # center-crop to the target aspect first (the wrist device's
                    # native 1920x1080 is 16:9; squashing it to 4:3 would distort
                    # the view the policy was trained on), then resize
                    fh, fw = frame.shape[:2]
                    want = self.width / self.height
                    if abs(fw / fh - want) > 0.01:
                        if fw / fh > want:
                            cw = int(fh * want)
                            x0 = (fw - cw) // 2
                            frame = frame[:, x0:x0 + cw]
                        else:
                            ch = int(fw / want)
                            y0 = (fh - ch) // 2
                            frame = frame[y0:y0 + ch, :]
                    frame = cv2.resize(frame, (self.width, self.height),
                                       interpolation=cv2.INTER_AREA)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                self._n_reads += 1
                if self._n_reads % 4 == 0:      # change check a few times/second
                    small = rgb[::8, ::8].astype(np.int16)
                    if self._prev_small is not None and \
                            float(np.abs(small - self._prev_small).mean()) > CHANGE_EPS:
                        self._last_change = time.time()
                    self._prev_small = small
                with self._lock:
                    self._frame = rgb
            else:
                time.sleep(0.01)
            # Self-heal: the wrist device sometimes keeps answering reads with the
            # same buffer. A release+reopen restarts its stream; do that after
            # REOPEN_AFTER_S of no change (rate-limited), and log timestamps so
            # tainted episodes can be identified and re-recorded afterwards.
            now = time.time()
            if self._last_change is not None and \
                    now - self._last_change > REOPEN_AFTER_S and \
                    now - last_reopen > REOPEN_AFTER_S:
                stale_for = now - self._last_change
                print(f"\n[record] WARNING PlainCamera({self.index}) stale "
                      f"{stale_for:.1f} s at {time.strftime('%H:%M:%S')} — reopening device",
                      flush=True)
                try:
                    self.cap.release()
                    time.sleep(0.3)
                    self.cap = self._open_device()
                except Exception as exc:   # keep trying until FREEZE_LIMIT aborts
                    print(f"[record] reopen failed: {exc}", flush=True)
                last_reopen = time.time()
                self.reopen_count += 1

    def _latest_unchecked(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def read_latest(self, max_age_ms: int | None = None):
        if self._last_change is not None and \
                time.time() - self._last_change > FREEZE_LIMIT_S:
            raise RuntimeError(
                f"PlainCamera({self.index}) FROZEN mid-session: no pixel change "
                f"for {FREEZE_LIMIT_S:.0f} s despite {self.reopen_count} device "
                f"reopen(s) — aborting instead of recording a static image. "
                f"Move the camera to a different USB port (not the hub) and retry.")
        return self._latest_unchecked()

    def async_read(self, timeout_ms: float = 0):   # compatibility alias
        return self.read_latest()

    def read(self):                                 # compatibility alias
        return self.read_latest()

    def disconnect(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self.cap is not None:
            self.cap.release()


def _patch_cameras() -> None:
    """Route every OpenCV camera config to PlainCamera, wherever it's built."""
    from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
    import lerobot.cameras.utils as cam_utils

    original = cam_utils.make_cameras_from_configs

    def patched(camera_configs):
        cams = {}
        for key, cfg in camera_configs.items():
            if isinstance(cfg, OpenCVCameraConfig):
                cams[key] = PlainCamera(cfg)
            else:
                cams.update(original({key: cfg}))
        return cams

    cam_utils.make_cameras_from_configs = patched
    # so_follower imported the symbol directly; patch its reference too
    import lerobot.robots.so_follower.so_follower as sf
    if hasattr(sf, "make_cameras_from_configs"):
        sf.make_cameras_from_configs = patched


def main() -> None:
    _patch_cameras()
    from lerobot.scripts.lerobot_record import main as record_main
    record_main()


if __name__ == "__main__":
    main()
