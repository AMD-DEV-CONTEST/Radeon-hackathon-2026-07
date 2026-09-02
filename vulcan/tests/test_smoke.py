import json
from pathlib import Path

from vulcan import bench, rag, tools
from vulcan.config import Config
from vulcan.llm import ChatResult


def test_read_file_blocks_escape(tmp_path: Path):
    assert "escapes" in tools.read_file(tmp_path, "../secrets.txt")


def test_run_cmd_allowlist(tmp_path: Path):
    assert "not in allowlist" in tools.run_cmd(tmp_path, "rm -rf /")


def test_write_and_read_roundtrip(tmp_path: Path):
    tools.write_file(tmp_path, "a/b.txt", "hello")
    assert "hello" in tools.read_file(tmp_path, "a/b.txt")


def test_grep(tmp_path: Path):
    (tmp_path / "x.py").write_text("needle = 1\n")
    assert "x.py:1" in tools.grep(tmp_path, "needle")


class _StubLLM:
    """Returns a fixed-size streamed response without touching a backend."""

    def __init__(self, cfg):
        self.cfg = cfg

    def chat(self, messages, stream=False):
        return ChatResult(text="x", prompt_tokens=0, completion_tokens=10, ttft_s=0.1, total_s=1.1)


def test_run_concurrency_schema(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(bench, "LLM", _StubLLM)
    out = bench.run_concurrency(Config(), "t", levels=(1, 2), out_dir=tmp_path)
    assert set(out["runs"]) == {"concurrency_1", "concurrency_2"}
    two = out["runs"]["concurrency_2"]
    assert two["requests"] == 2
    # 2 requests x 10 chunks, so aggregate must exceed per-request
    assert two["aggregate_chunks_per_s"] > two["per_request_chunks_per_s"]
    assert json.loads((tmp_path / "t.json").read_text())["axis"] == "concurrency"


def test_run_prefill_schema(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(bench, "LLM", _StubLLM)
    out = bench.run_prefill(Config(), "p", word_counts=(8, 16), out_dir=tmp_path)
    assert set(out["runs"]) == {"prefill_8w", "prefill_16w"}
    assert out["runs"]["prefill_8w"]["input_words"] == 8
    assert json.loads((tmp_path / "p.json").read_text())["axis"] == "prefill"


def test_venv_dirs_detects_oddly_named_env(tmp_path: Path):
    odd = tmp_path / ".myenv"
    (odd / "lib").mkdir(parents=True)
    (odd / "pyvenv.cfg").write_text("home = /usr/bin\n")
    (tmp_path / "src").mkdir()
    assert rag._venv_dirs(tmp_path) == {odd}


def test_build_indexes_source_and_not_its_own_output(tmp_path: Path, monkeypatch):
    """Benchmark JSON outranked real code until it stopped being indexed as code."""
    root = tmp_path / "repo"
    (root / "bench-results").mkdir(parents=True)
    (root / ".pytest_cache").mkdir()
    (root / "privacy.py").write_text("def record_hosts(): ...\n")
    (root / "package.json").write_text('{"name": "x"}\n')
    (root / "bench-results" / "decode.json").write_text('{"ttft": 0.3}\n')
    (root / ".pytest_cache" / "README.md").write_text("cache\n")

    cfg = Config(data_dir=tmp_path / "data")
    idx = rag.Index(cfg, _ScriptedLLM([]), "t")
    seen: list[str] = []
    monkeypatch.setattr(idx, "_flush", lambda texts, meta: seen.extend(m[0] for m in meta) or len(meta))
    idx.build(root)

    assert sorted(seen) == ["package.json", "privacy.py"]


def test_bench_compare(tmp_path: Path):
    base = {"label": "laptop", "runs": {
        "short": {"ttft_s_median": 1.0, "chunks_per_s_median": 20.0},
        "medium": {"ttft_s_median": 1.5, "chunks_per_s_median": 18.0},
        "long": {"ttft_s_median": 2.0, "chunks_per_s_median": 15.0}}}
    cand = {"label": "radeon", "runs": {
        "short": {"ttft_s_median": 0.25, "chunks_per_s_median": 60.0},
        "medium": {"ttft_s_median": 0.4, "chunks_per_s_median": 54.0}}}
    b, c = tmp_path / "b.json", tmp_path / "c.json"
    b.write_text(json.dumps(base))
    c.write_text(json.dumps(cand))
    out = bench.compare(b, c)
    assert "3.00x" in out
    assert out.count("|") > 10
    assert "n/a" in out


class _ScriptedLLM:
    """Replays a fixed list of replies, so the agent loop is testable offline."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def chat(self, messages, stream=False):
        self.seen.append(messages[-1]["content"])
        return ChatResult(text=self.replies.pop(0), prompt_tokens=0,
                          completion_tokens=0, ttft_s=None, total_s=0.0)

    def embed(self, texts):
        return [[0.0, 1.0] for _ in texts]


def _agent(tmp_path: Path, replies, monkeypatch):
    from vulcan import agent as agent_mod
    monkeypatch.setattr(agent_mod, "LLM", lambda cfg: _ScriptedLLM(replies))
    cfg = Config(data_dir=tmp_path / "data")
    a = agent_mod.Agent(cfg, tmp_path, "t")
    return a


def test_thought_only_reply_is_not_dispatched_as_a_tool(tmp_path: Path, monkeypatch):
    """It used to become tool "" -> ERROR: unknown tool, and the agent then
    told the user all its tools were unavailable."""
    a = _agent(tmp_path, ['{"thought": "thinking"}',
                          '{"thought": "ok", "final": "done"}'], monkeypatch)
    assert a.run("q") == "done"
    assert not any("unknown tool" in m for m in a.llm.seen)


def test_search_observation_is_bounded(tmp_path: Path, monkeypatch):
    """One unbounded search observation could exceed the whole context."""
    from vulcan import agent as agent_mod
    a = _agent(tmp_path, ['{"thought": "x", "final": "y"}'], monkeypatch)
    monkeypatch.setattr(a.index, "search", lambda q, k=6: [
        {"path": f"f{i}.py", "start": 1, "end": 60, "text": "x" * 20000, "score": 0.5}
        for i in range(6)
    ])
    obs = a._dispatch("search_code", {"query": "anything"})
    assert len(obs) < agent_mod.SEARCH_HITS * (agent_mod.SEARCH_HIT_CHARS + 200)
    assert obs.count("truncated") == agent_mod.SEARCH_HITS


def test_lexical_signal_lifts_the_matching_path(tmp_path: Path, monkeypatch):
    """Dense scores bunch together; the path term is what separates them."""
    cfg = Config(data_dir=tmp_path / "data")
    idx = rag.Index(cfg, _ScriptedLLM([]), "t")
    rows = [("vulcan/rag.py", 1, 60, "def search(): ..."),
            ("vulcan/cli.py", 1, 60, "import typer")]
    lex = idx._lexical("which module implements the rag index", rows)
    assert lex[0] > lex[1]


def test_chat_carries_context_between_turns(tmp_path: Path, monkeypatch):
    """`chat` was multi-turn in name only: turn 2 started from an empty
    conversation, so a follow-up had no referent."""
    a = _agent(tmp_path, ['{"thought":"t","final":"A1"}',
                          '{"thought":"t","final":"A2"}'], monkeypatch)
    a.run("first question")
    a.run("second question")
    turn2 = a.llm.seen[-1]
    assert a.history, "the exchange was recorded"
    assert any("first question" in m["content"] for m in a.history)
    assert any("A1" in m["content"] for m in a.history)


def test_history_is_bounded(tmp_path: Path, monkeypatch):
    """An unbounded history is the context overflow again, just slower."""
    from vulcan import agent as agent_mod
    a = _agent(tmp_path, ['{"thought":"t","final":"%s"}' % ("y" * 3000)] * 6, monkeypatch)
    for i in range(6):
        a.run(f"question {i} " + "x" * 500)
    assert sum(len(m["content"]) for m in a.history) <= agent_mod.HISTORY_CHARS + 4000
    assert len(a.history) >= 2


def test_privacy_check_detects_a_third_party_call(monkeypatch):
    """A check that cannot fail proves nothing. Make it fail on purpose."""
    import httpx
    from vulcan import privacy

    # Never actually leave the machine: the transport is faked, but the request
    # still travels the same httpx.Client.send path the hook watches.
    def fake_send(self, request, **kwargs):
        return httpx.Response(200, request=request)

    monkeypatch.setattr(httpx.Client, "send", fake_send, raising=True)
    cfg = Config(base_url="http://localhost:11434/v1")

    with privacy.record_hosts() as hosts:
        with httpx.Client() as c:
            c.get("http://localhost:11434/v1/models")
            c.get("https://api.openai.com/v1/models")

    r = privacy.check(cfg, hosts)
    assert r["requests"] == 2
    assert "api.openai.com" in r["unexpected"]
    assert not r["private"]


def test_privacy_check_passes_when_only_configured_hosts_are_used(monkeypatch):
    import httpx
    from vulcan import privacy

    monkeypatch.setattr(httpx.Client, "send",
                        lambda self, request, **kw: httpx.Response(200, request=request))
    cfg = Config(base_url="http://localhost:11434/v1",
                 embed_base_url="http://localhost:11434/v1")
    with privacy.record_hosts() as hosts:
        with httpx.Client() as c:
            c.get("http://localhost:11434/v1/models")
    r = privacy.check(cfg, hosts)
    assert r["private"] and not r["unexpected"]


def test_bench_results_never_carry_the_instance_id():
    """The id is the credential: the tunnel takes none. It reached a public
    repo once by being serialised verbatim into a committed result file."""
    from vulcan.privacy import mask_endpoint
    # A synthetic id on purpose: a test that hardcodes the real one puts it
    # back in the repository, which is the leak this test exists to prevent.
    url = "https://radeon-global.anruicloud.com/spaces/u-0000-testfixture/8000/v1"
    masked = mask_endpoint(url)
    assert "testfixture" not in masked
    assert masked.endswith("/spaces/<instance>/8000/v1")
    assert mask_endpoint("http://localhost:11434/v1") == "http://localhost:11434/v1"


def test_no_committed_bench_result_leaks_an_instance_id():
    import json, re
    from pathlib import Path
    for f in Path("bench-results").glob("*.json"):
        assert not re.search(r"/spaces/u-[0-9a-z]{3,}-", f.read_text()), f
