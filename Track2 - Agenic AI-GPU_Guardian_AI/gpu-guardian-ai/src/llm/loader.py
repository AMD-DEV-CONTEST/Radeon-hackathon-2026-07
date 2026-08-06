"""
LLM Loader

Loads the tokenizer and model only once.
"""

import os
from transformers.utils import logging
#from huggingface_hub import hf_hub_disable_progress_bars

from transformers import AutoTokenizer, AutoModelForCausalLM
from config.settings import MODEL_NAME

_tokenizer = None
_model = None


def load_model():
    global _tokenizer
    global _model

    # Disable HuggingFace logs and progress bars
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    logging.set_verbosity_error()

    if _tokenizer is None:
        print("Initializing AI Engine...")
        _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        print("✓ Tokenizer Ready")

    if _model is None:
        _model = AutoModelForCausalLM.from_pretrained(
            MODEL_NAME,
            torch_dtype="auto",
            device_map="auto"
        )
        print("✓ Local LLM Ready")

    return _tokenizer, _model
