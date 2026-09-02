"""阶段 9 — 配音 agent(IndexTTS2 / CosyVoice2)。

为每个有台词的镜头按说话人音色生成配音 wav。
首选 IndexTTS2: 支持零样本音色克隆 + 情感控制 + **精确时长控制**(对短剧对轨极关键)。
后端通过 config/pipeline.yaml 的 tts.endpoint 配置(一个本地 HTTP 服务)。
镜头级并行(CPU/GPU 轻, 可多线程)。
"""
from __future__ import annotations

import base64
import shutil
import wave
from pathlib import Path

from .base import Agent
from ..schemas import Shot, CharacterBible

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


class TTSAgent(Agent):
    name = "配音"

    def __init__(self, ctx, chars: CharacterBible):
        super().__init__(ctx)
        self.chars = chars
        self.endpoint = ctx.cfg("tts", "endpoint", default="http://127.0.0.1:7861/tts")
        self.backend = ctx.cfg("tts", "backend", default="indextts2")
        self.timeout = ctx.cfg("tts", "timeout_sec", default=120)

    def __call__(self, shot: Shot, shard: int = 0) -> None:
        if not shot.dialogue.strip():
            shot.status = "voice_ok"  # 无台词镜头跳过
            return
        c = self.chars.get(shot.speaker) if shot.speaker else None
        audio_dir = self.ctx.paths.audio / shot.episode_id
        audio_dir.mkdir(parents=True, exist_ok=True)

        if self.ctx.dry_run:
            out = audio_dir / f"{shot.shot_id}.wav"
            self._write_silence(out, sec=max(shot.duration_sec, 1.0))
        elif self.backend == "edge":
            # edge-tts：微软在线中文配音，免部署/免 key。voices 里可按 char_id 指定音色名，
            # 否则用 default_voice。情感/时长精确控制 edge 不支持(要这些就用 indextts2)。
            out = audio_dir / f"{shot.shot_id}.mp3"
            voice = (self.ctx.cfg("tts", "voices", c.char_id, default="") if c else "") \
                or self.ctx.cfg("tts", "default_voice", default="zh-CN-XiaoxiaoNeural")
            self._edge_tts(shot.dialogue, voice, out)
        else:
            out = audio_dir / f"{shot.shot_id}.wav"
            if requests is None:
                raise RuntimeError("缺少 requests 包，请 pip install requests")
            ref_audio = self.ctx.cfg("tts", "voices", c.char_id, default="") if c else ""
            payload = {
                "text": shot.dialogue,
                "speaker": c.char_id if c else "default",
                "ref_audio": ref_audio,
                "emotion": shot.emotion,
                "target_seconds": shot.duration_sec,  # IndexTTS2 时长控制
            }
            r = requests.post(self.endpoint, json=payload, timeout=self.timeout)
            r.raise_for_status()
            self._save_response(r, out)

        shot.voice_path = str(out)
        shot.status = "voice_ok"

    def _edge_tts(self, text: str, voice: str, out: Path) -> None:
        """用 edge-tts(微软在线 TTS)合成中文配音到 out(mp3)。在线程池内调用安全。"""
        try:
            import edge_tts
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("缺少 edge-tts，请 pip install edge-tts") from e
        import asyncio

        async def _go():
            await edge_tts.Communicate(text, voice).save(str(out))

        asyncio.run(_go())

    def _save_response(self, r, out: Path) -> None:
        """容忍多种 TTS 服务返回形态, 统一落成 wav 文件。

        优先级:
          1. Content-Type 为 audio/* 或 octet-stream -> 直接写 r.content(原始 wav 字节)。
          2. 否则按 JSON 解析, 依次接受:
             - audio_base64: base64 解码为字节;
             - audio_url:    GET 下载;
             - path:         服务端本地路径(同机部署常见), 存在则复制。
          3. 形态未知 -> 抛清晰错误。
        """
        ctype = (r.headers.get("Content-Type") or "").lower()
        if ctype.startswith("audio/") or "octet-stream" in ctype:
            out.write_bytes(r.content)
            return

        try:
            data = r.json()
        except ValueError:
            # 既不是音频也不是 JSON: 兜底当原始字节(部分服务不带 Content-Type)
            if r.content:
                out.write_bytes(r.content)
                return
            raise RuntimeError(f"TTS 返回无法识别(Content-Type={ctype!r}, 非音频非 JSON)")

        if not isinstance(data, dict):
            raise RuntimeError(f"TTS 返回 JSON 形态未知: {str(data)[:300]}")

        b64 = data.get("audio_base64") or data.get("audio_b64")
        if b64:
            out.write_bytes(base64.b64decode(b64))
            return

        url = data.get("audio_url")
        if url:
            dl = requests.get(url, timeout=self.timeout)
            dl.raise_for_status()
            out.write_bytes(dl.content)
            return

        path = data.get("path") or data.get("audio_path")
        if path and Path(path).exists():
            shutil.copyfile(path, out)
            return

        raise RuntimeError(f"TTS 返回 JSON 缺少可用音频字段(audio_base64/audio_url/path): {str(data)[:300]}")

    @staticmethod
    def _write_silence(path: Path, sec: float, rate: int = 24000) -> None:
        with wave.open(str(path), "w") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
            w.writeframes(b"\x00\x00" * int(rate * sec))
