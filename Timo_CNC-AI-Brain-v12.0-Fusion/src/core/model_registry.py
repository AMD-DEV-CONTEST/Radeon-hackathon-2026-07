"""
模型注册表 — 统一管理本地Ollama + 云端API模型。
零硬编码，自动检测+手动配置双通道。
作者: timo.cao | 邮箱: miscdd@163.com | 生成: 大帅教练系统
"""
import json, os
from pathlib import Path
from typing import Dict, Any, List, Optional


class ModelRegistry:
    """统一模型注册表。合并Ollama自动检测 + 云端配置，按质量排序。"""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or Path(__file__).resolve().parent.parent.parent / "config" / "models.json"
        self._config = self._load_config()
        self._all_models = []

    def _load_config(self) -> dict:
        """加载模型配置文件。文件不存在则返回默认空配置。"""
        if self.config_path and self.config_path.exists():
            with open(self.config_path, encoding="utf-8") as f:
                return json.load(f)
        return {"cloud": [], "preference": "auto", "selection_rules": {}}

    def detect_ollama_models(self) -> List[Dict[str, Any]]:
        """自动检测本机Ollama已安装模型。"""
        try:
            import urllib.request
            req = urllib.request.Request("http://localhost:11434/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            models = []
            for m in data.get("models", []):
                name = m.get("name", "unknown")
                # 过滤黑名单
                blocklist = self._config.get("ollama_blocklist", [])
                if name in blocklist:
                    continue
                size_gb = round(m.get("size", 0) / (1024**3), 2)
                param_size = m.get("details", {}).get("parameter_size", "0B")
                param_count = self._parse_param(param_size)
                models.append({
                    "name": name, "size_gb": size_gb, "param_size": param_size,
                    "param_count": param_count, "source": "ollama",
                    "quality_score": self._score_local(name, param_count),
                    "provider": "ollama",
                })
            return models
        except Exception:
            return []

    def load_cloud_models(self) -> List[Dict[str, Any]]:
        """从配置文件加载云端+本地OpenAI兼容模型列表。

        读取三个键: cloud / local / models(UI通过 /api/models/config 保存)。
        按 (api_url, model_id) 去重，models 键(UI最新保存)优先覆盖同名配置。
        """
        merged: Dict[tuple, Dict[str, Any]] = {}

        def _put(cfg: dict, default_source: str, default_key: str):
            name = cfg.get("name") or cfg.get("model_id", "unknown")
            api_url = cfg.get("api_url", "")
            model_id = cfg.get("model_id", name)
            if not api_url:
                return
            api_key = cfg.get("api_key", default_key)
            # 支持环境变量引用: ${ENV_VAR_NAME}
            if isinstance(api_key, str) and api_key.startswith("${") and api_key.endswith("}"):
                env_var = api_key[2:-1]
                api_key = os.environ.get(env_var, default_key)
            merged[(api_url, model_id)] = {
                "name": name,
                "provider": cfg.get("provider", "openai"),
                "api_key": api_key,
                "api_url": api_url,
                "model_id": model_id,
                "quality_score": cfg.get("quality_score", 50),
                "param_count": cfg.get("param_count", 10),
                "source": cfg.get("source", default_source),
                "description": cfg.get("description", ""),
            }

        for cfg in self._config.get("cloud", []):
            _put(cfg, "cloud", "")
        # 本地llamacpp / LM Studio等OpenAI兼容服务
        for cfg in self._config.get("local", []):
            _put(cfg, "local", "none")
        # UI保存的自定义配置(优先级最高，覆盖同端点同模型的旧配置)
        for cfg in self._config.get("models", []):
            _put(cfg, cfg.get("source", "local"), "none")
        return list(merged.values())


    # ── 常见云端API环境变量映射 ──
    ENV_CLOUD_MAP = [
        {"env": "OPENAI_API_KEY",    "name": "OpenAI",        "provider": "openai",    "api_url": "https://api.openai.com/v1",               "model_id": "gpt-4o",             "quality_score": 95, "param_count": 200},
        {"env": "ANTHROPIC_API_KEY", "name": "Claude",        "provider": "anthropic", "api_url": "https://api.anthropic.com/v1",             "model_id": "claude-sonnet-4-20250514", "quality_score": 93, "param_count": 200},
        {"env": "DEEPSEEK_API_KEY",  "name": "DeepSeek",      "provider": "openai",    "api_url": "https://api.deepseek.com/v1",              "model_id": "deepseek-chat",      "quality_score": 88, "param_count": 67},
        {"env": "ZHIPU_API_KEY",     "name": "GLM-4",         "provider": "openai",    "api_url": "https://open.bigmodel.cn/api/paas/v4",     "model_id": "glm-4",              "quality_score": 82, "param_count": 130},
        {"env": "QWEN_API_KEY",      "name": "Qwen",          "provider": "openai",    "api_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model_id": "qwen-max",    "quality_score": 85, "param_count": 110},
        {"env": "MOONSHOT_API_KEY",  "name": "Moonshot",      "provider": "openai",    "api_url": "https://api.moonshot.cn/v1",               "model_id": "moonshot-v1-128k",   "quality_score": 78, "param_count": 100},
        {"env": "BAIDU_API_KEY",     "name": "ERNIE",         "provider": "openai",    "api_url": "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop", "model_id": "ernie-4.0", "quality_score": 76, "param_count": 100},
        {"env": "SILICONFLOW_API_KEY", "name": "SiliconFlow", "provider": "openai",    "api_url": "https://api.siliconflow.cn/v1",            "model_id": "deepseek-ai/DeepSeek-V3", "quality_score": 86, "param_count": 67},
        {"env": "GROQ_API_KEY",      "name": "Groq",          "provider": "openai",    "api_url": "https://api.groq.com/openai/v1",           "model_id": "llama-3.3-70b-versatile", "quality_score": 80, "param_count": 70},
        {"env": "TOGETHER_API_KEY",  "name": "Together",      "provider": "openai",    "api_url": "https://api.together.xyz/v1",              "model_id": "meta-llama/Llama-3.3-70B-Instruct-Turbo", "quality_score": 79, "param_count": 70},
        {"env": "OPENROUTER_API_KEY","name": "OpenRouter",    "provider": "openai",    "api_url": "https://openrouter.ai/api/v1",             "model_id": "anthropic/claude-sonnet-4", "quality_score": 90, "param_count": 200},
        {"env": "XAI_API_KEY",       "name": "Grok",          "provider": "openai",    "api_url": "https://api.x.ai/v1",                     "model_id": "grok-3",             "quality_score": 87, "param_count": 200},
    ]

    def scan_env_cloud_models(self) -> list:
        """扫描环境变量中的云端API Key，自动注册为可用模型。"""
        found = []
        for entry in self.ENV_CLOUD_MAP:
            key = os.environ.get(entry["env"], "")
            if not key:
                continue
            # Check if already in config (don't duplicate)
            config_names = [c.get("name", "") for c in self._config.get("cloud", [])]
            config_names += [c.get("name", "") or c.get("model_id", "") for c in self._config.get("models", [])]
            if entry["name"] in config_names:
                continue
            found.append({
                "name": entry["name"],
                "provider": entry["provider"],
                "api_key": key,
                "api_url": entry["api_url"],
                "model_id": entry["model_id"],
                "quality_score": entry["quality_score"],
                "param_count": entry["param_count"],
                "source": "cloud",
                "description": f'{entry["name"]} (auto-discovered from ${entry["env"]})',
                "auto_discovered": True,
            })
        return found

    def get_all_ranked(self, preference: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取所有可用模型，按质量排序。"""
        pref = preference or self._config.get("preference", "auto")
        ollama_models = self.detect_ollama_models()
        cloud_models = self.load_cloud_models() + self.scan_env_cloud_models()

        # 过滤：云端模型必须已配置API key，本地模型不过滤
        valid_cloud = [m for m in cloud_models if m.get("source") == "local" or (m.get("api_key") and m.get("api_key") != "sk-your-key-here")]

        if pref == "local":
            all_models = ollama_models + valid_cloud
        elif pref == "cloud":
            all_models = valid_cloud + ollama_models
        else:
            all_models = ollama_models + valid_cloud

        all_models.sort(key=lambda m: m.get("quality_score", 0), reverse=True)
        return all_models

    def select_best(self, min_quality: int = 0, task: str = "chat") -> Optional[Dict[str, Any]]:
        """按任务类型选择最佳模型。"""
        rules = self._config.get("selection_rules", {}).get(task, {})
        pref = rules.get("prefer", self._config.get("preference", "auto"))
        min_q = rules.get("min_quality", min_quality)

        all_models = self.get_all_ranked(pref)
        for m in all_models:
            if m.get("quality_score", 0) >= min_q:
                return m
        return all_models[0] if all_models else None

    @staticmethod
    def _parse_param(param_str: str) -> float:
        """解析 '1.5B' → 1.5, '7B' → 7.0"""
        try:
            return float(param_str.upper().replace("B", "").strip())
        except (ValueError, AttributeError):
            return 0.0

    @staticmethod
    def _score_local(name: str, param_count: float) -> float:
        """本地模型质量评分（~100满分）。"""
        name_lower = name.lower()
        # 内存自适应：不再硬性禁用大模型，而是降分
        score = param_count * 8
        # 中文原生模型加分
        if any(k in name_lower for k in ("qwen", "glm", "chatglm", "baichuan", "yi", "deepseek")):
            score += 30
        # 指令微调加分
        if any(k in name_lower for k in ("chat", "instruct", "it")):
            score += 10
        if any(k in name_lower for k in ("llama", "gemma")):
            score -= 10
        if "granite" in name_lower:
            score -= 20
        # 大模型降分但不禁用（内存不足时自然排后面）
        if param_count > 7:
            score -= 15
        return max(score, 0)


    def select_with_fallback(self, task: str = "chat") -> list:
        """返回降级链，顺序尊重配置 preference("local"本地优先/"cloud"云端优先)。"""
        pref = self._config.get("selection_rules", {}).get(task, {}).get(
            "prefer", self._config.get("preference", "auto"))
        all_models = self.get_all_ranked()
        cloud = [m for m in all_models if m.get("source") == "cloud"]
        local = [m for m in all_models if m.get("source") == "local"]
        ollama = [m for m in all_models if m.get("source") == "ollama"]
        chain = []
        groups = [local, cloud, ollama] if pref == "local" else [cloud, local, ollama]
        for group in groups:
            if group:
                chain.append(group[0])
        # 去重
        seen = set()
        deduped = []
        for m in chain:
            if m["name"] not in seen:
                seen.add(m["name"])
                deduped.append(m)
        return deduped if deduped else (all_models[:1] if all_models else [])

    def get_report(self) -> str:
        """状态报告JSON。"""
        all_m = self.get_all_ranked()
        best = self.select_best()
        return json.dumps({
            "total_models": len(all_m),
            "ollama_count": len([m for m in all_m if m["source"] == "ollama"]),
            "cloud_count": len([m for m in all_m if m["source"] == "cloud"]),
            "best_model": best,
            "all_models": [{"name": m["name"], "source": m["source"], "score": m["quality_score"]} for m in all_m[:10]],
        }, ensure_ascii=False, indent=2)
