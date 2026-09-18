"""Local-network HTTP detector adapter."""

from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Any

import cv2
import httpx
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_fixed

from buildguard.config import VisionModelConfig
from buildguard.exceptions import ModelUnavailableError
from buildguard.schemas.vision import Detection
from buildguard.security.network_guard import NetworkGuard
from buildguard.vision.base_detector import Detector
from buildguard.vision.postprocessing import class_aware_nms
from buildguard.vision.preprocessing import DecodedImage

HttpOutputAdapter = Callable[[Any, str, int, int], list[Detection]]


class HttpLocalDetector(Detector):
    def __init__(
        self,
        config: VisionModelConfig,
        network_guard: NetworkGuard,
        output_adapter: HttpOutputAdapter | None,
        *,
        timeout_seconds: float,
        retry_attempts: int,
        retry_wait_seconds: float,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(config)
        if config.endpoint is None:
            raise ModelUnavailableError(f"HTTP detector {self.name} has no endpoint")
        self.endpoint = str(config.endpoint)
        network_guard.validate(self.endpoint)
        self.output_adapter = output_adapter
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=timeout_seconds)
        self.retry_attempts = retry_attempts
        self.retry_wait_seconds = retry_wait_seconds

    def predict(
        self,
        image: DecodedImage,
        requested_classes: list[str] | None = None,
    ) -> list[Detection]:
        if self.output_adapter is None:
            raise ModelUnavailableError(
                f"HTTP detector {self.name} requires an explicit response adapter"
            )
        ok, encoded = cv2.imencode(".jpg", image.bgr)
        if not ok:
            raise ValueError(f"Could not encode image for detector {self.name}")
        payload = {
            "model": self.name,
            "image_base64": base64.b64encode(encoded.tobytes()).decode("ascii"),
            "requested_classes": requested_classes,
        }

        def request() -> httpx.Response:
            response = self.client.post(self.endpoint, json=payload)
            response.raise_for_status()
            return response

        response = Retrying(
            stop=stop_after_attempt(self.retry_attempts),
            wait=wait_fixed(self.retry_wait_seconds),
            retry=retry_if_exception_type(
                (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)
            ),
            reraise=True,
        )(request)
        detections = self.output_adapter(
            response.json(), self.name, image.width, image.height
        )
        filtered = [
            item
            for item in detections
            if item.confidence >= self.config.confidence_threshold
            and (requested_classes is None or item.label in requested_classes)
        ]
        return class_aware_nms(filtered, self.config.nms_iou)

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

