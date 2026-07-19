import numpy as np
import ctypes
from pathlib import Path
import logging

logger = logging.getLogger("VTE.RoPECache")


class RoPECacheBuilder:
    """
    Constrói caches de RoPE (cosseno e seno) para embeddings posicionais.
    
    O RoPE aplica rotações complexas aos embeddings Q e K baseadas na posição
    do token na sequência. Pré-computamos esses valores para evitar cálculos
    trigonométricos em runtime.
    """
    
    def __init__(
        self,
        max_seq_len: int = 2048,
        head_dim: int = 128,
        rope_theta: float = 10000.0,
        freq_scaling: "np.ndarray | None" = None
    ):
        self.max_seq_len = max_seq_len
        self.head_dim = head_dim
        self.rope_theta = rope_theta
        # Fatores de escala NTK-by-parts do Llama 3.1 (tensor `rope_freqs.weight`
        # do GGUF, shape [head_dim//2]): llama.cpp já vem com esses valores
        # pré-computados no arquivo (1.0 nas dimensões de alta frequência/onda
        # curta, subindo suavemente até `factor` -- 8.0 no Llama 3.1 8B -- nas
        # de baixa frequência/onda longa), em vez de expor os hiperparâmetros
        # crus (factor/low_freq_factor/high_freq_factor/original_context_length)
        # como chaves de metadado. Aplicado como DIVISOR da frequência base,
        # mesma convenção do `ggml_rope_ext`/`freq_factors` do llama.cpp
        # (confirmado lendo o tensor real do GGUF: valores crescem de 1.0 a
        # 8.0 ao longo das 64 dimensões, batendo com o factor=8 documentado
        # do Llama 3.1). None (padrão) preserva o RoPE θ puro de antes --
        # Qwen2.5/Granite/Qwen3.5 não têm esse tensor, comportamento intocado.
        self.freq_scaling = freq_scaling
    
    def build_cache(self) -> tuple[np.ndarray, np.ndarray]:
        """
        Constrói caches de cos e sin para todas as posições.
        
        Returns:
            (cos_cache, sin_cache): arrays de shape (max_seq_len, head_dim)
        """
        logger.info(
            f"Construindo RoPE cache: max_seq={self.max_seq_len}, "
            f"head_dim={self.head_dim}, theta={self.rope_theta}"
        )
        
        # Calcula frequências: freq_i = 1 / (theta^(2i/d))
        # Onde i = 0, 1, 2, ..., head_dim/2 - 1
        freq_dim = self.head_dim // 2
        freqs = 1.0 / (
            self.rope_theta ** (np.arange(0, freq_dim, dtype=np.float32) / freq_dim)
        )

        if self.freq_scaling is not None:
            if len(self.freq_scaling) != freq_dim:
                raise ValueError(
                    f"freq_scaling tem {len(self.freq_scaling)} elementos, "
                    f"esperado {freq_dim} (head_dim//2)."
                )
            freqs = freqs / self.freq_scaling.astype(np.float32)

        # Posições: 0, 1, 2, ..., max_seq_len-1
        positions = np.arange(self.max_seq_len, dtype=np.float32)
        
        # Produto externo: (max_seq_len, freq_dim)
        # angles[pos, i] = pos * freq_i
        angles = np.outer(positions, freqs)
        
        # Calcula cos e sin
        cos_values = np.cos(angles)  # (max_seq_len, freq_dim)
        sin_values = np.sin(angles)  # (max_seq_len, freq_dim)
        
        # Expande para head_dim completo usando Sliced / Rotate Half (Qwen/LLaMA)
        # Primeira metade e segunda metade recebem os mesmos valores de cosseno e seno
        cos_cache = np.zeros((self.max_seq_len, self.head_dim), dtype=np.float16)
        sin_cache = np.zeros((self.max_seq_len, self.head_dim), dtype=np.float16)
        
        # Padrão Sliced: as duas metades são idênticas para cos e sin
        cos_cache[:, :freq_dim] = cos_values.astype(np.float16)
        cos_cache[:, freq_dim:] = cos_values.astype(np.float16)
        
        sin_cache[:, :freq_dim] = sin_values.astype(np.float16)
        sin_cache[:, freq_dim:] = sin_values.astype(np.float16)
        
        logger.info(
            f"RoPE cache Sliced (FP16) construído: "
            f"cos={cos_cache.shape}, sin={sin_cache.shape}"
        )
        
        return cos_cache, sin_cache
    
    def upload_to_vram(
        self,
        cos_cache: np.ndarray,
        sin_cache: np.ndarray,
        hip_runtime,
        allocator
    ) -> tuple[int, int]:
        """
        Faz upload dos caches para VRAM.
        
        Returns:
            (cos_ptr, sin_ptr): ponteiros de VRAM
        """
        # Converte para bytes
        cos_bytes = cos_cache.tobytes()
        sin_bytes = sin_cache.tobytes()
        
        # Aloca na VRAM
        cos_size = len(cos_bytes)
        sin_size = len(sin_bytes)
        
        cos_block = allocator.allocate(
            size=cos_size,
            tag="rope_cos",
            region="weights"
        )
        
        sin_block = allocator.allocate(
            size=sin_size,
            tag="rope_sin",
            region="weights"
        )
        
        # Copia para VRAM
        hip_runtime.safe_memcpy_host_to_device(
            dst=ctypes.c_void_p(cos_block.ptr),
            src=cos_bytes,
            tag="rope_cos"
        )
        
        hip_runtime.safe_memcpy_host_to_device(
            dst=ctypes.c_void_p(sin_block.ptr),
            src=sin_bytes,
            tag="rope_sin"
        )
        
        logger.info(
            f"RoPE cache enviado para VRAM: "
            f"cos={cos_size} bytes, sin={sin_size} bytes"
        )
        
        return cos_block.ptr, sin_block.ptr
