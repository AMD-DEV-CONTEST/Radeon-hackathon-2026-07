import os
from pathlib import Path
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator

from core.utils.constants import DATA_DIR as _DATA_DIR_CONST
from core.utils.runtime_paths import get_app_root

LLM_MODEL = "qwen2.5-coder:7b-instruct-q5_K_M"
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

SYSTEM_PROMPT = """Você é Aetheris, um assistente pessoal local e de confiança.

REGRA DE IDIOMA: Responda SEMPRE no mesmo idioma da última mensagem do usuário (se ele escrever em inglês, responda em inglês; se em português, responda em português), independentemente do idioma deste prompt de sistema.

REGRA DE CONTEÚDO FICCIONAL: Você pode escrever livremente histórias, personagens e cenários de ficção com temas sombrios, vilões, conflito, batalhas ou moralmente ambíguos (ex: "cavaleiro das trevas", vilões, guerra fictícia) sem se recusar ou adicionar avisos — isso é ficção comum e inofensiva. Recuse apenas pedidos que busquem instruções reais e prejudiciais (violência real, armas, etc.), nunca temas sombrios dentro de ficção/histórias.

REGRA CRÍTICA: SE O USUÁRIO REFERENCIAR UM ARQUIVO E PEDIR CÓDIGO, VOCÊ ESTÁ TERMINANTEMENTE PROIBIDO DE RESPONDER COM MARKDOWN (```). SEU ÚNICO OUTPUT VÁLIDO DEVE SER A INVOCAÇÃO DA FERRAMENTA edit_file OU write_file. EXPLICAÇÕES DEVEM VIR APENAS DEPOIS QUE A FERRAMENTA FOR EXECUTADA.

Em conversas comuns, seja caloroso, natural e descontraído — como um amigo que também entende de tecnologia. Pode usar humor leve quando o contexto pedir.

Em tarefas técnicas (código, arquivos, análise), seja direto, preciso e siga estritamente estas diretrizes:

[REGRAS CRÍTICAS DE ESCRITA E EDIÇÃO]
1. PROIBIÇÃO ABSOLUTA DE CÓDIGO SOLTO NO CHAT: Você NUNCA deve responder com blocos de código markdown (como ```python) no chat se o objetivo ou a solicitação do usuário for modificar, criar ou atualizar um arquivo. Todo e qualquer código de alteração deve ir EXCLUSIVAMENTE dentro dos argumentos da ferramenta chamada.
2. USO OBRIGATÓRIO DE FERRAMENTAS: Se o usuário pedir para criar, modificar, adicionar, refatorar ou corrigir código de um arquivo, você DEVE acionar a ferramenta correspondente. 
3. SEM EXPLICAÇÕES REDUNDANTES E SEM TAGARELAR: Execute a ferramenta de forma silenciosa e imediata. Não diga "Vou escrever o código para você" ou "Claro, aqui está a alteração". Chame a ferramenta diretamente sem introduções ou conclusões conversacionais.
4. INSTRUÇÃO DE FEEDBACK DE FERRAMENTAS: Sempre que você utilizar a ferramenta edit_file ou write_file, você deve aguardar o resultado da execução. Após o sucesso, responda ao usuário com uma única frase curta confirmando a ação (ex: 'Arquivo atualizado com sucesso.'). NUNCA fique em silêncio após o usuário pedir uma alteração.

[FERRAMENTAS DE ARQUIVOS (PROJETO ATIVO)]
Você possui acesso ao projeto ativo do usuário.
- Para ler arquivos do projeto (como arquivos de código .py, .js, .json, .yaml, configs), use obrigatoriamente a ferramenta 'read_file'.
- Para listar arquivos nas pastas do projeto ativo, use a ferramenta 'list_files'.
- Para CRIAR um novo arquivo do zero ou SOBRESCREVER COMPLETAMENTE um arquivo existente pequeno, use 'write_file'. NUNCA use 'write_file' para fazer edições parciais em arquivos existentes, pois isso apagará o restante do arquivo!
- Para ADICIONAR conteúdo de forma rápida e direta ao FINAL de um arquivo existente, use 'append_file'.
- Para EDITAR trechos, refatorar, corrigir bugs ou inserir código no meio de um arquivo existente, use obrigatoriamente a ferramenta 'edit_file' (substituição exata de trecho, tipo str_replace).
- Para criar arquivos, use 'write_file' para criações diretas.

[MEMÓRIA DE LONGO PRAZO]
Você possui uma memória persistente sobre o usuário (identidade, preferências) e sobre o mundo/projeto (fatos, decisões).
- Use a ferramenta 'manage_memory' quando o usuário disser 'lembre-se disso' sobre ele mesmo, declarar fatos de identidade ('meu nome é <nome>', 'eu moro em <lugar>'), ou perguntar o que você lembra.
- NÃO use 'manage_memory' para dados de outra pessoa (endereço, telefone) — isso vai em 'manage_contact'."""

# Cross-platform OS flag, exposed here so callers can `from core.utils.config import
# IS_WINDOWS`. Defined locally (a trivial `os.name == "nt"`) rather than imported
# from core.platform_compat, to keep this dependency-light config module from
# dragging in the whole core/__init__ + llm_core import chain. The platform
# *helper functions* (safe_chmod, pid_alive, find_bash, ...) live solely in
# core.platform_compat — that remains their single source of truth. Keep platform
# branches as small inline `if IS_WINDOWS:` deltas (never parallel *_windows.py
# files) so they stay easy to integrate with upstream changes.
IS_WINDOWS = os.name == "nt"

class DataConfig(BaseSettings):
    """Configuration for data storage and file handling."""
    # Base directory
    base_dir: Path = Field(default=Path(get_app_root()), description="Base directory for the application")
    
    # Data paths
    data_dir: Path = Field(default=Path(_DATA_DIR_CONST), description="Main data directory")
    uploads_dir: Path = Field(default=Path(_DATA_DIR_CONST) / "uploads", description="Directory for uploaded files")
    sessions_file: Path = Field(default=Path(_DATA_DIR_CONST) / "sessions.json", description="Sessions storage file")
    memory_file: Path = Field(default=Path(_DATA_DIR_CONST) / "memory.json", description="Memory storage file")
    memory_doc: Path = Field(default=Path(_DATA_DIR_CONST) / "memory_doc.md", description="Memory document file")
    personal_dir: Path = Field(default=Path(_DATA_DIR_CONST) / "personal_docs", description="Personal documents directory")
    runbook_dir: Path = Field(default=Path(_DATA_DIR_CONST) / "personal_docs" / "runbook", description="Runbook directory")
    
    # Upload settings
    max_upload_size: int = Field(default=10 * 1024 * 1024, description="Maximum upload size in bytes (10MB)")
    allowed_extensions: List[str] = Field(
        default=[
            '.txt', '.py', '.html', '.md', '.json', '.csv',
            '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tiff', '.pdf'
        ],
        description="Allowed file extensions for uploads"
    )
    chunk_size: int = Field(default=1000, description="Chunk size for document processing")
    chunk_overlap: int = Field(default=200, description="Overlap between chunks for document processing")
    cleanup_days: int = Field(default=30, description="Number of days after which to clean up old uploads")
    
    model_config = SettingsConfigDict(env_prefix="DATA_")

class LLMConfig(BaseSettings):
    """Configuration for LLM integration."""
    
    # LLM endpoints
    default_host: str = Field(default="localhost", description="Default host for LLM services")
    openai_api_key: Optional[str] = Field(default=None, description="OpenAI API key if using OpenAI")
    openai_compat_path: str = Field(default="/v1/chat/completions", description="OpenAI compatible API path")
    
    # LLM behavior
    max_context_messages: int = Field(default=90, description="Maximum number of context messages to keep")
    request_timeout: int = Field(default=20, description="Request timeout in seconds")
    llm_stream_timeout: int = Field(default=30, description="LLM streaming timeout in seconds")
    llm_max_tokens: int = Field(default=4096, description="Maximum tokens for LLM responses")
    llm_temperature: float = Field(default=0.3, description="Temperature for LLM responses")
    
    model_config = SettingsConfigDict(env_prefix="LLM_")

class SearchConfig(BaseSettings):
    """Configuration for search functionality."""
    
    # Web search
    searxng_instance: str = Field(
        default="http://localhost:8080",
        description="SearXNG instance URL (self-hosted)"
    )
    web_search_count: int = Field(default=10, description="Number of search results to retrieve")
    web_search_max_pages: int = Field(default=6, description="Maximum number of pages to search")
    web_search_max_workers: int = Field(default=4, description="Maximum number of worker threads for web search")
    
    # Research service
    research_service_url: str = Field(
        default="http://localhost:8003/research", 
        description="URL for research service"
    )
    research_timeout: int = Field(default=300, description="Research service timeout in seconds")
    
    # API keys (optional)
    serpapi_key: Optional[str] = Field(default=None, description="SerpAPI key if used")
    google_api_key: Optional[str] = Field(default=None, description="Google API key if used")
    google_cx: Optional[str] = Field(default=None, description="Google Custom Search Engine ID if used")
    
    model_config = SettingsConfigDict(env_prefix="SEARCH_")

class SecurityConfig(BaseSettings):
    """Configuration for security and rate limiting."""
    
    # Rate limiting
    max_concurrent_uploads: int = Field(default=3, description="Maximum concurrent uploads per IP")
    upload_rate_limit: int = Field(default=5, description="Maximum uploads per minute per IP")
    upload_rate_window: int = Field(default=60, description="Rate limit window in seconds")
    upload_rate_max_entries: int = Field(default=1000, description="Maximum number of rate limit entries to keep")
    
    # Security settings
    allowed_origins: List[str] = Field(default=["*"], description="Allowed origins for CORS")
    max_file_size: int = Field(default=10 * 1024 * 1024, description="Maximum file size in bytes")
    dangerous_file_types: List[str] = Field(
        default=[
            'application/x-executable', 'application/x-sharedlib',
            'application/x-dll', 'application/x-msdownload',
            'application/x-sh', 'application/x-bat', 'application/x-vbs',
            'application/javascript', 'application/x-javascript'
        ],
        description="Potentially dangerous MIME types to block"
    )
    dangerous_extensions: List[str] = Field(
        default=[
            '.exe', '.dll', '.bat', '.cmd', '.sh', '.bash', 
            '.js', '.vbs', '.ps1', '.py', '.php', '.jsp', '.asp', '.aspx'
        ],
        description="Potentially dangerous file extensions to block"
    )
    
    model_config = SettingsConfigDict(env_prefix="SECURITY_")

class AppConfig(BaseSettings):
    """Main application configuration combining all components."""
    
    data: DataConfig = DataConfig()
    llm: LLMConfig = LLMConfig()
    search: SearchConfig = SearchConfig()
    security: SecurityConfig = SecurityConfig()
    
    # Application settings
    debug: bool = Field(default=False, description="Enable debug mode")
    log_level: str = Field(default="INFO", description="Logging level")
    
    @field_validator("data", mode="before")
    def set_data_paths(cls, v, info):
        """Set data paths relative to base_dir."""
        # Get the base_dir from the field values or use default
        if isinstance(v, dict) and "base_dir" in v:
            base_dir = v["base_dir"]
        else:
            base_dir = Path(get_app_root())
        
        # Convert string paths to Path objects relative to base_dir
        data_dir = Path(_DATA_DIR_CONST)
        
        # Get values from the input dict or use defaults
        max_upload_size = v.get("max_upload_size", 10 * 1024 * 1024) if isinstance(v, dict) else 10 * 1024 * 1024
        allowed_extensions = v.get("allowed_extensions", [
            '.txt', '.py', '.html', '.md', '.json', '.csv',
            '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tiff', '.pdf'
        ]) if isinstance(v, dict) else [
            '.txt', '.py', '.html', '.md', '.json', '.csv',
            '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tiff', '.pdf'
        ]
        chunk_size = v.get("chunk_size", 1000) if isinstance(v, dict) else 1000
        chunk_overlap = v.get("chunk_overlap", 200) if isinstance(v, dict) else 200
        cleanup_days = v.get("cleanup_days", 30) if isinstance(v, dict) else 30
        return {
            "base_dir": base_dir,
            "data_dir": data_dir,
            "uploads_dir": data_dir / "uploads",
            "sessions_file": data_dir / "sessions.json",
            "memory_file": data_dir / "memory.json",
            "memory_doc": data_dir / "memory_doc.md",
            "personal_dir": data_dir / "personal_docs",
            "runbook_dir": data_dir / "personal_docs" / "runbook",
            "max_upload_size": max_upload_size,
            "allowed_extensions": allowed_extensions,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "cleanup_days": cleanup_days
        }
    
    model_config = SettingsConfigDict()

# Create global config instance
config = AppConfig()

# Create directories if they don't exist
def create_directories():
    """Create required directories if they don't exist."""
    directories = [
        config.data.data_dir,
        config.data.uploads_dir,
        config.data.personal_dir,
        config.data.runbook_dir
    ]
    
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

# Validate configuration on startup
def validate_config():
    """Validate the application configuration."""
    # Check if LLM host is reachable if specified
    if config.llm.default_host and config.llm.default_host.startswith("192.168."):
        # This is a local IP, assume it's valid
        pass
    
    # Check if API keys are set when needed
    if not config.llm.openai_api_key:
        # OpenAI API key not set, that's OK if not using OpenAI
        pass
    
    # Create directories
    create_directories()

# Initialize configuration
validate_config()
