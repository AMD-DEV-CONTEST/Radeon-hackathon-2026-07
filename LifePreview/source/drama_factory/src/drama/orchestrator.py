"""流水线编排器：状态机 + 任务队列。

阶段(stage)是粗粒度状态机，串行推进：
    split -> story_bible -> characters -> scenes -> storyboard
          -> char_assets -> keyframes -> clips -> voice -> lipsync
          -> subtitles -> assemble -> review

镜头级(shot)任务是细粒度任务队列：keyframes/clips/voice/lipsync 这些重活
按 shot 拆成独立任务，用线程池分发到两张 4090(两个 ComfyUI 实例)并行执行，
失败的单个 shot 可重试且不影响整集。

断点续跑：每个阶段产物落盘并写 state.json；重跑时跳过已完成阶段。
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Optional

from .context import Context
from .schemas import ShotList, Shot

# 阶段顺序
STAGES = [
    "split", "story_bible", "characters", "scenes", "storyboard",
    "char_assets", "keyframes", "clips", "voice", "lipsync",
    "subtitles", "assemble", "review",
]


class Orchestrator:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.state_path = ctx.paths.root / "state.json"
        self.state = self._load_state()

    # ---------- 状态持久化 ----------
    def _load_state(self) -> dict:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        return {"done_stages": [], "current": None}

    def _save_state(self) -> None:
        from .runtime import atomic_write_json
        atomic_write_json(self.state_path, self.state)
        if self.ctx.state_listener is not None:
            self.ctx.state_listener(dict(self.state))

    def mark_done(self, stage: str) -> None:
        if stage not in self.state["done_stages"]:
            self.state["done_stages"].append(stage)
        self.state["current"] = None
        self._save_state()

    def is_done(self, stage: str) -> bool:
        return stage in self.state["done_stages"]

    def run_stage(self, stage: str, fn: Callable, force: bool = False) -> None:
        self.ctx.check_cancelled()
        if self.is_done(stage) and not force:
            self.ctx.log.info(f"== 跳过已完成阶段: {stage}")
            return
        self.ctx.log.info(f"== 开始阶段: {stage}")
        self.state["current"] = stage
        self._save_state()
        t0 = time.time()
        fn()
        self.ctx.check_cancelled()
        self.mark_done(stage)
        self.ctx.log.info(f"== 完成阶段: {stage}  ({time.time()-t0:.1f}s)")

    # ---------- 镜头级并行任务队列(双卡) ----------
    def run_shots_parallel(
        self,
        shot_list: ShotList,
        worker: Callable[[Shot, int], None],
        filter_status: tuple[str, ...],
        save_path: Path,
        max_retries: int = 2,
        predicate: Optional[Callable[[Shot], bool]] = None,
    ) -> None:
        """把符合 filter_status (且 predicate) 的 shot 拆成任务，按卡数并行执行 worker(shot, shard)。

        worker 负责生成产物并就地修改 shot 的字段/状态；本方法负责调度、重试、落盘。
        predicate: 额外筛选(如"只跑切镜头"); None 表示不额外筛。
        """
        n = max(self.ctx.n_gpus, 1)
        todo = [s for s in shot_list.shots
                if s.status in filter_status and (predicate is None or predicate(s))]
        if not todo:
            return
        self.ctx.log.info(f"   并行处理 {len(todo)} 个镜头, 使用 {n} 张卡")

        def _task(idx: int, shot: Shot) -> tuple[Shot, Optional[Exception]]:
            for attempt in range(max_retries + 1):
                # 每次重试轮换实例。某个 ComfyUI 进程退出时，继续连接同一死亡端口
                # 不可能恢复；换到存活实例后可排队完成，同时保留原有轮询分片策略。
                shard = (idx + attempt) % n
                try:
                    self.ctx.check_cancelled()
                    # 绑定线程本地 shot_id：worker 内各 agent 通过 ctx.log 打出的
                    # 所有日志会被额外汇聚到 logs/shots/<shot_id>.log。
                    with self.ctx.shot_log(shot.shot_id):
                        worker(shot, shard)
                    self.ctx.check_cancelled()
                    return shot, None
                except Exception as e:  # noqa: BLE001
                    shot.retries += 1
                    self.ctx.log.warning(
                        f"   镜头 {shot.shot_id} 第 {attempt+1} 次失败: {e}")
                    if attempt == max_retries:
                        shot.status = "failed"
                        shot.qc_notes = f"重试耗尽: {e}"
                        return shot, e
                    time.sleep(2)
            return shot, None

        # ComfyUI 推理本身占满一张卡，故线程数=卡数即可(线程只负责等待 HTTP)
        with ThreadPoolExecutor(max_workers=max(n, 1)) as pool:
            futures = {pool.submit(_task, i, s): s for i, s in enumerate(todo)}
            for fut in as_completed(futures):
                fut.result()
                shot_list.save(save_path)  # 每完成一个就落盘，保证断点续跑

        failed = [s.shot_id for s in todo if s.status == "failed"]
        if failed:
            self.ctx.log.warning(f"   有 {len(failed)} 个镜头失败(可单独返工): {failed}")

    def run_shots_sequential(
        self,
        shot_list: ShotList,
        worker: Callable[[Shot, int], None],
        filter_status: tuple[str, ...],
        save_path: Path,
        max_retries: int = 2,
        predicate: Optional[Callable[[Shot], bool]] = None,
    ) -> None:
        """按 shot 顺序逐个执行(不并行)。用于"接上一镜末帧"的连续镜头：必须等前一镜
        成片后才能取其末帧；单镜重试仍轮换 shard，避开已退出的实例。"""
        todo = [s for s in shot_list.shots
                if s.status in filter_status and (predicate is None or predicate(s))]
        if not todo:
            return
        self.ctx.log.info(f"   顺序处理 {len(todo)} 个连续镜头(接上一镜末帧)")
        for shot in todo:
            for attempt in range(max_retries + 1):
                try:
                    self.ctx.check_cancelled()
                    with self.ctx.shot_log(shot.shot_id):
                        worker(shot, attempt % max(self.ctx.n_gpus, 1))
                    self.ctx.check_cancelled()
                    break
                except Exception as e:  # noqa: BLE001
                    shot.retries += 1
                    self.ctx.log.warning(
                        f"   镜头 {shot.shot_id} 第 {attempt+1} 次失败: {e}")
                    if attempt == max_retries:
                        shot.status = "failed"
                        shot.qc_notes = f"重试耗尽: {e}"
                    else:
                        time.sleep(2)
            shot_list.save(save_path)
