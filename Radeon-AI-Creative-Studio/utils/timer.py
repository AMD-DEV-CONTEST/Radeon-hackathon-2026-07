import time

import torch


class Timer:
    def __enter__(self):
        if torch.cuda.is_available():
            torch.cuda.synchronize()

        self.start = time.perf_counter()
        self.cost = 0.0
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if torch.cuda.is_available():
            torch.cuda.synchronize()

        self.end = time.perf_counter()
        self.cost = self.end - self.start
