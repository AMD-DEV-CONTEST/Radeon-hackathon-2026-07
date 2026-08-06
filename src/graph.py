# graph.py
from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
import os
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter


# Import the tools we built over the last 4 days
from main import (
    clone_repo, 
    explore_files, 
    build_repository_knowledge, 
    build_dependency_graph
)
import json
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

# Initialize the fast standard model for combinatorial routing and drafting
llm = ChatOpenAI(
    model="qwen2.5-coder", # Must match the exact name you pulled in Ollama
    api_key="ollama",      # LangChain requires a string here, but Ollama ignores it
    base_url="http://localhost:11434/v1", # Ollama's native OpenAI-compatible port
    temperature=0.1
)

# # Replace these with the exact values from your Radeon Cloud dialog
# RADEON_BASE_URL = "https://radeon-global.anruicloud.com/spaces/thatonesid/8000/v1"
# RADEON_API_KEY = "your-copied-api-key"

# llm = ChatOpenAI(
#     model="Qwen/Qwen2.5-Coder-7B-Instruct-AWQ",
#     base_url=RADEON_BASE_URL,
#     api_key=RADEON_API_KEY,
#     temperature=0.2, # Keep it low for coding accuracy
#     max_tokens=2000
# )

class AgentState(TypedDict):
    user_prompt: str
    github_url: str
    
    local_repo_path: Optional[str]
    relevant_files: Optional[List[str]]
    readme_content: Optional[str]
    
    # AST and Graph Data
    parsed_structure: Optional[Dict[str, Any]]
    dependency_graph: Optional[Dict[str, Any]]
    
    # --- NEW: Exploration Memory ---
    critical_nodes: Optional[Dict[str, List[str]]] # stores 'entry_points', 'god_classes', etc.
    subsystem_summaries: Optional[Dict[str, str]]  # stores notes taken after reading files
    
    final_answer: Optional[str]
    next_action: Optional[str]
    step_count: int
    # --- NEW: Reflection Variables ---
    critique: Optional[str]
    revision_count: int
    retrieved_context: Optional[str]  # NEW: Holds the RAG search results
    # --- NEW: ReAct Memory ---
    plan: Optional[str]
    observations: Optional[List[str]]


def planner_node(state: AgentState):
    """The ReAct Orchestrator: Plans, chooses tools, and acts."""
    print("[Router] Dynamic Planner evaluating state...")
    current_steps = state.get("step_count", 0)
    next_step_count = current_steps + 1
    
    # Circuit breaker bumped to 8 to allow for tool-use loops
    if current_steps > 8: 
        print(f"[Router] 🚨 ERROR: Infinite loop detected. Force quitting.")
        return {"next_action": "end", "step_count": next_step_count}
    
    # 1. Base Case: If we don't have the graph, we MUST clone first.
    if state.get("dependency_graph") is None:
        return {"next_action": "clone_repository", "step_count": next_step_count}
    
    prompt = state.get("user_prompt", "").strip()
    if not prompt:
        return {"next_action": "end", "step_count": next_step_count}
        
    # --- THE ReAct LLM ---
    observations = state.get("observations", [])
    obs_text = "\n- ".join(observations) if observations else "No actions taken yet."
    
    planner_prompt = (
        "You are an intelligent Orchestration Agent. Your job is to decide the next step to answer the user's request.\n\n"
        f"User Request: {prompt}\n"
        f"Past Observations: \n- {obs_text}\n\n"
        "Available Actions:\n"
        "1. RETRIEVE: Search the Vector DB for specific code snippets (Use this FIRST for specific questions).\n"
        "2. GENERATE: Synthesize the final answer (Use this if you already retrieved code in your Past Observations, OR if the user just wants a general 'Architecture overview').\n\n"
        "You must output a brief, step-by-step plan, followed by the exact action word.\n"
        "Format:\n"
        "PLAN:\n"
        "✓ Step 1...\n"
        "✓ Step 2...\n"
        "ACTION: [RETRIEVE or GENERATE]"
    )
    
    response = llm.invoke([
        SystemMessage(content="You are a strict routing AI. Follow the exact formatting rules."),
        HumanMessage(content=planner_prompt)
    ])
    
    # Parse the LLM's decision
    content = response.content
    if "ACTION: RETRIEVE" in content.upper():
        next_action = "retrieve_context"
    else:
        next_action = "generate_onboarding"
        
    return {"next_action": next_action, "plan": content, "step_count": next_step_count}


def clone_repo_node(state: AgentState):
    """Transition State 1: Download the codebase."""
    url = state["github_url"]
    # We call our Tool 1 from agent.py
    local_path = clone_repo(url)
    return {"local_repo_path": str(local_path)}

def explore_files_node(state: AgentState):
    """Transition State 2: Filter the noise."""
    from pathlib import Path
    repo_path = Path(state["local_repo_path"])
    # Call Tool 2
    files = explore_files(repo_path)
    return {"relevant_files": files}

def extract_readme_node(state: AgentState):
    """Transition State: Extract the original README for human context."""
    print("[Tool 2.5] Searching for original README...")
    from pathlib import Path
    
    repo_path = Path(state["local_repo_path"])
    relevant_files = state["relevant_files"]
    readme_text = None
    
    # Look for common README filenames
    for f in relevant_files:
        if f.lower() in ["readme.md", "readme.rst", "readme.txt", "readme"]:
            try:
                with open(repo_path / f, "r", encoding="utf-8") as file:
                    readme_text = file.read()
                print(f"[Tool 2.5] Successfully extracted {f}.")
                break # Stop searching once we find the main one
            except Exception as e:
                print(f"[Tool 2.5] Found {f} but failed to read: {e}")
                
    return {"readme_content": readme_text}

def parse_structure_node(state: AgentState):
    """Transition State 3: Extract the AST."""
    from pathlib import Path
    repo_path = Path(state["local_repo_path"])
    files = state["relevant_files"]
    # Call Tool 3
    repo_map = build_repository_knowledge(repo_path, files)
    return {"parsed_structure": repo_map}

def build_graph_node(state: AgentState):
    """Transition State 4: Build the adjacency list."""
    repo_map = state["parsed_structure"]
    files = state["relevant_files"]
    # Call Tool 4
    dep_graph = build_dependency_graph(repo_map, files)
    return {"dependency_graph": dep_graph}

def analyze_graph_node(state: AgentState):
    """Transition State: Find entry points, orchestrators, and core interfaces."""
    print("[Analyzer] Calculating graph centrality to find critical nodes...")
    dep_graph = state["dependency_graph"]
    
    # Calculate Out-Degree (Files importing others)
    out_degrees = {node: len(edges) for node, edges in dep_graph.items()}
    # Calculate In-Degree (Files being imported)
    in_degrees = {node: 0 for node in dep_graph.keys()}
    for node, edges in dep_graph.items():
        for edge in edges:
            if edge in in_degrees:
                in_degrees[edge] += 1
                
    # Sort to find the most important files
    orchestrators = sorted(out_degrees, key=out_degrees.get, reverse=True)[:3]
    core_interfaces = sorted(in_degrees, key=in_degrees.get, reverse=True)[:3]
    
    critical_nodes = {
        "orchestrators": orchestrators,
        "interfaces": core_interfaces
    }
    
    print(f"[Analyzer] Found Orchestrators: {orchestrators}")
    print(f"[Analyzer] Found Interfaces: {core_interfaces}")
    
    return {"critical_nodes": critical_nodes}

def explore_codebase_node(state: AgentState):
    """Transition State: Reads critical files and summarizes their purpose."""
    print("[Explorer] Reading critical files and summarizing subsystems...")
    from pathlib import Path
    
    repo_path = Path(state["local_repo_path"])
    critical_nodes = state["critical_nodes"]
    
    # Combine the lists of files we need to read
    files_to_read = set(critical_nodes["orchestrators"] + critical_nodes["interfaces"])
    summaries = {}
    
    for file_path in files_to_read:
        print(f"[Explorer] Reading and summarizing: {file_path}")
        try:
            with open(repo_path / file_path, "r", encoding="utf-8") as f:
                # We read the first 150 lines to avoid blowing up local LLM context limits
                code_content = "".join(f.readlines()[:150]) 
                
            prompt = (
                f"Analyze this raw code from {file_path}.\n"
                f"Write a dense, 3-sentence summary of what this specific subsystem does.\n\n"
                f"Code:\n{code_content}"
            )
            
            response = llm.invoke([
                SystemMessage(content="You are a senior developer analyzing a single file."),
                HumanMessage(content=prompt)
            ])
            summaries[file_path] = response.content
            
        except Exception as e:
            summaries[file_path] = f"Failed to read file: {e}"
            
    return {"subsystem_summaries": summaries}

# Initialize the local embedding model (downloads a small, fast model on first run)
# Remove the global initialization and replace it with this caching function
DB_PATH = "./chroma_db"
_embeddings_instance = None

def get_embeddings():
    """Lazy-loads the embedding model only when needed to prevent UI freezes."""
    global _embeddings_instance
    if _embeddings_instance is None:
        print("[RAG Engine] Booting up HuggingFace Embeddings...")
        _embeddings_instance = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    return _embeddings_instance

def build_vector_db_node(state: AgentState):
    """Ingestion Phase: Chunks and embeds the repository into a Vector DB."""
    repo_path = state.get("local_repo_path")
    
    print("\n[RAG Engine] Initializing Vector Database...")
    
    # Circuit Breaker: If DB exists, we already embedded this repo.
    if os.path.exists(DB_PATH):
        print("[RAG Engine] Vector DB already exists. Skipping ingestion.")
        return {}

    # 1. Load files (Filter for code and text)
    docs = []
    for root, _, files in os.walk(repo_path):
        for file in files:
            if file.endswith(('.cpp', '.h', '.py', '.js', '.ts', '.md')):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        docs.append(Document(page_content=f.read(), metadata={"source": file_path}))
                except:
                    pass # Skip unreadable binaries

    # 2. Chunk the code for the LLM's context window
    print(f"[RAG Engine] Chunking {len(docs)} files...")
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    chunks = splitter.split_documents(docs)

    # 3. Embed and store in Chroma
    print(f"[RAG Engine] Embedding {len(chunks)} chunks into Chroma...")
    Chroma.from_documents(documents=chunks, embedding=get_embeddings(), persist_directory=DB_PATH)
    
    print("[RAG Engine] ✅ Vector DB Built.")
    return {}

def retrieve_context_node(state: AgentState):
    """Retrieval Phase: Pulls relevant code snippets based on the user's prompt."""
    print("\n[RAG Engine] Searching Vector DB for relevant context...")
    
    if not os.path.exists(DB_PATH):
        print("[RAG Engine] No DB found.")
        obs = state.get("observations", [])
        obs.append("Failed to retrieve context: No Vector DB found.")
        return {"retrieved_context": "No specific code chunks found.", "observations": obs}

    # Load the DB and search
    db = Chroma(persist_directory=DB_PATH, embedding_function=get_embeddings())
    retriever = db.as_retriever(search_kwargs={"k": 5}) # Get the top 5 most relevant chunks
    
    results = retriever.invoke(state["user_prompt"])
    
    # Format the results into a string for the LLM
    context = "\n\n".join([f"--- Source: {doc.metadata['source']} ---\n{doc.page_content}" for doc in results])
    
    # --- Create an observation for the planner ---
    obs = state.get("observations", [])
    obs.append(f"Successfully retrieved {len(results)} relevant code snippets for context.")
    
    print("[RAG Engine] ✅ Relevant code chunks retrieved.")
    return {"retrieved_context": context, "observations": obs}

def onboarding_generator_node(state: AgentState):
    """Uses the ingested graph data and deep exploration notes to answer user prompts naturally."""
    print("[Tool 5] LLM drafting architectural response...")
    
    repo_map = state["parsed_structure"]
    dep_graph = state["dependency_graph"]
    
    # 1. DATA CAMOUFLAGE: Convert JSON to a flat, readable text format
    arch_text = ""
    for file_path, dependencies in dep_graph.items():
        arch_text += f"\nFile: {file_path}\n"
        classes = repo_map[file_path].get("classes", [])
        if classes:
            arch_text += f"  - Classes: {', '.join(classes)}\n"
        if dependencies:
            arch_text += f"  - Depends on {len(dependencies)} other files.\n"
            
    original_readme = state.get("readme_content") or "No README provided in this repository."
    
    summaries = state.get("subsystem_summaries", {})
    formatted_summaries = "\n".join([f"**{k}**:\n{v}" for k, v in summaries.items()])
    
    # --- UPGRADED SYSTEM PERSONA ---
    system_prompt = (
        "You are a Principal Software Engineer giving a whiteboard architecture breakdown to a talented new teammate. "
        "You speak naturally, prioritizing data flow, system design patterns, and 'the big picture'. "
        "NEVER output dry, dictionary-style lists of files and classes. Be engaging, insightful, and pedagogical."
    )
    
    critique = state.get("critique")
    critique_prompt = f"🚨 QA REJECTED PREVIOUS DRAFT. FEEDBACK:\n{critique}\n\nFIX THIS IMMEDIATELY.\n\n" if critique else ""
    
    # --- UPGRADED DYNAMIC INSTRUCTION LOGIC ---
    user_prompt_lower = state['user_prompt'].lower()
    is_general_analysis = "analyze" in user_prompt_lower or "onboard" in user_prompt_lower or "architecture" in user_prompt_lower

    if is_general_analysis:
        task_instructions = (
            f"CRITICAL INSTRUCTIONS:\n"
            f"Give a comprehensive, high-level architectural tour of this codebase. Structure your response naturally:\n\n"
            f"1. **The 10,000-Foot View:** A sharp summary of what this system is and its core design philosophy.\n"
            f"2. **The Heavy Lifters:** Identify the central orchestrators ('god' classes) and explain their purpose.\n"
            f"3. **The Execution Flow:** How do the main subsystems (found in the Deep Exploration Notes) talk to each other?\n"
            f"4. **Where to Start:** Name the top 3 critical files the developer should read first, and explain *why*.\n\n"
            f"Do not just list files. Tell the story of the architecture."
        )
    else:
        # --- FLIPPED THE ORDER HERE ---
        task_instructions = (
            f"CRITICAL INSTRUCTIONS:\n"
            f"Answer the user's specific question using a 'Deep-Dive to Summary' framework:\n\n"
            f"1. **The Core Mechanics:** Dive straight into the 2-3 most important classes/functions from the RAG snippets and explain *what* they do.\n"
            f"2. **The Architecture Flow:** Explain how these components interact in practice (e.g., 'When an asset is packed, X calls Y to serialize Z').\n"
            f"3. **The TL;DR:** Conclude with a concise, high-level summary at the absolute bottom wrapping up the core answer.\n\n"
            f"STRICT RULE: DO NOT output a dry list of file paths, dependencies, or generic class definitions. "
            f"Synthesize the RAG snippets into a cohesive, readable technical explanation."
        )

    rag_context = state.get("retrieved_context", "No specific code chunks retrieved.")
    human_prompt = (
        f"{critique_prompt}"
        f"User Request: {state['user_prompt']}\n\n"
        f"--- RELEVANT CODE SNIPPETS (RAG) ---\n{rag_context}\n\n"
        f"--- ORIGINAL AUTHOR README ---\n{original_readme}\n\n"
        f"--- DEEP EXPLORATION NOTES ---\n{formatted_summaries}\n\n"
        f"--- RAW DEPENDENCY DATA (For reference only, DO NOT blindly list these) ---\n{arch_text}\n\n"
        f"{task_instructions}"
    )
    
    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ])
    
    return {"final_answer": response.content}

def reflection_node(state: AgentState):
    """Transition State: QA Reviewer that grades the generated guide."""
    draft = state.get("final_answer", "")
    revisions = state.get("revision_count", 0)
    
    # --- DYNAMIC QA LOGIC ---
    user_prompt_lower = state.get("user_prompt", "").lower()
    is_general_analysis = "analyze" in user_prompt_lower or "onboard" in user_prompt_lower or "architecture" in user_prompt_lower

    if not is_general_analysis:
        print("\n[QA Reviewer] Specific question detected. Skipping strict format checks.")
        return {"next_action": "end", "critique": None}

    print("\n[QA Reviewer] Inspecting generated guide for compliance...")
    
    # Circuit Breaker: Max 3 rewrites
    if revisions >= 3:
        print("[QA Reviewer] Max revisions reached. Accepting current draft.")
        return {"next_action": "end"}
        
    # --- BULLETPROOF GRADING RUBRIC ---
    # We convert the draft to lowercase to ignore Markdown formatting issues (bolding, headers, etc.)
    draft_lower = draft.lower()
    missing_sections = []
    
    if "10,000-foot view" not in draft_lower and "10,000 foot view" not in draft_lower: 
        missing_sections.append("1. **The 10,000-Foot View:**")
    if "heavy lifters" not in draft_lower: 
        missing_sections.append("2. **The Heavy Lifters:**")
    if "execution flow" not in draft_lower: 
        missing_sections.append("3. **The Execution Flow:**")
    if "where to start" not in draft_lower: 
        missing_sections.append("4. **Where to Start:**")
    
    if missing_sections:
        critique = (
            f"Your draft FAILED QA. You must include sections covering these exact topics: "
            f"{', '.join(missing_sections)}. Please rewrite and use clear headers."
        )
        print(f"[QA Reviewer] ❌ Draft failed. Missing: {missing_sections}. Routing back to Generator.")
        return {
            "critique": critique, 
            "next_action": "generate_onboarding", 
            "revision_count": revisions + 1
        }
        
    print("[QA Reviewer] ✅ Draft passed! All sections present. Finishing execution.")
    return {"next_action": "end", "critique": None}

# 1. Initialize
workflow = StateGraph(AgentState)

# 2. Register Nodes
workflow.add_node("planner_llm", planner_node)
workflow.add_node("clone_repo", clone_repo_node)
workflow.add_node("explore_files", explore_files_node)
workflow.add_node("extract_readme", extract_readme_node)
workflow.add_node("parse_structure", parse_structure_node)
workflow.add_node("build_dependency_graph", build_graph_node)
workflow.add_node("analyze_graph", analyze_graph_node)
workflow.add_node("explore_codebase", explore_codebase_node)
workflow.add_node("onboarding_generator", onboarding_generator_node)

# --- NEW: Register the QA & RAG Nodes ---
workflow.add_node("reflection", reflection_node)
workflow.add_node("build_vector_db", build_vector_db_node)
workflow.add_node("retrieve_context", retrieve_context_node)


def route_next_action(state: AgentState):
    return state["next_action"]

# 3. Define the Edges
workflow.add_edge(START, "planner_llm")

workflow.add_conditional_edges(
    "planner_llm",
    route_next_action,
    {
        "clone_repository": "clone_repo",
        "retrieve_context": "retrieve_context",          # <--- NEW: Map the RETRIEVE action
        "generate_onboarding": "onboarding_generator",   # <--- UPDATED: Map the GENERATE action
        "end": END
    }
)

# The Deep Extraction & Vectorization Pipeline
workflow.add_edge("clone_repo", "build_vector_db")     # NEW: Chunk and embed the code after cloning
workflow.add_edge("build_vector_db", "explore_files")  # NEW: Continue original pipeline
workflow.add_edge("explore_files", "extract_readme")
workflow.add_edge("extract_readme", "parse_structure")
workflow.add_edge("parse_structure", "build_dependency_graph")

# The Exploration Loop
workflow.add_edge("build_dependency_graph", "analyze_graph")
workflow.add_edge("analyze_graph", "explore_codebase")
workflow.add_edge("explore_codebase", "planner_llm") # Return to planner to trigger generation

# --- RAG Retrieval Pipeline ---
# After RAG retrieves context, feed it to the generator
workflow.add_edge("retrieve_context", "planner_llm") # <--- Loops back to Planner!

# --- The Reflection (QA) Loop ---
# Route the drafted text to the QA Reviewer instead of END
workflow.add_edge("onboarding_generator", "reflection")

# The QA Reviewer decides if we go back to the Generator for a rewrite, or if we are DONE
workflow.add_conditional_edges(
    "reflection",
    route_next_action,
    {
        "generate_onboarding": "onboarding_generator", 
        "end": END
    }
)

# Initialize the memory checkpointer
memory = MemorySaver()

# Compile the graph with true multi-turn memory attached
app = workflow.compile(checkpointer=memory)
if __name__ == "__main__":
    print("--- Booting AI Agent Loop ---")
    
    initial_state = {
        "github_url": "https://github.com/amzeratul/halley", 
        "user_prompt": "Generate an onboarding guide and architecture map for this codebase.", 
        "local_repo_path": None,
        "relevant_files": None,
        "readme_content": None,
        "parsed_structure": None,
        "dependency_graph": None,
        "critical_nodes": None,
        "subsystem_summaries": None,
        "final_answer": None,
        "next_action": None,
        "step_count": 0,
        "critique": None,
        "revision_count": 0
    }
    
    # Track the generated answer across the stream
    captured_answer = None 
    
    for event in app.stream(initial_state):
        for node_name, state_update in event.items():
            print(f"\n[Transition] Exiting node: {node_name}")
            
            # If a node updates the final answer, capture it!
            if "final_answer" in state_update and state_update["final_answer"] is not None:
                captured_answer = state_update["final_answer"]
            
            # Print the QA Reviewer's critique if it failed
            if node_name == "reflection" and state_update.get("critique"):
                print(f"⚠️ REVISION REQUIRED:\n{state_update['critique']}")
            
    print("\n" + "="*50)
    print("FINAL ARCHITECTURE & ONBOARDING GUIDE:")
    print("="*50)
    
    if captured_answer:
        print(captured_answer)
    else:
        print("Error: No answer was generated.")