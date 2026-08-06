#!/usr/bin/env python3
"""lerobot-record with BotverseX guards against empty-episode crashes.

LeRobot always calls ``dataset.save_episode()`` after a record+reset cycle.
If the operator presses → / UI「跳过」before any ``add_frame`` (or a stale
``exit_early`` from the previous save gap), the buffer is empty and upstream
raises::

    ValueError: You must add one or several frames with add_frame before calling add_episode.

This launcher:
1. Clears stale ``exit_early`` when a *recording* loop starts (dataset set).
2. While recording with an empty buffer, continuously clears premature skips.
3. No-ops ``save_episode`` on an empty buffer instead of crashing.
"""
from __future__ import annotations

import logging
import threading


def _apply_empty_episode_guards() -> None:
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.scripts import lerobot_record as record_mod

    if getattr(LeRobotDataset.save_episode, "_botversex_patched", False):
        return

    _orig_save = LeRobotDataset.save_episode

    def save_episode(self, episode_data=None, parallel_encoding=True):  # type: ignore[no-untyped-def]
        if episode_data is None and not self.has_pending_frames():
            logging.warning(
                "BotverseX: empty episode buffer — skip save "
                "(示教几秒后再按 → / 点「跳过」)."
            )
            try:
                self.clear_episode_buffer()
            except Exception:
                pass
            return None
        return _orig_save(self, episode_data, parallel_encoding)

    save_episode._botversex_patched = True  # type: ignore[attr-defined]
    LeRobotDataset.save_episode = save_episode  # type: ignore[method-assign]

    _orig_loop = record_mod.record_loop

    def record_loop(*args, **kwargs):  # type: ignore[no-untyped-def]
        events = kwargs.get("events")
        dataset = kwargs.get("dataset")
        if events is None and len(args) >= 2:
            events = args[1]

        # Recording loops pass dataset=; reset loops do not.
        if dataset is None or not isinstance(events, dict):
            return _orig_loop(*args, **kwargs)

        # Drop skip pressed during previous episode's video encode / UI gap.
        events["exit_early"] = False

        stop = threading.Event()

        def _suppress_empty_skip() -> None:
            while not stop.wait(0.05):
                try:
                    if events.get("exit_early") and not dataset.has_pending_frames():
                        events["exit_early"] = False
                        logging.warning(
                            "BotverseX: ignore skip — no frames recorded yet"
                        )
                except Exception:
                    pass

        guard = threading.Thread(target=_suppress_empty_skip, name="b601-skip-guard", daemon=True)
        guard.start()
        try:
            return _orig_loop(*args, **kwargs)
        finally:
            stop.set()
            guard.join(timeout=1.0)

    record_mod.record_loop = record_loop  # type: ignore[assignment]


def main() -> None:
    _apply_empty_episode_guards()
    from lerobot.scripts.lerobot_record import main as lerobot_main

    lerobot_main()


if __name__ == "__main__":
    main()
