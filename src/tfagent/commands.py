"""tfagent-specific slash commands, layered on top of the vendored console."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .console.commands import CommandHandler, build_default_command_handlers
from .flow import FLOWS, GREENFIELD
from .tools.plan_summary import summarize_last_plan

if TYPE_CHECKING:
    from agent_framework import Agent, AgentSession

    from .console.state_driver import IUXStateDriver
    from .flow import FlowState
    from .runner import TerraformRunner


class PlanCommandHandler(CommandHandler):
    """`/plan` — show the saved plan's diff straight from disk.

    Bypasses the model entirely (calls the same `summarize_last_plan` the
    tf_apply approval card uses) so a human can check what tf_apply would
    actually do without waiting for, or trusting, the model's paraphrase.
    """

    def __init__(self, runner: TerraformRunner) -> None:
        self._runner = runner

    def get_help_text(self) -> str | None:
        return "/plan (show the saved plan's diff)"

    async def try_handle(
        self,
        user_input: str,
        session: AgentSession,
        ux: IUXStateDriver,
    ) -> bool:
        if user_input.strip().lower() != "/plan":
            return False

        ux.append_info_line(summarize_last_plan(self._runner))
        return True


class FlowCommandHandler(CommandHandler):
    """`/flow` — show or set the session flow (greenfield | brownfield).

    Sets the shared FlowState directly, bypassing the model entirely: the
    human can pick or correct the flow without waiting for (or trusting) the
    agent's set_session_flow call. The model reads the result through
    get_session_flow and through the flow-gated tools' error messages.
    """

    def __init__(self, flow_state: FlowState) -> None:
        self._flow_state = flow_state

    def get_help_text(self) -> str | None:
        return "/flow [greenfield|brownfield] (show or set the session flow)"

    async def try_handle(
        self,
        user_input: str,
        session: AgentSession,
        ux: IUXStateDriver,
    ) -> bool:
        stripped = user_input.strip()
        lower = stripped.lower()
        if not (lower == "/flow" or lower.startswith("/flow ")):
            return False

        parts = stripped.split(None, 1)
        if len(parts) < 2:
            current = self._flow_state.flow or "not chosen"
            ux.append_info_line(f"Current flow: {current}")
            return True

        new_flow = parts[1].strip().lower()
        if new_flow not in FLOWS:
            ux.append_info_line(
                f"Unknown flow '{parts[1].strip()}'; expected one of: {', '.join(FLOWS)}.",
                color="red",
            )
            return True

        self._flow_state.flow = new_flow
        detail = (
            "sandbox self-validation with human-gated apply and teardown, then export"
            if new_flow == GREENFIELD
            else "plan-only against deployed infra; apply/destroy disabled, diff is the deliverable"
        )
        ux.append_info_line(f"Flow set to {new_flow} ({detail}).", color="green")
        return True


def build_tfagent_command_handlers(
    agent: Agent,
    runner: TerraformRunner,
    *,
    mode_colors: dict[str, str] | None = None,
) -> list[CommandHandler]:
    """Default command handlers plus `/plan` and `/flow`."""
    handlers = build_default_command_handlers(agent, mode_colors=mode_colors)
    handlers.append(PlanCommandHandler(runner))
    if runner.flow_state is not None:
        handlers.append(FlowCommandHandler(runner.flow_state))
    return handlers
