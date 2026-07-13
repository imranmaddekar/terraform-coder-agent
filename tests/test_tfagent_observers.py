import json

import pytest
from agent_framework import Content

from tfagent.commands import PlanCommandHandler
from tfagent.observers import TerraformApprovalObserver, TerraformResultDisplayObserver
from tfagent.runner import TfResult


class FakeUX:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def append_info_line(self, text: str, color: str | None = None) -> None:
        self.lines.append(text)


class FakePlanRunner:
    """Duck-types TerraformRunner.run() for summarize_last_plan()."""

    def run(self, *args: str) -> TfResult:
        plan = {
            "resource_changes": [
                {"address": "azurerm_resource_group.demo", "change": {"actions": ["create"]}},
            ]
        }
        return TfResult("terraform show", 0, json.dumps(plan), "")


def _approval_request(name: str, call_id: str = "call-1"):
    call = Content.from_function_call(call_id=call_id, name=name, arguments={})
    return Content.from_function_approval_request(id="req-1", function_call=call)


@pytest.mark.asyncio
async def test_tf_apply_approval_card_shows_plan_diff_and_no_always_options() -> None:
    observer = TerraformApprovalObserver(FakePlanRunner())  # type: ignore[arg-type]
    ux = FakeUX()

    await observer.on_content(ux, _approval_request("tf_apply"), agent=None, session=None)
    actions = await observer.on_stream_complete(ux, agent=None, session=None)

    assert actions is not None and len(actions) == 1
    question = actions[0]
    assert "tf_apply" in question.prompt
    assert "1 to add" in question.prompt
    assert "azurerm_resource_group.demo" in question.prompt
    assert question.choices == ["Approve this call", "Deny"]


@pytest.mark.asyncio
async def test_non_apply_tool_keeps_always_approve_options_and_no_plan_text() -> None:
    observer = TerraformApprovalObserver(FakePlanRunner())  # type: ignore[arg-type]
    ux = FakeUX()

    await observer.on_content(ux, _approval_request("some_other_tool"), agent=None, session=None)
    actions = await observer.on_stream_complete(ux, agent=None, session=None)

    assert actions is not None and len(actions) == 1
    question = actions[0]
    assert "1 to add" not in question.prompt
    assert len(question.choices) == 4
    assert "Deny" in question.choices


@pytest.mark.asyncio
async def test_result_display_observer_shows_watched_tool_output() -> None:
    observer = TerraformResultDisplayObserver()
    ux = FakeUX()

    call = Content.from_function_call(call_id="call-1", name="tf_validate", arguments={})
    await observer.on_content(ux, call, agent=None, session=None)

    result = Content.from_function_result(call_id="call-1", result="Success! The configuration is valid.")
    await observer.on_content(ux, result, agent=None, session=None)

    assert len(ux.lines) == 1
    assert "tf_validate" in ux.lines[0]
    assert "Success! The configuration is valid." in ux.lines[0]


@pytest.mark.asyncio
async def test_result_display_observer_ignores_unwatched_tools() -> None:
    observer = TerraformResultDisplayObserver()
    ux = FakeUX()

    call = Content.from_function_call(call_id="call-1", name="file_access_write", arguments={})
    await observer.on_content(ux, call, agent=None, session=None)

    result = Content.from_function_result(call_id="call-1", result="wrote main.tf")
    await observer.on_content(ux, result, agent=None, session=None)

    assert ux.lines == []


@pytest.mark.asyncio
async def test_plan_command_bypasses_the_model() -> None:
    handler = PlanCommandHandler(FakePlanRunner())  # type: ignore[arg-type]
    ux = FakeUX()

    handled = await handler.try_handle("/plan", session=None, ux=ux)

    assert handled is True
    assert len(ux.lines) == 1
    assert "1 to add" in ux.lines[0]


@pytest.mark.asyncio
async def test_plan_command_ignores_other_input() -> None:
    handler = PlanCommandHandler(FakePlanRunner())  # type: ignore[arg-type]
    ux = FakeUX()

    handled = await handler.try_handle("/todos", session=None, ux=ux)

    assert handled is False
    assert ux.lines == []
