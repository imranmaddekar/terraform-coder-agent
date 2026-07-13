"""tfagent-specific console observers layered on top of the vendored console.

Kept out of `console/` (Microsoft's vendored package, see THIRD_PARTY_NOTICES)
so the provenance of that directory stays clean; these subclass/compose the
vendored observers instead of patching them in place.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .console.app_state import ChoiceFollowUpQuestion
from .console.formatters import ToolCallFormatter, build_default_formatters
from .console.observers import (
    ConsoleObserver,
    ErrorDisplayObserver,
    PlanningOutputObserver,
    ReasoningDisplayObserver,
    TextOutputObserver,
    ToolApprovalObserver,
    ToolCallDisplayObserver,
    UsageDisplayObserver,
    WebSearchDisplayObserver,
)
from .tools.plan_summary import summarize_last_plan
from .tools.terraform import APPROVAL_REQUIRED_TOOL_NAMES

if TYPE_CHECKING:
    from agent_framework import Agent, Content

    from .console.app_state import FollowUpAction
    from .console.state_driver import IUXStateDriver
    from .runner import TerraformRunner

# Tools whose result is worth showing the human as it happens, since the
# model's own narration of "ran validate, it passed" is not something the
# human can independently check otherwise (see README: tool calls are shown,
# tool *results* are not, by the vendored console).
_WATCHED_RESULT_TOOLS = {"tf_fmt", "tf_validate", "tf_init", "tf_plan", "tf_apply", "summarize_plan"}

_RESULT_PREVIEW_CHARS = 1200


class TerraformToolFormatter(ToolCallFormatter):
    """Formats tf_* tool calls with a short human-readable detail string."""

    _DETAILS = {
        "tf_fmt": "(reformat *.tf)",
        "tf_validate": "(syntax + internal consistency check)",
        "tf_init": "(download providers/modules, local state)",
        "tf_plan": "(save plan.tfplan; read-only)",
        "tf_apply": "(apply plan.tfplan -> REAL Azure)",
        "summarize_plan": "(diff saved plan.tfplan)",
    }

    def can_format(self, call: Content) -> bool:
        return call.name in self._DETAILS

    def format_detail(self, call: Content) -> str | None:
        return self._DETAILS.get(call.name or "")


class TerraformResultDisplayObserver(ConsoleObserver):
    """Displays the result of tf_* (and summarize_plan) tool calls.

    The vendored console shows tool *calls* (ToolCallDisplayObserver) but
    never tool *results* — for a verification tool like Terraform that
    inverts the trust model: the human would otherwise only learn whether
    `tf_validate` or `tf_plan` succeeded from the model's own paraphrase.
    """

    def __init__(self) -> None:
        self._names_by_call_id: dict[str, str] = {}

    async def on_content(
        self,
        ux: IUXStateDriver,
        content: Content,
        agent: Agent,
        session: Any,
    ) -> None:
        if content.type == "function_call":
            if content.call_id and content.name:
                self._names_by_call_id[content.call_id] = content.name
            return

        if content.type != "function_result":
            return

        name = self._names_by_call_id.pop(content.call_id or "", None)
        if name not in _WATCHED_RESULT_TOOLS:
            return

        if content.exception:
            text = f"error: {content.exception}"
            color = "red"
        else:
            text = (content.result or "").strip() or "(no output)"
            color = "dim"

        if len(text) > _RESULT_PREVIEW_CHARS:
            text = text[:_RESULT_PREVIEW_CHARS] + "\n... (truncated)"

        ux.append_info_line(f"   └─ {name} result:\n{text}", color)


class TerraformApprovalObserver(ToolApprovalObserver):
    """Approval observer that shows the saved plan's diff on the tf_apply card
    and never offers a blanket "always approve" for it.

    The base observer's card carries only the tool name — `tf_apply` takes no
    arguments, so there is nothing else on the card, and the human's decision
    rests entirely on the model's chat-text paraphrase of the plan. This
    subclass reads plan.tfplan directly (the same deterministic path
    `summarize_plan` uses) and puts that diff on the card itself.
    """

    def __init__(self, runner: TerraformRunner) -> None:
        super().__init__()
        self._runner = runner

    def _build_approval_question(self, request: Content):
        tool_name = self._format_tool_name(request)
        function_call = getattr(request, "function_call", None)
        call_name = getattr(function_call, "name", None)
        is_gated_apply = call_name in APPROVAL_REQUIRED_TOOL_NAMES

        prompt = f"🔐 Tool approval: {tool_name}"
        if is_gated_apply:
            try:
                plan_text = summarize_last_plan(self._runner)
            except Exception as exc:  # noqa: BLE001 - surface failure to the human, don't hide it
                plan_text = f"(could not read the saved plan: {exc})"
            prompt = f"{prompt}\n{plan_text}"

        approve_once = "Approve this call"
        deny = "Deny"
        if is_gated_apply:
            # No "always approve" choice for a human-gated apply: this tool
            # must be confirmed every time, never blanket-approved by a
            # misclick or muscle memory carried over from other tools.
            choices = [approve_once, deny]
        else:
            always_tool = "Always approve this tool (any arguments)"
            always_tool_args = "Always approve this tool with these arguments"
            choices = [approve_once, always_tool, always_tool_args, deny]

        async def continuation(selection: str, ux: IUXStateDriver):
            from agent_framework import (
                Message,
                create_always_approve_tool_response,
                create_always_approve_tool_with_arguments_response,
            )

            if selection == deny:
                response_content = request.to_function_approval_response(approved=False)
                action_label = "❌ Denied"
                color = "red"
            elif not is_gated_apply and selection == always_tool:
                response_content = create_always_approve_tool_response(
                    request, reason="User chose to always approve this tool"
                )
                action_label = "✅ Always approved (any args)"
                color = "green"
            elif not is_gated_apply and selection == always_tool_args:
                response_content = create_always_approve_tool_with_arguments_response(
                    request, reason="User chose to always approve this tool with these arguments"
                )
                action_label = "✅ Always approved (these args)"
                color = "green"
            else:
                response_content = request.to_function_approval_response(approved=True)
                action_label = "✅ Approved"
                color = "green"

            ux.append_info_line(
                f"🔹 {prompt}\n   └─ [{color}]{action_label}[/{color}]",
                "dim",
            )

            return Message(role="user", contents=[response_content])

        return ChoiceFollowUpQuestion(
            prompt=prompt,
            choices=choices,
            allow_custom_text=False,
            continuation=continuation,
        )


def build_tfagent_observers(
    agent: Agent,
    runner: TerraformRunner,
    plan_mode_name: str = "plan",
    execution_mode_name: str = "execute",
    *,
    mode_colors: dict[str, str] | None = None,
) -> list[ConsoleObserver]:
    """Same shape as console.build_observers_with_planning(), substituting the
    Terraform-aware approval observer, a formatter for tf_* tool calls, and a
    tool-result display observer for tf_* / summarize_plan."""
    from agent_framework import AgentModeProvider

    mode_provider = next(
        (p for p in agent.context_providers if isinstance(p, AgentModeProvider)),
        None,
    )
    if mode_provider is None:
        msg = (
            "Planning observers require an AgentModeProvider on the agent. "
            "Use create_harness_agent() or add AgentModeProvider to context_providers."
        )
        raise ValueError(msg)

    formatters = [TerraformToolFormatter(), *build_default_formatters()]

    return [
        ToolCallDisplayObserver(formatters=formatters),
        TerraformResultDisplayObserver(),
        WebSearchDisplayObserver(),
        TerraformApprovalObserver(runner),
        ErrorDisplayObserver(),
        ReasoningDisplayObserver(),
        UsageDisplayObserver(),
        PlanningOutputObserver(
            mode_provider,
            plan_mode_name,
            execution_mode_name,
            mode_colors=mode_colors,
        ),
    ]
