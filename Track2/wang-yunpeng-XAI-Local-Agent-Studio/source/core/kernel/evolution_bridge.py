"""XAI 进化桥接 —— 从 engine_xai.py 上帝类外移（Phase E）。

承载：
- trigger_gepa_evolution(engine, task, confidence)：GEPA 自进化触发器（daemon 线程 fire-and-forget）

行为零变更：所有逻辑原样平移，仅 self -> engine。
"""

from __future__ import annotations


def trigger_gepa_evolution(engine, task: str, confidence: float) -> None:
    """B1: GEPA 自进化触发器 — daemon 线程 fire-and-forget，不阻塞主流程。"""
    def _do_evolve():
        try:
            engine.gepa_scheduler.trigger_evolution(
                reason=f"auto: confidence {confidence:.2f} below 0.5 on task: {task[:80]}"
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"GEPA 自进化触发失败（已忽略）: {e}")
    import threading
    th = threading.Thread(target=_do_evolve, daemon=True)
    th.start()
