"""Image generation via OpenRouter API (black-forest-labs/flux.2-pro)."""

import os
import re
import sys
import tempfile
from pathlib import Path

import requests

from fluxreel.gen_video.video import _sanitize_prompt, _download_image
from .base import ImageProvider


class OpenRouterProvider(ImageProvider):
    """Generate images via OpenRouter's flux.2-pro model."""

    def __init__(self, model: str = "black-forest-labs/flux.2-pro", api_key: str | None = None):
        self._model = model
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "OpenRouter"

    @property
    def model_name(self) -> str:
        return self._model

    def generate_image(self, prompt: str, scene_index: int = 0) -> str | None:
        """Generate an image via OpenRouter.

        Returns path to downloaded image, or None on failure.
        """
        api_key = self._api_key or os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            print("  Error: OPENROUTER_API_KEY not set.")
            return None

        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        messages = [{"role": "user", "content": prompt}]
        data = {"model": self._model, "messages": messages, "max_tokens": 1024}

        print(f"  Generating image via OpenRouter ({self._model})...")
        try:
            resp = requests.post(url, headers=headers, json=data, timeout=(10, 120))
        except Exception as e:
            print(f"  Error: OpenRouter request failed: {e}")
            # Retry with sanitized prompt
            sanitized = _sanitize_prompt(prompt)
            if sanitized != prompt:
                print("  Retrying with sanitized prompt...")
                return self._retry_with_prompt(sanitized, scene_index)
            return None

        if not resp.ok:
            detail = resp.text[:500]
            if "Request Moderated" in detail or "Protected Content" in detail:
                sanitized = _sanitize_prompt(prompt)
                print("  Moderation blocked — retrying with sanitized prompt...")
                return self._retry_with_prompt(sanitized, scene_index)
            print(f"  Warning: OpenRouter error HTTP {resp.status_code}")
            print(f"  {detail}")
            return None

        body = resp.json()
        img_url = self._extract_image_url(body)
        if not img_url:
            print(f"  Warning: No image URL in response. Keys: {list(body.keys())}")
            return None

        return self._download_to_temp(img_url, scene_index)

    def _retry_with_prompt(self, prompt: str, scene_index: int) -> str | None:
        """Retry image generation with a modified prompt."""
        api_key = self._api_key or os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            return None

        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        messages = [{"role": "user", "content": prompt}]
        data = {"model": self._model, "messages": messages, "max_tokens": 1024}

        try:
            resp = requests.post(url, headers=headers, json=data, timeout=(10, 120))
            if resp.ok:
                body = resp.json()
                img_url = self._extract_image_url(body)
                if img_url:
                    return self._download_to_temp(img_url, scene_index)
        except Exception:
            pass
        return None

    def _extract_image_url(self, body: dict) -> str | None:
        """Extract an image URL from an OpenRouter response."""
        content = body.get("choices", [{}])[0].get("message", {}).get("content")
        if content:
            # Markdown image syntax
            urls = re.findall(r"!\[.*?\]\((https?://[^\s)]+)\)", content)
            if urls:
                return urls[0]
            # Direct image URL
            urls = re.findall(
                r"https?://[^\s)]+\.(?:png|jpg|jpeg|webp)(?:\?[^\s)]*)?",
                content,
                re.IGNORECASE,
            )
            if urls:
                return urls[0]

        # Check message.images array
        for choice in body.get("choices", []):
            msg = choice.get("message", {})
            images = msg.get("images", [])
            if images:
                for img in images:
                    if isinstance(img, dict):
                        url = img.get("image_url", {}).get("url", "") or img.get("url", "")
                        if url:
                            return url
            # Check for url in message
            if msg.get("url"):
                return msg["url"]

        # Check data array
        images = body.get("data", [])
        if images:
            for img in images:
                if isinstance(img, dict) and img.get("url"):
                    return img["url"]

        if body.get("url"):
            return body["url"]

        return None

    def _download_to_temp(self, url_or_data: str, scene_index: int) -> str | None:
        """Download an image URL to a temp file."""
        temp_dir = Path(tempfile.mkdtemp(prefix=f"openrouter_img_{scene_index}_"))
        out_path = str(temp_dir / f"openrouter_scene_{scene_index:03d}.png")
        if _download_image(url_or_data, out_path):
            return out_path
        return None
