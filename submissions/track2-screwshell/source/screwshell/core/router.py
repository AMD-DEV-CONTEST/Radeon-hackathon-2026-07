"""Heuristic Skill Router: maps an investigation task to a LoRA expert.

Routing signals (in priority order):
  1. Explicit task tag from the Orchestrator (e.g. step type "security")
  2. Keyword heuristics on the user query (security > code > doc > tool > plan)
  3. Default -> agent (multi-step planning) expert

A learned router is future work; heuristics are deterministic and easy to
demo/benchmark, which matters more for the hackathon.

Path D (llama.cpp + Qwen3.6-27B GGUF + hot LoRA) — FINALIZED expert lineup
(user-confirmed 2026-07-29; every base verified == Qwen/Qwen3.6-27B upstream):

  tool     -> btl3                 (badtheorylabs/BTL-3, r32/α64)
  code     -> btl3                 (BTL-3 dual-routed for code; HumanEval 95.1%)
  agent    -> teichai_plan         (TeichAI Fable-5 planning LoRA, r64; KEPT as agent expert.
                                    LOGICAL name; on-disk folder is `teichai_fable5_plan/` —
                                    see EXPERT_NAME_ALIASES / logical_expert_name().
                                    Bare "fable5" is a DIFFERENT, FORBIDDEN LoRA — see below)
  security -> cybersec             (hotdogs/qwen3.6-27b-cybersecurity-lora, r8/α16)  NEW step
  doc      -> rag_n7               (lananhyeuem/qwen3.6-27b-multilingual-rag-lora-n7, r128/α256)
                                    fallback: None -> base native thinking if n7 fails G-gates
  base     -> None                 (pure frozen base)

Removed (do NOT resurrect — see docs/LORA_SOURCE_VERIFICATION.md):
  hermes_s2 : silent base mismatch — true base is samscrack/Qwen3.6-27B-Opus-CoT-Stage1,
              NOT clean Qwen3.6-27B. Loads fine, behaves wrong.
  fable5    : repo 404 / privatized, never downloaded successfully.
Legacy peft names retired: sygnif / deltacoder / metro (Qwen3.5-9B).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# skill -> adapter name (local GGUF basename == engine registration name).
# All four LoRA bases verified == Qwen/Qwen3.6-27B via upstream adapter_config.json.
DEFAULT_SKILL_MAP = {
    "tool": "btl3",
    "code": "btl3",                 # BTL-3 dual-route (agentic-coding, HumanEval 95.1%)
    # LOGICAL name, not the on-disk folder name. The planning LoRA lives in
    # `teichai_fable5_plan/` on the W7900 box; EXPERT_NAME_ALIASES below maps
    # between the two and `logical_expert_name()` is the single authority.
    # Putting the DISK name here silently breaks mounting: discover_adapters()
    # registers experts under their LOGICAL name, so the lookup misses and
    # app.py "gracefully degrades" the agent expert to base -- no error, no
    # crash, planning just quietly runs on the bare base model forever.
    # Bare "fable5" remains FORBIDDEN (see below); this is a different LoRA.
    "agent": "teichai_plan",
    "security": "cybersec",         # new pipeline step (audit / vuln analysis)
    "doc": "rag_n7",                # fallback: set None if n7 fails acceptance gates
    "base": None,
}

# Experts that must NEVER be loaded, even if a stale copy sits on disk
# (TRUTH §6). hermes_s2 = silent base mismatch; fable5 = repo 404/privatized.
# The ban is enforced at BOTH the routing layer (DEFAULT_SKILL_MAP above) and
# the adapter discovery layer (screwshell.core.lora_scan.discover_adapters),
# so a leftover on-disk folder can never be registered.
FORBIDDEN_EXPERTS = frozenset({"hermes_s2", "fable5"})

# Anchored EXACT match — never substring. A naive `fable5 in name` would have
# wrongly banned the (now renamed) planning expert `teichai_plan`, which
# previously contained the substring "fable5". This regex matches only the full
# name, so e.g. "xfable5y" or "my_hermes_s2" are NOT forbidden.
FORBIDDEN_RE = re.compile(r"^(?:" + "|".join(re.escape(e) for e in FORBIDDEN_EXPERTS) + r")$")

def is_forbidden(name: Optional[str]) -> bool:
    """True only for the exact forbidden expert names (anchored, not substring).

    ``None`` (== the pure-base route, ``skill_map["base"]``) is never forbidden;
    accepting it here keeps every caller free of null-guards.
    """
    return bool(name) and bool(FORBIDDEN_RE.match(name))

# Logical expert name -> on-disk GGUF folder name on the W7900 instance.
# The remote folder keeps its historical name; this alias lets us rename the
# expert in code/docs without touching the (immutable-for-this-contest) remote
# directory. discover_adapters() resolves the disk folder back to the logical
# name via the reverse map, so routing always uses the clean logical name.
EXPERT_NAME_ALIASES = {"teichai_plan": "teichai_fable5_plan"}

# Reverse map, built once. Never invert EXPERT_NAME_ALIASES inline at a call
# site -- see logical_expert_name() below for why.
_ONDISK_TO_LOGICAL = {v: k for k, v in EXPERT_NAME_ALIASES.items()}


def logical_expert_name(disk_name: str) -> str:
    """THE single authority for on-disk folder name -> logical expert name.

    Every layer that turns a filesystem/server path into an adapter key MUST go
    through this function: ``lora_scan.discover_adapters`` (peft + llama.cpp
    directory scan) and ``MoLLlamaCpp.load_base`` (server-preloaded LoRA list).
    Both used to name adapters independently, so the same LoRA could get
    registered under two different keys (`teichai_plan` from the scan,
    `teichai_fable5_plan` from the server) and one of them would carry a bogus
    id -- with roomy-mode activate() then zeroing every scale and "succeeding"
    at mounting nothing. Keep the naming in exactly one place.

    Names with no alias pass through unchanged.
    """
    return _ONDISK_TO_LOGICAL.get(disk_name, disk_name)

CODE_EXT = r"\.(py|js|ts|tsx|jsx|c|cc|cpp|h|hpp|rs|go|java|rb|sh|ps1|cmake|mk)\b"
# CJK keyword fragments (2026-08-04, per plan Phase 2a). The relay's default
# routing path serves Chinese / natural-language queries from opencode/pi; the
# English-only regexes above missed them entirely, so every request fell
# through to the `agent` (no-weighted-expert) route and MoL never engaged.
# These are deliberately broad single-char/bigram classes so a query like
# "写一段计算质数的代码" hits CODE_KW and "审一下注入漏洞" hits SECURITY_KW.
# Keep \b boundaries off for the CJK parts (CJK has no word boundaries in re).
_CJK = (
    r"(?:代码|函数|类|重构|改[写进]|实现|接口|模块|导入|性能|优化|慢|"
    r"报错|异常|调试|编译|算法|脚本|程序|质数|素数|正则|注入)"
)
CODE_KW = re.compile(
    r"\b(code|repo|repository|function|class|bug|benchmark|kernel|compile|"
    r"stack ?trace|refactor|implement|api|module|import|slow|performance)\b"
    r"|" + CODE_EXT + r"|" + _CJK, re.I)
DOC_KW = re.compile(
    r"\b(document|doc|docs|summar|report|risk|plan|note|markdown|pdf|readme|"
    r"policy|meeting|spec)\b"
    r"|(?:文档|报告|总结|概括|摘要|笔记|纪要|说明)"
    , re.I)
TOOL_KW = re.compile(
    r"\b(run|execute|search|grep|list|read file|shell|command|tool)\b"
    r"|(?:搜索|查找|查询|列出|运行|执行|命令|脚本|文件|目录|grep|遍历)"
    , re.I)
PLAN_KW = re.compile(
    r"\b(investigate|multi-?step|plan|steps|why|analy[sz]e|compare|verify|"
    r"cross-?check)\b"
    r"|(?:调查|排查|对比|核实|验证|分析|规划|步骤|为什么|多步|检查)"
    , re.I)
# Security-audit keywords. Checked BEFORE code/doc so audit-style queries win
# the new `security` expert; explicit task_tag still beats everything. Some
# overlap with PLAN_KW/DOC_KW is expected (e.g. "investigate the CVE") — that is
# the desired behavior. Keep this list reviewed against the cybersec LoRA domain.
SECURITY_KW = re.compile(
    r"\b(audit|vulnerab|CVE|exploit|injection|payload|rce|ssrf|xss|"
    r"malicious|hardening|threat|breach|permission|leak|security|"
    r"attack|sanitiz|escape|auth[bz]?|overflow|unsafe|backdoor|"
    r"privileg|exfiltrat)\b"
    r"|(?:审计|漏洞|安全|注入|攻击|恶意|提权|越权|泄露|权限|逃逸|"
    r"加固|威胁|后门|溢出|破解|钓鱼|防护|防御)"
    , re.I)


@dataclass
class RouteDecision:
    skill: str
    adapter: Optional[str]
    reason: str


# Semantic fallback (2026-08-04, per docs/OPENSOURCE_COMPARISON.md §4.2 —
# semantic-router pattern). Keyword regexes miss paraphrased / implicit
# intents ("帮我审一下这个 .env 的泄露风险" has no security keyword). When an
# embedder is injected (reuses Qwen3-Embedding-0.6B), a query that NO regex
# matched is compared against per-skill example queries; the best match above
# SEMANTIC_THRESHOLD routes semantically. Zero new deps; without an embedder
# the router is byte-identical to the pure-regex behaviour.
SEMANTIC_EXAMPLES = {
    "security": ["审计这个仓库有没有漏洞", "检查这段代码的注入风险",
                 "review this repository for vulnerabilities",
                 "检查权限配置是否安全"],
    "code": ["解释这个函数怎么工作", "重构这段 python 代码", "这个 bug 出在哪",
             "explain how this class works", "为什么 benchmark 这么慢"],
    "doc": ["总结这份文档", "这份报告的主要风险是什么", "概括 README 内容",
            "summarize these meeting notes"],
    "tool": ["帮我搜一下包含这个关键词的文件", "grep 一下这段逻辑",
             "list the files in this repo"],
}
SEMANTIC_THRESHOLD = 0.55


class SkillRouter:
    def __init__(self, skill_map: dict | None = None):
        self.skill_map = dict(skill_map or DEFAULT_SKILL_MAP)
        self._embed_fn = None
        self._example_labels: list[str] = []
        self._example_vecs = None

    @classmethod
    def from_packs(cls, directory: str, deployed_base: str = "") -> "SkillRouter":
        """Build a router from scanned SkillPacks (L1). Falls back to the
        hardcoded DEFAULT_SKILL_MAP when the directory is empty, so existing
        callers are unaffected. Lazy import keeps autotune out of the hot path
        and out of the unit-test import graph unless explicitly used.
        """
        from screwshell.autotune.skillpack import scan_skillpacks, build_skill_map
        packs = scan_skillpacks(directory)
        if not packs:
            return cls()
        return cls(skill_map=build_skill_map(packs, deployed_base))

    def set_embedder(self, embed_fn) -> None:
        """Inject an embedding callable (texts: list[str] -> np.ndarray) for
        the semantic fallback layer. Optional: without it, routing stays pure
        keyword-based (byte-identical to the pre-fallback behaviour)."""
        self._embed_fn = embed_fn
        if embed_fn is None:
            return
        try:
            flat = [(skill, ex) for skill, exs in SEMANTIC_EXAMPLES.items()
                    for ex in exs]
            self._example_labels = [s for s, _ in flat]
            self._example_vecs = embed_fn([ex for _, ex in flat])
        except Exception:  # embedder unusable -> fall back to regex-only
            self._embed_fn = None
            self._example_vecs = None

    def _semantic_skill(self, q: str) -> Optional[tuple[str, float]]:
        if self._embed_fn is None or self._example_vecs is None or not q:
            return None
        try:
            import numpy as np
            qv = self._embed_fn([q])[0]
            sims = self._example_vecs @ qv
            best = int(np.argmax(sims))
            score = float(sims[best])
            if score >= SEMANTIC_THRESHOLD:
                return self._example_labels[best], score
        except Exception:
            pass
        return None

    def _decide(self, skill: str, reason: str) -> RouteDecision:
        """SINGLE construction point for every RouteDecision.

        The forbidden-expert guard lives here and nowhere else. It used to sit
        on the last `return` of route() only -- which is dead code on the main
        path, because the Orchestrator always calls
        ``route(desc, task_tag=step["skill"])`` and that hits the very first
        branch. A poisoned skill_map (e.g. a SkillPack scan that resurrected
        `fable5`) would sail straight through. Routing every return point
        through here means the guard cannot be bypassed by adding a branch.

        A forbidden adapter degrades to ``None`` (pure base) rather than
        raising: refusing to answer is worse than answering without the expert,
        but the reason string records the downgrade so it stays visible.
        """
        adapter = self.skill_map.get(skill)
        if is_forbidden(adapter):
            return RouteDecision(
                skill, None,
                f"{reason} [FORBIDDEN expert '{adapter}' blocked -> base]")
        return RouteDecision(skill, adapter, reason)

    def route(self, query: str, task_tag: str | None = None) -> RouteDecision:
        # 1. explicit tag wins
        if task_tag and task_tag in self.skill_map:
            return self._decide(task_tag, f"explicit task tag '{task_tag}'")
        # 2. security-intent keywords -> security expert (checked before code/doc)
        q = query or ""
        if SECURITY_KW.search(q):
            return self._decide("security", "security/audit keywords detected")
        # 3. heuristics on the query text
        if CODE_KW.search(q):
            return self._decide("code", "code keywords/file-extensions detected")
        if DOC_KW.search(q):
            return self._decide("doc", "document/summary keywords detected")
        if TOOL_KW.search(q):
            return self._decide("tool", "tool-execution keywords detected")
        if PLAN_KW.search(q):
            return self._decide("agent", "multi-step planning keywords detected")
        # 4. semantic fallback: every regex missed -> embedding similarity
        # against per-skill example queries (optional, ADR-2 switchable).
        sem = self._semantic_skill(q)
        if sem:
            skill, score = sem
            return self._decide(skill, f"semantic fallback (cos={score:.2f})")
        return self._decide("agent", "default -> multi-turn agent expert")
