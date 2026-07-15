---
name: plan-review-checklist
description: Checklist for reviewing a saved Terraform plan diff before summarizing it and requesting apply approval.
---

# Plan Review Checklist

Work through this checklist every time you summarize a saved plan for the
human, BEFORE requesting tf_apply approval. The approval card shows the raw
diff; your job is to make its implications obvious.

## Verify the shape of the change
- State the counts plainly: N to add, N to change, N to destroy. The
  tooling already rejects destructive apply plans, but if the counts differ
  from what the todos imply, say so and explain why.
- Name every resource being changed (not just created) and what attribute
  changes — an in-place `change` can still cause downtime (e.g. SKU resize).

## Verify conventions (load terraform-conventions if you haven't)
- Every taggable resource carries the required tags, including
  `tfagent-session-scope = "sandbox"` in the greenfield flow.
- Names follow the org pattern; region matches the agreed default unless
  the human chose otherwise.

## Verify exposure and cost
- Flag anything that creates public network exposure (public IPs, open
  NSG rules, `public_network_access_enabled = true`) — this needs the
  human's explicit attention even though it will apply cleanly.
- Flag resources with meaningful running cost (compute, databases,
  gateways) and their SKU, so the human knows what the sandbox will bill.

## Then, and only then
- Give a one-paragraph recommendation ("safe to apply because ...") and
  request approval. Never present the model's memory of the plan as the
  diff — the card computes the real diff from disk.
