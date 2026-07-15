from pathlib import Path
from unittest.mock import patch

import pytest

from tfagent.agent import build_agent
from tfagent.commands import build_tfagent_command_handlers
from tfagent.config import Settings
from tfagent.console.app import HarnessApp
from tfagent.instructions import SYSTEM_INSTRUCTIONS
from tfagent.observers import build_tfagent_observers
from tfagent.runner import TerraformRunner
from tfagent.tools.terraform import build_terraform_tools


def settings(tmp_path: Path, provider: str = "azure_openai") -> Settings:
    return Settings(
        model_provider=provider,
        azure_openai_endpoint="https://unit-test.openai.azure.com",
        azure_openai_api_key="test-key",
        azure_openai_deployment="gpt-4.1",
        azure_openai_api_version="2024-10-21",
        anthropic_foundry_resource="unit-test-foundry",
        anthropic_foundry_api_key="test-claude-key",
        anthropic_model="claude-sonnet-4-5",
        workspace=tmp_path,
        max_iterations=5,
        tf_timeout_seconds=30,
    )


def test_tool_approval_modes_are_enforced(tmp_path: Path) -> None:
    with patch("tfagent.runner.shutil.which", return_value="/usr/bin/terraform"):
        runner = TerraformRunner(tmp_path)
    tools = {t.name: t for t in build_terraform_tools(runner)}
    assert tools["tf_plan"].approval_mode == "never_require"
    assert tools["tf_plan_destroy"].approval_mode == "never_require"
    assert tools["tf_state_list"].approval_mode == "never_require"
    assert tools["tf_apply"].approval_mode == "always_require"
    assert tools["tf_destroy_sandbox"].approval_mode == "always_require"


def test_file_edit_instructions_match_maf_file_access_contract() -> None:
    assert "relative to the workspace" in SYSTEM_INSTRUCTIONS
    assert "overwrite=true" in SYSTEM_INSTRUCTIONS
    assert "file_access_replace" in SYSTEM_INSTRUCTIONS


def test_instructions_cover_apply_rejection_and_hcl_level_bypasses() -> None:
    assert "denies the apply approval" in SYSTEM_INSTRUCTIONS
    assert "provisioner" in SYSTEM_INSTRUCTIONS
    assert 'data "external"' in SYSTEM_INSTRUCTIONS


def test_instructions_point_at_the_three_skills() -> None:
    for skill in ("terraform-conventions", "plan-review-checklist", "brownfield-drift-review"):
        assert skill in SYSTEM_INSTRUCTIONS


def test_harness_builds_with_azure_openai_and_official_console(tmp_path: Path) -> None:
    with patch("tfagent.runner.shutil.which", return_value="/usr/bin/terraform"):
        agent, runner = build_agent(settings(tmp_path))
    assert agent.name == "TerraformCoderAgent"
    provider_names = {type(provider).__name__ for provider in agent.context_providers}
    assert {"TodoProvider", "AgentModeProvider", "FileAccessProvider", "SkillsProvider"} <= provider_names
    assert build_tfagent_observers(agent, runner)
    handlers = build_tfagent_command_handlers(agent, runner)
    handler_names = {type(h).__name__ for h in handlers}
    assert {"PlanCommandHandler", "FlowCommandHandler"} <= handler_names


def test_harness_builds_with_claude_on_foundry(tmp_path: Path) -> None:
    with patch("tfagent.runner.shutil.which", return_value="/usr/bin/terraform"):
        agent, _runner = build_agent(settings(tmp_path, provider="foundry_claude"))
    assert agent.name == "TerraformCoderAgent"


def test_chat_client_factory_picks_the_configured_provider(tmp_path: Path) -> None:
    from agent_framework.anthropic import AnthropicFoundryClient
    from agent_framework.openai import OpenAIChatCompletionClient

    from tfagent.agent import _build_chat_client

    assert isinstance(_build_chat_client(settings(tmp_path)), OpenAIChatCompletionClient)
    assert isinstance(
        _build_chat_client(settings(tmp_path, provider="foundry_claude")),
        AnthropicFoundryClient,
    )


@pytest.mark.asyncio
async def test_official_textual_console_mounts_headlessly(tmp_path: Path) -> None:
    with patch("tfagent.runner.shutil.which", return_value="/usr/bin/terraform"):
        agent, runner = build_agent(settings(tmp_path))
    app = HarnessApp(
        agent=agent,
        observers=build_tfagent_observers(agent, runner),
        session=agent.create_session(),
        initial_mode="plan",
        title="Terraform Coder Agent",
        command_handlers=build_tfagent_command_handlers(agent, runner),
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.title == "Terraform Coder Agent"
