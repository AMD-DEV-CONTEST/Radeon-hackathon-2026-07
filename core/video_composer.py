"""模块四: 视频合成模块.

将编辑+传播后的帧序列合成为最终 MP4, 可选保留原音轨。
"""
from __future__ import annotations

from pathlib import Path

from config import CONFIG, ComposerConfig
from core.frame_utils import (
    build_final_sequence,
    list_frames,
    materialize_final_sequence,
)
from utils.video_utils import extract_audio, frames_to_video


class VideoComposer:
    """视频合成模块 (FFmpeg)."""

    def __init__(self):
        self.cfg = ComposerConfig()

    def compose(
        self,
        original_frames_dir: str | Path,
        edited_indices: dict[int, str | Path] | None = None,
        propagated_dir: str | Path | None = None,
        output_path: str | Path | None = None,
        audio_path: str | Path | None = None,
        fps: int | None = None,
        session_id: str | None = None,
    ) -> dict:
        """合成最终视频.

        优先级: propagated > edited > original。

        Parameters
        ----------
        audio_path : Path, optional
            音轨文件 (aac)。若提供则合并。
        output_path : Path, optional
            输出路径; 不提供则放到 ``outputs/final/{session_id}.mp4``。

        Returns
        -------
        dict
            ``{"output_video_path", "frame_count", "fps", "has_audio"}``
        """
        from config import FINAL_DIR
        session_id = session_id or "default"
        fps = fps or self.cfg.fps
        edited_indices = edited_indices or {}

        if output_path is None:
            output_path = FINAL_DIR / f"{session_id}.mp4"
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 物化最终帧序列到临时目录
        from config import FINAL_DIR
        final_dir = FINAL_DIR.parent / "final_frames" / session_id
        materialized = materialize_final_sequence(
            original_frames_dir, edited_indices, propagated_dir, final_dir,
        )
        if not materialized:
            raise RuntimeError("无可合成的帧")

        # 合成视频
        frames_to_video(
            frames_dir=final_dir,
            output_path=output_path,
            fps=fps,
            audio_path=audio_path,
            crf=self.cfg.crf,
            preset=self.cfg.preset,
            pix_fmt=self.cfg.pix_fmt,
        )

        return {
            "output_video_path": str(output_path),
            "frame_count": len(materialized),
            "fps": fps,
            "has_audio": audio_path is not None,
        }

    def compose_with_original_audio(
        self,
        original_video_path: str | Path,
        original_frames_dir: str | Path,
        edited_indices: dict[int, str | Path] | None = None,
        propagated_dir: str | Path | None = None,
        output_path: str | Path | None = None,
        fps: int | None = None,
        session_id: str | None = None,
    ) -> dict:
        """合成并保留原视频音轨."""
        original_video_path = Path(original_video_path)
        # 抽取音轨
        from config import OUTPUT_DIR
        audio_tmp = OUTPUT_DIR / f"{session_id or 'default'}_audio.aac"
        try:
            extract_audio(original_video_path, audio_tmp)
            audio = audio_tmp
        except Exception:
            audio = None
        return self.compose(
            original_frames_dir=original_frames_dir,
            edited_indices=edited_indices,
            propagated_dir=propagated_dir,
            output_path=output_path,
            audio_path=audio,
            fps=fps,
            session_id=session_id,
        )
