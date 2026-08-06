"""
模型自动加载器 — 从 Ollama 模型中自动选择最佳可用模型。
零硬编码，根据参数规模自动决定专家数量。
输出为标准 JSON。
"""
import json
from typing import Optional, Dict, Any, List


class ModelAutoLoader:
    """
    自动选择最佳本地模型。
    优先 Ollama 模型，后备本地 gguf 文件。
    根据参数规模决定专家董事会人数（≥7B→5，<7B→3）。
    """

    def __init__(self, environment: Dict[str, Any]):
        self.env = environment
        self.ollama = environment.get("ollama", {})
        self.gpu = environment.get("gpu", [])
        self.memory_gb = environment.get("memory_gb", 0)

    def select_best_model(self) -> Optional[Dict[str, Any]]:
        """自动选择最佳模型。返回标准 JSON dict。"""
        # ① 优先 Ollama 已加载模型
        if self.ollama.get("available"):
            ollama_models = self._rank_ollama_models()
            if ollama_models:
                best = ollama_models[0]
                best["expert_count"] = self._expert_count(best["param_count"])
                best["execution_mode"] = "cpu"
                best["source"] = "ollama"
                return best

        # ② 后备：本地模型文件
        local_models = self.env.get("models", [])
        viable = self._filter_viable_local(local_models)
        if viable:
            best = viable[0]
            best["expert_count"] = self._expert_count(best.get("estimated_params_b", 0))
            best["source"] = "local_file"
            return best

        return None

    def _rank_ollama_models(self) -> List[Dict[str, Any]]:
        """对 Ollama 模型按质量排序。过滤掉明显不可用的。"""
        models = self.ollama.get("models", [])
        ranked = []
        for m in models:
            param_count = self._parse_param_count(m.get("param_size", "0"))
            size_gb = m.get("size_gb", 0)
            # 检查本机能否跑（保守：模型大小 * 2 ≤ 可用内存 * 0.6）
            if self.memory_gb > 0 and size_gb * 2 > self.memory_gb * 0.6:
                continue  # 内存不够，跳过
            ranked.append({
                "name": m.get("name"),
                "size_gb": size_gb,
                "format": m.get("format", "gguf"),
                "param_count": param_count,
                "param_size": m.get("param_size"),
                "quality_score": self._score_model(m),
            })
        # 按质量分降序排列
        ranked.sort(key=lambda x: x["quality_score"], reverse=True)
        return ranked

    @staticmethod
    def _parse_param_count(param_str: str) -> float:
        """解析参数字符串如 '1.5B' → 1.5, '7B' → 7.0"""
        try:
            param_str = param_str.upper().replace("B", "").strip()
            return float(param_str)
        except (ValueError, AttributeError):
            return 0.0

    @staticmethod
    def _score_model(model: Dict[str, Any]) -> float:
        """
        模型质量评分。
        权重：中文能力 > 参数量 > 格式。
        """
        name = model.get("name", "").lower()
        param_str = str(model.get("param_size", "0"))
        param_count = ModelAutoLoader._parse_param_count(param_str)

        score = param_count * 10  # 基础分：参数越多分越高

        # 中文原生模型加分
        if any(k in name for k in ("qwen", "glm", "chatglm", "baichuan", "yi", "deepseek")):
            score += 50
        # llama/gemma 是英文原生，中文弱
        if any(k in name for k in ("llama", "gemma")):
            score -= 20
        # granite 是英文
        if "granite" in name:
            score -= 30

        return score

    def _filter_viable_local(self, models: List[Dict]) -> List[Dict]:
        """过滤可在本机运行的本地模型文件。"""
        viable = []
        available_vram = self._available_vram()
        for m in models:
            required = m.get("size_gb", 0) + 2
            if available_vram > 0 and required <= available_vram:
                m["execution_mode"] = "gpu"
                viable.append(m)
            elif self.memory_gb > 0 and required <= self.memory_gb * 0.7:
                m["execution_mode"] = "cpu"
                viable.append(m)
        viable.sort(key=lambda x: x.get("estimated_params_b", 0), reverse=True)
        return viable

    def _available_vram(self) -> float:
        if self.gpu:
            return self.gpu[0].get("vram_gb", 0)
        return 0.0

    @staticmethod
    def _expert_count(param_count: float) -> int:
        """参数 ≥ 7B → 5 专家，否则 3 专家。"""
        return 5 if param_count >= 7.0 else 3

    def get_selection_report(self) -> str:
        """标准 JSON 选择报告。"""
        best = self.select_best_model()
        if not best:
            return json.dumps({"status": "no_model_found", "error": "无可用模型"}, ensure_ascii=False)
        return json.dumps(best, ensure_ascii=False, indent=2)
