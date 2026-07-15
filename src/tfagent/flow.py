"""Session flow: greenfield build vs brownfield change.

Every session works in one of two flows, and the REAL deployment always
happens through the user's pipeline from their repo — never from this agent:

- GREENFIELD: the agent builds new infrastructure and self-validates it by
  applying into the sandbox subscription. Once the human confirms the result,
  the sandbox is torn down (human-gated) and the HCL is exported for the
  pipeline to deploy.
- BROWNFIELD: the workspace holds already-deployed infrastructure's HCL and
  state. The agent may read state and produce a plan diff — the diff is the
  deliverable — but apply and destroy are disabled entirely.

The flow is chosen by the human, not the model: `set_session_flow` is
registered `always_require` so the choice surfaces as an approval card, and
the `/flow` console command sets it directly without involving the model.
Mutating Terraform tools refuse to run until a flow is chosen.
"""
from __future__ import annotations

from dataclasses import dataclass

GREENFIELD = "greenfield"
BROWNFIELD = "brownfield"
FLOWS = (GREENFIELD, BROWNFIELD)

# Tool names the console approval card treats like tf_apply: human-gated,
# with no "always approve" choice offered.
SET_FLOW_TOOL_NAME = "set_session_flow"


@dataclass
class FlowState:
    """Mutable, session-scoped flow shared by the runner, tools, and console.

    ``flow`` stays None until the human confirms a choice; ``applied_this_session``
    records a successful greenfield tf_apply so teardown can require something
    to actually exist before offering to destroy it.
    """

    flow: str | None = None
    applied_this_session: bool = False


def build_flow_tools(flow_state: FlowState) -> list:
    """Return the flow query/selection tools, closed over ``flow_state``."""
    from agent_framework import tool

    @tool(approval_mode="never_require")
    def get_session_flow() -> str:
        """Report the session's flow: 'greenfield', 'brownfield', or not chosen yet."""
        if flow_state.flow is None:
            return (
                "No flow chosen yet. Ask the human whether this session is a "
                "greenfield build or a brownfield change, then call set_session_flow."
            )
        return flow_state.flow

    @tool(approval_mode="always_require")
    def set_session_flow(flow: str) -> str:
        """Set the session flow to 'greenfield' or 'brownfield' AFTER the human has
        stated which one applies. greenfield = build new infra, sandbox-validate
        with tf_apply, tear down, export for the pipeline. brownfield = change
        deployed infra: plan-only, tf_apply/destroy disabled, the plan diff is the
        deliverable. Never call this with a value the human did not state."""
        normalized = flow.strip().lower()
        if normalized not in FLOWS:
            raise ValueError(f"Unknown flow {flow!r}; expected one of {', '.join(FLOWS)}.")
        flow_state.flow = normalized
        return f"Session flow set to {normalized}."

    return [get_session_flow, set_session_flow]
