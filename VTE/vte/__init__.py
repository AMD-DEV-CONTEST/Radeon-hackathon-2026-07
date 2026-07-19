"""
VTE (Vector & Tensor Engine)
Motor de inferência de LLMs AMD-native para Windows.

Exemplo de uso:
    >>> import vte
    >>> model = vte.VTEModel.from_pretrained("qwen2.5:1.5b-q4_k_m")
    >>> response = model.generate("Olá, como você está?", max_tokens=100)
    >>> print(response)
"""

from .core.model import VTEModel
from .bridge.dll_discovery import validate_hip_installation

__version__ = "0.3.7"
__author__ = "VTE Contributors"

import sys
if 'pytest' not in sys.modules:
    _success, _message = validate_hip_installation()
    if not _success:
        import warnings
        warnings.warn(f"VTE: {_message}", RuntimeWarning)

__all__ = [
    "VTEModel",
    "__version__",
]
