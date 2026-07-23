"""
Hardware profiling and GPU backend detection.

Supports:
- NVIDIA CUDA
- AMD ROCm (Linux)
- AMD DirectML (Windows via onnxruntime)
- Apple Silicon MPS
- CPU fallback
"""


class LocalAccelerator:
    """
    Universal accelerator that works with both CUDA and AMD ROCm GPUs.
    """

    def __init__(self):
        self.accelerator = None
        self.device = "cpu"
        self.backend = "cpu"
        self.fp16_support = False
        self._detected = False

    def init_accelerator(self):
        if self._detected:
            return

        import torch

        if torch.cuda.is_available():
            try:
                device_name = torch.cuda.get_device_name().lower()
                if "amd" in device_name:
                    self.device = "cuda"
                    self.backend = "rocm"
                    self.fp16_support = True
                    self._detected = True
                    print(f"Initialized with ROCm backend on AMD GPU")
                    return
                else:
                    self.device = "cuda"
                    self.backend = "cuda"
                    self.fp16_support = True
                    self._detected = True
                    print(f"Initialized with CUDA backend on {torch.cuda.get_device_name()}")
                    return
            except Exception as e:
                print(f"CUDA init failed: {e}")

        try:
            import onnxruntime as ort
            providers = ort.get_available_providers()
            if any("Dml" in p for p in providers):
                self.device = "directml"
                self.backend = "directml"
                self.fp16_support = True
                self._detected = True
                print("Initialized with DirectML backend (Windows AMD)")
                return
        except Exception as e:
            print(f"DirectML init check failed: {e}")

        if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            self.device = "mps"
            self.backend = "mps"
            self.fp16_support = False
            self._detected = True
            print("Initialized with MPS backend (Apple Silicon)")
            return

        self.device = "cpu"
        self.backend = "cpu"
        self.fp16_support = False
        self._detected = True
        print("Initialized with CPU backend (no GPU detected)")

    def get_device(self):
        if not self._detected:
            self.init_accelerator()
        return self.device

    def get_backend(self):
        if not self._detected:
            self.init_accelerator()
        return self.backend

    def is_gpu_available(self):
        if not self._detected:
            self.init_accelerator()
        return self.backend in ("cuda", "rocm", "directml", "mps")
