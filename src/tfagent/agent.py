"""Build the MAF harness using GitHub Models and scoped Terraform tools."""
from __future__ import annotations

from pathlib import Path

from .config import Settings
from .instructions import SYSTEM_INSTRUCTIONS
from .runner import TerraformRunner
from .tools.plan_summary import summarize_last_plan
from .tools.terraform import build_terraform_tools


def build_agent(settings: Settings):
    # --- Terraform tools (share one runner rooted at the workspace) ---
    runner = TerraformRunner(
        workspace=settings.workspace,
        timeout_seconds=settings.tf_timeout_seconds,
    )
    tf_tools = build_terraform_tools(runner)

    # summarize_last_plan needs the runner bound; expose a zero-arg tool.
    from agent_framework import FileSystemAgentFileStore, create_harness_agent, todos_remaining, todos_remaining_message, tool

    @tool(approval_mode="never_require")
    def summarize_plan() -> str:
        """Summarize the saved plan (plan.tfplan) as a human-readable diff:
        'N to add, N to change, N to destroy' plus a per-resource list."""
        return summarize_last_plan(runner)

    tools = [*tf_tools, summarize_plan]

    conventions_path = Path(settings.workspace).parent / "conventions" / "conventions.md"
    conventions = conventions_path.read_text(encoding="utf-8") if conventions_path.exists() else ""
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
    return agent
