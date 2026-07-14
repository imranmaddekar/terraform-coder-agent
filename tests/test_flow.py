import pytest

from tfagent.flow import BROWNFIELD, GREENFIELD, FlowState, build_flow_tools


def test_flow_tools_report_and_set_the_shared_state() -> None:
    state = FlowState()
    get_session_flow, set_session_flow = build_flow_tools(state)

    assert "No flow chosen yet" in get_session_flow()
    assert set_session_flow("Greenfield ") == "Session flow set to greenfield."
    assert state.flow == GREENFIELD
    assert get_session_flow() == GREENFIELD

    set_session_flow(BROWNFIELD)
    assert state.flow == BROWNFIELD


def test_set_session_flow_rejects_unknown_values() -> None:
    state = FlowState()
    _get, set_session_flow = build_flow_tools(state)
    with pytest.raises(ValueError, match="Unknown flow"):
        set_session_flow("production")
    assert state.flow is None


def test_flow_selection_is_human_gated_and_query_is_not() -> None:
    get_session_flow, set_session_flow = build_flow_tools(FlowState())
    assert get_session_flow.approval_mode == "never_require"
    assert set_session_flow.approval_mode == "always_require"
