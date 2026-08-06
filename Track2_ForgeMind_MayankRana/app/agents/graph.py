"""
ForgeMind Agents - State and LangGraph Swarm
5 Agents: Planner, Coder, Tester, Reviewer, DocWriter
All local on ROCm
"""
from typing import TypedDict, List, Dict, Annotated
from langgraph.graph import StateGraph, END
import time

# Try import langgraph, fallback to simple orchestration if not available
try:
    from langgraph.graph.message import add_messages
    LANGGRAPH_AVAILABLE = True
except:
    LANGGRAPH_AVAILABLE = False

class AgentState(TypedDict):
    task: str
    workspace: str
    plan: str
    files_changed: List[str]
    code_context: str
    test_result: str
    review_feedback: str
    docs: str
    iteration: int
    messages: List[Dict]
    status: str  # planning, coding, testing, reviewing, done, error

# Import local modules
from app.models.llm_rocm import get_llm
from app.tools import file_tools
from app.tools.rag_tool import get_rag

def planner_node(state: AgentState) -> AgentState:
    print("[Agent] Planner thinking...")
    llm = get_llm()
    rag = get_rag(state["workspace"])
    file_tools.set_workspace(state["workspace"])
    
    tree = file_tools.file_tree()
    rag_context = rag.query(state["task"], k=5)
    
    prompt = f"""
You are the Planner Agent. You run on AMD Radeon GPU locally.

Task: {state['task']}
Workspace file tree:
{tree}

Relevant code context from RAG:
{rag_context}

Create a detailed step-by-step execution plan (5-7 steps). Each step should be actionable: file to edit, function to create, test to write.
Be concise but technical.
"""
    plan = llm.generate(prompt, system="You are a senior architect planning tasks for a local dev swarm. Output only the plan.")
    state["plan"] = plan
    state["messages"].append({"agent": "planner", "content": plan, "time": time.time()})
    state["status"] = "coding"
    return state

def coder_node(state: AgentState) -> AgentState:
    print("[Agent] Coder implementing...")
    llm = get_llm()
    file_tools.set_workspace(state["workspace"])
    rag = get_rag(state["workspace"])
    
    context = rag.query(state["plan"], k=8)
    
    # Try to read main files to give context
    main_files = ["app.py", "main.py", "auth.py", "app/auth.py"]
    existing = ""
    for f in main_files:
        content = file_tools.read_file(f)
        if "not found" not in content.lower():
            existing += f"\n--- {f} ---\n{content[:2000]}"

    prompt = f"""
You are the Coder Agent running on AMD Radeon + ROCm. You write production-ready code.

Task: {state['task']}
Plan: {state['plan']}

Relevant codebase:
{context}
{existing}

Instructions:
- Write complete, working code
- If file needs creation, output full file with path: FILE: path/to/file.py
- If edit, output diff or full file
- Use best practices, error handling
- For auth: use JWT, bcrypt
- Keep it local, no external API calls

Output format:
FILE: filename
```language
code
```
"""
    code_output = llm.generate(prompt, system="You are an expert Python coder. Output code files with FILE: prefix.", max_tokens=3000)
    
    # Parse and write files
    import re
    files_written = []
    # Regex for FILE: pattern
    pattern = r"FILE:\s*([^\n]+)\n```(?:\w+)?\n(.*?)```"
    matches = re.findall(pattern, code_output, re.DOTALL)
    if matches:
        for path, code in matches:
            path = path.strip()
            result = file_tools.write_file(path, code.strip())
            files_written.append(f"{path}: {result}")
    else:
        # Fallback: try to extract single python block and save to suggested file
        code_blocks = re.findall(r"```(?:python)?\n(.*?)```", code_output, re.DOTALL)
        if code_blocks:
            # Heuristic: save to auth.py or main file
            target = "app/auth.py" if "jwt" in state["task"].lower() or "auth" in state["task"].lower() else "app/generated.py"
            result = file_tools.write_file(target, code_blocks[0].strip())
            files_written.append(f"{target}: {result}")
    
    state["files_changed"].extend(files_written)
    state["code_context"] = code_output[:5000]
    state["messages"].append({"agent": "coder", "content": f"Wrote {len(files_written)} files\n" + code_output[:2000], "time": time.time()})
    state["status"] = "testing"
    state["iteration"] += 1
    return state

def tester_node(state: AgentState) -> AgentState:
    print("[Agent] Tester running...")
    file_tools.set_workspace(state["workspace"])
    llm = get_llm()
    
    # Generate test if needed
    test_prompt = f"""
Task: {state['task']}
Code written: {state['code_context'][:2000]}
Files changed: {state['files_changed']}

Write a pytest file to test the new functionality. Save to tests/test_forgemind.py
Cover edge cases. Output as FILE: tests/test_forgemind.py
"""
    if state["iteration"] == 1:  # Only generate tests first iteration
        test_code = llm.generate(test_prompt, system="You are a QA engineer writing pytest tests.")
        import re
        pattern = r"FILE:\s*([^\n]+)\n```(?:\w+)?\n(.*?)```"
        matches = re.findall(pattern, test_code, re.DOTALL)
        for path, code in matches:
            file_tools.write_file(path.strip(), code.strip())
        # Also try raw block
        if not matches:
            blocks = re.findall(r"```(?:python)?\n(.*?)```", test_code, re.DOTALL)
            if blocks:
                file_tools.write_file("tests/test_forgemind.py", blocks[0])

    # Run tests
    test_result = file_tools.run_terminal("python -m pytest tests/ -v --tb=short 2>&1 || python -m pytest -v 2>&1 || pytest -v 2>&1", timeout=60)
    state["test_result"] = test_result
    state["messages"].append({"agent": "tester", "content": test_result[:3000], "time": time.time()})

    # Decision: if tests fail and iteration <3, loop back to coder
    if ("failed" in test_result.lower() or "error" in test_result.lower()) and state["iteration"] < 3 and "passed" not in test_result.lower():
        state["status"] = "coding"  # retry
        # Add failure context for coder
        state["code_context"] += f"\n\nTEST FAILURE TO FIX:\n{test_result[:2000]}"
    else:
        state["status"] = "reviewing"
    return state

def reviewer_node(state: AgentState) -> AgentState:
    print("[Agent] Reviewer checking...")
    llm = get_llm()
    file_tools.set_workspace(state["workspace"])
    
    # Gather changed files content
    changed_content = ""
    for entry in state["files_changed"][-3:]:
        fname = entry.split(":")[0]
        changed_content += f"\n--- {fname} ---\n{file_tools.read_file(fname)[:1500]}"

    prompt = f"""
Review this code for security, quality, and task completion.

Task: {state['task']}
Plan: {state['plan']}
Test Result: {state['test_result'][:1500]}

Code:
{changed_content}

Check:
1. Does it fulfill the task?
2. Security issues (JWT secret handling, injection)
3. Code quality

Output: APPROVED or NEEDS_FIX: <reasons>
"""
    feedback = llm.generate(prompt, system="You are a senior code reviewer. Be strict but concise.")
    state["review_feedback"] = feedback
    state["messages"].append({"agent": "reviewer", "content": feedback, "time": time.time()})
    
    if "NEEDS_FIX" in feedback and state["iteration"] < 3:
        state["status"] = "coding"
        state["code_context"] += f"\n\nREVIEW FEEDBACK TO FIX:\n{feedback}"
    else:
        state["status"] = "documenting"
    return state

def doc_writer_node(state: AgentState) -> AgentState:
    print("[Agent] DocWriter...")
    llm = get_llm()
    prompt = f"""
Task: {state['task']}
Plan: {state['plan']}
Files changed: {state['files_changed']}
Test result: {state['test_result'][:500]}

Write a short summary for README/Changelog:
- What was built
- How to use
- Files changed
Keep under 300 words.
"""
    docs = llm.generate(prompt, system="You are a technical writer.")
    state["docs"] = docs
    state["messages"].append({"agent": "doc_writer", "content": docs, "time": time.time()})
    state["status"] = "done"
    return state

def build_graph():
    """Build LangGraph swarm"""
    workflow = StateGraph(AgentState)
    
    workflow.add_node("planner", planner_node)
    workflow.add_node("coder", coder_node)
    workflow.add_node("tester", tester_node)
    workflow.add_node("reviewer", reviewer_node)
    workflow.add_node("doc_writer", doc_writer_node)

    workflow.set_entry_point("planner")
    workflow.add_edge("planner", "coder")
    
    # Conditional edges handled inside nodes via status
    def route(state: AgentState):
        s = state["status"]
        if s == "coding":
            return "coder"
        elif s == "testing":
            return "tester"
        elif s == "reviewing":
            return "reviewer"
        elif s == "documenting":
            return "doc_writer"
        else:
            return "doc_writer"

    workflow.add_conditional_edges("coder", route, {"coder": "coder", "testing": "tester", "reviewing": "reviewer", "doc_writer": "doc_writer"})
    workflow.add_conditional_edges("tester", route, {"coder": "coder", "reviewing": "reviewer", "doc_writer": "doc_writer"})
    workflow.add_conditional_edges("reviewer", route, {"coder": "coder", "doc_writer": "doc_writer"})
    workflow.add_edge("doc_writer", END)

    return workflow.compile()

# Fallback simple loop if LangGraph not available
def run_swarm_simple(task: str, workspace: str):
    state: AgentState = {
        "task": task,
        "workspace": workspace,
        "plan": "",
        "files_changed": [],
        "code_context": "",
        "test_result": "",
        "review_feedback": "",
        "docs": "",
        "iteration": 0,
        "messages": [],
        "status": "planning"
    }
    state = planner_node(state)
    while state["status"] != "done" and state["iteration"] < 4:
        if state["status"] == "coding":
            state = coder_node(state)
        elif state["status"] == "testing":
            state = tester_node(state)
        elif state["status"] == "reviewing":
            state = reviewer_node(state)
        elif state["status"] == "documenting":
            state = doc_writer_node(state)
        else:
            break
    if state["status"] != "done":
        state = doc_writer_node(state)
    return state
