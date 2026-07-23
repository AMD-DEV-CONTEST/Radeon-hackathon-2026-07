"""
Replicate API client.

Wraps the subset of Replicate's API needed for image-to-video generation:

    POST /v1/predictions              -- submit a prediction
    GET  /v1/predictions/{id}         -- poll for status + output
    GET  <output_url>                 -- download the resulting video

Workflow-specific payload assembly lives in app.workflows.ltx_i2v.
"""

import base64
import json
import mimetypes
from pathlib import Path
from typing import Optional

import httpx

from app.core.config import settings


class ReplicateError(Exception):
    """Raised when Replicate rejects a request or returns an unexpected shape."""


class ReplicateClient:
    def __init__(
        self,
        api_token: Optional[str] = None,
        api_base: Optional[str] = None,
    ):
        self.api_token = api_token or settings.REPLICATE_API_TOKEN
        self.api_base = (api_base or settings.replicate_api_url).rstrip("/")
        if not self.api_token:
            raise ReplicateError(
                "No Replicate API token configured. Set the REPLICATE_API_TOKEN "
                "environment variable or pass api_token to ReplicateClient."
            )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Token {self.api_token}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Health / token check
    # ------------------------------------------------------------------
    async def is_reachable(self) -> bool:
        """Cheap connectivity check hitting Replicate's account endpoint."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.api_base}/account",
                    headers={"Authorization": f"Token {self.api_token}"},
                )
                return resp.status_code == 200
        except httpx.HTTPError:
            return False

    # ------------------------------------------------------------------
    # Prediction lifecycle
    # ------------------------------------------------------------------
    async def create_prediction(
        self,
        model: str,
        input_payload: dict,
        webhook: Optional[str] = None,
    ) -> dict:
        """
        Submit a prediction to a Replicate model.

        model can be "owner/name" or "owner/name:version_hash". We POST to
        /predictions with a version field derived from that string.
        """
        version: Optional[str] = None
        model_id = model
        if ":" in model:
            model_id, version = model.split(":", 1)

        body: dict = {"input": input_payload}
        if version:
            body["version"] = version
        if webhook:
            body["webhook"] = webhook

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.api_base}/predictions",
                json=body,
                headers=self._headers(),
            )

        if resp.status_code not in (200, 201):
            raise ReplicateError(
                f"Replicate rejected the prediction ({resp.status_code}): {resp.text}"
            )
        return resp.json()

    async def get_prediction(self, prediction_id: str) -> dict:
        """Poll a single prediction by id."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.api_base}/predictions/{prediction_id}",
                headers=self._headers(),
            )
        if resp.status_code != 200:
            raise ReplicateError(
                f"Prediction lookup failed ({resp.status_code}): {resp.text}"
            )
        return resp.json()

    async def fetch_output_bytes(self, url: str) -> bytes:
        """Download a result file (image/video) from a signed URL."""
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            raise ReplicateError(f"Fetching output '{url}' failed ({resp.status_code}): {resp.text}")
        return resp.content

    # ------------------------------------------------------------------
    # File encoding helper
    # ------------------------------------------------------------------
    @staticmethod
    def file_to_data_uri(file_path: Path) -> str:
        """
        Encode a local file as a data URI so it can be passed inline in a
        Replicate JSON input payload. Replicate also supports public URLs,
        but for FrameForge's upload-then-render flow data URIs avoid an
        extra public-upload step.
        """
        mime, _ = mimetypes.guess_type(str(file_path))
        mime = mime or "application/octet-stream"
        b64 = base64.b64encode(file_path.read_bytes()).decode()
        return f"data:{mime};base64,{b64}"
