"""帧处理工具: 命名、列举、缓存、复制帧序列等."""
from __future__ import annotations

import shutil
from pathlib import Path

from config import FRAME_NAME_TEMPLATE, FRAMES_DIR, EDITED_DIR, MASKS_DIR, PROPAGATED_DIR
from utils.video_utils import read_frame, write_frame


def frame_name(index: int) -> str:
    """根据 1-based 索引生成帧文件名: frame_00001.png."""
    return FRAME_NAME_TEMPLATE.format(index)


def _parse_frame_index(name: str) -> int | None:
    """从帧文件名解析索引, 如 ``frame_00023.png`` -> 23. 失败返回 None."""
    import re
    m = re.search(r"frame_(\d+)\.png", name)
    return int(m.group(1)) if m else None


def frame_path(index: int, frames_dir: str | Path) -> Path:
    """帧索引 -> 帧文件路径."""
    return Path(frames_dir) / frame_name(index)


def list_frames(frames_dir: str | Path) -> list[Path]:
    """列出目录中所有 PNG 帧, 按文件名排序."""
    frames_dir = Path(frames_dir)
    return sorted(frames_dir.glob("frame_*.png"))


def count_frames(frames_dir: str | Path) -> int:
    """统计帧数."""
    return len(list_frames(frames_dir))


def ensure_session_dirs(session_id: str) -> dict[str, Path]:
    """为一次会话创建独立的子目录树.

    Returns
    -------
    dict
        ``{"frames": ..., "edited": ..., "masks": ..., "propagated": ...}``
    """
    sub = {
        "frames": FRAMES_DIR / session_id,
        "edited": EDITED_DIR / session_id,
        "masks": MASKS_DIR / session_id,
        "propagated": PROPAGATED_DIR / session_id,
    }
    for d in sub.values():
        d.mkdir(parents=True, exist_ok=True)
    return sub


def copy_frame(src: str | Path, dst: str | Path) -> Path:
    """复制单帧."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def copy_frame_sequence(src_dir: str | Path, dst_dir: str | Path,
                        indices: list[int] | None = None) -> list[Path]:
    """复制帧序列 (全部或指定索引) 到目标目录.

    帧索引从 1 开始。目标目录的帧重新从 1 开始编号。
    """
    src_dir = Path(src_dir)
    dst_dir = Path(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    src_frames = list_frames(src_dir)
    if indices is None:
        indices = list(range(1, len(src_frames) + 1))

    copied: list[Path] = []
    for new_idx, src_idx in enumerate(indices, start=1):
        if src_idx < 1 or src_idx > len(src_frames):
            continue
        dst = dst_dir / frame_name(new_idx)
        shutil.copy2(src_frames[src_idx - 1], dst)
        copied.append(dst)
    return copied


def load_frame_array(frames_dir: str | Path,
                     indices: list[int] | None = None) -> list[dict]:
    """加载帧为 ``[{"index": 1, "path": ..., "image": ndarray}, ...]``.

    注意: 大量帧会占用内存, 仅用于 UI 预览少量帧。
    """
    frames = list_frames(frames_dir)
    out = []
    target = indices or range(1, len(frames) + 1)
    for idx in target:
        if idx < 1 or idx > len(frames):
            continue
        out.append({
            "index": idx,
            "path": frames[idx - 1],
            "image": read_frame(frames[idx - 1]),
        })
    return out


def build_final_sequence(
    original_dir: str | Path,
    edited_indices: dict[int, str | Path],
    propagated_dir: str | Path | None = None,
) -> list[Path]:
    """构建最终合帧用的有序帧列表.

    优先级: propagated > edited > original.

    Parameters
    ----------
    original_dir : Path
        原始帧目录。
    edited_indices : dict
        ``{frame_index: edited_frame_path}`` 关键帧编辑结果。
    propagated_dir : Path, optional
        传播结果目录 (帧索引与原始一致)。

    Returns
    -------
    list[Path]
        合帧所需的有序帧路径列表 (与原始帧一一对应)。
    """
    original = list_frames(original_dir)
    # 传播目录只含被传播的关键帧 + 目标帧, 按帧名建立索引而非位置
    prop_map: dict[str, Path] = {}
    if propagated_dir:
        for p in list_frames(propagated_dir):
            prop_map[p.name] = p
    result: list[Path] = []
    for orig in original:
        if orig.name in prop_map:
            result.append(prop_map[orig.name])
        else:
            # 通过帧名解析索引, 查 edited
            idx = _parse_frame_index(orig.name)
            if idx is not None and idx in edited_indices:
                result.append(Path(edited_indices[idx]))
            else:
                result.append(orig)
    return result


def materialize_final_sequence(
    original_dir: str | Path,
    edited_indices: dict[int, str | Path],
    propagated_dir: str | Path | None,
    final_dir: str | Path,
) -> list[Path]:
    """将 build_final_sequence 结果物化为目录中的连续帧文件."""
    final_dir = Path(final_dir)
    final_dir.mkdir(parents=True, exist_ok=True)
    for old in final_dir.glob("frame_*.png"):
        old.unlink()
    ordered = build_final_sequence(original_dir, edited_indices, propagated_dir)
    copied = []
    for new_idx, src in enumerate(ordered, start=1):
        dst = final_dir / frame_name(new_idx)
        shutil.copy2(src, dst)
        copied.append(dst)
    return copied
