"""Configurable OpenAI-compatible model providers for AutoFlow."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import keyring
from openai import OpenAI

SERVICE_NAME = "AutoFlow Model Provider"
CONFIG_ACCOUNT = "active-config"
LEGACY_SERVICE_NAME = "AutoFlow DeepSeek"
BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"

PROVIDERS: dict[str, dict[str, Any]] = {
    "deepseek": {
        "name": "DeepSeek",
        "description": "DeepSeek 模型服务",
        "base_url": "https://api.deepseek.com",
        "requires_key": True,
        "manual_model": False,
        "credential_hint": "API Key",
        "model_hint": "从账号自动读取模型",
        "preferred_models": ["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"],
    },
    "moonshot_cn": {
        "name": "Moonshot / Kimi（中国）",
        "description": "适合 Kimi 中国区账号",
        "base_url": "https://api.moonshot.cn/v1",
        "requires_key": True,
        "manual_model": False,
        "credential_hint": "API Key",
        "model_hint": "从账号自动读取模型",
        "preferred_models": ["kimi-k3", "kimi-k2.7-code", "kimi-k2.6", "kimi-k2.5", "moonshot-v1-auto"],
    },
    "moonshot_global": {
        "name": "Moonshot / Kimi（国际）",
        "description": "适合 Kimi 国际区账号",
        "base_url": "https://api.moonshot.ai/v1",
        "requires_key": True,
        "manual_model": False,
        "credential_hint": "API Key",
        "model_hint": "从账号自动读取模型",
        "preferred_models": ["kimi-k3", "kimi-k2.7-code", "kimi-k2.6", "kimi-k2.5"],
    },
    "openai": {
        "name": "OpenAI", "description": "OpenAI 模型服务", "base_url": "https://api.openai.com/v1",
        "requires_key": True, "manual_model": False, "credential_hint": "API Key", "model_hint": "从账号自动读取模型", "preferred_models": [],
    },
    "openrouter": {
        "name": "OpenRouter", "description": "一个 Key 访问多家模型", "base_url": "https://openrouter.ai/api/v1",
        "requires_key": True, "manual_model": False, "credential_hint": "OpenRouter API Key", "model_hint": "从账号自动读取模型", "preferred_models": [],
    },
    "siliconflow": {
        "name": "SiliconFlow / 硅基流动", "description": "国内多模型服务", "base_url": "https://api.siliconflow.cn/v1",
        "requires_key": True, "manual_model": False, "credential_hint": "API Key", "model_hint": "从账号自动读取模型", "preferred_models": [],
    },
    "zhipu": {
        "name": "智谱 BigModel / GLM", "description": "智谱 GLM 系列模型", "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "requires_key": True, "manual_model": False, "credential_hint": "API Key", "model_hint": "从账号自动读取模型", "preferred_models": [],
    },
    "dashscope": {
        "name": "阿里云百炼 / 通义千问", "description": "通义千问系列模型", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "requires_key": True, "manual_model": False, "credential_hint": "DashScope API Key", "model_hint": "从账号自动读取模型", "preferred_models": [],
    },
    "volcengine_ark": {
        "name": "火山方舟 / 豆包", "description": "需要 Key 和模型或推理接入点 ID", "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "requires_key": True, "manual_model": True, "credential_hint": "Ark API Key", "model_hint": "模型 ID / Endpoint ID（必填）", "preferred_models": [],
    },
    "ollama": {
        "name": "Ollama（本机）", "description": "连接本机 Ollama，无需 API Key", "base_url": "http://127.0.0.1:11434/v1",
        "requires_key": False, "manual_model": False, "credential_hint": "无需凭证", "model_hint": "从本机自动读取模型", "preferred_models": [],
    },
    "custom": {
        "name": "其他 OpenAI 兼容接口",
        "description": "自行填写接口地址、Key 和模型 ID",
        "base_url": "",
        "requires_key": False,
        "manual_model": True,
        "credential_hint": "API Key（按服务商要求，可留空）",
        "model_hint": "模型 ID（必填）",
        "preferred_models": [],
    },
}


class ProviderCredentials:
    """Store the full active provider configuration in Windows Credential Manager."""

    def get_config(self) -> dict[str, Any]:
        try:
            raw = keyring.get_password(SERVICE_NAME, CONFIG_ACCOUNT)
        except keyring.errors.KeyringError:
            raw = None
        if raw:
            try:
                value = json.loads(raw)
                return value if isinstance(value, dict) else {}
            except json.JSONDecodeError:
                return {}
        return self._legacy_config()

    def set_config(self, config: dict[str, Any]) -> None:
        try:
            keyring.set_password(SERVICE_NAME, CONFIG_ACCOUNT, json.dumps(config, ensure_ascii=False))
        except keyring.errors.KeyringError as exc:
            raise RuntimeError("无法写入 Windows 凭据库。") from exc

    def delete_config(self) -> None:
        try:
            keyring.delete_password(SERVICE_NAME, CONFIG_ACCOUNT)
        except keyring.errors.PasswordDeleteError:
            pass
        except keyring.errors.KeyringError as exc:
            raise RuntimeError("无法从 Windows 凭据库删除模型配置。") from exc

    def get_key(self) -> str:
        return str(self.get_config().get("api_key", ""))

    def set_key(self, api_key: str) -> None:
        config = self.get_config() or self._base_config("deepseek")
        config["api_key"] = api_key.strip()
        self.set_config(config)

    def get_model(self) -> str:
        return str(self.get_config().get("model", ""))

    def set_model(self, model: str) -> None:
        config = self.get_config() or self._base_config("deepseek")
        config["model"] = model
        self.set_config(config)

    def delete_key(self) -> None:
        self.delete_config()

    def _legacy_config(self) -> dict[str, Any]:
        try:
            api_key = keyring.get_password(LEGACY_SERVICE_NAME, "api-key") or ""
            model = keyring.get_password(LEGACY_SERVICE_NAME, "model") or DEFAULT_MODEL
        except keyring.errors.KeyringError:
            return {}
        if not api_key:
            return {}
        config = self._base_config("deepseek") | {"api_key": api_key, "model": model, "models": [model]}
        try:
            self.set_config(config)
        except RuntimeError:
            pass
        return config

    @staticmethod
    def _base_config(provider: str) -> dict[str, Any]:
        definition = PROVIDERS[provider]
        return {"provider": provider, "provider_name": definition["name"], "base_url": definition["base_url"], "api_key": "", "model": "", "models": [], "account_id": "", "account_header": "X-Account-ID"}


DeepSeekCredentials = ProviderCredentials


class DeepSeekInterpreter:
    """General model interpreter; historical name retained for compatibility."""

    def __init__(self, credentials: ProviderCredentials | None = None, model: str = DEFAULT_MODEL) -> None:
        self.credentials = credentials or ProviderCredentials()
        config = self.credentials.get_config()
        self.model = str(config.get("model") or model)

    @property
    def available(self) -> bool:
        config = self.credentials.get_config()
        if not config or not config.get("base_url") or not config.get("model"):
            return False
        definition = PROVIDERS.get(str(config.get("provider")), PROVIDERS["custom"])
        return bool(config.get("api_key")) or not definition["requires_key"]

    def status(self) -> dict[str, Any]:
        config = self.credentials.get_config()
        provider = str(config.get("provider") or "deepseek")
        definition = PROVIDERS.get(provider, PROVIDERS["custom"])
        default_model = definition["preferred_models"][0] if definition["preferred_models"] else ""
        return {
            "provider": provider,
            "provider_name": str(config.get("provider_name") or definition["name"]),
            "model": str(config.get("model") or default_model),
            "configured": self.available,
            "base_url": str(config.get("base_url") or definition["base_url"]),
            "models": list(config.get("models") or []),
            "requires_key": bool(definition["requires_key"]),
            "providers": [
                {
                    "id": key,
                    "name": value["name"],
                    "description": value["description"],
                    "base_url": value["base_url"],
                    "requires_key": value["requires_key"],
                    "manual_model": value["manual_model"],
                    "credential_hint": value["credential_hint"],
                    "model_hint": value["model_hint"],
                }
                for key, value in PROVIDERS.items()
            ],
        }

    def configure_provider(
        self,
        provider: str,
        api_key: str = "",
        base_url: str = "",
        model: str = "",
        account_id: str = "",
        account_header: str = "X-Account-ID",
    ) -> dict[str, Any]:
        if provider not in PROVIDERS:
            raise ValueError("不支持这个模型服务商。")
        definition = PROVIDERS[provider]
        current = self.credentials.get_config()
        requested_url = base_url.strip().rstrip("/")
        if provider != "custom" and requested_url and requested_url != definition["base_url"]:
            raise ValueError("内置模型服务商不允许修改接口地址；需要其他地址时请选择自定义接口。")
        selected_url = (requested_url or definition["base_url"]).strip().rstrip("/")
        if not api_key.strip() and current.get("provider") == provider:
            api_key = str(current.get("api_key", ""))
        if not selected_url.startswith(("http://", "https://")):
            raise ValueError("接口地址必须以 http:// 或 https:// 开头。")
        if definition["requires_key"] and len(api_key.strip()) < 12:
            raise ValueError("请输入完整的 API Key。")
        parsed_url = urlparse(selected_url)
        if api_key.strip() and parsed_url.scheme == "http" and parsed_url.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("携带 API Key 的远程接口必须使用 HTTPS；本机 localhost 接口除外。")
        headers = self._headers(account_id, account_header)
        client = OpenAI(api_key=api_key.strip() or "not-required", base_url=selected_url, timeout=20.0, max_retries=0, default_headers=headers or None)
        manual_model = bool(definition["manual_model"] and model.strip())
        available = self._list_models(client, allow_manual=manual_model)
        if manual_model:
            selected_model = model.strip()
        elif available:
            preferred = [model.strip()] + list(definition["preferred_models"])
            selected_model = next((name for name in preferred if name and name in available), available[0])
        else:
            selected_model = model.strip()
        if not selected_model:
            raise ValueError("没有发现可用模型，请手动填写模型 ID。")
        config = {
            "provider": provider,
            "provider_name": definition["name"],
            "base_url": selected_url,
            "api_key": api_key.strip(),
            "model": selected_model,
            "models": available or [selected_model],
            "account_id": account_id.strip(),
            "account_header": account_header.strip() or "X-Account-ID",
        }
        self.credentials.set_config(config)
        self.model = selected_model
        return self.status()

    def select_model(self, model: str) -> dict[str, Any]:
        config = self.credentials.get_config()
        if not config:
            raise ValueError("请先连接一个模型服务商。")
        model = model.strip()
        if not model:
            raise ValueError("模型不能为空。")
        known = list(config.get("models") or [])
        if known and model not in known:
            raise ValueError("这个模型不在账户返回的可用列表中。")
        config["model"] = model
        self.credentials.set_config(config)
        self.model = model
        return self.status()

    def configure(self, api_key: str) -> None:
        self.configure_provider("deepseek", api_key=api_key)

    def disconnect(self) -> dict[str, Any]:
        self.credentials.delete_config()
        self.model = DEFAULT_MODEL
        return self.status()

    def interpret(self, command: str) -> dict[str, Any]:
        value = self._chat_json([
            {"role": "system", "content": "你是 AutoFlow 的指令解释器。只输出 JSON。支持 intent=open 和 intent=pdf_to_txt，不支持则 intent=unsupported。字段固定为 intent,target,source,destination。路径和名称必须来自用户原话，不得猜测。"},
            {"role": "user", "content": command},
        ], max_tokens=500)
        if value.get("intent") not in {"open", "pdf_to_txt", "unsupported"}:
            raise RuntimeError("模型返回了不允许的操作类型。")
        return value

    def next_action(self, goal: str, observation: dict[str, Any], history: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        system_prompt = (
            "你是 AutoFlow，一个可靠的 Windows 电脑操作 Agent。先在心里把用户目标拆成可验证的子目标，再决定当前唯一的下一步。"
            "每次行动前都要结合当前画面、最近结果和完整进度判断；不要重复已经失败的同一动作，失败后应换控件、窗口、路径或工具。"
            "只能使用观察结果里真实存在的 element_id、窗口、路径和文件，不得编造任何界面、结果或成功证据。"
            "优先使用语义 UI 控件；只有找不到合适控件时才使用坐标。不要为了看起来有进展而盲目点击。"
            "标题含 AutoFlow 的窗口是你的控制面板，不是用户任务的工作对象。若它出现在前台，应从 windows 中找到任务应用并用 focus_window 切回。"
            "当 observation.execution_mode=background_preferred 时，优先使用 click_element 和带 element_id 的 type_text 静默操作后台控件。"
            "只有后台控件无法完成时才使用 press_keys、click_at 或 focus_window；这些会短暂占用用户前台。"
            "完成前必须核对目标的所有条件，并从当前观察或工具结果中找到完成证据。证据不足就继续观察或操作，不能提前 finish。"
            "调用 finish 时，message 必须是给用户看的完整答复：说明做成了什么、关键结果或保存位置，以及任何需要注意的情况；禁止只写‘完成’或‘目标完成’。"
            "只有缺少用户独有信息、登录、验证码或系统权限时才调用 ask_user，并把问题一次说清楚。"
            '只输出 JSON：{"summary":"当前步骤及选择原因","action":"工具名","arguments":{}}。'
        )
        failed = [item for item in history[-8:] if item.get("status") in {"failed", "blocked", "rejected"}]
        value = self._chat_json([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps({
                "goal": goal,
                "success_rule": "目标中每一项都有真实完成证据才可结束",
                "observation": observation,
                "recent_history": history[-16:],
                "recent_failures": failed,
                "tools": tools,
            }, ensure_ascii=False)},
        ], max_tokens=1000)
        if not isinstance(value.get("action"), str) or not isinstance(value.get("arguments", {}), dict):
            raise RuntimeError("模型没有返回可执行动作。")
        return value

    def final_response(self, goal: str, observation: dict[str, Any], history: list[dict[str, Any]], proposed: str) -> str:
        """Turn execution evidence into a concise, user-facing completion reply."""
        value = self._chat_json([
            {"role": "system", "content": (
                "你负责给 AutoFlow 用户汇报任务结果。只依据提供的执行记录和最终观察回答，不得编造成果。"
                "用自然、明确的中文说明：实际完成了什么；关键结果、文件位置或应用状态；如有未完成或需注意事项也要直说。"
                "不要只说‘完成’、‘目标完成’或复述用户目标。只输出 JSON：{\"message\":\"最终答复\"}。"
            )},
            {"role": "user", "content": json.dumps({
                "goal": goal,
                "planner_message": proposed,
                "final_observation": observation,
                "execution_history": history[-20:],
            }, ensure_ascii=False)},
        ], max_tokens=600)
        message = str(value.get("message", "")).strip()
        return message or proposed

    def _chat_json(self, messages: list[dict[str, str]], max_tokens: int) -> dict[str, Any]:
        config = self.credentials.get_config()
        if not self.available:
            raise RuntimeError("尚未配置可用模型。")
        client = OpenAI(api_key=str(config.get("api_key") or "not-required"), base_url=str(config["base_url"]), timeout=45.0, max_retries=1, default_headers=self._headers(str(config.get("account_id", "")), str(config.get("account_header", ""))) or None)
        kwargs = {"model": str(config["model"]), "messages": messages, "max_tokens": max_tokens, "temperature": 0}
        try:
            response = client.chat.completions.create(**kwargs, response_format={"type": "json_object"})
        except Exception as exc:
            if getattr(exc, "status_code", None) != 400:
                raise RuntimeError(self._friendly_error(exc)) from exc
            response = client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or "{}"
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            value = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError("模型返回的 JSON 格式不正确。") from exc
        if not isinstance(value, dict):
            raise RuntimeError("模型没有返回 JSON 对象。")
        return value

    def _list_models(self, client: OpenAI, allow_manual: bool) -> list[str]:
        try:
            return [item.id for item in client.models.list().data if getattr(item, "id", "")]
        except Exception as exc:
            if allow_manual and getattr(exc, "status_code", None) in {400, 404, 405}:
                return []
            raise RuntimeError(self._friendly_error(exc)) from exc

    @staticmethod
    def _headers(account_id: str, account_header: str) -> dict[str, str]:
        return {(account_header.strip() or "X-Account-ID"): account_id.strip()} if account_id.strip() else {}

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        status = getattr(exc, "status_code", None)
        name = type(exc).__name__
        if status == 401 or name == "AuthenticationError":
            return "服务商拒绝了这个 Key，请确认复制完整且没有多余空格。"
        if status == 402:
            return "账户余额不足，请先在服务商平台充值。"
        if status == 403 or name == "PermissionDeniedError":
            return "这个凭据没有 API 访问权限，请检查账户或项目 ID。"
        if name in {"APIConnectionError", "APITimeoutError"}:
            return "无法连接模型服务，请检查网络、接口地址或代理。"
        return f"模型服务返回错误：{exc}"


ModelInterpreter = DeepSeekInterpreter
