"""Offline tests for workflow-phase MCP tool isolation."""

from a11y_gent.model.tool import Tool
from a11y_gent.model.workflow import WorkflowPhase
from a11y_gent.tooling.phase_tools import tools_for_phase


def _tool(name: str) -> Tool:
    def tool_function():
        return name

    return {"name": name, "description": name, "tool_function": tool_function}


_NVDA_TOOLS = [_tool("send_key")]
_DEVTOOLS_TOOLS = [_tool("navigate_page")]


def test_devtools_phases_receive_only_devtools_tools():
    for phase in (WorkflowPhase.DISCOVERY, WorkflowPhase.GATHER_INFO_FOR_REPORT):
        tools = tools_for_phase(phase, _NVDA_TOOLS, _DEVTOOLS_TOOLS)

        assert [tool["name"] for tool in tools] == ["navigate_page"]
        assert tools is not _DEVTOOLS_TOOLS


def test_screen_reader_phases_receive_only_nvda_tools():
    for phase in (WorkflowPhase.SOLVE_TASK, WorkflowPhase.VERIFY):
        tools = tools_for_phase(phase, _NVDA_TOOLS, _DEVTOOLS_TOOLS)

        assert [tool["name"] for tool in tools] == ["send_key"]
        assert tools is not _NVDA_TOOLS


def test_non_interactive_phases_receive_no_external_tools():
    for phase in (WorkflowPhase.RETROSPECTIVE, WorkflowPhase.WRITE_REPORT):
        assert tools_for_phase(phase, _NVDA_TOOLS, _DEVTOOLS_TOOLS) == []


def _run_all():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()