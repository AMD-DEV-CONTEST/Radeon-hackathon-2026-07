"""离线中英翻译（Helsinki-NLP opus-mt-zh-en，无需 API key）"""
import os
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOCAL_MODEL_DIR = PROJECT_ROOT / "ComfyUI" / "models" / "translator" / "opus-mt-zh-en"

_lock = threading.Lock()
_tok = None
_model = None


def needs_translation(text: str) -> bool:
    """文本包含中文字符时返回 True"""
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _load():
    global _tok, _model
    with _lock:
        if _model is None:
            from transformers import MarianMTModel, MarianTokenizer

            model_name = (
                str(LOCAL_MODEL_DIR)
                if (LOCAL_MODEL_DIR / "pytorch_model.bin").exists()
                else os.environ.get("TRANSLATOR_MODEL", "Helsinki-NLP/opus-mt-zh-en")
            )
            _tok = MarianTokenizer.from_pretrained(model_name)
            _model = MarianMTModel.from_pretrained(model_name)
            _model.eval()
    return _tok, _model


def translate(text: str) -> str:
    """中文 → 英文；已是英文（不含中文）则原样返回"""
    if not needs_translation(text):
        return text
    tok, model = _load()
    import torch

    batch = tok([text], return_tensors="pt", truncation=True, max_length=512)
    with torch.no_grad():
        out = model.generate(**batch, max_new_tokens=512)
    return tok.batch_decode(out, skip_special_tokens=True)[0]
