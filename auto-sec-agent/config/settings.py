"""
AutoSec Configuration
"""
import os
from pathlib import Path

class Config:
    # Directories
    BASE_DIR = Path(__file__).parent.parent
    TOOLS_DIR = Path(os.path.expanduser("~/go/bin"))
    OUTPUT_DIR = BASE_DIR / "output"
    TEMPLATES_DIR = BASE_DIR / "templates"
    
    # Security Tools
    SUBFINDER_PATH = os.path.normpath(str(TOOLS_DIR / "subfinder.exe"))
    NUCLEI_PATH = os.path.normpath(str(TOOLS_DIR / "nuclei.exe"))
    NUCLEI_TEMPLATES = os.path.normpath("D:/tools/arsenal/nuclei-templates")
    NAABU_PATH = os.path.normpath(str(TOOLS_DIR / "naabu.exe"))
    HTTPX_PATH = os.path.normpath(str(TOOLS_DIR / "httpx.exe"))
    KATANA_PATH = os.path.normpath(str(TOOLS_DIR / "katana.exe"))
    GAU_PATH = os.path.normpath(str(TOOLS_DIR / "gau.exe"))
    WAYBACKURLS_PATH = os.path.normpath(str(TOOLS_DIR / "waybackurls.exe"))
    GF_PATH = os.path.normpath(str(TOOLS_DIR / "gf.exe"))
    
    # Notion
    NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
    NOTION_VERSION = "2025-09-03"
    
    # Gmail (Himalaya)
    HIMALAYA_PATH = os.path.normpath(str(Path(os.path.expanduser("~/tools/himalaya/himalaya.exe"))))
    GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "alizafarbati@gmail.com")
    
    # AMD ROCm
    ROCM_ENABLED = os.environ.get("ROCM_ENABLED", "false").lower() == "true"
    ROCM_DEVICE = os.environ.get("ROCM_DEVICE", "gpu:0")
    AMD_MODEL_PATH = os.environ.get("AMD_MODEL_PATH", "")
    
    # Agent
    MAX_CONCURRENT_TOOLS = 5
    DEFAULT_TIMEOUT = 120
    VERBOSE = True
    
    @classmethod
    def setup(cls):
        """Create required directories"""
        cls.OUTPUT_DIR.mkdir(exist_ok=True, parents=True)
        cls.TEMPLATES_DIR.mkdir(exist_ok=True, parents=True)
