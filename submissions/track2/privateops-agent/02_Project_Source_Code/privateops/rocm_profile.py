from __future__ import annotations

import os
import shlex
from dataclasses import dataclass


@dataclass(frozen=True)
class RadeonDeploymentProfile:
    model_name: str
    host: str
    port: int
    max_model_len: int
    gpu_memory_utilization: float

    @classmethod
    def competition_default(cls) -> "RadeonDeploymentProfile":
        return cls(
            model_name="Qwen/Qwen2.5-7B-Instruct",
            host="127.0.0.1",
            port=8000,
            max_model_len=8192,
            gpu_memory_utilization=0.85,
        )

    @classmethod
    def from_env(cls) -> "RadeonDeploymentProfile":
        default = cls.competition_default()
        return cls(
            model_name=os.environ.get("PRIVATEOPS_MODEL_NAME", default.model_name),
            host=default.host,
            port=int(os.environ.get("PRIVATEOPS_MODEL_PORT", str(default.port))),
            max_model_len=int(os.environ.get("PRIVATEOPS_MAX_MODEL_LEN", str(default.max_model_len))),
            gpu_memory_utilization=float(
                os.environ.get("PRIVATEOPS_GPU_MEMORY_UTILIZATION", str(default.gpu_memory_utilization))
            ),
        )

    @property
    def chat_completions_endpoint(self) -> str:
        return f"http://{self.host}:{self.port}/v1/chat/completions"

    @property
    def models_endpoint(self) -> str:
        return f"http://{self.host}:{self.port}/v1/models"

    def shell_exports(self) -> str:
        values = {
            "PRIVATEOPS_MODEL_NAME": self.model_name,
            "PRIVATEOPS_MODEL_HOST": self.host,
            "PRIVATEOPS_MODEL_PORT": str(self.port),
            "PRIVATEOPS_MAX_MODEL_LEN": str(self.max_model_len),
            "PRIVATEOPS_GPU_MEMORY_UTILIZATION": str(self.gpu_memory_utilization),
            "PRIVATEOPS_MODEL_ENDPOINT": self.chat_completions_endpoint,
            "PRIVATEOPS_MODELS_ENDPOINT": self.models_endpoint,
        }
        return "\n".join(f"export {key}={shlex.quote(value)}" for key, value in values.items())


if __name__ == "__main__":
    print(RadeonDeploymentProfile.from_env().shell_exports())
