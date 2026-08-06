# Local AI runtime

Decompile never requires an OpenAI API key. The API starts with deterministic local fallback adapters for a reliable demo. For GPU inference, install the optional requirements and select either vLLM with ROCm or `llama.cpp` built with HIP.

Recommended local stack:

- Inference: Qwen2.5-Coder through vLLM ROCm or llama.cpp HIP
- Vision: Qwen2.5-VL
- Embeddings: `BAAI/bge-small-en-v1.5`
- Retrieval: FAISS
- Source collection: `yt-dlp` and `youtube-transcript-api`
- OCR: PaddleOCR

Each adapter is deliberately isolated from the API contract, so the demo mode can be replaced with model calls without changing the frontend.
