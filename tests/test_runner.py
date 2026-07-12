from pathlib import Path
from unittest.mock import patch

import pytest

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
