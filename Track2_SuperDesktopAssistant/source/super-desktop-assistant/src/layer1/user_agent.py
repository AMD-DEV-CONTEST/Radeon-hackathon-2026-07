"""
Layer 1: 用户交互层（User Agent）（v2.0）

核心职责：
1. 接收用户自然语言输入
2. 上下文截断与摘要生成
   - 固定保留最近 N 轮（默认6轮）完整对话 + 首轮目标
   - 截断前调用轻量模型对即将丢弃的对话生成一句摘要（≤50字）
   - 摘要注入实体字典的 truncation_summary 字段
3. 轻量级实体提取
   - 通过正则/小模型提取关键信息（ID、日期、核心名词）
   - 安全过滤（去除潜在注入字符）
4. 将 [最近N轮对话] + [实体字典] + [首轮目标] + [截断摘要] 传给第2层

v2.0 新增：截断摘要、安全过滤、渐进修改追踪
v3 P6b：Layer 1 是唯一拥有配置修改权限的层。前置 ConfigIntentHandler
    拦截配置指令（切换模型/调参/改目录/启停供应商），不进入多 Agent 编排。
"""
from __future__ import annotations

import re
import html
from typing import Any
from loguru import logger


# ═══════════════════════════════════════════════════════════════
# v3 P6b: 配置意图处理器（Layer 1 唯一配置修改权限）
# ═══════════════════════════════════════════════════════════════

class ConfigIntentHandler:
    """
    检测并执行对话中的配置指令。

    触发示例：
    - "把 LLM 换成 deepseek"
    - "用 openai 的 gpt-4o 做视觉"
    - "temperature 调到 0.7"
    - "工作目录改成 E:\\test\\agent-framework-test"
    - "优先用本地 ollama"
    - "禁用 zhipu 这个 API"

    处理成功返回 {"handled": True, "reply": "..."}；
    非配置指令返回 None（交由正常编排）。
    """

    # 功能别名 → assignment key
    _CAP_ALIASES = {
        "llm": "llm", "对话": "llm", "大模型": "llm", "语言模型": "llm",
        "vision": "vision", "视觉": "vision", "看图": "vision", "图像识别": "vision", "识图": "vision",
        "stt": "stt", "语音识别": "stt", "转写": "stt", "听写": "stt",
        "tts": "tts", "语音合成": "tts", "朗读": "tts", "发声": "tts",
        "image_gen": "image_gen", "生图": "image_gen", "绘图": "image_gen",
        "画图": "image_gen", "文生图": "image_gen", "出图": "image_gen",
        "推理": "llm_reasoning", "reasoning": "llm_reasoning",
        "创意": "llm_creative", "写作": "llm_creative", "creative": "llm_creative",
        "摘要": "llm_summary", "summary": "llm_summary",
    }

    # 供应商别名 → provider key
    _PROVIDER_ALIASES = {
        "deepseek": "deepseek", "deep seek": "deepseek",
        "openai": "openai", "gpt": "openai", "open ai": "openai",
        "qwen": "qwen", "千问": "qwen", "通义": "qwen", "阿里": "qwen", "aliyun": "qwen",
        "mimo": "mimo", "小米": "mimo", "米墨": "mimo", "xiaomi": "mimo", "mi mo": "mimo",
        "zhipu": "zhipu", "智谱": "zhipu", "glm": "zhipu",
        "vllm": "vllm", "本地": "vllm", "本地推理": "vllm",
        "ollama": "ollama", "llama": "ollama",
        "siliconflow": "siliconflow", "硅基流动": "siliconflow",
        "硅基": "siliconflow", "sf": "siliconflow",
    }

    def __init__(self):
        self._switch_verbs = ("换成", "切换成", "切到", "改为", "改成", "设为",
                              "设置为", "换回", "换到", "切换为")
        self._toggle_verbs = ("禁用", "停用", "关闭", "启用", "开启")

    def handle(self, message: str) -> dict | None:
        """处理配置意图。返回 {"handled": True, "reply": str} 或 None。"""
        try:
            if r := self._try_assignment_switch(message):
                return r
            if r := self._try_numeric_setting(message):
                return r
            if r := self._try_path_setting(message):
                return r
            if r := self._try_provider_toggle(message):
                return r
            if r := self._try_api_preference(message):
                return r
        except Exception as e:
            logger.warning(f"[L1:Config] 配置指令处理异常: {e}")
            return {"handled": True, "reply": f"⚠️ 配置指令无法执行: {e}"}
        return None

    # ── 功能分配切换 ──

    def _try_assignment_switch(self, message: str) -> dict | None:
        if not any(v in message for v in self._switch_verbs):
            return None

        cap = self._find_capability(message)
        provider, model = self._find_provider_and_model(message)
        if not cap or not provider:
            return None

        from ..config import get_config, reload_config
        cfg = get_config()
        p = cfg.get_provider(provider)
        if not p:
            return {"handled": True, "reply": f"❌ 供应商 {provider} 不存在（可用: {list(cfg._providers.keys())}）"}

        # 确定模型：用户指定 or 该供应商支持该能力的第一模型
        if model is None:
            base_cap = cfg._base_capability(cap)
            models = p.list_models_by_capability(base_cap)
            if not models:
                return {"handled": True, "reply": f"❌ {provider} 没有支持 {cap} 的模型"}
            model = models[0].id
        else:
            if model not in p.models:
                return {"handled": True, "reply": f"❌ {provider} 没有模型 {model}"}

        cfg.set_assignment(cap, provider, model)
        if not cfg.save_to_file():
            return {"handled": True, "reply": "⚠️ 配置保存失败（请检查 config.json 文件权限）"}
        reload_config()
        return {"handled": True, "reply": f"✅ 已把 {cap} 切换到 {provider}/{model}"}

    def _find_capability(self, message: str) -> str | None:
        msg_lower = message.lower()
        for alias, cap in self._CAP_ALIASES.items():
            if alias.lower() in msg_lower:
                return cap
        return None

    def _find_provider_and_model(self, message: str) -> tuple[str | None, str | None]:
        """识别消息中的供应商与模型。

        模型名从该供应商的模型列表做包含匹配（支持 deepseek-reasoner、qwen-max 等
        不含数字的模型名，避免正则误取消息中的无关数字）。
        """
        msg_lower = message.lower()
        provider = None
        for alias, key in self._PROVIDER_ALIASES.items():
            if alias.lower() in msg_lower:
                provider = key
                break
        if not provider:
            return None, None

        from ..config import get_config
        p = get_config().get_provider(provider)
        if p:
            for mid in p.models:
                if mid.lower() in msg_lower:
                    return provider, mid
        return provider, None

    # ── 数值参数 ──

    def _try_numeric_setting(self, message: str) -> dict | None:
        """识别 temperature/max_tokens 配置指令。

        严格限定指令结构，避免把"今天温度30度"等闲聊误判为配置。
        """
        # 英文关键词（temperature/temp/max_tokens/tokens）+ 可选动词 + 数值
        m = re.search(
            r"(?:temperature|temp|max_tokens|最大token数?|tokens)"
            r"\s*(?:调到|设为|改成|设置为|改为|=)?\s*(\d+(?:\.\d+)?)",
            message, re.IGNORECASE,
        )
        raw_key = m.group(0).lower() if m else ""
        if not m:
            # 中文"温度"必须带明确指令动词
            m = re.search(
                r"(?:把\s*)?(?:temperature|temp|温度)\s*"
                r"(?:调到|设为|改成|设置为|改为|调整到)\s*(\d+(?:\.\d+)?)",
                message, re.IGNORECASE,
            )
            if not m:
                return None
            raw_key = "temperature"

        if "max_tokens" in raw_key or "token" in raw_key:
            key = "max_tokens"
            try:
                value = int(float(m.group(1)))
            except ValueError:
                return None
            if not (1 <= value <= 32768):
                return {"handled": True, "reply": f"⚠️ max_tokens 超出范围 (1-32768): {value}"}
        else:
            key = "temperature"
            try:
                value = float(m.group(1))
            except ValueError:
                return None
            if not (0.0 <= value <= 2.0):
                return {"handled": True, "reply": f"⚠️ temperature 超出范围 (0-2): {value}"}

        from ..config import get_config, reload_config
        cfg = get_config()
        reply = cfg.update_setting(key, value)
        if not cfg.save_to_file():
            return {"handled": True, "reply": "⚠️ 配置保存失败（请检查 config.json 文件权限）"}
        reload_config()
        return {"handled": True, "reply": f"✅ {reply}"}

    # ── 路径设置 ──

    def _try_path_setting(self, message: str) -> dict | None:
        m = re.search(
            r"(工作目录|输出目录|workspace_dir|output_dir)"
            r"\s*(改成|设为|设置为|改为)?\s*"
            r"([A-Za-z]:[\\/][^\s，。,;；]*|(?:\.\.?/)[^\s，。,;；]*)",
            message, re.IGNORECASE,
        )
        if not m:
            return None
        raw_key = m.group(1).lower()
        path = m.group(3).strip()
        # 重构修复（Bug 4）：先判中文"输出"，避免"输出目录"落入 else 被写成 workspace_dir
        if "output" in raw_key or "输出" in raw_key:
            key = "output_dir"
        else:
            key = "workspace_dir"

        from ..config import get_config, reload_config
        cfg = get_config()
        reply = cfg.update_setting(key, path)
        if not cfg.save_to_file():
            return {"handled": True, "reply": "⚠️ 配置保存失败（请检查 config.json 文件权限）"}
        reload_config()
        return {"handled": True, "reply": f"✅ {reply}"}

    # ── 供应商启停 ──

    def _try_provider_toggle(self, message: str) -> dict | None:
        for verb in self._toggle_verbs:
            if verb in message:
                for alias, key in self._PROVIDER_ALIASES.items():
                    if alias.lower() in message.lower():
                        enabled = verb in ("启用", "开启")
                        from ..config import get_config, reload_config
                        cfg = get_config()
                        if not cfg.get_provider(key):
                            break
                        reply = cfg.set_provider_enabled(key, enabled)
                        if not cfg.save_to_file():
                            return {"handled": True, "reply": "⚠️ 配置保存失败（请检查 config.json 文件权限）"}
                        reload_config()
                        return {"handled": True, "reply": f"✅ {reply}"}
        return None

    # ── API 偏好 ──

    def _is_question(self, message: str) -> bool:
        """判断是否为疑问句（Bug 8：避免疑问句误触发配置写盘）。"""
        stripped = message.strip()
        if not stripped:
            return False
        # 句尾疑问语气词/问号
        if stripped[-1] in "？?吗呢么":
            return True
        # 疑问代词
        return any(q in message for q in ("哪些", "什么", "怎么", "是不是", "能否", "可以吗"))

    def _try_api_preference(self, message: str) -> dict | None:
        """识别 API 偏好指令（本地优先 / 云端默认）。

        要求含明确指令词（优先/默认/切换/改为/api/推理/模型），
        避免把"我本地用的是Windows"等描述误判为配置。
        重构修复（Bug 8）：疑问句（"本地优先吗？""怎么切云端？"）不触发写盘。
        """
        msg_lower = message.lower()
        has_local = ("本地" in msg_lower) or ("local" in msg_lower)
        has_cloud = ("云端" in msg_lower) or ("cloud" in msg_lower)
        has_cmd = any(v in msg_lower for v in (
            "优先", "默认", "切换", "改为", "走", "api", "推理", "模型", "preference"
        ))
        if self._is_question(message):
            return None
        if has_local and has_cmd:
            return self._apply_api_preference("local_first")
        if has_cloud and has_cmd:
            return self._apply_api_preference("cloud_default")
        return None

    def _apply_api_preference(self, value: str) -> dict:
        from ..config import get_config, reload_config
        cfg = get_config()
        reply = cfg.update_setting("api_preference", value)
        if not cfg.save_to_file():
            return {"handled": True, "reply": "⚠️ 配置保存失败（请检查 config.json 文件权限）"}
        reload_config()
        return {"handled": True, "reply": f"✅ {reply}"}


class UserAgent:
    """
    用户交互层 —— 对话管理、截断、实体提取、安全过滤。

    配置：
    - max_turns: 保留的完整对话轮次（默认6轮）
    - max_summary_chars: 截断摘要最大字数（默认50字）
    """

    def __init__(self, max_turns: int = 6, max_summary_chars: int = 50):
        self.max_turns = max_turns
        self.max_summary_chars = max_summary_chars

        # 渐进修改追踪（记录用户对核心参数的修改历史）
        self._parameter_history: dict[str, list[str]] = {}

        # v3 P6b: 配置意图处理器（Layer 1 唯一配置修改权限）
        self._config_handler = ConfigIntentHandler()

    # ── 主入口 ──

    def process(
        self,
        user_message: str,
        conversation_history: list[dict] | None = None,
        session_id: str = "",
    ) -> dict:
        """
        处理用户输入，生成第2层所需的数据包。

        Args:
            user_message: 用户当前输入
            conversation_history: 完整对话历史
            session_id: 会话ID

        Returns:
            {
                "session_id": str,
                "recent_dialogs": list[dict],      # 最近N轮
                "original_goal": str,               # 首轮用户原话
                "entities": {
                    "ids": [...],
                    "dates": [...],
                    "keywords": [...],
                    "truncation_summary": str,       # 被截断对话摘要
                    "progressive_changes": dict,     # 渐进修改追踪
                }
            }
        """
        history = conversation_history or []

        # 0. v3 P6b: 配置指令拦截（Layer 1 唯一配置修改权限，不进入编排）
        config_result = self._config_handler.handle(user_message)
        if config_result:
            logger.info(f"[L1] 配置指令处理: {config_result['reply']}")
            return {
                "session_id": session_id,
                "config_handled": True,
                "reply": config_result["reply"],
                "recent_dialogs": [],
                "original_goal": user_message,
                "entities": {
                    "keywords": [],
                    "truncation_summary": "",
                    "progressive_changes": {},
                },
            }

        # 1. 提取首轮目标
        original_goal = self._extract_original_goal(history, user_message)

        # 2. 执行截断 + 生成摘要
        recent_dialogs, truncation_summary = self._truncate_with_summary(history)

        # 3. 实体提取 + 安全过滤
        entities = self._extract_entities(user_message, history)

        # 4. 注入截断摘要
        entities["truncation_summary"] = truncation_summary

        # 5. 渐进修改追踪
        entities["progressive_changes"] = self._track_changes(user_message)

        # 6. 安全过滤：HTML 转义防注入
        entities = self._sanitize_entities(entities)
        user_message_safe = self._sanitize_text(user_message)

        logger.info(
            f"[L1] 处理完成: turns={len(recent_dialogs)}, "
            f"entities={len(entities.get('keywords', []))}, "
            f"truncated={bool(truncation_summary)}"
        )

        return {
            "session_id": session_id,
            "recent_dialogs": recent_dialogs,
            "original_goal": original_goal,
            "entities": entities,
        }

    # ── 截断与摘要 ──

    def _truncate_with_summary(
        self, history: list[dict]
    ) -> tuple[list[dict], str]:
        """
        截断对话历史，生成被截断部分的摘要。

        策略：保留最近 max_turns 轮，其余生成一句摘要。
        """
        if not history:
            return [], ""

        # 计算要保留的轮次（按 user+assistant 对计算）
        pairs = self._extract_turn_pairs(history)
        if len(pairs) <= self.max_turns:
            return history, ""

        # 截断：保留最近 N 轮 + 丢弃的生成摘要
        kept_pairs = pairs[-self.max_turns:]
        discarded_pairs = pairs[:-self.max_turns]

        # 生成被截断部分的摘要
        summary = self._generate_truncation_summary(discarded_pairs)

        # 重建对话列表（只保留最近 N 轮的消息）
        kept_count = self.max_turns * 2  # user + assistant
        recent_dialogs = history[-kept_count:]

        logger.info(
            f"[L1] 截断: {len(discarded_pairs)}轮 → 摘要({len(summary)}字), "
            f"保留 {len(kept_pairs)}轮"
        )

        return recent_dialogs, summary

    def _extract_turn_pairs(self, history: list[dict]) -> list[tuple]:
        """从完整历史中提取对话轮次对（user, assistant）。"""
        pairs = []
        i = 0
        while i < len(history):
            msg = history[i]
            role = msg.get("role", "")
            if role == "user":
                user_content = msg.get("content", "")[:200]
                # 找到对应的 assistant 回复
                assistant_content = ""
                for j in range(i + 1, len(history)):
                    if history[j].get("role") == "assistant":
                        assistant_content = history[j].get("content", "")[:200]
                        break
                pairs.append((user_content, assistant_content))
                i += 2 if assistant_content else 1
            else:
                i += 1
        return pairs

    def _generate_truncation_summary(self, discarded_pairs: list[tuple]) -> str:
        """
        为被丢弃的对话生成一句话摘要。

        优先用 LLM 生成，如果失败则用简单关键词拼接。
        """
        if not discarded_pairs:
            return ""

        # 简单策略：提取被丢弃对话的关键信息关键词
        all_text = " ".join(
            user[:100] + " " + asst[:100]
            for user, asst in discarded_pairs
        )

        # 提取出现频率最高的名词/主题词作为摘要
        keywords = self._extract_key_keywords(all_text, top_n=5)
        if keywords:
            summary = f"之前讨论过: {'、'.join(keywords[:3])}"
            return summary[:self.max_summary_chars]

        # 兜底
        sample = all_text[:100].strip()
        return f"之前讨论了: {sample}"[:self.max_summary_chars]

    # ── 实体提取 ──

    def _extract_entities(
        self, user_message: str, history: list[dict]
    ) -> dict:
        """提取关键实体。"""
        all_text = user_message
        for h in history[-3:]:  # 最近3条历史
            all_text += " " + str(h.get("content", ""))[:500]

        return {
            "ids": self._extract_ids(all_text),
            "dates": self._extract_dates(all_text),
            "keywords": self._extract_key_keywords(all_text),
        }

    def _extract_ids(self, text: str) -> list[str]:
        """提取各类 ID。"""
        patterns = [
            r'\b[A-Z]{2,}-\d+\b',          # JIRA-1234
            r'\b[0-9a-f]{8}-[0-9a-f]{4}',  # UUID 前缀
            r'\b[a-zA-Z]+\d{4,}\b',        # 字母+数字组合
        ]
        ids = []
        for pat in patterns:
            ids.extend(re.findall(pat, text, re.IGNORECASE))
        return list(dict.fromkeys(ids))[:10]  # 去重，最多10个

    def _extract_dates(self, text: str) -> list[str]:
        """提取日期信息。"""
        patterns = [
            r'\d{4}[-/]\d{1,2}[-/]\d{1,2}',   # 2024-01-15
            r'\d{1,2}月\d{1,2}日',             # 1月15日
            r'\d{4}年\d{1,2}月\d{1,2}日',       # 2024年1月15日
        ]
        dates = []
        for pat in patterns:
            dates.extend(re.findall(pat, text))
        return dates[:5]

    def _extract_key_keywords(self, text: str, top_n: int = 8) -> list[str]:
        """提取核心关键词（基于词频）。"""
        # 分词（中英文混合的简单方法）
        # 提取中文双字和三字词组
        words = []
        cn_chars = re.findall(r'[\u4e00-\u9fff]{2,4}', text)
        words.extend(cn_chars)

        # 提取英文单词（≥3字母）
        en_words = re.findall(r'\b[a-zA-Z]{3,}\b', text)
        words.extend(en_words)

        # 按频率排序，过滤停用词
        stop_words = {"这个", "那个", "什么", "怎么", "可以", "需要", "一个",
                      "the", "and", "for", "this", "that", "with", "what"}
        freq = {}
        for w in words:
            wl = w.lower()
            if wl not in stop_words and len(w) >= 2:
                freq[wl] = freq.get(wl, 0) + 1

        sorted_words = sorted(freq.items(), key=lambda x: -x[1])
        return [w for w, _ in sorted_words[:top_n]]

    # ── 渐进修改追踪 ──

    def _track_changes(self, user_message: str) -> dict[str, list[str]]:
        """
        追踪用户对核心参数的渐进式修改。
        例如：{subject: ["猫", "狗", "兔子"], style: ["水墨", "工笔"]}
        """
        # 关键词→修改词的映射
        change_patterns = {
            "subject": ["画", "生成", "创建", "制作"],
            "style": ["风格", "style"],
            "size": ["尺寸", "大小", "size", "分辨率"],
            "color": ["颜色", "色", "color"],
        }

        changes = {}
        for key, triggers in change_patterns.items():
            if any(t in user_message for t in triggers):
                # 提取修改目标
                subjects = self._extract_key_keywords(user_message, top_n=5)
                if subjects:
                    if key not in self._parameter_history:
                        self._parameter_history[key] = []
                    self._parameter_history[key].append(subjects[0])
                    # 保留最近10次修改
                    if len(self._parameter_history[key]) > 10:
                        self._parameter_history[key] = self._parameter_history[key][-10:]

        return dict(self._parameter_history)

    # ── 安全过滤 ──

    def _sanitize_entities(self, entities: dict) -> dict:
        """对实体值进行安全过滤。"""
        sanitized = {}
        for key, value in entities.items():
            if isinstance(value, list):
                sanitized[key] = [
                    self._sanitize_text(str(v)) for v in value
                ]
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_entities(value)
            elif isinstance(value, str):
                sanitized[key] = self._sanitize_text(value)
            else:
                sanitized[key] = value
        return sanitized

    @staticmethod
    def _sanitize_text(text: str) -> str:
        """
        安全过滤用户输入，防止 Prompt 注入。

        策略：
        - HTML 转义（防标记注入）
        - 移除/替换常见注入模式
        - 白名单过滤控制字符
        """
        if not text:
            return text

        # 1. 移除控制字符（保留换行和制表符）
        sanitized = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

        # 2. HTML 转义
        sanitized = html.escape(sanitized, quote=False)

        # 3. 移除常见注入模式
        injection_patterns = [
            (r'<\s*script[^>]*>.*?<\s*/\s*script\s*>', '[FILTERED]'),
            (r'<\s*img[^>]*onerror\s*=', '[FILTERED]'),
            (r'javascript\s*:', '[FILTERED]'),
        ]
        for pattern, replacement in injection_patterns:
            sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE | re.DOTALL)

        return sanitized

    # ── 首轮目标提取 ──

    def _extract_original_goal(
        self, history: list[dict], current_message: str
    ) -> str:
        """提取首轮用户原始目标。"""
        # 如果历史为空，当前消息就是首轮
        if not history:
            return current_message

        # 找到第一条 user 消息
        for msg in history:
            if msg.get("role") == "user":
                return str(msg.get("content", ""))[:500]

        return current_message

    # ── 重置 ──

    def reset(self):
        """重置状态（新会话开始时调用）。"""
        self._parameter_history.clear()
        logger.info("[L1] UserAgent 状态已重置")
