from pathlib import Path
from unittest.mock import patch

import pytest

from tfagent.flow import BROWNFIELD, GREENFIELD, FlowState
from tfagent.runner import TerraformError, TerraformRunner, _validate_args


@pytest.mark.parametrize("subcommand", ["destroy", "state", "import", "force-unlock"])
def test_destructive_subcommands_are_blocked(subcommand: str) -> None:
    with pytest.raises(TerraformError):
        _validate_args(subcommand, [])


@pytest.mark.parametrize("flag", ["-auto-approve", "-target=x", "-replace=thing", "-destroy"])
def test_dangerous_flags_are_blocked(flag: str) -> None:
    with pytest.raises(TerraformError):
        _validate_args("plan", [flag])


def test_runner_uses_argument_list_and_workspace(tmp_path: Path) -> None:
    with patch("tfagent.runner.shutil.which", return_value="/usr/bin/terraform"):
        runner = TerraformRunner(tmp_path)
    with patch("tfagent.runner.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "ok"
        run.return_value.stderr = ""
        result = runner.run("validate", "-no-color")
    assert result.ok
    run.assert_called_once_with(
        ["terraform", "validate", "-no-color"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )


def _flow_runner(tmp_path: Path, flow: str | None) -> TerraformRunner:
    with patch("tfagent.runner.shutil.which", return_value="/usr/bin/terraform"):
        return TerraformRunner(tmp_path, flow_state=FlowState(flow=flow))


def test_run_destroy_plan_is_refused_outside_greenfield(tmp_path: Path) -> None:
    for flow in (None, BROWNFIELD):
        with pytest.raises(TerraformError, match="only permitted in the greenfield flow"):
            _flow_runner(tmp_path, flow).run_destroy_plan()
    # No flow state at all (bare runner) is refused too.
    with patch("tfagent.runner.shutil.which", return_value="/usr/bin/terraform"):
        bare = TerraformRunner(tmp_path)
    with pytest.raises(TerraformError, match="only permitted in the greenfield flow"):
        bare.run_destroy_plan()


def test_run_destroy_plan_builds_the_expected_command_in_greenfield(tmp_path: Path) -> None:
    runner = _flow_runner(tmp_path, GREENFIELD)
    with patch("tfagent.runner.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "ok"
        run.return_value.stderr = ""
        result = runner.run_destroy_plan()
    assert result.ok
    assert run.call_args.args[0] == [
        "terraform", "plan", "-destroy", "-no-color", "-input=false", "-out=destroy.tfplan"
    ]


def test_run_still_blocks_destroy_flag_even_in_greenfield(tmp_path: Path) -> None:
    runner = _flow_runner(tmp_path, GREENFIELD)
    with pytest.raises(TerraformError):
        runner.run("plan", "-destroy")


@pytest.mark.parametrize("verb", ["rm", "mv", "push", "replace-provider", "pull"])
def test_run_state_read_blocks_mutating_verbs(tmp_path: Path, verb: str) -> None:
    runner = _flow_runner(tmp_path, BROWNFIELD)
    with pytest.raises(TerraformError, match="not permitted"):
        runner.run_state_read(verb)


def test_run_state_read_blocks_flags(tmp_path: Path) -> None:
    runner = _flow_runner(tmp_path, BROWNFIELD)
    with pytest.raises(TerraformError, match="not permitted"):
        runner.run_state_read("list", "-state=elsewhere.tfstate")


def test_run_state_read_allows_read_only_verbs(tmp_path: Path) -> None:
    runner = _flow_runner(tmp_path, BROWNFIELD)
    with patch("tfagent.runner.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "azurerm_resource_group.demo_rg"
        run.return_value.stderr = ""
        result = runner.run_state_read("show", "azurerm_resource_group.demo_rg")
    assert result.ok
    assert run.call_args.args[0] == ["terraform", "state", "show", "azurerm_resource_group.demo_rg"]
