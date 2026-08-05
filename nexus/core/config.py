"""
Configuration management for NEXUS
"""
from pathlib import Path
from typing import Optional, Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class InferenceConfig(BaseSettings):
    """Inference engine configuration"""

    device: Literal["hip", "cuda", "cpu"] = Field(
        default="hip",
        description="Device to use for inference (hip=ROCm, cuda=NVIDIA, cpu=fallback)"
    )

    # Model paths
    reasoning_model: str = Field(
        default="meta-llama/Llama-3.3-70B-Instruct",
        description="Large model for deep reasoning"
    )
    code_model: str = Field(
        default="Qwen/Qwen2.5-Coder-32B-Instruct",
        description="Model specialized for code analysis"
    )
    fast_model: str = Field(
        default="microsoft/phi-4",
        description="Small fast model for quick responses"
    )

    # Quantization
    reasoning_quantization: Literal["int4", "int8", "fp16", "fp32"] = "int4"
    code_quantization: Literal["int4", "int8", "fp16", "fp32"] = "fp16"
    fast_quantization: Literal["int4", "int8", "fp16", "fp32"] = "int4"

    # Performance
    max_parallel_agents: int = Field(default=8, description="Max concurrent agent inferences")
    max_context_length: int = Field(default=32768, description="Max context window")
    batch_size: int = Field(default=1, description="Inference batch size")

    # ROCm specific
    use_flash_attention: bool = Field(default=True, description="Enable Flash Attention 2")
    use_kv_cache: bool = Field(default=True, description="Enable KV cache sharing")
    memory_fraction: float = Field(default=0.9, description="Fraction of GPU memory to use")

    model_config = SettingsConfigDict(env_prefix="NEXUS_INFERENCE_")


class GraphConfig(BaseSettings):
    """Causal graph configuration"""

    storage_backend: Literal["memory", "rocksdb", "sqlite"] = Field(
        default="rocksdb",
        description="Storage backend for graph"
    )

    db_path: Path = Field(
        default=Path(".nexus/graph.db"),
        description="Database path"
    )

    max_nodes: int = Field(default=100000, description="Maximum graph nodes")
    max_history_days: int = Field(default=90, description="Days of history to retain")

    # Graph processing
    enable_gpu_acceleration: bool = Field(
        default=True,
        description="Use GPU for graph algorithms"
    )
    traversal_timeout: float = Field(default=5.0, description="Timeout for graph traversal")

    model_config = SettingsConfigDict(env_prefix="NEXUS_GRAPH_")


class MonitoringConfig(BaseSettings):
    """File system and git monitoring configuration"""

    watch_patterns: list[str] = Field(
        default=["*.py", "*.js", "*.ts", "*.tsx", "*.go", "*.rs", "*.java"],
        description="File patterns to monitor"
    )

    ignore_patterns: list[str] = Field(
        default=["node_modules", "venv", ".git", "__pycache__", "*.pyc", ".nexus"],
        description="Patterns to ignore"
    )

    enable_git_hooks: bool = Field(default=True, description="Install git hooks")
    scan_interval: float = Field(default=1.0, description="File system scan interval (seconds)")

    model_config = SettingsConfigDict(env_prefix="NEXUS_MONITOR_")


class AgentConfig(BaseSettings):
    """Agent swarm configuration"""

    max_agents: int = Field(default=16, description="Maximum concurrent agents")
    agent_timeout: float = Field(default=60.0, description="Agent execution timeout")

    # Agent types enabled
    enable_temporal_analyst: bool = True
    enable_code_archaeologist: bool = True
    enable_fix_simulator: bool = True
    enable_adaptive_generation: bool = True

    # Simulation
    max_simulation_branches: int = Field(default=4, description="Max parallel simulations")
    simulation_depth: int = Field(default=5, description="Simulation lookahead depth")

    model_config = SettingsConfigDict(env_prefix="NEXUS_AGENT_")


class NexusConfig(BaseSettings):
    """Main NEXUS configuration"""

    # Project settings
    project_root: Path = Field(default=Path.cwd(), description="Project root directory")
    nexus_dir: Path = Field(default=Path(".nexus"), description="NEXUS data directory")

    # Sub-configurations
    inference: InferenceConfig = Field(default_factory=InferenceConfig)
    graph: GraphConfig = Field(default_factory=GraphConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    agents: AgentConfig = Field(default_factory=AgentConfig)

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_file: Optional[Path] = Field(default=Path(".nexus/nexus.log"))

    # API
    api_host: str = "127.0.0.1"
    api_port: int = 8765

    model_config = SettingsConfigDict(
        env_prefix="NEXUS_",
        env_file=".env",
        env_file_encoding="utf-8"
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Ensure paths are absolute
        if not self.project_root.is_absolute():
            self.project_root = self.project_root.resolve()

        if not self.nexus_dir.is_absolute():
            self.nexus_dir = self.project_root / self.nexus_dir

        if self.graph.db_path and not self.graph.db_path.is_absolute():
            self.graph.db_path = self.nexus_dir / self.graph.db_path.name

        if self.log_file and not self.log_file.is_absolute():
            self.log_file = self.nexus_dir / self.log_file.name

    def ensure_directories(self) -> None:
        """Create necessary directories"""
        self.nexus_dir.mkdir(parents=True, exist_ok=True)
        (self.nexus_dir / "models").mkdir(exist_ok=True)
        (self.nexus_dir / "cache").mkdir(exist_ok=True)
        (self.nexus_dir / "logs").mkdir(exist_ok=True)
