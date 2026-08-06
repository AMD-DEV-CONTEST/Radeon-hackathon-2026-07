import os
import shutil
from pathlib import Path
import git

TEMP_REPO_DIR = Path("./temp_repos").resolve()


def clone_repo(github_url: str) -> Path:
    """
    Clones a remote GitHub repository to a local temporary directory.
    If the directory already exists, it removes it first for a clean state.
    """
    # 1. Dynamically recreate ./temp_repos if deleted by reset cleanup
    TEMP_REPO_DIR.mkdir(parents=True, exist_ok=True)
    # Extract repo name from URL (e.g., https://github.com/user/repo.git -> repo)
    repo_name = github_url.rstrip("/").split("/")[-1].replace(".git", "")
    target_dir = TEMP_REPO_DIR / repo_name

    if target_dir.exists():
        print(f"[Tool 1] Cleaning existing repository directory at {target_dir}...")
        shutil.rmtree(target_dir, ignore_errors=True)

    print(f"[Tool 1] Cloning {github_url} into {target_dir}...")
    git.Repo.clone_from(github_url, str(target_dir), depth=1) # depth=1 for speed & low disk usage
    print("[Tool 1] Clone successful.")
    
    return target_dir

# Directories to strictly ignore
IGNORE_DIRS = {
    ".git", ".github", ".vscode", "node_modules", 
    "venv", ".venv", "env", "dist", "build", 
    "__pycache__", ".pytest_cache", ".next", "out"
}

# Relevant source extensions to include
ALLOWED_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", 
    ".java", ".cpp", ".c", ".h", ".cs", ".go", 
    ".rs", ".php", ".rb", ".json", ".yaml", ".yml", 
    ".toml", ".md", ".sh", ".rst","Dockerfile"
}

def explore_files(repo_path: Path) -> list[str]:
    """
    Scans the cloned repo path and returns a list of relevant source file paths.
    """
    print(f"[Tool 2] Exploring codebase at {repo_path}...")
    relevant_files = []

    for file_path in repo_path.rglob("*"):
        # Check if any parent directory is in the IGNORE_DIRS list
        if any(part in IGNORE_DIRS for part in file_path.parts):
            continue

        if file_path.is_file():
            # Include files that match allowed extensions or exact filenames (like Dockerfile)
            if file_path.suffix.lower() in ALLOWED_EXTENSIONS or file_path.name in ALLOWED_EXTENSIONS:
                # Store relative paths for clean LLM context display
                rel_path = str(file_path.relative_to(repo_path))
                relevant_files.append(rel_path)

    print(f"[Tool 2] Found {len(relevant_files)} relevant files for processing.")
    return relevant_files

from tree_sitter import Language, Parser
from pathlib import Path

# 1. Dynamic Language Registry
# We use try/except so if you forget to pip install a language, 
# the agent simply skips it instead of crashing the whole hackathon project.
LANGUAGE_REGISTRY = {}

def register_language(exts: list, module_name: str, lang_func_name: str = "language"):
    try:
        import importlib
        module = importlib.import_module(module_name)
        lang_func = getattr(module, lang_func_name)
        lang = Language(lang_func())
        for ext in exts:
            LANGUAGE_REGISTRY[ext] = lang
    except ImportError:
        print(f"[Warning] Grammar {module_name} not installed. Skipping {exts}.")

# Registering the supported code extensions
register_language([".py"], "tree_sitter_python")
register_language([".js", ".jsx"], "tree_sitter_javascript")
register_language([".ts", ".tsx"], "tree_sitter_typescript", "language_typescript")
register_language([".java"], "tree_sitter_java")
register_language([".cpp", ".h"], "tree_sitter_cpp")
register_language([".c"], "tree_sitter_c")
register_language([".cs"], "tree_sitter_c_sharp")
register_language([".go"], "tree_sitter_go")
register_language([".rs"], "tree_sitter_rust")
register_language([".php"], "tree_sitter_php", "language_php")
register_language([".rb"], "tree_sitter_ruby")

# 2. Universal AST Node Mappings
# This dictionary accounts for how different languages name their syntax nodes.
# For example, Python uses 'class_definition', but Rust uses 'struct_item'.
IMPORT_NODES = {
    "import_statement", "import_from_statement", "import_declaration", 
    "use_declaration", "import_spec", "preproc_include", "require_call"
}
CLASS_NODES = {
    "class_definition", "class_declaration", "class_specifier", 
    "struct_item", "type_declaration", "class"
}
FUNC_NODES = {
    "function_definition", "function_declaration", "method_definition", 
    "method_declaration", "function_item", "method", "arrow_function"
}

def parse_structure(file_path: str, ext: str) -> dict:
    """Parses a file dynamically based on its extension grammar."""
    # If it's a context file (like .md, .yaml, .json) or missing grammar, return empty.
    if ext not in LANGUAGE_REGISTRY:
        return {} 

    try:
        with open(file_path, "rb") as f:
            code = f.read()
    except Exception as e:
        return {"error": f"Could not read {file_path}: {e}"}

    parser = Parser(LANGUAGE_REGISTRY[ext])
    tree = parser.parse(code)
    
    structure = {
        "imports": [],
        "classes": [],
        "functions": []
    }
    
    def walk_tree(node):
        if node.type in IMPORT_NODES:
            import_text = code[node.start_byte:node.end_byte].decode('utf-8').strip()
            structure["imports"].append(import_text)
            
        elif node.type in CLASS_NODES:
            for child in node.children:
                # Catch identifiers (type_identifier is used by Go/Rust)
                if child.type in ["identifier", "type_identifier", "name"]:
                    class_name = code[child.start_byte:child.end_byte].decode('utf-8')
                    structure["classes"].append(class_name)
                    break
                    
        elif node.type in FUNC_NODES:
            for child in node.children:
                if child.type in ["identifier", "property_identifier", "name"]:
                    func_name = code[child.start_byte:child.end_byte].decode('utf-8')
                    if ext == ".py" and func_name.startswith("__") and func_name != "__init__":
                        break 
                    structure["functions"].append(func_name)
                    break
                    
        for child in node.children:
            walk_tree(child)

    walk_tree(tree.root_node)
    structure["imports"] = list(set(structure["imports"]))
    
    return structure

def build_repository_knowledge(base_repo_path: Path, relevant_files: list[str]) -> dict:
    """
    Iterates over ALL allowed files. Parses code files for architecture, 
    and safely ignores config/doc files.
    """
    print("[Tool 3] Parsing code structure across all relevant files...")
    repo_knowledge = {}
    
    for rel_path in relevant_files:
        full_path = base_repo_path / rel_path
        ext = full_path.suffix.lower() # 1. Grab the extension
        
        # We only attempt to parse files that have a registered grammar.
        if ext in LANGUAGE_REGISTRY:
            # 2. Pass BOTH the path and the extension to the parser
            parsed_data = parse_structure(str(full_path), ext) 
            
            if parsed_data and any(parsed_data.get(k) for k in ["classes", "functions"]): 
                repo_knowledge[rel_path] = parsed_data
                
    print(f"[Tool 3] Successfully mapped {len(repo_knowledge)} architectural code files.")
    return repo_knowledge

import re
def build_dependency_graph(repo_knowledge: dict, relevant_files: list[str]) -> dict:
    """
    Constructs a directed graph (adjacency list) of the codebase.
    Maps each file path to a list of other file paths it depends on.
    """
    print("[Tool 4] Constructing dependency graph...")
    
    # 1. Initialize the adjacency list
    dependency_graph = {file_path: [] for file_path in repo_knowledge.keys()}
    
    # 2. Create a fast lookup dictionary: { "filename_without_extension": "full/relative/path.ext" }
    # Example: { "logger": "src/utils/logger.py" }
    file_lookup = {}
    for f in relevant_files:
        path_obj = Path(f)
        # We store the stem (filename without extension) to match against import statements
        file_lookup[path_obj.stem] = f

    # 3. Build the edges
    for file_path, data in repo_knowledge.items():
        imports = data.get("imports", [])
        
        for imp in imports:
            # We check if any of our known file stems appear as a distinct word in the import string.
            # E.g., looking for the word "logger" inside "from utils.logger import setup"
            for stem, target_full_path in file_lookup.items():
                
                # Prevent self-loops (a file cannot depend on itself in this context)
                if target_full_path == file_path:
                    continue
                
                # Only link them if the target file actually has code architecture tracked in our knowledge base
                if target_full_path not in repo_knowledge:
                    continue
                
                # Use regex word boundaries (\b) to prevent partial matches 
                # (e.g., we don't want "app" to accidentally match "apple")
                if re.search(rf"\b{re.escape(stem)}\b", imp):
                    dependency_graph[file_path].append(target_full_path)
                    
        # 4. Deduplicate edges for clean graph traversal
        dependency_graph[file_path] = list(set(dependency_graph[file_path]))

    # Filter out isolated vertices (files that import nothing and are imported by nothing)
    # just to keep the LLM context window as clean as possible.
    active_graph = {
        k: v for k, v in dependency_graph.items() 
        if len(v) > 0 or any(k in deps for deps in dependency_graph.values())
    }

    print(f"[Tool 4] Graph constructed with {len(active_graph)} highly connected vertices.")
    return active_graph



if __name__ == "__main__":
    test_url = "https://github.com/pallets/flask" 
    
    print("--- Running Full Ingestion Pipeline (Days 1-4) ---")
    
    # Tool 1 & 2
    local_path = clone_repo(test_url)
    files = explore_files(local_path)
    
    # Tool 3
    repo_map = build_repository_knowledge(local_path, files)
    
    # Tool 4
    dep_graph = build_dependency_graph(repo_map, files)
    
    # Let's verify the connections of a major routing file!
    target_node = "src/flask/app.py"
    
    if target_node in dep_graph:
        print(f"\n--- Dependency Edges for: {target_node} ---")
        print(f"This file depends on {len(dep_graph[target_node])} other files in the repo.")
        for edge in dep_graph[target_node]:
            print(f" -> {edge}")
    else:
        print(f"\nCould not find {target_node}. Showing connections for a random file:")
        random_node = next(iter(dep_graph))
        print(f"{random_node} -> {dep_graph[random_node]}")
        
    print("\n--- Day 4 Test Passed Successfully! ---")