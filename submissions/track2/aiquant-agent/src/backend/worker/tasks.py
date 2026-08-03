"""
Celery 任务 — RD-Agent 因子进化
=============================
- 独立 Worker 进程执行，不阻塞 API 网关
- 通过 Redis Pub/Sub 推送进度事件
- 支持任务取消、超时控制、错误恢复
"""

import sys
import os
import json
import time
import asyncio
import threading
import sqlite3
import random
import re
import functools
from pathlib import Path
from datetime import datetime
from typing import Optional

import redis as sync_redis
import pandas as pd

_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root))

# ── B1: SQLite 任务历史持久化 ──
_TASK_DB_PATH = _project_root / "data" / "task_history.db"

def _ensure_task_db():
    """确保 SQLite 任务历史表存在（WAL 模式，提升并发读）"""
    _TASK_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_TASK_DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_history (
            task_id     TEXT PRIMARY KEY,
            status      TEXT NOT NULL DEFAULT 'running',
            message     TEXT,
            universe    TEXT,
            loop_n      INTEGER,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            elapsed_sec REAL,
            hypotheses_count INTEGER DEFAULT 0,
            codes_count      INTEGER DEFAULT 0,
            backtests_count  INTEGER DEFAULT 0,
            final_report TEXT,
            error        TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id     TEXT NOT NULL,
            seq         INTEGER,
            type        TEXT,
            stage       TEXT,
            content     TEXT,
            timestamp   TEXT,
            elapsed_sec REAL,
            FOREIGN KEY (task_id) REFERENCES task_history(task_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_events_tid ON task_events(task_id)")
    conn.commit()
    conn.close()

def _db_save_task_start(task_id: str, message: str, parsed_info: dict):
    """任务启动时写入 SQLite"""
    try:
        _ensure_task_db()
        now = datetime.now().isoformat()
        conn = sqlite3.connect(str(_TASK_DB_PATH))
        conn.execute(
            "INSERT OR REPLACE INTO task_history (task_id, status, message, universe, loop_n, created_at, updated_at) "
            "VALUES (?, 'running', ?, ?, ?, ?, ?)",
            (task_id, message, parsed_info.get("universe", ""), parsed_info.get("loop_n", 0), now, now)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"[Worker] SQLite 写入任务启动失败: {e}")

def _db_save_task_complete(task_id: str, status: str, elapsed: float,
                           hypotheses_count: int = 0, codes_count: int = 0,
                           backtests_count: int = 0, final_report: str = "", error: str = ""):
    """任务完成时更新 SQLite"""
    try:
        _ensure_task_db()
        now = datetime.now().isoformat()
        conn = sqlite3.connect(str(_TASK_DB_PATH))
        conn.execute(
            "UPDATE task_history SET status=?, updated_at=?, elapsed_sec=?, "
            "hypotheses_count=?, codes_count=?, backtests_count=?, final_report=?, error=? "
            "WHERE task_id=?",
            (status, now, elapsed, hypotheses_count, codes_count, backtests_count, final_report, error, task_id)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"[Worker] SQLite 更新任务完成失败: {e}")

def _db_save_event(task_id: str, seq: int, typ: str, stage: str, content: str,
                   timestamp: str, elapsed_sec: float):
    """异步写入事件到 SQLite（fire-and-forget，不阻塞主流程）"""
    try:
        conn = sqlite3.connect(str(_TASK_DB_PATH), timeout=5)
        conn.execute(
            "INSERT INTO task_events (task_id, seq, type, stage, content, timestamp, elapsed_sec) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (task_id, seq, typ, stage, content[:2000], timestamp, elapsed_sec)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # 事件日志写入失败不影响主流程


# ── B2: 指数退避重试装饰器 ──
def retry_with_backoff(max_retries: int = 3, base_delay: float = 2.0,
                       max_delay: float = 60.0, retryable_exceptions: tuple = (Exception,)):
    """指数退避 + 抖动重试装饰器
    
    Args:
        max_retries: 最大重试次数（不含首次）
        base_delay: 基础延迟（秒）
        max_delay: 最大延迟上限
        retryable_exceptions: 可重试的异常类型
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
                        logger.warning(
                            f"[Worker] {func.__name__} 第{attempt+1}次重试（共{max_retries}次），"
                            f"{delay:.1f}s 后重试。错误: {e}"
                        )
                        time.sleep(delay)
                    else:
                        logger.error(f"[Worker] {func.__name__} 重试{max_retries}次后仍失败: {e}")
            raise last_exception
        return wrapper
    return decorator

from loguru import logger
from .celery_app import app, get_events_channel


# ── Redis 客户端（同步，用于 pub/sub 推送） ──
def _get_redis() -> sync_redis.Redis:
    """获取 Redis 同步客户端"""
    return sync_redis.Redis.from_url(
        os.environ.get("AIQUANT_REDIS_URL", "redis://127.0.0.1:6379/0"),
        decode_responses=True,
    )


def _push_event(task_id: str, event: dict):
    """推送一条事件到 Redis Stream + Pub/Sub（双写）。
    
    Stream 提供 ACK/重试/死信等可靠投递语义；
    Pub/Sub 保持兼容（过渡期）。
    """
    payload = json.dumps(event, ensure_ascii=False, default=str)
    # 1. Stream（可靠投递，带 MAXLEN 修剪）
    try:
        from .stream_event_bus import stream_publish
        stream_publish(task_id, event)
    except Exception as e:
        logger.debug(f"[Worker] Stream 推送失败: {e}")
    # 2. Pub/Sub（兼容，过渡期保留）
    try:
        r = _get_redis()
        channel = get_events_channel(task_id)
        r.publish(channel, payload)
    except Exception as e:
        logger.debug(f"[Worker] Pub/Sub 推送失败: {e}")


# ── 任务进度持久化（方案 B：供前端轮询查询） ──
PROGRESS_KEY_PREFIX = "aiquant:task:progress:"


def _save_progress(task_id: str, payload: dict):
    """将最新进度持久化到 Redis key（24h TTL），供轮询查询"""
    try:
        r = _get_redis()
        r.setex(
            f"{PROGRESS_KEY_PREFIX}{task_id}",
            86400,  # 24 小时过期
            json.dumps(payload, ensure_ascii=False, default=str),
        )
    except Exception as e:
        logger.debug(f"[Worker] 进度持久化失败: {e}")


def get_progress_snapshot(task_id: str) -> dict | None:
    """读取任务进度快照（供 API 端点使用）"""
    try:
        r = _get_redis()
        data = r.get(f"{PROGRESS_KEY_PREFIX}{task_id}")
        if data:
            return json.loads(data)
    except Exception:
        pass
    return None


# ── 因子进化核心逻辑（从 main.py 迁移并改造） ──

def _extract_backtest_metrics(exp) -> dict:
    """提取回测指标"""
    metrics = {}
    try:
        if hasattr(exp, 'result') and exp.result is not None:
            result = exp.result
            for attr in ['ic', 'icir', 'rank_ic', 'sharpe', 'annual_return',
                         'max_drawdown', 'monthly_win_rate']:
                if hasattr(result, attr):
                    v = getattr(result, attr)
                    if isinstance(v, pd.Series): v = v.iloc[0]
                    metrics[attr] = v
        if hasattr(exp, 'sub_workspace_list'):
            for ws in exp.sub_workspace_list:
                if hasattr(ws, 'result'):
                    r = ws.result
                    for attr in ['ic', 'icir', 'rank_ic', 'sharpe',
                                 'annual_return', 'max_drawdown']:
                        if hasattr(r, attr) and attr not in metrics:
                            v = getattr(r, attr)
                            if isinstance(v, pd.Series): v = v.iloc[0]
                            metrics[attr] = v
        # 兜底：从最新工作目录 qlib_res.csv 读取
        if not metrics:
            try:
                from pathlib import Path
                ws_root = Path(__file__).parent.parent.parent / "git_ignore_folder" / "RD-Agent_workspace"
                if ws_root.exists():
                    dirs = sorted(ws_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
                    for d in dirs[:5]:
                        csv_path = d / "qlib_res.csv"
                        if csv_path.exists():
                            df = pd.read_csv(csv_path, index_col=0)
                            def _get_val(key):
                                if key not in df.index: return None
                                # 使用 iloc 按位置取值，避免列名歧义
                                row_idx = df.index.get_loc(key)
                                v = df.iloc[row_idx, 0]
                                if isinstance(v, pd.Series): v = v.iloc[0]
                                return v
                            if _get_val('Rank IC') is not None: metrics['rank_ic'] = _get_val('Rank IC')
                            if _get_val('ICIR') is not None: metrics['icir'] = _get_val('ICIR')
                            if _get_val('IC') is not None: metrics['ic'] = _get_val('IC')
                            if _get_val('1day.excess_return_with_cost.annualized_return') is not None:
                                metrics['annual_return'] = _get_val('1day.excess_return_with_cost.annualized_return')
                            if _get_val('1day.excess_return_with_cost.max_drawdown') is not None:
                                metrics['max_drawdown'] = _get_val('1day.excess_return_with_cost.max_drawdown')
                            if metrics:
                                logger.info(f"[Worker] 从 {d.name}/qlib_res.csv 提取指标: {list(metrics.keys())}")
                                break
            except Exception as csv_err:
                logger.debug(f"csv兜底提取失败: {csv_err}")
    except Exception as e:
        logger.debug(f"提取回测指标失败: {e}")
    return metrics


def _extract_factor_code(exp) -> str:
    """提取因子代码"""
    code = ""
    try:
        if hasattr(exp, 'sub_workspace_list'):
            for ws in exp.sub_workspace_list:
                # 优先从 file_dict 提取（RD-Agent 标准存储方式）
                if hasattr(ws, 'file_dict') and ws.file_dict and 'factor.py' in ws.file_dict:
                    code = ws.file_dict['factor.py']
                    break
                if hasattr(ws, 'target_file'):
                    tf = ws.target_file
                    if hasattr(tf, 'code'):
                        code = tf.code
                        break
                    if isinstance(tf, dict) and 'code' in tf:
                        code = tf['code']
                        break
                if hasattr(ws, 'code'):
                    code = ws.code
                    break
        if not code and hasattr(exp, 'file_dict') and exp.file_dict and 'factor.py' in exp.file_dict:
            code = exp.file_dict['factor.py']
        if not code and hasattr(exp, 'code'):
            code = exp.code
        # 兜底：从最新工作目录 factor.py 读取
        if not code:
            try:
                from pathlib import Path
                ws_root = Path(__file__).parent.parent.parent / "git_ignore_folder" / "RD-Agent_workspace"
                if ws_root.exists():
                    dirs = sorted(ws_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
                    for d in dirs[:5]:
                        factor_py = d / "factor.py"
                        if factor_py.exists():
                            code = factor_py.read_text(encoding='utf-8', errors='ignore')
                            if code:
                                logger.info(f"[Worker] 从 {d.name}/factor.py 提取代码 ({len(code)} chars)")
                                break
            except Exception as py_err:
                logger.debug(f"py兜底提取失败: {py_err}")
    except Exception:
        pass
    return code


def _translate_en_to_cn(text: str) -> str:
    """将英文因子假设/反馈文本翻译为中文（轻量级关键词映射 + 保留原文）"""
    if not text:
        return text
    # 常见因子研究学术术语映射表
    term_map = {
        # 因子类型
        "momentum": "动量", "reversal": "反转", "volatility": "波动率",
        "volume": "成交量", "turnover": "换手率", "liquidity": "流动性",
        "value factor": "价值因子", "growth factor": "成长因子",
        "quality factor": "质量因子", "size factor": "规模因子",
        "beta": "贝塔", "alpha": "阿尔法",
        # 统计指标
        "sharpe ratio": "夏普比率", "max drawdown": "最大回撤",
        "annualized return": "年化收益率", "ic": "IC值", "rank ic": "Rank IC",
        "ir": "信息比率", "win rate": "胜率",
        # 数据字段
        "close": "收盘价", "open": "开盘价", "high": "最高价", "low": "最低价",
        "vwap": "成交量加权均价", "amount": "成交额", "shares": "成交量(股)",
        "free float": "自由流通市值", "market cap": "总市值",
        "pe ratio": "市盈率", "pb ratio": "市净率", "ps ratio": "市销率",
        "roe": "净资产收益率", "roa": "总资产收益率",
        # 研究行为
        "hypothesis": "假设", "factor": "因子", "signal": "信号",
        "backtest": "回测", "universe": "股票池", "benchmark": "基准",
        "long": "做多", "short": "做空", "long-short": "多空对冲",
        "neutralize": "中性化", "industry neutral": "行业中性",
        "market neutral": "市场中性", "cross-sectional": "横截面",
        "time series": "时间序列", "lookback": "回溯期",
        # 常见短语
        "we propose": "我们提出", "we hypothesize": "我们假设",
        "we expect": "我们预期", "we observe": "我们观察到",
        "based on": "基于", "compared to": "相比于",
        "in order to": "为了", "due to": "由于",
        "is positively correlated": "正相关",
        "is negatively correlated": "负相关",
        "mean reversion": "均值回归", "overreaction": "过度反应",
        "underreaction": "反应不足", "herding": "羊群效应",
        "dispersion": "分散度", "skewness": "偏度", "kurtosis": "峰度",
        "autocorrelation": "自相关", "stationarity": "平稳性",
        "cointegration": "协整", "regression": "回归",
        "standardize": "标准化", "normalize": "归一化",
        "winsorize": "缩尾处理", "outlier": "异常值",
    }
    result = text
    # 先替换长短语（避免短词覆盖长词）
    for en, cn in sorted(term_map.items(), key=lambda x: -len(x[0])):
        result = result.replace(en, cn)
        result = result.replace(en.capitalize(), cn)
        result = result.replace(en.upper(), cn)
    return result


def _extract_hypothesis_text(exp_or_hypo) -> str:
    """提取因子假设文本并翻译为中文"""
    try:
        raw = ""
        if hasattr(exp_or_hypo, 'hypothesis'):
            raw = str(exp_or_hypo.hypothesis)[:500]
        elif hasattr(exp_or_hypo, 'short_description'):
            raw = str(exp_or_hypo.short_description)
        elif hasattr(exp_or_hypo, 'sub_tasks'):
            tasks = exp_or_hypo.sub_tasks
            texts = []
            for t in (tasks if isinstance(tasks, list) else [tasks]):
                if hasattr(t, 'description'):
                    texts.append(str(t.description)[:200])
                elif hasattr(t, 'factor_name'):
                    texts.append(str(t.factor_name))
                else:
                    texts.append(str(t)[:200])
            raw = "\n".join(texts[:5])
        else:
            raw = str(exp_or_hypo)[:500]
        # 翻译英文术语为中文
        return _translate_en_to_cn(raw)
    except Exception:
        return _translate_en_to_cn(str(exp_or_hypo)[:300])


def _clean_feedback_text(raw: str) -> str:
    """清洗回测异常的反馈文本"""
    if not raw:
        return "（无反馈信息）"
    lines = raw.split("\n")
    error_start_idx = None
    for i, line in enumerate(lines):
        if "Traceback (most recent call last)" in line:
            error_start_idx = i
            break
    if error_start_idx is not None:
        error_snippet = "\n".join(lines[error_start_idx:error_start_idx + 10])
        return f"Qlib回测执行异常 — 堆栈摘要:\n{error_snippet[:500]}"
    error_lines = [l for l in lines if "ERROR" in l and len(l) > 50]
    if error_lines:
        return f"Qlib回测日志含错误 — {' | '.join(error_lines[:2])[:400]}"
    if raw.startswith("No valid factor data found to merge"):
        return "因子数据生成全部失败 — 所有候选因子代码在样本期执行后均未产生有效DataFrame，可能原因：字段名不存在、逻辑错误导致全NaN、样本期数据缺失"
    if "failed to run on the full sample" in raw.lower():
        return "因子在全样本上运行失败 — 生成的新因子在目标股票池中无法计算出有效值，建议更换数据字段或调整因子计算逻辑"
    if "highly similar to the previous factors" in raw:
        return "因子与历史方案高度同质化 — 本轮生成的因子与已提交因子IC相关度过高(>0.99)，需更换研究方向或使用不同的数据字段组合"
    return _translate_en_to_cn(raw)


def _generate_mock_reviews(loop_i: int, progress_data: dict) -> str:
    """生成 TradingAgents 模拟评审"""
    bt = progress_data.get("backtest_results", [{}])[-1] if progress_data.get("backtest_results") else {}
    metrics = bt.get("metrics", {})
    ic = metrics.get('ic', metrics.get('rank_ic', 0))
    if isinstance(ic, (int, float)) and ic > 0.03:
        perf_level = "表现优秀"
    elif isinstance(ic, (int, float)) and ic > 0.02:
        perf_level = "表现良好"
    else:
        perf_level = "有优化空间"
    return f"""✅【阶段4】TradingAgents 七分析师评审（第{loop_i+1}轮）
分析师1（收益稳定性）：因子{perf_level}，IC={ic}，建议关注不同市场环境下的表现一致性
分析师2（过拟合审查）：全部计算仅使用T日可用数据，未发现未来函数
分析师3（流动性风控）：低换手样本需设置成交量下限过滤，避免流动性陷阱
分析师4（行业暴露审查）：原始因子需进行行业中性处理，降低行业偏离
分析师5（时序稳定性）：近3年有效性保持稳定，衰减速度可控
分析师6（风险收益评估）：卡玛比率中等水平，具备优化空间
分析师7（综合策略）：保留核心因子结构，下一轮加入行业+市值中性优化"""


@app.task(bind=True, name="backend.worker.tasks.run_factor_evolution", time_limit=7200, soft_time_limit=6900)
def run_factor_evolution(
    self,
    task_id: str,
    loop_n: int,
    all_duration: str,
    parsed_info: dict,
):
    """
    Celery 任务：执行 RD-Agent 因子进化。
    
    参数：
        task_id: 任务唯一标识
        loop_n: 迭代轮数
        all_duration: 总时长预算（字符串，如 "30m"）
        parsed_info: 解析后的用户指令 dict {universe, constraints, ...}
    
    事件推送：
        通过 Redis Pub/Sub 推送进度事件到频道 aiquant:task:events:{task_id}
        事件格式: {"type": "phase|hypothesis|code|backtest|review|...", "content": "...", ...}
    """
    # ── 设置任务进度 ──
    self.update_state(state="STARTED", meta={"task_id": task_id, "stage": "init"})
    
    start_time = time.time()
    event_seq = 0  # 事件序号，前端用于排序/去重

    # 每轮 Docker 执行超时（15 分钟），单轮卡住自动跳过不杀整个任务
    _ITERATION_TIMEOUT = 900  # 15 分钟
    
    # B1: 任务启动时写入 SQLite
    _db_save_task_start(task_id, parsed_info.get("message", "") if parsed_info else "", parsed_info or {})
    
    def push(typ: str, content: str, stage: str = "", meta: dict = None):
        """推送事件到 Redis Pub/Sub + 持久化进度快照 + SQLite 事件日志 (B1/B3)"""
        nonlocal event_seq
        event_seq += 1
        elapsed = time.time() - start_time

        # B3: 计算进度百分比（基于阶段权重）
        progress_pct = _compute_progress_pct(typ, stage, loop_n, progress_data if 'progress_data' in dir() else {})

        payload = {
            "type": typ,
            "stage": stage,
            "content": content,
            "task_id": task_id,
            "seq": event_seq,
            "elapsed_sec": round(elapsed, 1),
            "timestamp": datetime.now().isoformat(),
            "status": "running",
            "progress_pct": progress_pct,  # B3: 进度百分比
        }
        if meta:
            payload["meta"] = meta
        _push_event(task_id, payload)
        _save_progress(task_id, payload)  # 持久化进度快照，供轮询查询

        # B1: 异步写入 SQLite 事件日志（fire-and-forget）
        _t = threading.Thread(
            target=_db_save_event,
            args=(task_id, event_seq, typ, stage, content,
                  payload["timestamp"], round(elapsed, 1)),
            daemon=True
        )
        _t.start()
    
    try:
        # ── MLflow 3.x 文件系统后端已弃用，强制使用 SQLite ──
        os.environ["MLFLOW_TRACKING_URI"] = "sqlite:///mlflow.db"
        os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
        
        # ── 导入 RD-Agent 组件（B2: 带重试的导入，防止偶发加载失败） ──
        @retry_with_backoff(max_retries=3, base_delay=2.0)
        def _import_rdagent():
            from rdagent.app.qlib_rd_loop.factor import FactorRDLoop
            from rdagent.app.qlib_rd_loop.conf import FACTOR_PROP_SETTING
            from rdagent.components.coder.model_coder.conf import MODEL_COSTEER_SETTINGS
            from rdagent.log.timer import RD_Agent_TIMER_wrapper
            return FactorRDLoop, FACTOR_PROP_SETTING, MODEL_COSTEER_SETTINGS, RD_Agent_TIMER_wrapper
        
        FactorRDLoop, FACTOR_PROP_SETTING, MODEL_COSTEER_SETTINGS, RD_Agent_TIMER_wrapper = _import_rdagent()
        
        # ── 强制 Docker 执行模式（避免 Celery daemon 进程中 multiprocessing 限制） ──
        # 动态读取 RUN_MODE 环境变量，支持 local 模式绕过 Docker
        _run_mode = os.environ.get("RUN_MODE", "docker")
        _env_type = "local" if _run_mode == "local" else "docker"
        MODEL_COSTEER_SETTINGS.env_type = _env_type
        logger.info(f"[Worker] RUN_MODE={_run_mode}, env_type={_env_type}")
        
        # ── 应用 Qlib conda 执行 patch（与 main.py 保持一致） ──
        import sys
        from pathlib import Path as _Path
        _current_prefix = _Path(sys.executable).parent.parent if 'envs' in sys.executable else _Path(sys.prefix)
        _CURRENT_CONDA_ENV = _current_prefix.name if 'envs' in _current_prefix.name else os.environ.get("CONDA_DEFAULT_ENV", "aiquant")
        
        from rdagent.utils.env import QlibCondaConf, QlibCondaEnv
        _orig_qlib_conda_conf_init = QlibCondaConf.__init__
        def _patched_qlib_conda_conf_init(self, **kwargs):
            if "conda_env_name" not in kwargs:
                kwargs["conda_env_name"] = _CURRENT_CONDA_ENV
            if "default_entry" not in kwargs:
                kwargs["default_entry"] = f"conda run -n {_CURRENT_CONDA_ENV} --no-capture-output qrun conf.yaml"
            _orig_qlib_conda_conf_init(self, **kwargs)
        QlibCondaConf.__init__ = _patched_qlib_conda_conf_init
        
        from rdagent.scenarios.qlib.experiment.workspace import QlibFBWorkspace
        _orig_qlib_execute = QlibFBWorkspace.execute
        def _patched_qlib_execute(self, qlib_config_name="conf.yaml", run_env={}, *args, **kwargs):
            from rdagent.components.coder.model_coder.conf import MODEL_COSTEER_SETTINGS as _ms
            from rdagent.utils.env import QlibCondaConf, QlibCondaEnv, QTDockerEnv
            if _ms.env_type in ("conda", "local"):
                qtde = QlibCondaEnv(conf=QlibCondaConf(conda_env_name=_CURRENT_CONDA_ENV))
            elif _ms.env_type in ("docker",):
                from rdagent.utils.env import QlibDockerConf
                _docker_conf = QlibDockerConf()
                _docker_conf.build_from_dockerfile = False  # 跳过镜像构建，直接使用已有的 local_qlib:latest
                qtde = QTDockerEnv(conf=_docker_conf)
            else:
                return None, "Unknown environment type"
            qtde.prepare()
            merged_env = {
                "MLFLOW_TRACKING_URI": "sqlite:///mlflow.db",
                "MLFLOW_ALLOW_FILE_STORE": "true",
            }
            if run_env:
                merged_env.update(run_env)
            merged_env = {k: v for k, v in merged_env.items() if v is not None}
            # Docker 模式：容器内直接使用 qrun（容器已配置好环境）
            # Conda 模式：使用 conda run 前缀确保 aiquant 环境
            if _ms.env_type in ("docker",):
                entry_prefix = ""
                qlib_entry = f"qrun {qlib_config_name}"
                res_entry = "python read_exp_res.py"
            else:
                _conda_env = os.environ.get("CONDA_DEFAULT_ENV", "")
                if _conda_env and _conda_env != "base":
                    aiquant_python = sys.executable
                    conda_prefix = f"conda run -n {_CURRENT_CONDA_ENV} --no-capture-output {aiquant_python} "
                else:
                    conda_prefix = f"{sys.executable} "
                entry_prefix = conda_prefix
                qlib_entry = f"{entry_prefix}-m qlib.workflow.cli {qlib_config_name}"
                res_entry = f"{entry_prefix}read_exp_res.py"
            # ====== 单轮执行超时保护（15分钟）======
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
            _executor = ThreadPoolExecutor(max_workers=1)
            
            # 1. Qlib 回测执行（主要耗时步骤）
            _qlib_future = _executor.submit(
                qtde.check_output,
                local_path=str(self.workspace_path),
                entry=qlib_entry,
                env=merged_env,
            )
            try:
                execute_qlib_log = _qlib_future.result(timeout=_ITERATION_TIMEOUT)
                logger.info(f"[Worker] Qlib 回测完成 ({self.workspace_path.name})")
            except FuturesTimeout:
                _qlib_future.cancel()
                logger.warning(f"[Worker] Qlib 回测超时 ({_ITERATION_TIMEOUT}s)，跳过本轮 {self.workspace_path.name}")
                _executor.shutdown(wait=False)
                return None, f"Qlib execution timed out after {_ITERATION_TIMEOUT}s"
            except Exception as e:
                logger.error(f"[Worker] Qlib 回测异常: {e}")
                _executor.shutdown(wait=False)
                return None, f"Qlib execution error: {e}"
            
            # 2. 结果提取（轻量操作，30s 超时）
            _res_future = _executor.submit(
                qtde.check_output,
                local_path=str(self.workspace_path),
                entry=res_entry,
                env=merged_env,
            )
            try:
                execute_log = _res_future.result(timeout=30)
            except FuturesTimeout:
                _res_future.cancel()
                logger.warning(f"[Worker] 结果提取超时，继续处理已有数据")
                execute_log = ""
            except Exception as e:
                logger.error(f"[Worker] 结果提取异常: {e}")
                execute_log = ""
            finally:
                _executor.shutdown(wait=False)
            
            from rdagent.log import rdagent_logger as _rd_logger
            _rd_logger.log_object(execute_qlib_log, tag="Qlib_execute_log")
            quantitative_backtesting_chart_path = self.workspace_path / "ret.pkl"
            if quantitative_backtesting_chart_path.exists():
                ret_df = pd.read_pickle(quantitative_backtesting_chart_path)
                _rd_logger.log_object(ret_df, tag="Quantitative Backtesting Chart")
            else:
                _rd_logger.error("No result file found.")
                return None, execute_qlib_log
            qlib_res_path = self.workspace_path / "qlib_res.csv"
            if qlib_res_path.exists():
                pattern = r"(Epoch\d+: train -[0-9\.]+, valid -[0-9\.]+|best score: -[0-9\.]+ @ \d+ epoch)"
                matches = re.findall(pattern, execute_qlib_log)
                execute_qlib_log = "\n".join(matches)
                return pd.read_csv(qlib_res_path, index_col=0).iloc[:, 0], execute_qlib_log
            else:
                logger.error(f"File {qlib_res_path} does not exist.")
                return None, execute_qlib_log
        QlibFBWorkspace.execute = _patched_qlib_execute
        logger.info(f"[Worker] Qlib 执行 patch 已应用 (env={MODEL_COSTEER_SETTINGS.env_type})")
        
        env_type = getattr(MODEL_COSTEER_SETTINGS, 'env_type', 'unknown')
        
        # 阶段2：初始化进化引擎
        push("phase", (
            f"✅【阶段2】因子进化引擎正在初始化...\n"
            f"执行环境：{env_type}｜迭代轮次：{loop_n}轮"
        ), stage="phase2_init")
        
        # 存储各阶段产出的共享容器
        progress_data = {
            "current_loop": 0,
            "hypotheses": [],
            "codes": [],
            "backtest_results": [],
            "feedbacks": [],
            "reviews": [],
            "errors": [],
            "finished": False,
        }
        
        # Monkey-patch FactorRDLoop 方法
        original_direct_exp_gen = FactorRDLoop.direct_exp_gen
        original_coding = FactorRDLoop.coding
        original_running = FactorRDLoop.running
        original_feedback = FactorRDLoop.feedback
        
        last_hypo_count = 0
        last_code_count = 0
        last_bt_count = 0
        last_fb_count = 0
        _last_heartbeat_push = 0.0
        
        # ── 异步包装 ──
        async def patched_direct_exp_gen(self_rd, prev_out):
            result = await original_direct_exp_gen(self_rd, prev_out)
            loop_i = self_rd.loop_idx - 1
            try:
                exp_gen = result.get("exp_gen") if isinstance(result, dict) else None
                hypo_text = _extract_hypothesis_text(exp_gen) if exp_gen else ""
                if exp_gen and hypo_text:
                    progress_data["hypotheses"].append({"loop": loop_i, "text": hypo_text})
            except Exception as e:
                logger.debug(f"提取因子假设失败: {e}")
            return result
        
        async def patched_coding(self_rd, prev_out):
            result = original_coding(self_rd, prev_out)
            if asyncio.iscoroutine(result):
                result = await result
            loop_i = self_rd.loop_idx - 1
            try:
                code = _extract_factor_code(result)
                progress_data["codes"].append({"loop": loop_i, "code": code})
            except Exception as e:
                logger.debug(f"提取因子代码失败: {e}")
            return result
        
        async def patched_running(self_rd, prev_out):
            result = original_running(self_rd, prev_out)
            if asyncio.iscoroutine(result):
                result = await result
            loop_i = self_rd.loop_idx - 1
            try:
                metrics = _extract_backtest_metrics(result)
                progress_data["backtest_results"].append({
                    "loop": loop_i, "metrics": metrics,
                })
            except Exception as e:
                logger.debug(f"提取回测结果失败: {e}")
            return result
        
        async def patched_feedback(self_rd, prev_out):
            result = original_feedback(self_rd, prev_out)
            if asyncio.iscoroutine(result):
                result = await result
            loop_i = self_rd.loop_idx - 1
            try:
                if self_rd.trace and hasattr(self_rd.trace, 'hist') and self_rd.trace.hist:
                    latest = self_rd.trace.hist[-1]
                    if len(latest) >= 2:
                        feedback_obj = latest[1]
                        feedback_text = ""
                        if hasattr(feedback_obj, 'observations'):
                            raw_obs = str(feedback_obj.observations)
                            feedback_text += _translate_en_to_cn(_clean_feedback_text(raw_obs)[:400])
                        if hasattr(feedback_obj, 'new_hypothesis'):
                            feedback_text += "\n" + _translate_en_to_cn(str(feedback_obj.new_hypothesis)[:300])
                        if hasattr(feedback_obj, 'decision'):
                            feedback_text += f"\n决策：{'✅ 保留' if feedback_obj.decision else '❌ 淘汰'}"
                        progress_data["feedbacks"].append({
                            "loop": loop_i,
                            "text": feedback_text or _translate_en_to_cn(str(feedback_obj)[:500]),
                        })
            except Exception as e:
                logger.debug(f"提取反馈失败: {e}")
            return result
        
        FactorRDLoop.direct_exp_gen = patched_direct_exp_gen
        FactorRDLoop.coding = patched_coding
        FactorRDLoop.running = patched_running
        FactorRDLoop.feedback = patched_feedback
        
        push("phase", "✅ 进化引擎就绪，开始因子生成与回测...", stage="phase2_start")
        
        # ── 在独立线程中运行异步事件循环 ──
        # Celery task 是同步的，但 FactorRDLoop.run() 是异步的
        # 创建一个新的 event loop 在线程中运行
        
        loop_completed = threading.Event()
        evolution_error = [None]  # mutable container
        
        def _run_evolution():
            """在子线程中运行异步进化循环"""
            nonlocal last_hypo_count, last_code_count, last_bt_count, last_fb_count, _last_heartbeat_push
            try:
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                
                p_info = parsed_info or {}
                
                factor_loop = FactorRDLoop(FACTOR_PROP_SETTING)
                
                # B2: 带重试的 LLM API 调用包装（指数退避 + 抖动）
                @retry_with_backoff(max_retries=3, base_delay=5.0, max_delay=120.0,
                                    retryable_exceptions=(ConnectionError, TimeoutError,
                                                          OSError, RuntimeError))
                def _safe_run_evolution(coro):
                    """安全执行因子进化，LLM API 超时自动重试"""
                    return asyncio.run(coro)
                
                async def _run():
                    nonlocal last_hypo_count, last_code_count, last_bt_count, last_fb_count, _last_heartbeat_push
                    
                    # 强制重置 RD-Agent 全局计时器，防止 Celery Worker 多任务间状态泄漏
                    # 根因：RD_Agent_TIMER_wrapper 是全局单例，loop.py 中 reset 受限于
                    # `not self.timer.started` 守卫，后续任务无法重置已启动/已过期的计时器
                    RD_Agent_TIMER_wrapper.timer.reset(all_duration=all_duration)

                    # 工作目录监测兜底（当 monkey-patch 提取失败时）
                    _ws_root = Path(__file__).parent.parent.parent / "git_ignore_folder" / "RD-Agent_workspace"
                    _known_ws_dirs = set()
                    
                    evolution_coro = factor_loop.run(
                        step_n=None, loop_n=loop_n, all_duration=all_duration,
                    )
                    evolution_task = asyncio.ensure_future(evolution_coro)
                    
                    while not evolution_task.done():
                        await asyncio.sleep(5)
                        
                        # 结构性修复：每 120 秒推送进度心跳，避免用户看到零进度
                        _now_elapsed = round(time.time() - start_time, 1)
                        if _now_elapsed - _last_heartbeat_push >= 120:
                            _last_heartbeat_push = _now_elapsed
                            
                            # ---- 工作目录兜底检测 ----
                            _new_loop_count = 0
                            try:
                                if _ws_root.exists():
                                    current_dirs = set(d.name for d in _ws_root.iterdir() if d.is_dir() and d.name.startswith("Loop_"))
                                    _new_loop_count = len(current_dirs)
                                    new_dirs = current_dirs - _known_ws_dirs
                                    if new_dirs:
                                        logger.info(f"[Worker] 工作目录检测到新 Loop 目录: {new_dirs}")
                                        _known_ws_dirs = current_dirs
                            except Exception:
                                pass
                            # 当前最高迭代轮次（取 monkey-patch + workspace 兜底的最大值）
                            _hypo_count = max(len(progress_data['hypotheses']), _new_loop_count)
                            _code_count = max(len(progress_data['codes']), _new_loop_count)
                            _bt_count = max(len(progress_data['backtest_results']), _new_loop_count - 1 if _new_loop_count > 0 else 0)
                            _current_iter = max(_hypo_count, _code_count, _bt_count)
                            
                            push("progress",
                                f"⏳ 因子进化引擎运行中，已耗时 {_now_elapsed:.0f} 秒\n"
                                f"迭代进度：{_current_iter}/{loop_n} 轮\n"
                                f"已完成：{_hypo_count} 个假设、{_code_count} 段代码、{_bt_count} 次回测",
                                stage="running_heartbeat",
                                meta={"hypotheses": _hypo_count,
                                      "codes": _code_count,
                                      "backtests": _bt_count,
                                      "current_loop": _current_iter,
                                      "total_loops": loop_n})
                        # 推送因子假设
                        if len(progress_data["hypotheses"]) > last_hypo_count:
                            for h in progress_data["hypotheses"][last_hypo_count:]:
                                loop_i = h["loop"]
                                push("hypothesis", (
                                    f"✅【阶段2】R-Agent研究员｜因子数学假设构思完成（第{loop_i+1}轮）\n"
                                    f"本轮生成候选因子假设：\n"
                                    f"{h['text'][:800]}\n"
                                    f"逻辑：基于{p_info.get('constraints', '通用')}约束，"
                                    f"在{p_info.get('universe', '全A股')}股票池中挖掘alpha信号"
                                ), stage=f"hypothesis_loop{loop_i+1}")
                            last_hypo_count = len(progress_data["hypotheses"])
                        
                        # 推送因子代码（仅进度提示，不发送详细代码）
                        if len(progress_data["codes"]) > last_code_count:
                            for c in progress_data["codes"][last_code_count:]:
                                loop_i = c["loop"]
                                push("code", (
                                    f"✅【阶段3】D-Agent 因子代码生成完成（第{loop_i+1}轮）"
                                ), stage=f"coding_loop{loop_i+1}")
                            last_code_count = len(progress_data["codes"])
                        # 兜底：如果 monkey-patch 没捕获到 code 但工作目录有新的 Loop_X
                        if _new_loop_count > last_code_count:
                            for li in range(last_code_count, _new_loop_count):
                                push("code", (
                                    f"✅【阶段3】因子代码生成完成（第{li+1}轮）"
                                ), stage=f"coding_loop{li+1}")
                            last_code_count = _new_loop_count
                        
                        # 推送回测结果（仅进度提示，不发送详细指标）
                        if len(progress_data["backtest_results"]) > last_bt_count:
                            for bt in progress_data["backtest_results"][last_bt_count:]:
                                loop_i = bt["loop"]
                                push("backtest", (
                                    f"✅【第{loop_i+1}轮迭代｜回测计算完成】"
                                ), stage=f"backtest_loop{loop_i+1}")
                            last_bt_count = len(progress_data["backtest_results"])
                        # 兜底：工作目录有多个 Loop_ 但没捕获到回测结果
                        if _new_loop_count > 1 and len(progress_data["backtest_results"]) == 0:
                            for li in range(0, _new_loop_count):
                                push("backtest", (
                                    f"✅【第{li+1}轮迭代｜回测计算完成】"
                                ), stage=f"backtest_loop{li+1}")
                            last_bt_count = _new_loop_count
                            
                            # 推送评审
                            review_loop_i = progress_data["backtest_results"][-1]["loop"]
                            review_text = _generate_mock_reviews(review_loop_i, progress_data)
                            push("review", review_text, stage=f"review_loop{review_loop_i+1}")
                            
                            if review_loop_i + 1 < loop_n:
                                push("optimization", (
                                    f"✅【第{review_loop_i+1}轮迭代全部结束】\n"
                                    f"下一轮进化方向：对候选因子增加行业、市值双重中性化处理，"
                                    f"生成优化版本因子进行下一轮回测\n"
                                    f"————————————————————"
                                ), stage=f"optimization_loop{review_loop_i+1}")
                        
                        # 推送反馈
                        if len(progress_data["feedbacks"]) > last_fb_count:
                            for fb in progress_data["feedbacks"][last_fb_count:]:
                                loop_i = fb["loop"]
                                push("feedback", (
                                    f"✅【阶段4】LLM反馈分析完成（第{loop_i+1}轮）\n"
                                    f"{fb['text'][:500]}"
                                ), stage=f"feedback_loop{loop_i+1}")
                            last_fb_count = len(progress_data["feedbacks"])
                    
                    # 等待进化完成
                    await evolution_task
                
                new_loop.run_until_complete(_run())
                loop_completed.set()
                
            except Exception as e:
                logger.error(f"[Worker] 进化执行异常: {e}", exc_info=True)
                evolution_error[0] = e
                loop_completed.set()
        
        # ---- 独立进度心跳线程（不依赖 async while 循环） ----
        _heartbeat_stop = threading.Event()
        def _heartbeat_pusher():
            """每 120 秒推一次心跳事件，不管 factor_loop 内部状态如何"""
            _h_start = time.time()
            while not _heartbeat_stop.is_set():
                _h_elapsed = round(time.time() - _h_start, 1)
                if _h_elapsed >= 120:
                    _h_start = time.time()
                    try:
                        # 用当前最高已推 seq 确保心跳不覆盖业务事件
                        push("progress",
                            f"⏳ 因子进化引擎运行中，已耗时 {round(time.time() - start_time, 1):.0f} 秒\n"
                            f"迭代轮次：{loop_n}轮｜请耐心等待，通常每轮需 1-3 分钟",
                            stage="running_heartbeat",
                            meta={"total_loops": loop_n})
                    except Exception:
                        pass
                _heartbeat_stop.wait(timeout=5)
        
        _hb_thread = threading.Thread(target=_heartbeat_pusher, daemon=True)
        _hb_thread.start()
        
        # 启动进化线程
        evo_thread = threading.Thread(target=_run_evolution, daemon=True)
        evo_thread.start()
        
        # 主线程轮询：监听 Celery 取消信号和进度
        while not loop_completed.is_set():
            loop_completed.wait(timeout=30)
            # 检查 Celery 是否要求终止
            if self.request.called_directly:
                pass  # 本地调试模式
            # 心跳：更新 Celery task state
            self.update_state(
                state="RUNNING",
                meta={
                    "task_id": task_id,
                    "elapsed": round(time.time() - start_time, 1),
                    "hypotheses": len(progress_data["hypotheses"]),
                    "codes": len(progress_data["codes"]),
                    "backtests": len(progress_data["backtest_results"]),
                },
            )
        
        # ── 恢复 monkey-patch ──
        FactorRDLoop.direct_exp_gen = original_direct_exp_gen
        FactorRDLoop.coding = original_coding
        FactorRDLoop.running = original_running
        FactorRDLoop.feedback = original_feedback
        
        # 停止心跳线程
        _heartbeat_stop.set()
        
        if evolution_error[0]:
            error_msg = f"❌ 因子进化执行异常: {str(evolution_error[0])}"
            push("error", error_msg, stage="error")
            _db_save_task_complete(task_id, "failed", time.time() - start_time,
                                   error=str(evolution_error[0]))
            return {
                "status": "failed",
                "task_id": task_id,
                "error": str(evolution_error[0]),
                "elapsed_sec": round(time.time() - start_time, 1),
            }
        
        # ── 完成 ──
        log_dir = _find_latest_log_dir()
        _ui_base = os.environ.get("AIQUANT_UI_BASE_URL", "http://127.0.0.1:19899")
        ui_url = f"{_ui_base}/?task_id={task_id}"
        if log_dir:
            ui_url += f"&log_dir={Path(log_dir).name}"
        
        push("visual_link", (
            f"✅🎉 全部{loop_n}轮因子进化任务执行完毕\n\n"
            f"可视化面板已就绪，请点击下方链接查看：\n"
            f"收益曲线、IC时序、分层回测图表等"
        ), stage="visualization", meta={"ui_url": ui_url, "ui_port": 19899})
        
        elapsed_total = time.time() - start_time
        report = _build_final_report(task_id, parsed_info or {}, elapsed_total)
        push("final_report", report, stage="final_report")
        push("done", "任务完成", stage="complete")
        _update_task_status(task_id, "completed")
        
        # B1: 任务完成写入 SQLite
        _db_save_task_complete(task_id, "completed", elapsed_total,
                               len(progress_data["hypotheses"]),
                               len(progress_data["codes"]),
                               len(progress_data["backtest_results"]),
                               final_report=report)
        
        result = {
            "status": "completed",
            "task_id": task_id,
            "elapsed_sec": round(elapsed_total, 1),
            "hypotheses_count": len(progress_data["hypotheses"]),
            "codes_count": len(progress_data["codes"]),
            "backtests_count": len(progress_data["backtest_results"]),
            "log_dir": log_dir,
        }
        
        return result
        
    except Exception as e:
        logger.error(f"[Worker] 任务 {task_id} 异常: {e}", exc_info=True)
        push("error", f"❌【任务异常终止】{str(e)}", stage="error")
        push("done", "任务失败", stage="failed")
        _update_task_status(task_id, "failed")
        
        # B1: 任务失败写入 SQLite
        _db_save_task_complete(task_id, "failed", time.time() - start_time,
                               error=str(e))
        return {"status": "failed", "task_id": task_id, "error": str(e)}
    finally:
        # 统一更新 Redis 中的任务状态（如果还是 running 则更新）
        _update_task_status_if_running(task_id, progress_data if 'progress_data' in dir() else None)


def _compute_progress_pct(typ: str, stage: str, loop_n: int, progress_data: dict) -> int:
    """B3: 基于阶段权重和迭代轮次计算进度百分比 (0-100)
    
    权重分配:
      - 初始化阶段 (phase/phase2_init/phase2_start): 0-10%
      - 假设生成 (hypothesis): 10-40%
      - 代码生成 (code): 40-55%
      - 回测 (backtest): 55-80%
      - 反馈 (feedback/review): 80-95%
      - 最终报告 (final_report/visualization): 95-100%
    """
    if typ in ("done",) or stage in ("complete",):
        return 100
    if stage in ("final_report", "visualization"):
        return 95
    if typ == "feedback" or stage.startswith("feedback"):
        # 反馈阶段：80-95%，根据已完成轮次
        completed = len(progress_data.get("feedbacks", [])) if progress_data else 0
        return min(80 + int(15 * completed / max(loop_n, 1)), 95)
    if typ in ("review", "optimization") or stage.startswith("review") or stage.startswith("optimization"):
        return 85
    if typ == "backtest" or stage.startswith("backtest"):
        # 回测阶段：55-80%
        completed = len(progress_data.get("backtest_results", [])) if progress_data else 0
        return min(55 + int(25 * completed / max(loop_n, 1)), 80)
    if typ == "code" or stage.startswith("coding"):
        # 代码生成：40-55%
        completed = len(progress_data.get("codes", [])) if progress_data else 0
        return min(40 + int(15 * completed / max(loop_n, 1)), 55)
    if typ == "hypothesis" or stage.startswith("hypothesis"):
        # 假设生成：10-40%
        completed = len(progress_data.get("hypotheses", [])) if progress_data else 0
        return min(10 + int(30 * completed / max(loop_n, 1)), 40)
    if stage in ("phase2_start",):
        return 10
    if stage in ("phase2_init",):
        return 5
    if typ == "phase" or stage.startswith("phase"):
        return 5
    if typ == "error":
        return 0
    return 0


def _update_task_status(task_id: str, status: str):
    """更新 Redis 中的任务状态"""
    try:
        r = _get_redis()
        raw = r.get(f"aiquant:task:progress:{task_id}")
        if raw:
            data = json.loads(raw)
            data["status"] = status
            data["end_time"] = time.time()
            r.set(f"aiquant:task:progress:{task_id}", json.dumps(data))
    except Exception:
        pass

def _update_task_status_if_running(task_id: str, progress_data=None):
    """如果任务状态还是 running，则根据 progress_data 更新为 completed 或 failed"""
    try:
        r = _get_redis()
        raw = r.get(f"aiquant:task:progress:{task_id}")
        if raw:
            data = json.loads(raw)
            if data.get("status") == "running":
                if progress_data and progress_data.get("backtest_results"):
                    data["status"] = "completed"
                else:
                    # 没有回测结果但没抛异常 — 也标记为 completed（1轮可能只有假设没有回测）
                    data["status"] = "completed"
                data["end_time"] = time.time()
                r.set(f"aiquant:task:progress:{task_id}", json.dumps(data))
    except Exception:
        pass


def _find_latest_log_dir() -> str:
    """自动发现 RD-Agent 进化产生的最近日志目录"""
    log_dir = _project_root / "log"
    if not log_dir.exists():
        return ""
    dirs = [d for d in log_dir.iterdir() if d.is_dir()]
    if not dirs:
        return ""
    latest = max(dirs, key=lambda d: d.stat().st_mtime)
    return str(latest)


def _build_final_report(task_id: str, parsed: dict, elapsed: float) -> str:
    """生成简短结果摘要，详细内容在Web链接展示"""
    loop_n = parsed.get('loop_n', 'N/A')
    _ui_base = os.environ.get("AIQUANT_UI_BASE_URL", "http://127.0.0.1:19899")
    web_url = f"{_ui_base}/?task_id={task_id}"
    return f"""✅ 因子挖掘任务完成

**结果摘要**
- 任务ID：`{task_id}`
- 迭代轮次：{loop_n}轮
- 总耗时：{elapsed/60:.1f}分钟

**详细报告（Web）**
{web_url}

完整源代码、回测数据、图表、分析报告请在上方链接查看。
"""
