"""全流程数据资产的数据结构定义。

设计原则：每个 agent 的产物都是**结构化 JSON**，落盘到 project 目录，
下游 agent 只读取 JSON，不直接读小说原文。这样可断点续跑、可单镜头返工、可审计。

数据流：
    novel.txt
      -> ChapterManifest   (拆书)
      -> StoryBible        (故事圣经)
      -> CharacterBible    (人物圣经, 含锁定卡)
      -> SceneBible        (场景圣经)
      -> ShotList          (分镜表, 每个 Shot 含图像/视频提示词+台词)
      -> CharacterAsset    (人物参考图, ComfyUI)
      -> Keyframe          (每镜头关键帧, ComfyUI)
      -> Clip              (每镜头 I2V 视频, ComfyUI)
      -> VoiceTrack        (每句台词配音, TTS)
      -> Clip(对口型后)     (InfiniteTalk)
      -> Subtitle          (字幕)
      -> Episode           (FFmpeg 合成成片)
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

from .runtime import ProjectPathCodec, atomic_write_json


_PROJECT_ASSET_DIRECTORIES = frozenset({"bible", "shots", "output"})
_PATH_FIELDS = frozenset(
    {
        "ref_images",
        "angle_refs",
        "keyframe_path",
        "clip_path",
        "voice_path",
        "final_clip_path",
        "final_path",
        "subtitle_path",
    }
)


def _project_root_for_asset(path: Path) -> Path | None:
    for ancestor in path.parents:
        if ancestor.name in _PROJECT_ASSET_DIRECTORIES:
            return ancestor.parent
    return None


def _transform_paths(
    value: Any,
    codec: ProjectPathCodec,
    *,
    encode: bool,
    field_name: str | None = None,
) -> Any:
    if isinstance(value, dict):
        return {
            key: _transform_paths(
                item,
                codec,
                encode=encode,
                field_name=key if field_name != "angle_refs" else field_name,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _transform_paths(item, codec, encode=encode, field_name=field_name)
            for item in value
        ]
    if isinstance(value, str) and field_name in _PATH_FIELDS and value:
        if encode:
            path = Path(value)
            if not path.is_absolute():
                return codec.encode(path)
            try:
                return codec.encode(path)
            except ValueError:
                return value
        return str(codec.decode(value))
    return value


# ---------------------------------------------------------------------------
# 通用序列化基类
# ---------------------------------------------------------------------------
@dataclass
class JsonAsset:
    """所有结构化资产的基类，提供统一的存取与字典互转。"""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        data = self.to_dict()
        project_root = _project_root_for_asset(p)
        if project_root is not None:
            data = _transform_paths(
                data,
                ProjectPathCodec(project_root),
                encode=True,
            )
        return atomic_write_json(p, data)

    @classmethod
    def load(cls, path: str | Path):
        source = Path(path)
        data = json.loads(source.read_text(encoding="utf-8"))
        project_root = _project_root_for_asset(source)
        if project_root is not None:
            data = _transform_paths(
                data,
                ProjectPathCodec(project_root),
                encode=False,
            )
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        # 仅取本类声明的字段，忽略多余键，保证向后兼容
        return cls(**_only_fields(cls, data))


def _only_fields(cls, d: dict[str, Any]) -> dict[str, Any]:
    """仅保留 cls(dataclass) 声明的字段，丢弃多余键。

    嵌套列表资产(ChapterManifest/ShotList/...)用它过滤每个子元素，
    使"忽略多余键、向后兼容"对嵌套元素同样生效(否则旧版分镜表加新字段后无法再加载)。
    """
    return {k: v for k, v in d.items() if k in cls.__dataclass_fields__}


# ---------------------------------------------------------------------------
# 1. 拆书：章节清单
# ---------------------------------------------------------------------------
@dataclass
class Chapter:
    chapter_id: str                 # CH001
    title: str
    summary: str                    # 200-500 字摘要
    characters: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    conflict: str = ""              # 核心冲突点
    emotion_arc: str = ""           # 情绪曲线
    raw_text: str = ""              # 原文(便于下游精修)
    est_episode_id: str = ""        # 预估归属集，如 E001


@dataclass
class ChapterManifest(JsonAsset):
    novel_title: str
    chapters: list[Chapter] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data):
        chs = [Chapter(**_only_fields(Chapter, c)) for c in data.get("chapters", [])]
        return cls(novel_title=data.get("novel_title", ""), chapters=chs)


# ---------------------------------------------------------------------------
# 2. 故事圣经
# ---------------------------------------------------------------------------
@dataclass
class StoryBible(JsonAsset):
    novel_title: str
    logline: str = ""               # 一句话故事
    genre: str = ""                 # 类型: 古风/都市/悬疑...
    tone: str = ""                  # 基调
    visual_style: str = ""          # 统一视觉风格(贯穿所有镜头的全局prompt)
    palette: str = ""               # 主色调
    aspect_ratio: str = "9:16"
    episode_plan: list[dict[str, Any]] = field(default_factory=list)  # 分集规划


# ---------------------------------------------------------------------------
# 3. 人物圣经(一致性核心)
# ---------------------------------------------------------------------------
@dataclass
class Character:
    char_id: str                    # lin_yue
    name: str                       # 林月
    age: int = 0
    role: str = ""                  # 主角/反派/配角
    appearance: str = ""            # 外貌(中文描述)
    outfit_default: str = ""        # 默认服装
    personality: str = ""           # 性格气质
    relations: dict[str, str] = field(default_factory=dict)
    # ---- 一致性锁定字段 ----
    prompt_lock_en: str = ""        # 英文锁定提示词(贯穿所有镜头)
    negative_prompt: str = ""       # 禁止变化项
    voice_profile: str = ""         # 配音音色描述/参考音频id
    forbidden_changes: list[str] = field(default_factory=list)
    # ---- 资产引用 ----
    ref_images: list[str] = field(default_factory=list)   # 已生成参考图路径
    seed: int = 0
    model_version: str = ""


@dataclass
class CharacterBible(JsonAsset):
    novel_title: str
    characters: list[Character] = field(default_factory=list)

    def get(self, char_id: str) -> Optional[Character]:
        return next((c for c in self.characters if c.char_id == char_id), None)

    @classmethod
    def from_dict(cls, data):
        cs = [Character(**_only_fields(Character, c)) for c in data.get("characters", [])]
        return cls(novel_title=data.get("novel_title", ""), characters=cs)


# ---------------------------------------------------------------------------
# 4. 场景圣经
# ---------------------------------------------------------------------------
@dataclass
class Scene:
    scene_id: str                   # tea_house_night
    name: str = ""
    location: str = ""
    era: str = ""
    palette: str = ""
    lighting: str = ""
    props: list[str] = field(default_factory=list)
    prompt_lock_en: str = ""        # 英文场景锁定提示词
    negative_prompt: str = ""
    forbidden_changes: list[str] = field(default_factory=list)
    ref_images: list[str] = field(default_factory=list)
    seed: int = 0
    angle_refs: dict[str, str] = field(default_factory=dict)  # 多角度场景锚: 角度标签->空场景图路径
    #   (车内等反复出现的内景: driver/backseat/rearview/side/exterior 各一张, 关键帧按镜头取景选角度)。


@dataclass
class SceneBible(JsonAsset):
    novel_title: str
    scenes: list[Scene] = field(default_factory=list)

    def get(self, scene_id: str) -> Optional[Scene]:
        return next((s for s in self.scenes if s.scene_id == scene_id), None)

    @classmethod
    def from_dict(cls, data):
        ss = [Scene(**_only_fields(Scene, s)) for s in data.get("scenes", [])]
        return cls(novel_title=data.get("novel_title", ""), scenes=ss)


# ---------------------------------------------------------------------------
# 5. 分镜表
# ---------------------------------------------------------------------------
@dataclass
class Shot:
    shot_id: str                    # E001_S001
    episode_id: str
    chapter_id: str
    scene_id: str
    duration_sec: float = 4.0
    shot_type: str = "medium"       # 景别: wide/medium/close-up...
    camera_motion: str = "static"   # 运镜
    characters: list[str] = field(default_factory=list)
    action: str = ""                # 中文动作描述
    dialogue: str = ""              # 台词(用于配音/字幕)
    speaker: str = ""               # 说话人 char_id
    emotion: str = ""               # 情绪(驱动TTS情感)
    visual_prompt_en: str = ""      # 关键帧英文提示词(已注入人物/场景锁定)
    video_prompt_en: str = ""       # I2V 运动提示词
    negative_prompt: str = ""
    audio_notes: str = ""           # 环境音/BGM 提示
    needs_lipsync: bool = False     # 是否需要对口型(有台词且为人物近景)
    continue_from_prev: bool = False  # I2V 起始帧用上一镜末帧(连续动作=true; 切镜头=false)
    keyframe_seed: int = 0          # 单镜关键帧种子覆盖(0=用角色/场景默认种子)。质检返工换种子重roll 时设。
    force_t2i: bool = False          # 单镜强制纯文生图(去人物/场景锚)。质检返工: 当构图需大幅偏离锚图
    #                                  (道具微距/特殊取景/景深反转/锚图缺关键元素)时设, 让提示词全权控图。
    anchor_mode: str = ""            # 锚点策略(分镜阶段由 LLM 声明): dual(人物+场景双锚)/char(仅人物)/
    #                                  scene(仅场景图生图,空镜)/none(纯文生图,等价 force_t2i)。
    #                                  留空=按 characters 自动推断(向后兼容)。force_t2i=True 等同 none。
    clip_seed: int = 0              # 单镜 I2V 视频种子覆盖(0=用稳定 SHA-256)。视频质检返工换种子重roll 时设。
    clip_retries: int = 0           # 视频质检返工次数(独立于关键帧 retries; 到上限标 needs_human)。
    # ---- 产物状态(由各 agent 回填) ----
    keyframe_path: str = ""
    clip_path: str = ""
    voice_path: str = ""
    final_clip_path: str = ""       # 对口型/精修后
    status: str = "pending"         # pending/keyframe_ok/clip_ok/voice_ok/done/failed
    qc_score: float = 0.0           # 审核评分 0-1
    qc_notes: str = ""
    retries: int = 0
    video_provider: str = "comfy_wan"
    provider_job_id: str = ""
    provider_state: str = ""
    provider_error_code: str = ""
    provider_submitted_at: float = 0.0
    provider_updated_at: float = 0.0


@dataclass
class ShotList(JsonAsset):
    episode_id: str
    novel_title: str = ""
    shots: list[Shot] = field(default_factory=list)

    def pending(self, *statuses: str) -> list[Shot]:
        return [s for s in self.shots if s.status in statuses]

    @classmethod
    def from_dict(cls, data):
        sh = [Shot(**_only_fields(Shot, s)) for s in data.get("shots", [])]
        return cls(episode_id=data.get("episode_id", ""),
                   novel_title=data.get("novel_title", ""), shots=sh)


# ---------------------------------------------------------------------------
# 6. 成片元数据
# ---------------------------------------------------------------------------
@dataclass
class Episode(JsonAsset):
    episode_id: str
    novel_title: str = ""
    title: str = ""
    shot_count: int = 0
    duration_sec: float = 0.0
    resolution: str = "1080x1920"
    fps: int = 24
    final_path: str = ""
    subtitle_path: str = ""
    qc_passed: bool = False
    qc_report: str = ""


# ---------------------------------------------------------------------------
# 7. 资产分层登记表(公共/私有) —— 跨集一致性 + 修改权限分层的依据
# ---------------------------------------------------------------------------
@dataclass
class AssetEntry:
    asset_id: str                   # char_id 或 scene_id
    scope: str = "public"           # public=全书反复出现, 全书一次生成、跨集复用; private=某集临时
    episodes: list[str] = field(default_factory=list)  # 出现的集
    freq: int = 0                   # 出现频次(参考)
    owner_episode: str = ""         # private 时归属的那一集


@dataclass
class AssetRegistry(JsonAsset):
    """谁是公共资产、谁是私有(逐集)资产、每集用到哪些。由 AssetPlanner 产出。
    用途: ①公共资产全书一次生成、固定锚 → 跨集人物/场景一致; ②修改权限分层——
    逐集/QC 返工只能改【私有(本级)资产】, 改公共资产需显式全局操作(防一集改坏全书一致)。"""
    novel_title: str
    characters: list[AssetEntry] = field(default_factory=list)
    scenes: list[AssetEntry] = field(default_factory=list)
    # Eid -> {"public": [id...], "private": [id...]}
    per_episode: dict[str, dict[str, list[str]]] = field(default_factory=dict)

    def public_char_ids(self) -> list[str]:
        return [c.asset_id for c in self.characters if c.scope == "public"]

    def public_scene_ids(self) -> list[str]:
        return [s.asset_id for s in self.scenes if s.scope == "public"]

    def scope_of(self, asset_id: str) -> str:
        for e in list(self.characters) + list(self.scenes):
            if e.asset_id == asset_id:
                return e.scope
        return "public"            # 不在表里 → 当公共(保守: 受保护, 不被逐集随意改)

    def episode_private(self, eid: str) -> dict[str, list[str]]:
        """该集的私有 角色/场景 id(逐集/QC 返工的可改范围)。"""
        ids = (self.per_episode.get(eid) or {}).get("private") or []
        cset = {c.asset_id for c in self.characters}
        return {"characters": [i for i in ids if i in cset],
                "scenes": [i for i in ids if i not in cset]}

    @classmethod
    def from_dict(cls, data):
        cs = [AssetEntry(**_only_fields(AssetEntry, c)) for c in data.get("characters", [])]
        ss = [AssetEntry(**_only_fields(AssetEntry, s)) for s in data.get("scenes", [])]
        return cls(novel_title=data.get("novel_title", ""), characters=cs, scenes=ss,
                   per_episode=data.get("per_episode", {}) or {})
