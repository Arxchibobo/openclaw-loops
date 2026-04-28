from __future__ import annotations

import importlib
from typing import Any, Protocol

from .config import StepSpec


class StepProtocol(Protocol):
    KEY: str

    def dry(self, ctx: dict[str, Any]) -> dict[str, Any]: ...
    def run(self, ctx: dict[str, Any]) -> dict[str, Any]: ...
    def metrics(self, ctx: dict[str, Any]) -> dict[str, Any]: ...


def load_step(spec: StepSpec) -> StepProtocol:
    mod = importlib.import_module(spec.module)
    if not hasattr(mod, "Step"):
        raise AttributeError(f"{spec.module} must define a `Step` class")
    return mod.Step()  # type: ignore[no-any-return]
