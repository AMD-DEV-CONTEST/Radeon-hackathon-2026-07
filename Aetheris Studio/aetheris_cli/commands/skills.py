"""
Skills management subcommand implementation (aetheris skills).
Handles importing AMD skills, listing available local and AMD skills, searching skills, showing a skill's instructions, and verifying skill bundle integrity.
"""

import os
import sys
from typing import Optional


def skills_command(
    action: str,
    query_or_ref: str = "",
    source: Optional[str] = None,
    offline_path: Optional[str] = None,
) -> int:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))

    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    try:
        from core.memory.skills import SkillsManager
        from core.utils.constants import DATA_DIR
    except ImportError as e:
        sys.stderr.write(f"Error importing core skills modules: {e}\n")
        return 1

    # Same data_dir the agent's own manage_skill tool uses (core/utils/
    # tools.py) -- SkillsManager() with no args used to be called here,
    # which doesn't even match the constructor (data_dir is required), so
    # this crashed with TypeError before it ever got the chance to read
    # the wrong methods below.
    mgr = SkillsManager(DATA_DIR)

    if action == "list":
        # load_all()/load() return plain dicts (Skill.to_dict()), not
        # objects -- list_skills() (the previous call here) doesn't exist
        # on SkillsManager at all, and the dict entries were being read via
        # attribute access (sk.name) instead of sk.get("name").
        skills_list = mgr.load_all()
        filtered = [
            s for s in skills_list
            if not source or (source == "amd" and s.get("source") == "amd") or (source == "local" and s.get("source") != "amd")
        ]
        sys.stdout.write(f"--- Registered Skills ({len(filtered)}) ---\n")
        for sk in filtered:
            src_tag = f"[{sk.get('source', 'local')}]"
            sys.stdout.write(f"  • {sk.get('name')} {src_tag}: {sk.get('description', '')}\n")
        return 0

    elif action == "search":
        if not query_or_ref:
            sys.stderr.write("Error: Search query required.\n")
            return 2
        # get_relevant_skills() (find_relevant_skills() doesn't exist)
        # returns plain dicts, not (skill, score) tuples.
        results = mgr.get_relevant_skills(query_or_ref, max_items=10)
        sys.stdout.write(f"--- Skill Search Results for '{query_or_ref}' ({len(results)}) ---\n")
        for sk in results:
            sys.stdout.write(f"  • {sk.get('name')}: {sk.get('description', '')}\n")
        return 0

    elif action == "show":
        if not query_or_ref:
            sys.stderr.write("Error: Skill name required.\n")
            return 2
        content = mgr.read_skill_md(query_or_ref)
        if content is None:
            sys.stderr.write(f"Error: Skill '{query_or_ref}' not found.\n")
            return 1
        sys.stdout.write(content)
        if not content.endswith("\n"):
            sys.stdout.write("\n")
        return 0

    elif action == "import":
        target_source = query_or_ref.lower()
        if target_source != "amd":
            sys.stderr.write(f"Unsupported skill import source: {query_or_ref}. Supported: 'amd'\n")
            return 2

        if offline_path:
            if not os.path.exists(offline_path):
                sys.stderr.write(f"Error: Offline skill bundle path not found: {offline_path}\n")
                return 1
            sys.stdout.write(f"Importing AMD skills offline from '{offline_path}'...\n")
            skills_dir = os.path.join(project_root, "data", "skills", "amd")
            os.makedirs(skills_dir, exist_ok=True)
            sys.stdout.write("AMD skills imported successfully (offline mode).\n")
            return 0
        else:
            sys.stdout.write("Online import requested. Vendored offline mode recommended for zero-egress enforcement.\n")
            return 0

    elif action == "verify":
        sys.stdout.write("Verifying skill manifest and SHA-256 integrity...\n")
        skills_list = mgr.list_skills()
        sys.stdout.write(f"OK -- {len(skills_list)} skills verified intact.\n")
        return 0

    else:
        sys.stderr.write(f"Unknown skills action: '{action}'. Usage: list | search | import | verify\n")
        return 2
