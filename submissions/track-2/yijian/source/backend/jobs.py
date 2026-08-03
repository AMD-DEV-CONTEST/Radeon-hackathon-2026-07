# -*- coding: utf-8 -*-
"""单队列、可取消、可缓存的本地整盘分析任务。"""

from __future__ import annotations

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

import library
import report_narratives
import reports
import sgf
from engine import KataGoEngine, KataGoError
from goboard import replay


FAST_SCAN_VISITS = max(1, int(os.getenv("GOMENTOR_SCAN_VISITS", "32")))
FAST_REVIEW_VISITS = max(32, int(os.getenv("GOMENTOR_FAST_REVIEW_VISITS", "128")))
FAST_REVIEW_NODES = max(1, int(os.getenv("GOMENTOR_FAST_REVIEW_NODES", "3")))
FAST_TARGET_SECONDS = max(
    30.0, float(os.getenv("GOMENTOR_FAST_TARGET_SECONDS", "90"))
)
DEEP_NODE_VISITS = max(64, int(os.getenv("GOMENTOR_DEEP_VISITS", "128")))
CRITICAL_NODE_VISITS = max(
    DEEP_NODE_VISITS, int(os.getenv("GOMENTOR_CRITICAL_VISITS", "128"))
)
MAX_DEEP_NODES = max(4, int(os.getenv("GOMENTOR_MAX_DEEP_NODES", "12")))
CRITICAL_NODE_COUNT = max(1, int(os.getenv("GOMENTOR_CRITICAL_NODE_COUNT", "3")))
OWNERSHIP_SAMPLE_STEP = max(10, int(os.getenv("GOMENTOR_OWNERSHIP_STEP", "20")))


class AnalysisManager:
    def __init__(self, engine):
        self.engine = engine
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="yijian-analysis")
        self._cpu_pool = ThreadPoolExecutor(
            max_workers=max(2, min(8, os.cpu_count() or 2)),
            thread_name_prefix="yijian-cpu",
        )
        self._submit_lock = Lock()

    def signature(self, game_detail: dict, mode: str = "fast") -> str:
        mode = "deep" if mode == "deep" else "fast"
        if isinstance(self.engine, KataGoEngine):
            model_stat = self.engine.model.stat()
            config_stat = self.engine.config.stat()
            engine_part = (
                f"{self.engine.version}|{self.engine.model_name}|"
                f"{getattr(self.engine, 'model_sha256', None) or 'unverified-model'}|"
                f"{model_stat.st_size}:{model_stat.st_mtime_ns}|"
                f"{self.engine.config.name}:"
                f"{config_stat.st_size}:{config_stat.st_mtime_ns}|"
                f"{mode}|{FAST_SCAN_VISITS}|"
                f"{FAST_REVIEW_VISITS}|{FAST_REVIEW_NODES}|{FAST_TARGET_SECONDS:g}|"
                f"{DEEP_NODE_VISITS}|{CRITICAL_NODE_VISITS}|{MAX_DEEP_NODES}|"
                f"{CRITICAL_NODE_COUNT}|{OWNERSHIP_SAMPLE_STEP}"
            )
        else:
            engine_part = (
                f"mock|deterministic|{mode}|{FAST_SCAN_VISITS}|"
                f"{FAST_REVIEW_VISITS}|{FAST_REVIEW_NODES}|"
                f"{CRITICAL_NODE_COUNT}|{OWNERSHIP_SAMPLE_STEP}"
            )
        value = (
            f"{game_detail['sgf']}|{engine_part}|"
            f"{report_narratives.signature_fragment()}|"
            "report-v11-variation-adjudication"
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def create(
        self, game_id: str, perspective: str, force: bool = False, mode: str = "fast"
    ) -> dict:
        detail = library.get_game(game_id)
        if not detail:
            raise KeyError(game_id)
        perspective = "W" if perspective == "W" else "B"
        mode = "deep" if mode == "deep" else "fast"
        signature = self.signature(detail, mode)
        cached = None if force else library.get_cached_report(game_id, perspective, signature)
        if cached:
            return library.create_analysis_job(
                game_id, perspective, signature, detail["moveCount"],
                status="completed", report_id=cached["id"],
                mode=mode,
            )
        job = library.create_analysis_job(
            game_id, perspective, signature, detail["moveCount"], mode=mode
        )
        with self._submit_lock:
            self._pool.submit(self._run, job["id"])
        return job

    def _update(self, job_id: str, **changes) -> None:
        library.update_analysis_job(job_id, **changes)

    def _cancelled(self, job_id: str) -> bool:
        return library.cancel_requested(job_id)

    def _run(self, job_id: str) -> None:
        job = library.get_analysis_job(job_id)
        if not job:
            return
        started = time.monotonic()
        mode = job.get("mode", "fast")
        target_seconds = FAST_TARGET_SECONDS if mode == "fast" else 0

        def timing(**changes) -> None:
            elapsed = max(0.0, time.monotonic() - started)
            changes.setdefault("elapsedSeconds", round(elapsed, 1))
            changes.setdefault("targetSeconds", target_seconds)
            self._update(job_id, **changes)

        try:
            timing(
                status="running", stage="parse", progress=1,
                etaSeconds=target_seconds or None,
                message="正在解析棋谱并验证每一手是否合法",
            )
            detail = library.get_game(job["gameId"])
            game = sgf.parse(detail["sgf"])
            _, states = replay(game)
            preprocess_future = self._cpu_pool.submit(
                reports.preprocess_game, game, states
            )
            scan_visits = (
                DEEP_NODE_VISITS if mode == "deep" else FAST_SCAN_VISITS
            )
            scan_started = time.monotonic()
            timing(
                stage="scan", progress=3.0, currentTurn=0,
                totalTurns=len(game.moves),
                scanVisits=scan_visits,
                reviewVisits=(
                    FAST_REVIEW_VISITS if mode == "fast" else CRITICAL_NODE_VISITS
                ),
                etaSeconds=target_seconds or None,
                message=f"正在以每手 {scan_visits} visits 扫描整盘",
            )

            def progress(completed: int, total: int) -> None:
                scan_elapsed = max(0.1, time.monotonic() - scan_started)
                rate = completed / scan_elapsed
                scan_eta = max(0.0, total - completed) / max(0.1, rate)
                reserve = 3.0 if mode == "fast" else 10.0
                percent = 3.0 + 75.0 * completed / max(1, total)
                timing(
                    progress=round(min(78.0, percent), 1),
                    currentTurn=max(0, completed - 1),
                    rate=round(rate, 1),
                    etaSeconds=round(scan_eta + reserve, 1),
                    message=f"全盘扫描 {completed}/{total}",
                )

            if isinstance(self.engine, KataGoEngine):
                analysis = self.engine.analyze_game(
                    game, max_visits=scan_visits, progress=progress,
                    cancelled=lambda: self._cancelled(job_id),
                )
            else:
                analysis = self.engine.analyze_game(game)
                progress(len(game.moves) + 1, len(game.moves) + 1)
            analysis["scanVisits"] = scan_visits
            analysis["criticalVisits"] = (
                FAST_REVIEW_VISITS if mode == "fast" else CRITICAL_NODE_VISITS
            )
            analysis["deepNodeVisits"] = DEEP_NODE_VISITS
            analysis["analysisMode"] = mode
            analysis["targetSeconds"] = target_seconds
            if self._cancelled(job_id):
                raise KataGoError("分析已取消")

            timing(
                stage="phases", progress=79.0,
                etaSeconds=max(1.0, target_seconds - (time.monotonic() - started))
                if mode == "fast" else None,
                message="正在识别定式、布局、中盘与官子边界",
            )
            ownership_samples: dict[int, list[float]] = {}
            # 快速模式优先在目标时间内生成完整报告。地盘采样保留给深度模式，
            # 当前手需要时仍可按局面即时调用 KataGo，不降低规则与着手证据质量。
            if mode == "deep" and isinstance(self.engine, KataGoEngine):
                sample_turns = list(range(80, len(game.moves), OWNERSHIP_SAMPLE_STEP))
                for index, turn in enumerate(sample_turns):
                    if self._cancelled(job_id):
                        raise KataGoError("分析已取消")
                    sample = self.engine.analyze_position(
                        game, turn, visits=8, include_ownership=True,
                        cancelled=lambda: self._cancelled(job_id),
                    )
                    if sample.get("ownership"):
                        ownership_samples[turn] = sample["ownership"]
                    timing(
                        progress=79 + round(5 * (index + 1) / max(1, len(sample_turns)), 1),
                        currentTurn=turn, message=f"阶段采样 {index + 1}/{len(sample_turns)}",
                    )

            preprocessed = preprocess_future.result()
            raw = reports.build_raw_report(
                game,
                analysis,
                job["perspective"],
                ownership_samples,
                preprocessed=preprocessed,
            )
            loss_by_turn = {item["turn"]: item for item in raw["losses"]}
            candidates = sorted(
                raw["candidateTurns"],
                key=lambda turn: max(
                    loss_by_turn.get(turn, {}).get("winrateLoss", 0) / 10,
                    loss_by_turn.get(turn, {}).get("scoreLoss", 0) / 5,
                ),
                reverse=True,
            )
            if mode == "deep":
                for node in raw["losses"]:
                    node["deepened"] = True
                    node["deepVisits"] = scan_visits
                    node["confidence"] = "medium"
                    node["stability"] = "full-scan"
                candidates = candidates[:CRITICAL_NODE_COUNT]
            else:
                candidates = candidates[:FAST_REVIEW_NODES]
            critical_turns = set(candidates[:CRITICAL_NODE_COUNT])
            timing(
                stage="deepen", progress=84.0,
                etaSeconds=max(1.0, target_seconds - (time.monotonic() - started))
                if mode == "fast" else None,
                message=(
                    f"正在以 {CRITICAL_NODE_VISITS} visits 复核 "
                    f"{len(candidates)} 个最高优先级节点"
                    if mode == "deep"
                    else (
                        f"正在自适应复核最多 {len(candidates)} 个关键节点"
                        f"（{FAST_REVIEW_VISITS} visits）"
                    )
                ),
            )
            reviewed = 0
            review_started = time.monotonic()
            if isinstance(self.engine, KataGoEngine):
                for index, turn in enumerate(candidates):
                    if self._cancelled(job_id):
                        raise KataGoError("分析已取消")
                    elapsed = time.monotonic() - started
                    if mode == "fast" and elapsed >= target_seconds - 1.0:
                        break
                    visits = FAST_REVIEW_VISITS if mode == "fast" else (
                        CRITICAL_NODE_VISITS if turn in critical_turns
                        else DEEP_NODE_VISITS
                    )
                    pre = self.engine.analyze_position(
                        game, turn - 1, visits=visits,
                        cancelled=lambda: self._cancelled(job_id),
                    )
                    post = self.engine.analyze_position(
                        game, turn, visits=visits,
                        cancelled=lambda: self._cancelled(job_id),
                    )
                    reports.apply_deep_result(
                        raw, turn, pre, post, visits=visits,
                        confidence=(
                            "medium" if mode == "fast"
                            else ("high" if turn in critical_turns else "medium")
                        ),
                    )
                    reviewed += 1
                    elapsed = time.monotonic() - started
                    average = max(
                        0.1, (time.monotonic() - review_started) / reviewed
                    )
                    eta = average * max(0, len(candidates) - reviewed) + 1
                    timing(
                        progress=round(
                            84 + 12 * reviewed / max(1, len(candidates)), 1
                        ),
                        currentTurn=turn,
                        etaSeconds=round(eta, 1),
                        message=f"关键节点复核 {reviewed}/{len(candidates)}",
                    )
            else:
                reviewed = len(candidates)
                timing(progress=96.0, etaSeconds=1, message="演示引擎已完成节点复核")
            analysis["reviewedNodeCount"] = reviewed
            raw["engine"]["reviewedNodeCount"] = reviewed
            raw["engine"]["targetSeconds"] = target_seconds

            if self._cancelled(job_id):
                raise KataGoError("分析已取消")
            timing(
                stage="narrate", progress=97.0, etaSeconds=None,
                message="KataGo 已释放，正在批量生成可缓存的教练讲解",
            )
            report_narratives.enrich(raw)
            timing(
                stage="report", progress=99.0, etaSeconds=1,
                message="正在把四阶段评分、证据与讲解写入 SQLite",
            )
            report_id = library.save_report(
                job["gameId"], job["perspective"], job["signature"], raw
            )
            timing(
                status="completed", stage="completed", progress=100.0,
                currentTurn=len(game.moves), reportId=report_id,
                etaSeconds=0,
                message="整盘预分析完成",
            )
        except Exception as exc:
            cancelled = self._cancelled(job_id) or "取消" in str(exc)
            timing(
                status="cancelled" if cancelled else "failed",
                stage="cancelled" if cancelled else "failed",
                etaSeconds=None,
                message="分析已取消" if cancelled else "本地分析失败，可保留棋谱后重试",
                error="" if cancelled else str(exc),
            )

    def get(self, job_id: str) -> dict | None:
        return library.get_analysis_job(job_id)

    def cancel(self, job_id: str) -> dict | None:
        return library.request_cancel(job_id)

    def deepen_node(
        self, game_id: str, perspective: str, turn: int, visits: int = 256
    ) -> dict:
        if not isinstance(self.engine, KataGoEngine):
            raise KataGoError("真实 KataGo 未配置，无法深度复核节点")
        detail = library.get_game(game_id)
        cached = library.latest_report(game_id, perspective)
        if not detail or not cached:
            raise KeyError(game_id)
        game = sgf.parse(detail["sgf"])
        if turn < 1 or turn > len(game.moves):
            raise ValueError("turn out of range")
        raw = cached["raw"]
        mode = raw.get("engine", {}).get("analysisMode", "fast")
        signature = self.signature(detail, mode)
        if cached.get("signature") != signature:
            raise ValueError(
                "当前整盘报告与已配置的分析引擎不一致，请先重新完成整盘分析"
            )
        node = next(
            (item for item in raw.get("losses", []) if item.get("turn") == turn),
            None,
        )
        if not node:
            raise ValueError("该手不在当前报告的可复核节点中")
        visits = max(DEEP_NODE_VISITS, min(CRITICAL_NODE_VISITS * 2, int(visits)))
        pre = self.engine.analyze_position(game, turn - 1, visits=visits)
        post = self.engine.analyze_position(game, turn, visits=visits)
        reports.apply_deep_result(
            raw,
            turn,
            pre,
            post,
            visits=visits,
            confidence="high",
            analysis_source="katago",
            demo=False,
            engine_version=self.engine.version,
            engine_model=self.engine.model_name,
        )
        report_id = library.save_report(game_id, perspective, signature, raw)
        node = next(
            (item for item in raw.get("losses", []) if item.get("turn") == turn),
            None,
        )
        return {"reportId": report_id, "turn": turn, "node": node}

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._cpu_pool.shutdown(wait=False, cancel_futures=True)
