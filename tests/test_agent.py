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


def settings(tmp_path: Path) -> Settings:
    return Settings(
        github_token="test-token",
        github_model="openai/gpt-4.1",
        github_endpoint="https://models.github.ai/inference",
        workspace=tmp_path,
        max_iterations=5,
        tf_timeout_seconds=30,
    )


def test_tool_approval_modes_are_enforced(tmp_path: Path) -> None:
    with patch("tfagent.runner.shutil.which", return_value="/usr/bin/terraform"):
        runner = TerraformRunner(tmp_path)
    _tf_fmt, _tf_validate, _tf_init, tf_plan, tf_apply = build_terraform_tools(runner)
    assert tf_plan.approval_mode == "never_require"
    assert tf_apply.approval_mode == "always_require"


def test_file_edit_instructions_match_maf_file_access_contract() -> None:
    assert "relative to the workspace" in SYSTEM_INSTRUCTIONS
    assert "overwrite=true" in SYSTEM_INSTRUCTIONS
    assert "file_access_replace" in SYSTEM_INSTRUCTIONS


def test_instructions_cover_apply_rejection_and_hcl_level_bypasses() -> None:
    assert "denies the apply approval" in SYSTEM_INSTRUCTIONS
    assert "provisioner" in SYSTEM_INSTRUCTIONS
    assert 'data "external"' in SYSTEM_INSTRUCTIONS


def test_harness_builds_with_github_models_and_official_console(tmp_path: Path) -> None:
    with patch("tfagent.runner.shutil.which", return_value="/usr/bin/terraform"):
        agent, runner = build_agent(settings(tmp_path))
    assert agent.name == "TerraformCoderAgent"
    provider_names = {type(provider).__name__ for provider in agent.context_providers}
    assert {"TodoProvider", "AgentModeProvider", "FileAccessProvider"} <= provider_names
    assert build_tfagent_observers(agent, runner)
    assert build_tfagent_command_handlers(agent, runner)


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
