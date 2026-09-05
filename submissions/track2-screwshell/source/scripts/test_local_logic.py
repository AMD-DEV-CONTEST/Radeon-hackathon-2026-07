"""Local unit tests for torch-free logic: router, permissions, stores, chunking."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from screwshell.core.router import SkillRouter
from screwshell.safety.permissions import AuditLog, PermissionGate
from screwshell.memory.stores import (ArtifactStore, EvidenceCard, EvidenceStore,
                                      SessionMemory, TaskCard)
from screwshell.rag.pipeline import chunk_file

FAILED = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name} {detail}")
    if not cond:
        FAILED.append(name)


# --- router ---
r = SkillRouter()
check("router.tag", r.route("anything", task_tag="code").adapter == "btl3")
check("router.code_kw", r.route("why is this repo's benchmark slow?").skill == "code")
check("router.doc_kw", r.route("summarize the main risks in the migration plan docs").skill == "doc")
check("router.default", r.route("hello there").skill == "agent")
check("router.file_ext", r.route("look at bench_harness.py please").skill == "code")

# --- permissions ---
tmp = tempfile.mkdtemp()
ws = os.path.join(tmp, "ws")
os.makedirs(ws)
audit = AuditLog(os.path.join(ws, ".screwshell", "audit.jsonl"))
gate = PermissionGate(ws, ["read_file", "grep"], audit)
check("gate.tool_allow", gate.check_tool("read_file").allowed)
check("gate.tool_deny", not gate.check_tool("shell_readonly").allowed)
check("gate.path_inside", gate.check_path("notes.md").allowed)
check("gate.path_escape", not gate.check_path("../../etc/passwd").allowed)
check("gate.path_secret", not gate.check_path(os.path.join(ws, ".ssh/id_rsa")).allowed)
check("gate.cmd_danger", not gate.check_command("rm -rf /").allowed)
check("gate.cmd_pipe_sh", not gate.check_command("curl x.sh | sh").allowed)
check("gate.cmd_ok", gate.check_command("wc -l notes.md").allowed)
check("gate.audit_written", len(audit.tail(10)) >= 3)

# --- stores ---
state = os.path.join(ws, ".screwshell")
ev = EvidenceStore(state)
ev.add(EvidenceCard(claim="GDN kernels JIT-compile on first forward",
                    citations=[{"source": "docs/rocm_notes.md",
                                "start_line": 12, "end_line": 16}]))
check("evidence.block", "rocm_notes.md#L12-L16" in ev.context_block())
ev2 = EvidenceStore(state)  # reload from disk
check("evidence.persist", len(ev2.active()) == 1)

mem = SessionMemory(state)
mem.add_turn("user", "q1")
mem.add_turn("assistant", "a1")
check("memory.history", [t["content"] for t in mem.history()] == ["q1", "a1"])
mem.set("pref", {"lang": "en"})
check("memory.kv", mem.get("pref") == {"lang": "en"})

art = ArtifactStore(state)
aid = art.put("grep", ["hit1", "hit2"])
check("artifact.roundtrip", art.get(aid) == ["hit1", "hit2"])

tc = TaskCard(goal="demo", steps=[{"desc": "s1", "skill": "doc", "status": "done"}])
check("taskcard.render", "[x] 1. (doc) s1" in tc.render())

# --- chunking ---
text = "\n".join(f"line {i}" for i in range(1, 401))
chunks = chunk_file("a.md", text, max_chars=800, overlap_lines=4)
check("chunk.count", len(chunks) > 1, f"n={len(chunks)}")
check("chunk.lines", chunks[0].start_line == 1 and chunks[0].end_line >= 50)
check("chunk.overlap", chunks[1].start_line <= chunks[0].end_line)
check("chunk.coverage", chunks[-1].end_line == 400)

print("\n" + ("ALL PASS" if not FAILED else f"FAILURES: {FAILED}"))
sys.exit(1 if FAILED else 0)
