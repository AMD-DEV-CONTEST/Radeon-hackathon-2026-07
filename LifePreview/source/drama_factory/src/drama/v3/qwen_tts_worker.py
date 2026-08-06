from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Isolated Qwen3-TTS local inference worker"
    )
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding="utf-8"))

    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    model = Qwen3TTSModel.from_pretrained(
        request["model_path"],
        device_map=request["device"],
        dtype=torch.bfloat16,
        attn_implementation="sdpa",
    )
    wavs, sample_rate = model.generate_custom_voice(
        text=request["text"],
        language=request["language"],
        speaker=request["speaker"],
        instruct=request["instruction"],
    )
    destination = Path(request["destination"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    sf.write(destination, wavs[0], sample_rate)


if __name__ == "__main__":
    main()
