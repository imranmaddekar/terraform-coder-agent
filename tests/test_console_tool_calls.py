from agent_framework import Content
import pytest

from tfagent.console.observers.tool_call_display import ToolCallDisplayObserver


class FakeUX:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def append_info_line(self, text: str, color: str) -> None:
        self.lines.append(text)


async def _send(observer: ToolCallDisplayObserver, ux: FakeUX, content: Content) -> None:
    await observer.on_content(ux, content, agent=None, session=None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_chat_completions_argument_deltas_keep_header_name() -> None:
    observer = ToolCallDisplayObserver()
    ux = FakeUX()

    await _send(
        observer,
        ux,
        Content.from_function_call(call_id="call-1", name="write_file", arguments=""),
    )
    for fragment in ['{"', "path", '":"', "main.tf", '"}']:
        await _send(
            observer,
            ux,
            Content.from_function_call(call_id="", name="", arguments=fragment),
        )

    assert len(ux.lines) == 1
    assert "write_file" in ux.lines[0]
    assert "Unknown" not in ux.lines[0]
