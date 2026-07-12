"""Turn a saved Terraform plan into a human-readable diff for the approval card.

Runs `terraform show -json plan.tfplan` and tallies resource_changes actions
into the familiar 'N to add, N to change, N to destroy' summary, plus a short
per-resource list. This is what the human sees before approving tf_apply.
"""
from __future__ import annotations

import json

from ..runner import TerraformError, TerraformRunner


def _load_plan(runner: TerraformRunner) -> dict:
    res = runner.run("show", "-json", "plan.tfplan")
    if not res.ok:
        raise TerraformError(f"Could not read saved plan: {res.stderr.strip() or 'unknown error'}")
    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError as exc:
        raise TerraformError("Saved plan did not produce valid JSON.") from exc


def assert_plan_is_non_destructive(runner: TerraformRunner) -> None:
    """Hard-stop applies containing deletes, including replacements."""
    data = _load_plan(runner)
    destructive = [
        change.get("address", "?")
        for change in data.get("resource_changes", [])
        if "delete" in change.get("change", {}).get("actions", [])
    ]
    if destructive:
        resources = ", ".join(destructive)
        raise TerraformError(
            "Apply blocked: the saved plan contains destroy or replacement actions for: " + resources
        )


def _classify(actions: list[str]) -> str:
    a = set(actions)
    if a == {"no-op"}:
        return "no-op"
    if a == {"create"}:
        return "add"
    if a == {"delete"}:
        return "destroy"
    if "delete" in a and "create" in a:
        return "replace"
    if a == {"update"}:
        return "change"
    return "/".join(sorted(a))


def summarize_last_plan(runner: TerraformRunner) -> str:
    """Return a readable summary of plan.tfplan; safe to call after tf_plan."""
    try:
        data = _load_plan(runner)
    except TerraformError as exc:
        return str(exc)

    changes = data.get("resource_changes", [])
    tally = {"add": 0, "change": 0, "destroy": 0, "replace": 0}
    lines: list[str] = []
    for ch in changes:
        kind = _classify(ch.get("change", {}).get("actions", []))
        if kind == "no-op":
            continue
        if kind == "replace":
            tally["replace"] += 1
            tally["add"] += 1
            tally["destroy"] += 1
        elif kind in tally:
            tally[kind] += 1
        addr = ch.get("address", "?")
        lines.append(f"  {kind:8s} {addr}")

    if not lines:
        return "Plan: no changes. Infrastructure matches configuration."

    header = (
        f"Plan: {tally['add']} to add, {tally['change']} to change, "
        f"{tally['destroy']} to destroy"
        + (f" (includes {tally['replace']} replacement(s))" if tally["replace"] else "")
    )
    return header + "\n" + "\n".join(lines)
