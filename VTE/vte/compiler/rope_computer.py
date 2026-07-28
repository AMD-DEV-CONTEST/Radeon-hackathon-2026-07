import numpy as np
from vte.bridge.logger import get_logger

logger = get_logger(__name__)

def compute_rope_cache(context_length: int, rope_freq_base: float, head_dim: int) -> np.ndarray:
    """
    Pré-computa tabela de RoPE (cos, sin) em FP16 na CPU para evitar 
    gasto massivo de VGPRs (instruções transcendentais) na GPU durante inferência.
    
    Retorna:
        np.ndarray de shape (context_length, head_dim) com [cos, sin] intercalados
    """
    logger.info(f"Pré-computando RoPE Cache (Ctx: {context_length}, Base: {rope_freq_base}, Dim: {head_dim})")
    
    freqs = 1.0 / (rope_freq_base ** (np.arange(0, head_dim, 2).astype(np.float32) / head_dim))
    
    positions = np.arange(context_length).astype(np.float32)
    
    angles = np.outer(positions, freqs)
    
    cos_vals = np.cos(angles)
    sin_vals = np.sin(angles)
    
    rope_cache = np.zeros((context_length, head_dim), dtype=np.float16)
    rope_cache[:, 0::2] = cos_vals
    rope_cache[:, 1::2] = sin_vals
    
    return rope_cache
