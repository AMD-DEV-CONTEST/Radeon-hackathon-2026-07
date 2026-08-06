"""Configured visual model registry."""

from __future__ import annotations

from typing import Any

import httpx

from buildguard.config import PermissionConfig, VisionConfig, VisionModelConfig
from buildguard.exceptions import ModelUnavailableError
from buildguard.security.network_guard import NetworkGuard
from buildguard.vision.base_detector import Detector
from buildguard.vision.http_detector import HttpLocalDetector, HttpOutputAdapter
from buildguard.vision.local_detector import (
    LocalDetectorAdapter,
    LocalOutputAdapter,
    LocalRunner,
)
from buildguard.vision.mock_detector import MockDetector
from buildguard.vision.rtdetr_v2 import RTDETRConfig, RTDETRRunner, RTDETRv2Adapter
from buildguard.vision.yolo11 import YOLO11Adapter, YOLO11Runner


class VisionModelRegistry:
    def __init__(self) -> None:
        self._configs: dict[str, VisionModelConfig] = {}
        self._detectors: dict[str, Detector] = {}

    def register(
        self,
        config: VisionModelConfig,
        detector: Detector | None,
    ) -> None:
        if config.model_name in self._configs:
            raise ValueError(f"Vision model already registered: {config.model_name}")
        if config.enabled and detector is None:
            raise ValueError("An enabled vision model requires a detector")
        if detector is not None and detector.name != config.model_name:
            raise ValueError("Detector name does not match model configuration")
        self._configs[config.model_name] = config
        if detector is not None:
            self._detectors[config.model_name] = detector

    def get(self, name: str) -> Detector:
        if name not in self._configs:
            raise KeyError(f"Unknown vision model: {name}")
        if not self._configs[name].enabled:
            raise PermissionError(f"Vision model is disabled: {name}")
        detector = self._detectors.get(name)
        if detector is None:
            raise ModelUnavailableError(f"Vision model has no detector: {name}")
        return detector

    def enabled(self, names: list[str] | None = None) -> list[Detector]:
        requested = set(names) if names is not None else None
        if requested is not None:
            unknown = requested - set(self._configs)
            if unknown:
                raise KeyError(f"Unknown vision models: {sorted(unknown)}")
        return [
            self._detectors[name]
            for name, config in self._configs.items()
            if config.enabled and (requested is None or name in requested)
        ]

    def metadata(self) -> list[dict[str, Any]]:
        return [
            config.model_dump(mode="json", exclude={"model_path", "endpoint"})
            for config in self._configs.values()
        ]

    def model_configs(self) -> list[VisionModelConfig]:
        """Return immutable copies for routing without exposing registry state."""
        return [config.model_copy(deep=True) for config in self._configs.values()]

    @classmethod
    def from_config(
        cls,
        config: VisionConfig,
        permissions: PermissionConfig,
        *,
        seed: int,
        local_adapters: dict[str, tuple[LocalRunner, LocalOutputAdapter]] | None = None,
        rtdetr_runners: dict[str, RTDETRRunner] | None = None,
        yolo11_runners: dict[str, YOLO11Runner] | None = None,
        http_adapters: dict[str, HttpOutputAdapter] | None = None,
        http_client: httpx.Client | None = None,
    ) -> VisionModelRegistry:
        registry = cls()
        local_adapters = local_adapters or {}
        rtdetr_runners = rtdetr_runners or {}
        yolo11_runners = yolo11_runners or {}
        http_adapters = http_adapters or {}
        endpoints = [
            str(model.endpoint)
            for model in config.models
            if model.backend == "http" and model.endpoint is not None
        ]
        network_guard = NetworkGuard(endpoints, permissions.allowed_lan_cidrs)
        for model in config.models:
            if not model.enabled:
                registry.register(model, None)
                continue
            if model.backend == "mock":
                detector: Detector = MockDetector(model, seed)
            elif model.backend == "local":
                if model.local_adapter == "rtdetr_v2":
                    if (
                        model.model_config_path is None
                        or model.model_path is None
                        or model.model_manifest_path is None
                        or model.model_revision is None
                        or model.model_sha256 is None
                    ):
                        raise ModelUnavailableError(
                            f"RT-DETRv2 model {model.model_name} has incomplete configuration"
                        )
                    detector = RTDETRv2Adapter(
                        model,
                        RTDETRConfig(
                            config_path=model.model_config_path,
                            weights_path=model.model_path,
                            manifest_path=model.model_manifest_path,
                            device=model.device,
                            batch_size=model.batch_size,
                            revision=model.model_revision,
                            model_sha256=model.model_sha256,
                            class_mapping=model.class_mapping,
                        ),
                        runner=rtdetr_runners.get(model.model_name),
                    )
                elif model.local_adapter == "yolo11":
                    if model.model_path is None or model.model_sha256 is None:
                        raise ModelUnavailableError(
                            f"YOLO11 model {model.model_name} has incomplete configuration"
                        )
                    detector = YOLO11Adapter(
                        model,
                        runner=yolo11_runners.get(model.model_name),
                    )
                else:
                    adapter = local_adapters.get(model.model_name)
                    if adapter is None:
                        raise ModelUnavailableError(
                            f"Local detector {model.model_name} "
                            "has no runner/output adapter"
                        )
                    detector = LocalDetectorAdapter(model, adapter[0], adapter[1])
            else:
                detector = HttpLocalDetector(
                    model,
                    network_guard,
                    http_adapters.get(model.model_name),
                    timeout_seconds=config.http_timeout_seconds,
                    retry_attempts=config.http_retry_attempts,
                    retry_wait_seconds=config.http_retry_wait_seconds,
                    client=http_client,
                )
            registry.register(model, detector)
        return registry
