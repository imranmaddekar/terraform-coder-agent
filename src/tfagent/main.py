"""Console entry point.

Uses MAF's shared harness console (Textual/Rich based) which streams the
agent's output, shows the todo list and current mode, and surfaces tool
approval prompts (Approve/Reject) — including the tf_apply gate — for free.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys

from rich.console import Console

from .agent import build_agent
from .commands import build_tfagent_command_handlers
from .config import Settings
from .observers import build_tfagent_observers

console = Console()

WELCOME = (
    "[bold]Terraform Coder Agent[/bold]\n"
    "Real Azure sandbox subscription - LOCAL Terraform state - apply is always human-approved.\n"
    "The real deployment happens via YOUR pipeline; this agent only validates.\n\n"
    "Each session runs one of two flows (the agent will ask, or use /flow):\n"
    "  greenfield - build new infra, sandbox-validate with apply, tear down, export\n"
    "  brownfield - change deployed infra, plan-only: the diff is the deliverable\n\n"
    "Describe what infrastructure you want. The agent starts in PLAN mode: it will\n"
    "ask clarifying questions, propose a structure, then (in EXECUTE mode) write HCL,\n"
    "run fmt/init/validate/plan, show you the diff, and ask before every apply.\n"
)

# Azure service-principal credentials the azurerm provider needs. Presence
# alone doesn't guarantee they're *valid*, but their absence is the more
# common failure: a dev with a working model API key sails through plan-mode
# conversation, file writes, fmt, init, and validate, and only hits an Azure
# auth error at tf_plan — many minutes into a session. Catch it up front.
_ARM_ENV_VARS = ("ARM_SUBSCRIPTION_ID", "ARM_TENANT_ID", "ARM_CLIENT_ID", "ARM_CLIENT_SECRET")


def _preflight(settings: Settings) -> None:
    missing = [
        k for k, v in {
            **settings.required_model_env,
            **{name: os.getenv(name, "") for name in _ARM_ENV_VARS},
        }.items() if not v
    ]
    if missing:
        console.print(f"[red]Missing env:[/red] {', '.join(missing)} — copy .env.example to .env")
        sys.exit(1)
    if shutil.which("terraform") is None:
        console.print("[red]terraform CLI was not found on PATH.[/red]")
        sys.exit(1)


def _print_check(settings: Settings) -> int:
    checks = {
        **{f"Model env ({name})": bool(value) for name, value in settings.required_model_env.items()},
        "Terraform CLI": shutil.which("terraform") is not None,
        "Workspace": settings.workspace.is_dir(),
        **{f"Azure env ({name})": bool(os.getenv(name)) for name in _ARM_ENV_VARS},
    }
    console.print(f"Provider: [bold]{settings.model_provider}[/bold]")
    console.print(f"MAF model: [bold]{settings.model_label}[/bold]")
    console.print(f"Endpoint: {settings.model_endpoint_label or '(not configured)'}")
    for label, ok in checks.items():
        console.print(f"[{'green' if ok else 'red'}]{'OK' if ok else 'MISSING'}[/] {label}")
    return 0 if all(checks.values()) else 1


async def _run() -> None:
    settings = Settings.load()
    _preflight(settings)
    console.print(WELCOME)
    agent, runner = build_agent(settings)

    from .console import run_agent_async

    await run_agent_async(
        agent,
        session=agent.create_session(),
        observers=build_tfagent_observers(agent, runner),
        command_handlers=build_tfagent_command_handlers(agent, runner),
        initial_mode="plan",
        title="Terraform Coder Agent",
        placeholder="Describe the Azure infrastructure you want to build...",
        max_context_window_tokens=128_000,
        max_output_tokens=16_384,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Terraform Coder Agent")
    parser.add_argument("--check", action="store_true", help="check configuration without starting the TUI")
    args = parser.parse_args()
    if args.check:
        raise SystemExit(_print_check(Settings.load()))
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        console.print("\n[dim]bye[/dim]")


if __name__ == "__main__":
    main()
