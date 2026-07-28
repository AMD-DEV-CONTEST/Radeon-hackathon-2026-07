import os
import sys
import subprocess
import json
import logging

logger = logging.getLogger("aider_client")

def get_server_token() -> str:
    return os.environ.get("AETHERIS_INTERNAL_TOKEN", "")

def read_file(file_path: str) -> str:
    """Lê o conteúdo de um arquivo de código localmente."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"

def create_file(file_path: str, content: str, token: str = "") -> str:
    """Cria um novo arquivo de código com o conteúdo fornecido."""
    expected_token = get_server_token()
    if expected_token and token != expected_token:
        return "Error: Unauthorized. Invalid server_token."
        
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Successfully created {file_path}"
    except Exception as e:
        return f"Error creating file: {e}"

def edit_file(file_path: str, instructions: str, token: str = "") -> str:
    """
    Executa uma edição em um arquivo utilizando o Aider via subprocesso,
    respeitando a aprovação do token de segurança.
    """
    expected_token = get_server_token()
    if expected_token and token != expected_token:
        return "Error: Unauthorized. Invalid server_token."
        
    prompt = f"File: {file_path}\nInstructions: {instructions}"
    return run_aider_command([file_path], prompt)

def run_aider_command(files: list[str], message: str) -> str:
    """Executa o Aider com restrições e um prompt específico e retorna o output."""
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    from models.config import LLM_MODEL
    
    # Sincroniza o diretório de execução com o ACTIVE_PROJECT_PATH
    active_dir = os.environ.get("ACTIVE_PROJECT_PATH", "").strip()
    if not active_dir:
        logger.warning("ACTIVE_PROJECT_PATH não definido no ambiente. Usando root como fallback.")
        active_dir = project_root
    
    import shutil
    aider_executable = shutil.which("aider") or "aider"
    cmd = [
        aider_executable,
        "--yes",
        "--no-auto-commits",
        "--model", f"ollama/{LLM_MODEL}",
        "--ollama-api-base", "http://localhost:11434",
        "--message", message
    ] + files
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180, cwd=active_dir)
        return result.stdout + "\n" + result.stderr
    except subprocess.TimeoutExpired:
        return "Error: Aider execution timed out after 180 seconds."
    except Exception as e:
        return f"Error executing aider: {str(e)}"
