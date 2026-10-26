"""Select the external tools allowed for one workflow phase."""

from a11y_gent.model.tool import Tool
from a11y_gent.model.workflow import WorkflowPhase


def tools_for_phase(
    phase: WorkflowPhase, nvda_tools: list[Tool], devtools_tools: list[Tool]
) -> list[Tool]:
    """Return only the MCP tools permitted in ``phase``."""
    if phase in (WorkflowPhase.DISCOVERY, WorkflowPhase.GATHER_INFO_FOR_REPORT):
        return list(devtools_tools)
    if phase in (WorkflowPhase.SOLVE_TASK, WorkflowPhase.VERIFY):
        return list(nvda_tools)
    return []