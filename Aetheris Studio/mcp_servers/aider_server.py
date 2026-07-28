"""
Aider MCP Server
Runs headless aider commands with strict flags.
"""

import sys
import subprocess
from mcp.server.stdio import stdio_server
from mcp.server import Server
from mcp.types import Tool, TextContent

import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
from models.config import LLM_MODEL

app = Server("aider_server")

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="aider_edit",
            description="Use Aider to autonomously edit codebase files based on a prompt.",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "The explicit instruction of what to code/refactor."},
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of absolute file paths to modify."
                    },
                    "server_token": {
                        "type": "string",
                        "description": "Internal server token, do not provide."
                    }
                },
                "required": ["prompt", "files"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "aider_edit":
        raise ValueError(f"Unknown tool: {name}")

    prompt = arguments.get("prompt")
    files = arguments.get("files", [])
    server_token = arguments.get("server_token")
    
    expected_token = os.environ.get("AETHERIS_INTERNAL_TOKEN")
    if expected_token and server_token != expected_token:
        return [TextContent(type="text", text="Error: Unauthorized. Invalid server_token.", isError=True)]
    
    if not prompt or not files:
        return [TextContent(type="text", text="Error: 'prompt' and 'files' are required.", isError=True)]
    
    # 2. Injeta RAG de forma controlada apenas no escopo do Aider
    import os
    import sys
    
    # Adiciona o diretório raiz ao sys.path para importar o core localmente
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
        
    try:
        from core.database import query_knowledge_base
        # Limita rigorosamente a injeção ao Top-2
        rag_results = query_knowledge_base(prompt, n_results=2)
        if rag_results and rag_results.get("chunks"):
            rag_context = "\n\n".join(rag_results["chunks"])
            prompt = f"{prompt}\n\n[CONTEXTO E DIRETRIZES DA BASE (RAG)]:\n{rag_context}"
    except Exception as e:
        print(f"[DEBUG AIDER] Erro silencioso ao injetar RAG: {e}", flush=True)

    # 3. Log de Debug do Tamanho do Prompt em KB
    prompt_kb = len(prompt.encode('utf-8')) / 1024
    print(f"\n[DEBUG AIDER] Tamanho real do payload de instrução enviado: {prompt_kb:.2f} KB\n", flush=True)
    
    cmd = [
        sys.executable, "-m", "aider",
        "--yes",
        "--no-auto-commits",
        "--model", f"ollama/{LLM_MODEL}",
        "--ollama-api-base", "http://localhost:11434",
        "--message", prompt
    ] + files
    
    try:
        # 180 seconds timeout as requested
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        output = result.stdout + "\n" + result.stderr
        
        return [TextContent(type="text", text=output)]
    except subprocess.TimeoutExpired:
        return [TextContent(type="text", text="Error: Aider execution timed out after 180 seconds.", isError=True)]
    except Exception as e:
        return [TextContent(type="text", text=f"Error executing aider: {str(e)}", isError=True)]

if __name__ == "__main__":
    import urllib.request
    status = "desconectado ✗"
    try:
        with urllib.request.urlopen("http://localhost:11434", timeout=2.0) as conn:
            if conn.status == 200:
                status = "conectado ✓"
    except Exception:
        pass

    print(f"[Aider] Modelo: ollama/{LLM_MODEL}")
    print("[Aider] API base: http://localhost:11434")
    print(f"[Aider] Status: {status}")
    sys.stdout.flush()

    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())

    import asyncio
    asyncio.run(main())
