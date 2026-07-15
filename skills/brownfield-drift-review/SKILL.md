---
name: brownfield-drift-review
description: How to work in the brownfield flow - inspect deployed state, keep edits minimal, deliver a plan diff. Load when the session flow is brownfield.
---

# Brownfield Drift Review

In the brownfield flow the workspace contains HCL and state for
infrastructure that is ALREADY DEPLOYED. Your deliverable is a reviewed
plan diff; the human's pipeline applies it. tf_apply and teardown are
disabled — do not fight the tooling.

## Orient before editing
- `tf_state_list` to see what is actually deployed and managed.
- `tf_state_show <address>` on any resource you are about to touch, so
  proposed edits are grounded in real attributes, not assumptions.
- Compare what the HCL declares against what state shows. If they already
  disagree (drift), report the drift to the human BEFORE layering new
  changes on top of it.

## Edit minimally
- Change only what the request requires. Do not reformat, rename, or
  "improve" unrelated resources — every extra diff line is extra review
  burden and extra blast radius in someone's production.
- Never write HCL whose plan would delete or replace a deployed resource
  without calling that out first; replacement (delete+create) is downtime.

## Deliver the diff
- Run fmt/validate/plan as usual; the saved plan diff is the deliverable.
- Walk the human through it with the plan-review-checklist skill, flag
  anything replace-shaped or exposure-related, then offer export_to_repo
  so their pipeline can apply the change.
