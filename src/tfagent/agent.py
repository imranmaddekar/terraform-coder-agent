"""Build the MAF harness using GitHub Models and scoped Terraform tools."""
from __future__ import annotations

from pathlib import Path

from .config import Settings
from .flow import FlowState, build_flow_tools
from .instructions import SYSTEM_INSTRUCTIONS
from .runner import DESTROY_PLAN_FILENAME, TerraformRunner
from .tools.export import build_export_tool
from .tools.plan_summary import summarize_last_plan
from .tools.terraform import build_terraform_tools

# repo_root/src/tfagent/agent.py -> parents[2] is the repo root, where
# conventions/ lives alongside workspace/. Anchored to this file's location
# (not settings.workspace.parent) so conventions still load correctly if
# TFAGENT_WORKSPACE points somewhere else entirely.
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_conventions(workspace: Path) -> str:
    """Read conventions/conventions.md, trying the repo root first and
    falling back to a directory adjacent to the workspace (the previous,
    workspace-relative convention) for non-standard layouts."""
    for candidate in (_REPO_ROOT / "conventions" / "conventions.md", workspace.parent / "conventions" / "conventions.md"):
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    return ""


def build_agent(settings: Settings) -> tuple:
    """Build the harness agent and return it together with the Terraform
    runner it was wired with, so callers (the console, tests) can build
    Terraform-aware observers/commands (plan summaries, approval cards) off
    the same runner instance instead of re-deriving it."""
    # --- Terraform tools (share one runner rooted at the workspace) ---
    # The FlowState rides on the runner so tools, commands, and observers all
    # see the same session flow without changing this function's return shape.
    flow_state = FlowState()
    runner = TerraformRunner(
        workspace=settings.workspace,
        timeout_seconds=settings.tf_timeout_seconds,
        flow_state=flow_state,
    )
    tf_tools = build_terraform_tools(runner)
    flow_tools = build_flow_tools(flow_state)
    export_tool = build_export_tool(runner, settings.export_repo, settings.export_subdir)

    # summarize_last_plan needs the runner bound; expose zero-arg tools.
    from agent_framework import FileSystemAgentFileStore, create_harness_agent, todos_remaining, todos_remaining_message, tool

    @tool(approval_mode="never_require")
    def summarize_plan() -> str:
        """Summarize the saved plan (plan.tfplan) as a human-readable diff:
        'N to add, N to change, N to destroy' plus a per-resource list."""
        return summarize_last_plan(runner)

    @tool(approval_mode="never_require")
    def summarize_destroy_plan() -> str:
        """Summarize the saved destroy plan (destroy.tfplan) as a human-readable
        diff, listing every sandbox resource the teardown would remove."""
        return summarize_last_plan(runner, DESTROY_PLAN_FILENAME)

    tools = [*tf_tools, *flow_tools, export_tool, summarize_plan, summarize_destroy_plan]

    conventions = _load_conventions(settings.workspace)
    agent_instructions = SYSTEM_INSTRUCTIONS
    if conventions:
        agent_instructions += "\n\n## Organization conventions\n\n" + conventions

    # GitHub Models implements the OpenAI chat-completions protocol.
    from agent_framework.openai import OpenAIChatCompletionClient

    client = OpenAIChatCompletionClient(
        model=settings.github_model,
        api_key=settings.github_token,
        base_url=settings.github_endpoint,
    )

    # --- Harness agent ---
    # todos_remaining() re-invokes the agent while its todo list has open items;
    # loop_max_iterations caps runaway loops.
    agent = create_harness_agent(
        client=client,
        name="TerraformCoderAgent",
        description="A human-gated Terraform coding agent for Azure.",
        agent_instructions=agent_instructions,
        tools=tools,
        max_context_window_tokens=128_000,
        max_output_tokens=16_384,
        file_access_store=FileSystemAgentFileStore(settings.workspace),
        file_memory_store=FileSystemAgentFileStore(settings.workspace / ".agent-memory"),
        file_access_disable_write_tool_approval=True,
        disable_web_search=True,
        loop_should_continue=todos_remaining(looping_modes=["execute"]),
        loop_next_message=todos_remaining_message,
        loop_max_iterations=settings.max_iterations,
    )
    return agent, runner
