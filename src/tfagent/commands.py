"""tfagent-specific slash commands, layered on top of the vendored console."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .console.commands import CommandHandler, build_default_command_handlers
from .tools.plan_summary import summarize_last_plan

if TYPE_CHECKING:
    from agent_framework import Agent, AgentSession

    from .console.state_driver import IUXStateDriver
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


def build_tfagent_command_handlers(
    agent: Agent,
    runner: TerraformRunner,
    *,
    mode_colors: dict[str, str] | None = None,
) -> list[CommandHandler]:
    """Default command handlers plus `/plan`."""
    handlers = build_default_command_handlers(agent, mode_colors=mode_colors)
    handlers.append(PlanCommandHandler(runner))
    return handlers
