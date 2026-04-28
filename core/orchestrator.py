from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import state
from .config import Config, LoopSpec, StepSpec, ROOT
from .logger import get_logger
from .registry import load_step
from .verifier import verify, VerifyResult

log = get_logger("openclaw.orchestrator")


@dataclass
class StepReport:
    loop: str
    step: StepSpec
    mode: str
    status: str
    metrics: dict[str, Any]
    verify: VerifyResult | None
    error: str | None = None

    def to_md(self) -> str:
        head = f"### Loop `{self.loop}` · Step {self.step.id} · {self.step.name}\n"
        head += f"- mode: `{self.mode}`  status: **{self.status}**\n"
        head += f"- key: `{self.step.key}`  module: `{self.step.module}`\n"
        if self.verify is not None:
            head += f"- verify: `{self.verify.expression}` → **{self.verify.ok}**\n"
        if self.metrics:
            head += "- metrics:\n"
            for k, v in self.metrics.items():
                head += f"  - {k}: {v}\n"
        if self.error:
            head += f"- error: `{self.error}`\n"
        return head + "\n"


class Orchestrator:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        state.init()

    def execute_step(self, loop_name: str, step: StepSpec, mode: str) -> StepReport:
        ctx: dict[str, Any] = {"loop": loop_name, "step_id": step.id, "step_key": step.key}
        log.info("step.start", extra={"loop": loop_name, "step": step.id, "mode": mode})
        try:
            handler = load_step(step)
        except Exception as exc:
            err = f"load_step failed: {exc}"
            log.exception(err)
            state.record_run(loop_name, step.id, step.key, mode, "failed", error=err)
            return StepReport(loop_name, step, mode, "failed", {}, None, err)

        try:
            if mode == "dry":
                payload = handler.dry(ctx)
            elif mode == "run":
                payload = handler.run(ctx)
            elif mode == "verify":
                payload = handler.metrics(ctx)
            else:
                raise ValueError(f"unknown mode {mode!r}")
        except NotImplementedError as exc:
            err = f"step not implemented: {exc}"
            log.warning(err)
            state.record_run(loop_name, step.id, step.key, mode, "blocked", error=err)
            return StepReport(loop_name, step, mode, "blocked", {}, None, err)
        except Exception as exc:
            err = f"step error: {exc}"
            log.exception(err)
            state.record_run(loop_name, step.id, step.key, mode, "failed",
                             error=err)
            return StepReport(loop_name, step, mode, "failed", {}, None, err)

        metrics = payload.get("metrics", {}) if isinstance(payload, dict) else {}
        v: VerifyResult | None = None
        if step.verify:
            v = verify(step.verify, metrics)
        status = "ok" if (v is None or v.ok) else "failed"
        state.record_run(loop_name, step.id, step.key, mode, status,
                         payload=payload, error=None)
        if mode == "run" and status == "ok":
            state.set_cursor(loop_name, step.id)
        return StepReport(loop_name, step, mode, status, metrics, v)

    def run_loop(self, loop_name: str, mode: str = "run",
                 from_step: int | None = None, to_step: int | None = None,
                 only: int | str | None = None) -> list[StepReport]:
        loop = self.cfg.loop(loop_name)
        if only is not None:
            return [self.execute_step(loop_name, loop.step(only), mode)]
        steps = [s for s in loop.steps
                 if (from_step is None or s.id >= from_step)
                 and (to_step is None or s.id <= to_step)]
        reports: list[StepReport] = []
        for s in steps:
            r = self.execute_step(loop_name, s, mode)
            reports.append(r)
            if r.status == "failed":
                log.warning("loop halted at step %s", s.id)
                break
        return reports

    def write_report(self, loop_name: str, mode: str, reports: list[StepReport]) -> Path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = ROOT / "reports" / f"{loop_name}-{mode}-{ts}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        body = [f"# openclaw report · {loop_name} · {mode}\n",
                f"_generated {ts}_\n\n"]
        ok = sum(1 for r in reports if r.status == "ok")
        body.append(f"**summary**: {ok}/{len(reports)} ok\n\n---\n\n")
        body.extend(r.to_md() for r in reports)
        path.write_text("".join(body), encoding="utf-8")
        log.info("report.written", extra={"path": str(path)})
        return path
