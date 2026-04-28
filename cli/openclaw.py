"""openclaw CLI · the single entrypoint claude code calls."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

# allow running as a script: python cli/openclaw.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import bridge, state  # noqa: E402
from core.config import load_config  # noqa: E402
from core.orchestrator import Orchestrator  # noqa: E402

console = Console()


@click.group()
def cli() -> None:
    """openclaw: 自动化两大 loop 的统一入口。"""


@cli.command()
def doctor() -> None:
    """检查环境与配置完整性。"""
    cfg = load_config()
    table = Table(title="openclaw doctor")
    table.add_column("check"); table.add_column("status"); table.add_column("detail")

    table.add_row("config", "ok", f"{len(cfg.loops)} loops loaded")
    for name, loop in cfg.loops.items():
        table.add_row(f"loop:{name}", "ok", f"{len(loop.steps)} steps")

    state.init()
    table.add_row("state.db", "ok", "sqlite ready")

    bridge_cfg = cfg.raw.get("bridge", {})
    for ch, c in bridge_cfg.items():
        enabled = c.get("enabled", False)
        table.add_row(f"bridge:{ch}", "enabled" if enabled else "disabled",
                      c.get("webhook_env", ""))

    console.print(table)


@cli.command()
@click.argument("loop")
@click.option("--from", "from_step", type=int, default=None,
              help="从第几步开始")
@click.option("--to", "to_step", type=int, default=None, help="执行到第几步")
@click.option("--step", "only", default=None, help="只执行某一步 (id 或 key)")
@click.option("--dry", is_flag=True, default=False, help="不真实执行，只产出计划")
def run(loop: str, from_step: int | None, to_step: int | None,
        only: str | None, dry: bool) -> None:
    """运行某个 loop（或其中片段）。"""
    cfg = load_config()
    orch = Orchestrator(cfg)
    mode = "dry" if dry else "run"
    reports = orch.run_loop(loop, mode=mode, from_step=from_step,
                            to_step=to_step, only=only)
    path = orch.write_report(loop, mode, reports)
    _print_reports(reports)
    console.print(f"\n[bold]report:[/bold] {path}")


@cli.command()
@click.argument("ref")
def verify(ref: str) -> None:
    """对单步做验证: openclaw verify <loop>.<step>"""
    if "." not in ref:
        raise click.BadParameter("用法: openclaw verify <loop>.<step>")
    loop_name, step_ref = ref.split(".", 1)
    cfg = load_config()
    orch = Orchestrator(cfg)
    reports = orch.run_loop(loop_name, mode="verify", only=step_ref)
    path = orch.write_report(loop_name, "verify", reports)
    _print_reports(reports)
    console.print(f"\n[bold]report:[/bold] {path}")


@cli.command()
def status() -> None:
    """展示每个 loop 当前游标与最近运行。"""
    cfg = load_config()
    table = Table(title="openclaw status")
    table.add_column("loop"); table.add_column("cursor")
    table.add_column("last status"); table.add_column("last step")
    for name in cfg.loops:
        cur = state.get_cursor(name)
        runs = state.recent_runs(name, limit=1)
        last = runs[0] if runs else None
        table.add_row(name, str(cur),
                      last["status"] if last else "-",
                      f"{last['step_id']}/{last['step_key']}" if last else "-")
    console.print(table)


@cli.group()
def bridge_cmd() -> None:
    """信息桥工具: wechat / slack / 本地队列。"""


@bridge_cmd.command("send")
@click.option("--channel", required=True, type=click.Choice(["wechat", "slack", "log"]))
@click.option("--message", required=True)
def bridge_send(channel: str, message: str) -> None:
    ok = bridge.send(channel, message)
    console.print(f"delivered: [bold]{ok}[/bold]")


@bridge_cmd.command("queue")
def bridge_queue() -> None:
    p = bridge.drain_queue()
    if not p.exists():
        console.print("(empty)")
        return
    for line in p.read_text(encoding="utf-8").splitlines()[-10:]:
        console.print(json.loads(line))


cli.add_command(bridge_cmd, name="bridge")


def _print_reports(reports: list) -> None:
    table = Table()
    table.add_column("step"); table.add_column("name")
    table.add_column("mode"); table.add_column("status"); table.add_column("verify")
    for r in reports:
        v = r.verify.expression + (" ✓" if r.verify.ok else " ✗") if r.verify else "-"
        table.add_row(str(r.step.id), r.step.name, r.mode, r.status, v)
    console.print(table)


if __name__ == "__main__":
    cli()
