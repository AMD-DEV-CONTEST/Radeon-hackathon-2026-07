import os
import platform
import psutil

class ToolExecutor:
    def __init__(self):
        self.tools = {
            "system_diagnostics": self.get_system_diagnostics,
            "list_directory": self.list_directory,
        }

    def get_system_diagnostics(self, *args) -> str:
        """Returns current CPU, RAM, and disk usage."""
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        diagnostics = (
            f"OS: {platform.system()} {platform.release()}\n"
            f"CPU Usage: {cpu}%\n"
            f"RAM Usage: {mem.percent}% ({mem.used / (1024**3):.2f}GB / {mem.total / (1024**3):.2f}GB)\n"
            f"Disk Usage: {disk.percent}%"
        )
        return diagnostics

    def list_directory(self, path=".") -> str:
        """Lists contents of the given directory."""
        try:
            items = os.listdir(path)
            return "\n".join(items) if items else "Directory is empty."
        except Exception as e:
            return f"Error listing directory: {str(e)}"

    def parse_and_execute(self, prompt: str):
        """
        Simple heuristic parser for tool execution.
        In a full implementation, the LLM would output structured JSON to call tools.
        """
        prompt_lower = prompt.lower()
        if "diagnostics" in prompt_lower or "system status" in prompt_lower:
            return self.get_system_diagnostics()
        if "list directory" in prompt_lower or "list files" in prompt_lower:
            return self.list_directory()
        return None
