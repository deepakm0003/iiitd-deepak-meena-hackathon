"""Device selection and thread limits for model inference (shared server: be polite)."""

import os
from functools import lru_cache


@lru_cache
def device() -> str:
    """'cuda' when a usable GPU is present (college server), else 'cpu' (laptops, judges)."""
    import torch

    forced = os.environ.get("TRIPWIRE_DEVICE")
    if forced:
        return forced
    return "cuda" if torch.cuda.is_available() else "cpu"


def limit_cpu_threads(default: int = 4) -> None:
    import torch

    torch.set_num_threads(int(os.environ.get("TRIPWIRE_TORCH_THREADS", default)))
