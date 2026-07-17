"""Build the MAF harness on an Azure AI Foundry-hosted model (GPT via Azure
OpenAI, or Claude via Foundry's Anthropic endpoint) with scoped Terraform
tools."""
from __future__ import annotations

from pathlib import Path

from .config import AZURE_OPENAI, GITHUB_MODELS, Settings
from .flow import FlowState, build_flow_tools
from .instructions import SYSTEM_INSTRUCTIONS
from .runner import DESTROY_PLAN_FILENAME, TerraformRunner
from .tools.export import build_export_tool
from .tools.plan_summary import summarize_last_plan
from .tools.terraform import build_terraform_tools

# repo_root/src/tfagent/agent.py -> parents[2] is the repo root, where
# skills/ lives alongside workspace/. Anchored to this file's location
# (not settings.workspace.parent) so skills still load correctly if
# TFAGENT_WORKSPACE points somewhere else entirely.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILLS_DIR = _REPO_ROOT / "skills"


def _build_skills_provider():
    """Progressive domain knowledge from skills/*/SKILL.md files.

    Loading a skill (and reading its resources) is read-only, so both are
    frictionless; deliberately NO script_runner is configured, so skill
    scripts can never execute — consistent with this project's
    no-arbitrary-execution safety posture even if someone drops a script
    into a skill folder.
    """
    from agent_framework import SkillsProvider

    return SkillsProvider.from_paths(
        [_SKILLS_DIR],
        disable_load_skill_approval=True,
        disable_read_skill_resource_approval=True,
    )


def _build_chat_client(settings: Settings):
    """Construct the MAF chat client for the configured provider.

    All branches authenticate with an API key (no Entra/azure-identity):
    - azure_openai: the unified OpenAIChatCompletionClient routes to Azure
      when given azure_endpoint/api_version; model is the DEPLOYMENT name.
    - github_models: free, rate-limited endpoint that speaks the same OpenAI
      chat-completions protocol, just with a different base_url and a
      GitHub token instead of an Azure key.
    - foundry_claude: Claude in Foundry speaks the Anthropic Messages API on
      the resource's /anthropic endpoint, not the OpenAI protocol, so it
      needs the dedicated AnthropicFoundryClient.
    """
    if settings.model_provider == AZURE_OPENAI:
        from agent_framework.openai import OpenAIChatCompletionClient

        return OpenAIChatCompletionClient(
            model=settings.azure_openai_deployment,
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
        )

    if settings.model_provider == GITHUB_MODELS:
        from agent_framework.openai import OpenAIChatCompletionClient

        return OpenAIChatCompletionClient(
            model=settings.github_model,
            api_key=settings.github_token,
            base_url=settings.github_endpoint,
        )

    from agent_framework.anthropic import AnthropicFoundryClient

    return AnthropicFoundryClient(
        model=settings.anthropic_model,
        resource=settings.anthropic_foundry_resource,
        api_key=settings.anthropic_foundry_api_key,
    )


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

    client = _build_chat_client(settings)

    # --- Harness agent ---
    # todos_remaining() re-invokes the agent while its todo list has open items;
    # loop_max_iterations caps runaway loops.
    agent = create_harness_agent(
        client=client,
        name="TerraformCoderAgent",
        description="A human-gated Terraform coding agent for Azure.",
        agent_instructions=SYSTEM_INSTRUCTIONS,
        tools=tools,
        max_context_window_tokens=128_000,
        max_output_tokens=16_384,
        file_access_store=FileSystemAgentFileStore(settings.workspace),
        file_memory_store=FileSystemAgentFileStore(settings.workspace / ".agent-memory"),
        file_access_disable_write_tool_approval=True,
        disable_web_search=True,
        skills_provider=_build_skills_provider(),
        loop_should_continue=todos_remaining(looping_modes=["execute"]),
        loop_next_message=todos_remaining_message,
        loop_max_iterations=settings.max_iterations,
    )
    return agent, runner
