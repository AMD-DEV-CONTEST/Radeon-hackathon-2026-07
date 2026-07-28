"""
Model name normalization helper module for Aetheris CLI.
Maps friendly GGUF filenames and command line aliases to VTE registered model identifiers.
"""


def normalize_model_name(name: str) -> str:
    cleaned = name.strip().lower()
    if not cleaned:
        return ""
    mapping = {
        "granite-4.1-3b-q8_0.gguf": "granite-4.1:3b-q8_0",
        "granite-4.1-3b-q8_0": "granite-4.1:3b-q8_0",
        "granite3b": "granite-4.1:3b-q8_0",
        "granite-3b": "granite-4.1:3b-q8_0",
        "granite3.0:3b": "granite-4.1:3b-q8_0",
        "granite-4.1:3b": "granite-4.1:3b-q8_0",
        "granite-4.1-8b-q4_k_m.gguf": "granite-4.1:30b-q8_0",
        "granite-4.1-8b-q4_k_m": "granite-4.1:30b-q8_0",
        "granite-4.1:8b": "granite-4.1:30b-q8_0",
        "meta-llama-3.1-8b-instruct-q4_k_m.gguf": "llama3.1:8b-instruct-q4_k_m",
        "llama3.1:8b": "llama3.1:8b-instruct-q4_k_m",
        "qwen2.5-1.5b-instruct-q4_k_m.gguf": "qwen2.5:1.5b-q4_k_m",
        "qwen2.5-7b-instruct.q4_k_m.gguf": "qwen2.5:7b-q4_k_m",
        "qwen3.5-2b-q6_k.gguf": "qwen3.5:2b-q6_k",
    }
    return mapping.get(cleaned, name.strip())
