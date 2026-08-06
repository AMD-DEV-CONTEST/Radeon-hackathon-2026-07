"""
Embedding generation — thin wrapper around InferenceClient.embed() so callers
depend on a stable interface (`EmbeddingService.embed_text` /
`embed_batch`) rather than the raw inference client, and so the embedding
model can be swapped (e.g. a smaller dedicated embedding model served on a
second vLLM/ROCm process) without touching call sites.
"""
from app.inference.client import InferenceClient, get_inference_client


class EmbeddingService:
    def __init__(self, client: InferenceClient | None = None) -> None:
        self._client = client or get_inference_client()

    async def embed_text(self, text: str) -> list[float]:
        results = await self._client.embed([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return await self._client.embed(texts)
