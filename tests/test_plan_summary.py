import json

from tfagent.runner import TfResult
import pytest

from tfagent.runner import TerraformError
from tfagent.tools.plan_summary import assert_plan_is_non_destructive, summarize_last_plan


class FakeRunner:
    def run(self, *args: str) -> TfResult:
        plan = {
            "resource_changes": [
                {"address": "azurerm_resource_group.demo", "change": {"actions": ["create"]}},
                {"address": "azurerm_storage_account.demo", "change": {"actions": ["update"]}},
                {"address": "azurerm_linux_web_app.demo", "change": {"actions": ["delete", "create"]}},
            ]
        }
        return TfResult("terraform show", 0, json.dumps(plan), "")


def test_plan_summary_counts_changes_and_replacements() -> None:
    summary = summarize_last_plan(FakeRunner())  # type: ignore[arg-type]
    assert "2 to add, 1 to change, 1 to destroy" in summary
    assert "includes 1 replacement" in summary
    assert "azurerm_resource_group.demo" in summary


def test_destructive_saved_plan_is_blocked_before_apply() -> None:
    with pytest.raises(TerraformError, match="Apply blocked"):
        assert_plan_is_non_destructive(FakeRunner())  # type: ignore[arg-type]
