from pathlib import Path
from unittest.mock import patch

import pytest

from tfagent.agent import build_agent
from tfagent.config import Settings
from tfagent.console import build_observers_with_planning
from tfagent.console.app import HarnessApp
from tfagent.tools.terraform import tf_apply, tf_plan


def settings(tmp_path: Path) -> Settings:
    return Settings(
        github_token="test-token",
        github_model="openai/gpt-4.1",
        github_endpoint="https://models.github.ai/inference",
        workspace=tmp_path,
        max_iterations=5,
        tf_timeout_seconds=30,
    )


def test_tool_approval_modes_are_enforced() -> None:
    assert tf_plan.approval_mode == "never_require"
    assert tf_apply.approval_mode == "always_require"


def test_harness_builds_with_github_models_and_official_console(tmp_path: Path) -> None:
    with patch("tfagent.runner.shutil.which", return_value="/usr/bin/terraform"):
        agent = build_agent(settings(tmp_path))
    assert agent.name == "TerraformCoderAgent"
    provider_names = {type(provider).__name__ for provider in agent.context_providers}
    assert {"TodoProvider", "AgentModeProvider", "FileAccessProvider"} <= provider_names
    assert build_observers_with_planning(agent)


@pytest.mark.asyncio
async def test_official_textual_console_mounts_headlessly(tmp_path: Path) -> None:
    with patch("tfagent.runner.shutil.which", return_value="/usr/bin/terraform"):
        agent = build_agent(settings(tmp_path))
    app = HarnessApp(
        agent=agent,
        observers=build_observers_with_planning(agent),
        session=agent.create_session(),
        initial_mode="plan",
        title="Terraform Coder Agent",
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.title == "Terraform Coder Agent"
