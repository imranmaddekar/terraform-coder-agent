"""Turn a saved Terraform plan into a human-readable diff for the approval card.

Runs `terraform show -json plan.tfplan` and tallies resource_changes actions
into the familiar 'N to add, N to change, N to destroy' summary, plus a short
per-resource list. This is what the human sees before approving tf_apply.
"""
from __future__ import annotations

import json

from ..runner import TerraformError, TerraformRunner


def _load_plan(runner: TerraformRunner, plan_filename: str = "plan.tfplan") -> dict:
    res = runner.run("show", "-json", plan_filename)
    if not res.ok:
        raise TerraformError(f"Could not read saved plan: {res.stderr.strip() or 'unknown error'}")
    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError as exc:
        raise TerraformError("Saved plan did not produce valid JSON.") from exc


def assert_plan_is_non_destructive(runner: TerraformRunner) -> None:
    """Hard-stop applies containing deletes, replacements, or state removal.

    "forget" is the action Terraform 1.7+ assigns to a `removed { ... }` block
    with no `destroy` provisioner: the resource is dropped from state (and
    thus from management) without a corresponding `delete` action, so it must
    be checked for explicitly rather than piggybacking on the "delete" check.
    """
    data = _load_plan(runner)
    destructive = [
        change.get("address", "?")
        for change in data.get("resource_changes", [])
        if {"delete", "forget"} & set(change.get("change", {}).get("actions", []))
    ]
    if destructive:
        resources = ", ".join(destructive)
        raise TerraformError(
            "Apply blocked: the saved plan contains destroy, replacement, or "
            "state-removal (forget) actions for: " + resources
        )


def assert_plan_is_destroy_only(runner: TerraformRunner, plan_filename: str) -> None:
    """Hard-stop a teardown apply whose plan does anything besides delete.

    The mirror image of ``assert_plan_is_non_destructive``: a greenfield
    sandbox teardown must only remove resources, so any create/update/forget
    action in the saved destroy plan means the file is not a pure destroy
    plan and must not be applied through the teardown path.
    """
    data = _load_plan(runner, plan_filename)
    unexpected = [
        change.get("address", "?")
        for change in data.get("resource_changes", [])
        if set(change.get("change", {}).get("actions", [])) - {"delete", "no-op"}
    ]
    if unexpected:
        raise TerraformError(
            "Teardown blocked: the saved destroy plan contains non-delete "
            "actions for: " + ", ".join(unexpected)
        )


def _classify(actions: list[str]) -> str:
    a = set(actions)
    if a == {"no-op"}:
        return "no-op"
    if a == {"create"}:
        return "add"
    if a == {"delete"}:
        return "destroy"
    if a == {"forget"}:
        return "forget"
    if "delete" in a and "create" in a:
        return "replace"
    if a == {"update"}:
        return "change"
    return "/".join(sorted(a))


def summarize_last_plan(runner: TerraformRunner, plan_filename: str = "plan.tfplan") -> str:
    """Return a readable summary of a saved plan; safe to call after tf_plan
    (default) or, with destroy.tfplan, after tf_plan_destroy."""
    try:
        data = _load_plan(runner, plan_filename)
    except TerraformError as exc:
        return str(exc)

    changes = data.get("resource_changes", [])
    tally = {"add": 0, "change": 0, "destroy": 0, "replace": 0, "forget": 0}
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
        + (f", {tally['forget']} to forget (remove from state)" if tally["forget"] else "")
    )
    return header + "\n" + "\n".join(lines)
