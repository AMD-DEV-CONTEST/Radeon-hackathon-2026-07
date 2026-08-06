"""Low-latency PyTorch and MIGraphX student-policy inference."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import torch


class TorchInference:
    def __init__(self, model: torch.nn.Module, *, device: str = "cuda") -> None:
        self.model = model.eval().to(device)
        self.device = torch.device(device)

    @torch.inference_mode()
    def __call__(self, observation: np.ndarray | torch.Tensor) -> np.ndarray:
        tensor = torch.as_tensor(observation, dtype=torch.float32, device=self.device)
        return self.model(tensor).detach().cpu().numpy()


class MIGraphXInference:
    def __init__(self, model_path: str | Path) -> None:
        try:
            import migraphx
        except ImportError as error:
            raise ImportError("Install ROCm MIGraphX before using MIGraphXInference.") from error
        self.migraphx = migraphx
        self.program = migraphx.load(str(model_path))

    def __call__(self, observation: np.ndarray) -> np.ndarray:
        value = np.ascontiguousarray(observation, dtype=np.float32)
        argument = self.migraphx.argument(self.program.get_parameter_shapes()["observation"], value)
        outputs = self.program.eval({"observation": argument})
        return np.asarray(outputs[0])
