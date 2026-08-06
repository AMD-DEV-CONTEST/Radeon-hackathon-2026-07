"""Semantic fallback routing tests (2026-08-04, OPENSOURCE_COMPARISON §4.2).

Keyword regexes miss paraphrased / implicit intents. With an embedder
injected, a query that no regex matched routes via embedding similarity to
the nearest skill example. Without an embedder the router is byte-identical
to the pure-regex behaviour.
"""
from __future__ import annotations

import numpy as np
import pytest

from screwshell.core.router import SEMANTIC_EXAMPLES, SkillRouter


class _FakeEmbed:
    """Toy embedder: one-hot per word (like the RAG test fake)."""

    def __init__(self):
        self.words = {}

    def __call__(self, texts):
        out = []
        import re
        for t in texts:
            v = np.zeros(64)
            for w in re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]", t.lower()):
                v[self.words.setdefault(w, len(self.words)) % 64] += 1
            n = np.linalg.norm(v)
            out.append(v / n if n else v)
        return np.array(out)


def test_router_without_embedder_is_unchanged():
    r = SkillRouter()
    # a query with an explicit keyword still routes by regex (CJK keyword too)
    assert r.route("解释这个 bug").skill == "code"
    assert r.route("帮我写一段计算质数的代码").skill == "code"
    # a paraphrase with NO code/security/doc/tool keyword falls through to agent
    assert r.route("这事儿你觉得咱应不应该再等等看").skill == "agent"
    assert r.route("这事儿你觉得咱应不应该再等等看").reason.startswith("default")


def test_router_semantic_fallback_routes_near_example():
    r = SkillRouter()
    emb = _FakeEmbed()
    r.set_embedder(emb)
    # Isolate the semantic layer (keywords intentionally bypassed): the
    # embedder matches a doc example "概括 README 内容" via shared CJK tokens
    # "README"/"内容" present in NO keyword regex.
    hit = r._semantic_skill("概括一下 README 里的内容")
    assert hit is not None and hit[0] == "doc", hit
    assert hit[1] >= 0.55


def test_router_semantic_low_similarity_stays_default():
    r = SkillRouter()
    r.set_embedder(_FakeEmbed())
    # text sharing NO token with any example -> similarity ~0 -> default
    d = r.route("zzzz qqqqq wwwww eeee rrrr tttt yyyy")
    assert d.skill == "agent"


def test_router_explicit_tag_beats_semantic():
    r = SkillRouter()
    r.set_embedder(_FakeEmbed())
    d = r.route("随便什么", task_tag="doc")
    assert d.skill == "doc"
    assert d.reason.startswith("explicit")


def test_router_broken_embedder_falls_back_cleanly():
    r = SkillRouter()

    def bad(texts):
        raise RuntimeError("embedder down")

    r.set_embedder(bad)  # set_embedder swallows the failure
    assert r._embed_fn is None
    d = r.route("帮我审一下这个仓库")
    assert d.skill in ("agent", "security")  # never crashes
