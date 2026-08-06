> Chinese version: [README.md](README.md)

# Model Payload Status

`Qwen3-32B-bnb-4bit-7f721e74/` retains 12 tokenizer/config/template/index metadata files, all byte-identical to the canonical remote copies.

The four `.safetensors` weight shards are intentionally omitted. Their expected combined size is `19,211,935,565 B`. The complete filenames, sizes, and SHA256 values are recorded in:

```text
../artifacts/model-acquisition/qwen3-32b-bnb-7f721e74-verification.json
```

The canonical trainer requires the model directory to contain exactly the 16 read-only files in that manifest. Missing files, extra files, symbolic links, writable files, or hash drift all fail closed.
