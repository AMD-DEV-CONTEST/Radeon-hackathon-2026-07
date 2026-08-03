# -*- coding: utf-8 -*-
"""KataGo analysis JSON 协议适配器。"""

from collections import deque
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import threading
import time
import uuid

from goboard import gtp_name
from .base import AnalysisEngine


class KataGoError(RuntimeError):
    pass


def normalize_komi(raw_value, rules="chinese"):
    """把平台私有贴目编码转换为 KataGo 接受的整数/半整数目数。"""
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(raw_value or ""))
    if not match:
        return 7.5 if rules in ("chinese", "aga") else 6.5
    value = float(match.group(0))
    if abs(value) > 150:
        # 腾讯/野狐中国规则 KM[375] = 3.75 子 = 7.5 目。
        value /= 50.0 if rules in ("chinese", "aga") else 100.0
    if not -150 <= value <= 150:
        return 7.5 if rules in ("chinese", "aga") else 6.5
    return round(value * 2) / 2


class KataGoEngine(AnalysisEngine):
    name = "katago"
    official_model_name = "kata1-zhizi-b40c768nbt-s11272M-d5935M.bin.gz"
    official_model_sha256 = (
        "15fb3baf85cdb6578e6c19b65e6201ca906cec3ba5fee19039d05221d57eb0e8"
    )

    def __init__(self, executable=None, model=None, config=None, max_visits=None,
                 timeout=None, chunk_size=None):
        runtime = Path(__file__).resolve().parents[2] / "runtime" / "katago"
        exe_name = "katago.exe" if os.name == "nt" else "katago"
        self.executable = Path(executable or os.getenv("KATAGO_PATH", runtime / exe_name))
        default_model = runtime / "kata1-zhizi-b40c768nbt-s11272M-d5935M.bin.gz"
        self.model = Path(model or os.getenv("KATAGO_MODEL", default_model))
        self.config = Path(config or os.getenv("KATAGO_CONFIG", runtime / "analysis.cfg"))
        self.remote_enabled = os.getenv("KATAGO_REMOTE_ENABLED", "").strip().lower() in {
            "1", "true", "yes", "on",
        }
        self.remote_host = os.getenv("KATAGO_REMOTE_HOST", "").strip()
        self.remote_executable = os.getenv(
            "KATAGO_REMOTE_PATH",
            "/persistent/yijian/katago-v1.16.5/build/katago",
        ).strip()
        self.remote_model = os.getenv(
            "KATAGO_REMOTE_MODEL",
            "/persistent/yijian/katago-models/"
            "kata1-zhizi-b40c768nbt-s11272M-d5935M.bin.gz",
        ).strip()
        self.remote_config = os.getenv(
            "KATAGO_REMOTE_CONFIG",
            "/persistent/yijian/project/gomentor/deploy/cloud/"
            "katago_analysis_w7900.cfg",
        ).strip()
        self.ssh_executable = os.getenv("KATAGO_SSH_PATH", "ssh").strip() or "ssh"
        self.max_visits = int(max_visits or os.getenv("KATAGO_MAX_VISITS", "32"))
        self.timeout = float(timeout or os.getenv("KATAGO_TIMEOUT", "300"))
        default_chunk_size = "64" if self.remote_enabled else "16"
        self.chunk_size = int(
            chunk_size or os.getenv("KATAGO_CHUNK_SIZE", default_chunk_size)
        )
        self.version = "1.16.5"
        active_model_name = (
            Path(self.remote_model).name if self.remote_enabled else self.model.name
        )
        self.model_name = active_model_name.removesuffix(".bin.gz")
        configured_hash = os.getenv("KATAGO_MODEL_SHA256", "").strip().lower()
        self.model_sha256 = configured_hash or (
            self.official_model_sha256
            if active_model_name == self.official_model_name else None
        )
        self._proc = None
        self._responses = queue.Queue()
        self._stderr = deque(maxlen=80)
        self._lock = threading.Lock()
        self._ready = False
        self._warming = False
        self._warm_error = ""
        self._validate_files()

    def _validate_files(self):
        if self.remote_enabled and not self.remote_host:
            raise KataGoError("KATAGO_REMOTE_ENABLED requires KATAGO_REMOTE_HOST")
        required = (self.model, self.config) if self.remote_enabled else (
            self.executable, self.model, self.config
        )
        missing = [str(p) for p in required if not p.is_file()]
        if missing:
            raise KataGoError("KataGo 文件缺失：" + "、".join(missing))

    def _command(self):
        if not self.remote_enabled:
            return [
                str(self.executable), "analysis", "-config", str(self.config),
                "-model", str(self.model),
            ]
        return [
            self.ssh_executable,
            "-T",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10",
            self.remote_host,
            self.remote_executable,
            "analysis",
            "-config", self.remote_config,
            "-model", self.remote_model,
        ]

    def health(self):
        return {
            "engine": self.name,
            "demo": False,
            "configured": True,
            "running": self._proc is not None and self._proc.poll() is None,
            "ready": self._ready,
            "warming": self._warming,
            "warmupError": self._warm_error,
            "katagoVersion": self.version,
            "backend": "OpenCL",
            "model": self.model_name,
            "modelSha256": self.model_sha256,
            "maxVisits": self.max_visits,
            "transport": "ssh" if self.remote_enabled else "local-process",
            "remoteHost": self.remote_host if self.remote_enabled else None,
        }

    def warm_up(self) -> bool:
        """后台加载模型并完成一次最小推理，让首次整盘分析不承担冷启动耗时。"""
        if self._ready:
            return True
        self._warming = True
        self._warm_error = ""
        try:
            with self._lock:
                if self._ready:
                    return True
                self._start()
                payload = {
                    "id": uuid.uuid4().hex,
                    "moves": [],
                    "rules": "chinese",
                    "komi": 7.5,
                    "boardXSize": 19,
                    "boardYSize": 19,
                    "analyzeTurns": [0],
                    "maxVisits": 1,
                    "analysisPVLen": 2,
                }
                self._query(payload, 1)
                self._ready = True
            return True
        except Exception as exc:
            self._warm_error = str(exc)
            return False
        finally:
            self._warming = False

    def _start(self):
        if self._proc is not None and self._proc.poll() is None:
            return
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self._proc = subprocess.Popen(
            self._command(),
            cwd=None if self.remote_enabled else str(self.executable.parent),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", bufsize=1, creationflags=flags,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self):
        for line in self._proc.stdout:
            try:
                self._responses.put(json.loads(line))
            except json.JSONDecodeError:
                self._stderr.append("无法解析 KataGo 输出：" + line.strip())

    def _read_stderr(self):
        for line in self._proc.stderr:
            self._stderr.append(line.rstrip())

    def _query(self, payload, expected, cancelled=None):
        query_id = payload["id"]
        self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()
        answers = {}
        deadline = time.monotonic() + self.timeout
        while len(answers) < expected:
            if cancelled and cancelled():
                raise KataGoError("分析已取消")
            if self._proc.poll() is not None:
                detail = "\n".join(self._stderr[-12:])
                raise KataGoError(f"KataGo 已退出（代码 {self._proc.returncode}）：{detail}")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise KataGoError(f"KataGo 分析超过 {self.timeout:g} 秒")
            try:
                item = self._responses.get(timeout=min(0.25, remaining))
            except queue.Empty:
                continue
            if item.get("id") != query_id:
                continue
            if "error" in item:
                raise KataGoError("KataGo 查询失败：" + item["error"])
            if "warning" in item:
                self._stderr.append("KataGo 警告：" + item["warning"])
                continue
            if not item.get("isDuringSearch", False) and "turnNumber" in item:
                answers[int(item["turnNumber"])] = item
        return answers

    @staticmethod
    def _rules(game):
        raw = str(game.info.get("RU", "chinese")).lower()
        if "japan" in raw:
            return "japanese"
        if "korea" in raw:
            return "korean"
        if "aga" in raw:
            return "aga"
        return "chinese"

    def analyze_game(self, game, max_visits=None, progress=None, cancelled=None) -> dict:
        moves = [[m.color, "pass" if m.is_pass else gtp_name(m.coord, game.size)]
                 for m in game.moves]
        rules = self._rules(game)
        komi = normalize_komi(game.info.get("KM"), rules)
        visit_limit = int(max_visits or self.max_visits)
        results = {}
        with self._lock:
            self._start()
            turns = list(range(len(moves) + 1))
            for offset in range(0, len(turns), self.chunk_size):
                if cancelled and cancelled():
                    raise KataGoError("分析已取消")
                part = turns[offset:offset + self.chunk_size]
                payload = {
                    "id": uuid.uuid4().hex,
                    "moves": moves,
                    "rules": rules,
                    "komi": komi,
                    "boardXSize": game.size,
                    "boardYSize": game.size,
                    "analyzeTurns": part,
                    "maxVisits": visit_limit,
                    "analysisPVLen": 12,
                }
                results.update(
                    self._query(payload, len(part), cancelled=cancelled)
                )
                self._ready = True
                if progress:
                    progress(min(offset + len(part), len(turns)), len(turns))

        positions, winrates = [], []
        for turn in range(len(moves) + 1):
            root = results[turn].get("rootInfo", {})
            move_infos = results[turn].get("moveInfos") or []
            winrate = float(root["winrate"])
            score = float(root.get("scoreLead", 0.0))
            recommendations = [{
                "move": info.get("move"),
                "winrateBlack": round(float(info.get("winrate", winrate)), 4),
                "scoreLeadBlack": round(float(info.get("scoreLead", score)), 2),
                "visits": int(info.get("visits", 0)),
                "pv": list(info.get("pv") or [info.get("move")])[:10],
            } for info in move_infos[:5] if info.get("move")]
            winrates.append(winrate)
            positions.append({
                "turn": turn,
                "winrateBlack": round(winrate, 4),
                "scoreLeadBlack": round(score, 2),
                "visits": int(root.get("visits", 0)),
                "bestMove": move_infos[0].get("move") if move_infos else None,
                "recommendations": recommendations,
            })
        return {
            "source": self.name,
            "demo": False,
            "label": f"真实 KataGo v{self.version} · {self.model_name} · OpenCL · {visit_limit} visits",
            "engineVersion": self.version,
            "model": self.model_name,
            "modelSha256": self.model_sha256,
            "backend": "OpenCL",
            "transport": "ssh" if self.remote_enabled else "local-process",
            "komi": komi,
            "positions": positions,
            "keyMoves": self.extract_key_moves(game, winrates),
        }

    @staticmethod
    def _moves_at_position(game, turn, variation=None):
        turn = max(0, min(int(turn), len(game.moves)))
        moves = [[m.color, "pass" if m.is_pass else gtp_name(m.coord, game.size)]
                 for m in game.moves[:turn]]
        if turn < len(game.moves):
            color = game.moves[turn].color
        elif moves:
            color = "W" if moves[-1][0] == "B" else "B"
        else:
            color = "B"
        for move in variation or []:
            moves.append([color, str(move)])
            color = "W" if color == "B" else "B"
        return moves, color

    def analyze_position(
        self, game, turn, variation=None, visits=None,
        include_ownership=False, cancelled=None
    ):
        """分析实战或任意变化分支的当前局面，返回可继续展开的候选手。"""
        moves, _ = self._moves_at_position(game, turn, variation)
        rules = self._rules(game)
        komi = normalize_komi(game.info.get("KM"), rules)
        final_turn = len(moves)
        visits = int(visits or os.getenv("KATAGO_VARIATION_VISITS", "16"))
        payload = {
            "id": uuid.uuid4().hex,
            "moves": moves,
            "rules": rules,
            "komi": komi,
            "boardXSize": game.size,
            "boardYSize": game.size,
            "analyzeTurns": [final_turn],
            "maxVisits": visits,
            "analysisPVLen": 12,
        }
        if include_ownership:
            payload["includeOwnership"] = True
        with self._lock:
            self._start()
            response = self._query(payload, 1, cancelled=cancelled)[final_turn]
            self._ready = True
        root = response.get("rootInfo", {})
        root_winrate = float(root.get("winrate", 0.5))
        root_score = float(root.get("scoreLead", 0.0))
        recommendations = [{
            "move": info.get("move"),
            "winrateBlack": round(float(info.get("winrate", root_winrate)), 4),
            "scoreLeadBlack": round(float(info.get("scoreLead", root_score)), 2),
            "visits": int(info.get("visits", 0)),
            "pv": list(info.get("pv") or [info.get("move")])[:10],
        } for info in (response.get("moveInfos") or [])[:5] if info.get("move")]
        result = {
            "recommendations": recommendations,
            "winrateBlack": round(root_winrate, 4),
            "scoreLeadBlack": round(root_score, 2),
            "visits": int(root.get("visits", 0)),
            "komi": komi,
        }
        if include_ownership:
            result["ownership"] = list(response.get("ownership") or [])
        return result

    def analyze_variation(self, game, turn, first_move, depth=10, prefix_moves=None):
        """从指定局面和候选点开始，逐手调用 KataGo 补全一条真实主变化。"""
        turn = max(0, min(int(turn), len(game.moves)))
        depth = max(1, min(int(depth), 20))
        prefix, next_color = self._moves_at_position(game, turn, prefix_moves)
        rules = self._rules(game)
        komi = normalize_komi(game.info.get("KM"), rules)
        line, variation_moves, color = [], [], next_color
        move = str(first_move)
        visits = int(os.getenv("KATAGO_VARIATION_VISITS", "16"))
        with self._lock:
            self._start()
            while len(line) < depth and move:
                line.append(move)
                variation_moves.append([color, move])
                color = "W" if color == "B" else "B"
                if len(line) >= depth or (len(line) >= 2 and line[-2:] == ["pass", "pass"]):
                    break
                all_moves = prefix + variation_moves
                final_turn = len(all_moves)
                payload = {
                    "id": uuid.uuid4().hex,
                    "moves": all_moves,
                    "rules": rules,
                    "komi": komi,
                    "boardXSize": game.size,
                    "boardYSize": game.size,
                    "analyzeTurns": [final_turn],
                    "maxVisits": visits,
                    "analysisPVLen": max(12, depth),
                }
                response = self._query(payload, 1)[final_turn]
                self._ready = True
                infos = response.get("moveInfos") or []
                move = infos[0].get("move") if infos else None
        return {"pv": line, "visitsPerStep": visits, "komi": komi}

    def close(self):
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
