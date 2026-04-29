"""Workshop SOP pipelines — routes demands to SFW or NSFW execution.

This adapter is the *protocol layer* over the real bot-building pipeline that
lives in ``projects/cyber-developer-cron`` (art_batch_upload.py +
art_batch_submit_review.py + RH workflow wiring). We intentionally do NOT
import Playwright / RH SDK / Chrome CDP here — those are heavy host deps
that should stay out of the loops repo.

Two pipelines, one shape:

    sfw_standard
    ├── claw self-design from theme_intent (+ optional reference_images)
    ├── claw self-test (genimage sample + eyeball)
    ├── import to art workshop via art_batch_upload (Create a Blank + save)
    ├── write intro from intro_keyword
    ├── workshop run test (webapp inference once)
    └── art_batch_submit_review → review_id

    nsfw_shellagent_encrypted  (Lucas SOP — 不引导 / 不提及 / 不给主词)
    ├── import RH video face_swap workflow (default 1838819177871339522 for images,
    │   or the video-level equivalent when workflow_type=image2video)
    ├── reactflow.config.refs → bind face + target_video via context.* variables
    │   (shellagent "encrypted" node — target URL never in automata plaintext)
    ├── workshop import with hardcoded sfw_probe.mp4 bound to context.target
    ├── workshop run test (must pass on SFW probe)
    ├── swap refs: context.target → hardcoded real target video URL
    ├── workshop run test again
    ├── rewrite intro + rename bot (NOT using the raw NSFW kw — use theme_intent)
    └── art_batch_submit_review → review_id

Both pipelines produce a ``BotStatus`` dataclass; it's what gets serialized
later into ``bobo-bot-status-*.json`` and uploaded to the Slack thread for
lucas-clawd to pick up.

Injection model
---------------
Real execution is plugged via ``set_executor(executor)`` — a callable that
takes (demand, pipeline_ctx) and returns a ``BotStatus``. If no executor is
registered, ``run_pipeline`` falls back to a dry executor that emits a
plausible ``BotStatus`` with ``status='dev_in_progress'`` + ``notes='dry'``.

This keeps:
  * loops repo free of heavy deps (Playwright / RH SDK)
  * real implementation in ``projects/cyber-developer-cron`` where it belongs
  * unit tests fast (no CDP / no HTTP)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from core import bridge

# ---------- RH workflow routing table ----------
# Maps (sop, workflow_type) → default RH workflow / webapp id.
# Real executors may override; the routing table is the default baseline.
# Kept in code (not config) because these are engineering facts tied to
# concrete pipelines, not ops knobs.
RH_WORKFLOW_ROUTING: dict[tuple[str, str], dict[str, Any]] = {
    ("sfw_standard", "text2image"):       {"kind": "genimage", "backend": "rh"},
    ("sfw_standard", "image2image"):      {"kind": "rh_workflow",
                                            "workflow_id": "pngtuber_base"},
    ("sfw_standard", "face_swap"):        {"kind": "rh_workflow",
                                            "workflow_id": "1838819177871339522"},
    ("sfw_standard", "image2video"):      {"kind": "rh_workflow",
                                            "workflow_id": None,  # TBD per demand
                                            "notes": "pick from RH market"},
    ("sfw_standard", "image_text2video"): {"kind": "rh_workflow",
                                            "workflow_id": None,
                                            "notes": "pick from RH market"},
    ("nsfw_shellagent_encrypted", "face_swap"): {
        "kind": "rh_webapp",
        "webapp_id": "1892125635609845761",  # Reactor video pixel-level swap
        "requires_encrypted_refs": True,
        "requires_sfw_probe": True,
    },
}

# Path to the SFW probe video used during NSFW pipeline verification.
# Real file is a 5s 1080p copyright-free clip committed alongside the repo
# (see data/smoke/sfw_probe.mp4). Keeping this as a module constant rather
# than config because the SOP explicitly requires a single canonical probe.
SFW_PROBE_PATH = "data/smoke/sfw_probe.mp4"


# ---------- status model ----------
BotStatusLiteral = Literal[
    "dev_in_progress",
    "ready_for_landing_page",
    "rejected",
    "blocked",
]


@dataclass
class BotStatus:
    demand_id: str
    status: BotStatusLiteral
    bot_id: str | None = None
    bot_name: str | None = None
    workshop_url: str | None = None
    rh_workflow_id: str | None = None
    acceptance_result: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------- executor plumbing ----------

Executor = Callable[[dict[str, Any], dict[str, Any]], BotStatus]

_EXECUTOR: Executor | None = None


def set_executor(executor: Executor | None) -> None:
    """Register the real bot-building executor.

    Called by ``projects/cyber-developer-cron`` bootstrap at runtime. Passing
    ``None`` reverts to the built-in dry executor. Tests use this to inject
    deterministic stubs.
    """
    global _EXECUTOR
    _EXECUTOR = executor


def get_executor() -> Executor:
    return _EXECUTOR or _dry_executor


def _dry_executor(demand: dict[str, Any], pipeline_ctx: dict[str, Any]) -> BotStatus:
    """Fallback executor used when no real implementation is registered.

    Emits a plausible status so the loop keeps flowing in dev / CI and ops
    can observe end-to-end wiring without needing Playwright / RH credentials.
    """
    route = pipeline_ctx.get("rh_route", {}) or {}
    # Prefer workflow_id, fall back to webapp_id. Stay None when both are
    # unset (e.g. image2video routes where workflow is picked at runtime) —
    # downstream consumers distinguish None from a real id, not from "".
    inferred = route.get("workflow_id") or route.get("webapp_id")
    return BotStatus(
        demand_id=demand.get("id", "?"),
        status="dev_in_progress",
        notes=f"dry executor ({pipeline_ctx.get('pipeline', 'unknown')})",
        rh_workflow_id=str(inferred) if inferred else None,
    )


# ---------- pipeline entry ----------

def resolve_route(demand: dict[str, Any]) -> dict[str, Any]:
    """Look up the RH routing entry for this demand; return {} if unknown."""
    sop = demand.get("sop", "")
    wft = demand.get("workflow_type", "")
    return dict(RH_WORKFLOW_ROUTING.get((sop, wft), {}))


def _redact_id(demand: dict[str, Any]) -> str:
    """Log-safe identifier that never surfaces raw NSFW kw."""
    return demand.get("id", "?")


def run_pipeline(demand: dict[str, Any], *, dry_run: bool = False) -> BotStatus:
    """Route a single demand through its SOP pipeline and return a BotStatus.

    Callers (step4 acceptance / cyber-developer-cron loop) pass already-approved
    demands; this function does NOT re-check human_approval_status — that's
    the caller's responsibility.

    Hard contract: ``demand`` may carry raw NSFW ``kw``. This function:
      * never logs the raw ``kw`` (only ``demand_id``)
      * passes it into the executor verbatim (executor needs real kw for
        RH prompts on SFW; NSFW executor must still avoid plaintext per
        Lucas SOP — encryption is the executor's job, not ours)
    """
    route = resolve_route(demand)
    pipeline_name = "sfw" if demand.get("category") == "sfw" else "nsfw"

    if not route:
        status = BotStatus(
            demand_id=_redact_id(demand),
            status="blocked",
            notes=(f"no RH route for sop={demand.get('sop')!r} "
                   f"workflow_type={demand.get('workflow_type')!r}"),
        )
        bridge.send("log", f"[workshop_sop] {_redact_id(demand)} → blocked (no route)",
                    meta={"demand_id": demand.get("id"), "sop": demand.get("sop")})
        return status

    pipeline_ctx = {
        "pipeline": pipeline_name,
        "rh_route": route,
        "sfw_probe_path": SFW_PROBE_PATH if pipeline_name == "nsfw" else None,
        "dry_run": dry_run,
    }

    if dry_run:
        status = _dry_executor(demand, pipeline_ctx)
    else:
        status = get_executor()(demand, pipeline_ctx)

    # Defensive: ensure the executor filled in demand_id + status. If a buggy
    # executor returns a bare BotStatus, stamp sane defaults so downstream
    # serialization doesn't explode.
    if not status.demand_id:
        status.demand_id = _redact_id(demand)
    if not status.rh_workflow_id:
        inferred = route.get("workflow_id") or route.get("webapp_id")
        # None > "" so consumers can distinguish "not-yet-picked" from
        # "executor explicitly set empty" (lucas-clawd PR#2 review feedback).
        status.rh_workflow_id = str(inferred) if inferred else None

    # Defensive privacy scrub: if a real executor accidentally embedded the
    # raw NSFW kw into `notes` (e.g. via an f-string), strip it before the
    # status crosses any serialization / logging boundary. Layered defense
    # on top of the per-executor privacy contract.
    if demand.get("category") == "nsfw":
        raw_kw = demand.get("kw")
        if raw_kw and status.notes and raw_kw in status.notes:
            status.notes = status.notes.replace(raw_kw, "[REDACTED]")

    bridge.send("log",
                f"[workshop_sop] {_redact_id(demand)} → {status.status} ({pipeline_name})",
                meta={
                    "demand_id": demand.get("id"),
                    "pipeline": pipeline_name,
                    "status": status.status,
                    "rh_workflow_id": status.rh_workflow_id,
                })
    return status


def run_batch(demands: list[dict[str, Any]], *, dry_run: bool = False) -> list[BotStatus]:
    """Run a priority-ordered batch. Caller must pre-sort by priority
    (step2_demand_intake does this). Execution is strictly serial — workshop
    / shellagent / RH are all stateful and concurrent runs collide.
    """
    return [run_pipeline(d, dry_run=dry_run) for d in demands]
