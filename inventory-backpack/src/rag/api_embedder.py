import requests
from typing import List

class APIEmbedder:
    def __init__(self, api_url: str, api_key: str, model: str):
        self.api_url = api_url
        self.headers = {}
        if api_key:
            try:
                api_key.encode("ascii")
                self.headers = {"Authorization": f"Bearer {api_key}"}
            except UnicodeEncodeError:
                pass
        self.model = model

    def encode(self, texts: List[str]) -> List[List[float]]:
        r = requests.post(
            f"{self.api_url.rstrip('/')}/embeddings",
            headers=self.headers,
            json={"model": self.model, "input": texts},
        )
        r.raise_for_status()
        return [d["embedding"] for d in r.json()["data"]]
