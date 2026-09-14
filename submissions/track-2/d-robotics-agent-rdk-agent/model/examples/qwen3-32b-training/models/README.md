# Model payload status

`Qwen3-32B-bnb-4bit-7f721e74/` 中保留了 12 个 tokenizer/config/template/index 元数据文件，均与正式远端逐字节一致。

四个 `.safetensors` 权重分片按要求省略，合计应为 `19,211,935,565 B`。完整文件名、大小和 SHA256 记录在：

```text
../artifacts/model-acquisition/qwen3-32b-bnb-7f721e74-verification.json
```

正式 trainer 要求模型目录最终恰好包含清单中的 16 个只读文件；少文件、多文件、软链接、可写文件或哈希漂移都会 fail closed。

