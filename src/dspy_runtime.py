"""DSPy runtime wiring for Bunker.

Binds DSPy's default language model based on config.inference.backend
("vllm", "ollama", or "radeon_api") and configures it as the process-wide default.
Import this module at application startup so every DSPy module resolves to the
served model. No un-audited traffic leaves localhost.
"""

import logging
import dspy  # https://dspy.ai/api/models/LM

from .config import get_config

logger = logging.getLogger(__name__)

def build_lm(config=None) -> dspy.LM:
    """Build a dspy.LM instance based on the inference configuration."""
    if config is None:
        config = get_config()
    
    backend = getattr(config.inference, "backend", "vllm").lower()
    
    if backend == "ollama":
        model_name = config.inference.ollama_model
        if not model_name.startswith("openai/"):
            model_string = f"openai/{model_name}"
        else:
            model_string = model_name
        api_base = config.inference.ollama_base_url
        api_key = "ollama"
    elif backend == "radeon_api":
        model_name = config.inference.radeon_model
        if not model_name.startswith("openai/"):
            model_string = f"openai/{model_name}"
        else:
            model_string = model_name
        api_base = config.inference.radeon_api_url
        api_key = config.inference.radeon_api_key or "EMPTY"
    else:  # default to vllm
        backend = "vllm"
        model_name = config.inference.primary_model
        if not model_name.startswith("openai/"):
            model_string = f"openai/{model_name}"
        else:
            model_string = model_name
        api_base = f"http://{config.inference.vllm_host}:{config.inference.vllm_port}/v1"
        api_key = "EMPTY"
        
    logger.info(f"Configuring DSPy LM with backend='{backend}', model='{model_string}', api_base='{api_base}'")
    
    # https://dspy.ai/api/models/LM
    return dspy.LM(
        model=model_string,
        api_base=api_base,
        api_key=api_key,
        max_tokens=config.agent.max_tokens_per_turn,
        temperature=0.0,
        cache=False,  # required by DataFlowMonitor: every request must be observable
    )

_config = get_config()
BUNKER_LM = build_lm(_config)

# Set the process-wide default LM. https://dspy.ai/api/models/LM
dspy.configure(lm=BUNKER_LM)

