from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "openclaw.yaml"


@dataclass
class StepSpec:
    id: int
    key: str
    name: str
    module: str
    verify: str


@dataclass
class LoopSpec:
    name: str
    description: str
    steps: list[StepSpec]

    def step(self, ref: str | int) -> StepSpec:
        for s in self.steps:
            if str(s.id) == str(ref) or s.key == str(ref):
                return s
        raise KeyError(f"step {ref!r} not found in loop {self.name}")


@dataclass
class Config:
    raw: dict[str, Any]
    loops: dict[str, LoopSpec]

    def loop(self, name: str) -> LoopSpec:
        if name not in self.loops:
            raise KeyError(f"loop {name!r} not configured. available: {list(self.loops)}")
        return self.loops[name]

    def path(self, key: str) -> Path:
        rel = self.raw.get("paths", {}).get(key)
        if not rel:
            raise KeyError(f"paths.{key} not configured")
        p = ROOT / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


def load_config(path: Path | None = None) -> Config:
    p = path or CONFIG_PATH
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    loops: dict[str, LoopSpec] = {}
    for name, body in raw.get("loops", {}).items():
        steps = [StepSpec(**s) for s in body["steps"]]
        loops[name] = LoopSpec(name=name, description=body.get("description", ""), steps=steps)
    return Config(raw=raw, loops=loops)


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)
