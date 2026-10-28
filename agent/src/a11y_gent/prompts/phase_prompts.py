"""Prompt and completion contracts for workflow phases."""

from a11y_gent.model.tool import Tool
from a11y_gent.model.message import Message
from a11y_gent.model.verdict import Barrier
from a11y_gent.model.workflow import Candidate, WorkflowTask


def build_discovery_prompt(url: str, instructions: str | None = None) -> str:
    """Build the DevTools-only contract for ordinary-user task discovery."""
    instruction_block = f"\nInstructions: {instructions}" if instructions else ""
    return (
        "Identify meaningful, distinct ordinary-user tasks for this application.\n"
        f"Application URL: {url}{instruction_block}\n\n"
        "Use a Reason-Act-Observe loop: Reason plans or revises the next exploration step "
        "without calling tools; Act is the only stage that calls a tool; Observe uses its result "
        "before the next Reason step. Explore only as needed to understand ordinary-user goals. Do not make "
        "accessibility findings. Complete by calling complete_discovery with short, "
        "numbered task descriptions in their intended execution order."
    )


def make_discovery_completion_tool() -> Tool:
    """Build the structured completion sink for discovery."""

    def complete_discovery(task_descriptions: list, incomplete: bool) -> str:
        """Record ordered task descriptions and whether discovery was incomplete."""
        return "discovery completed"

    return Tool(
        name="complete_discovery",
        description=(
            "Complete discovery with distinct, ordered ordinary-user task descriptions. "
            "Set incomplete when the available discovery budget prevented a complete inventory."
        ),
        tool_function=complete_discovery,
    )


def build_solve_task_prompt(task: WorkflowTask) -> str:
    """Build the NVDA-only contract for attempting one task."""
    return (
        "Attempt this task as an NVDA screen-reader user.\n"
        f"Application URL: {task['url']}\n"
        f"Task: {task['description']}\n\n"
        "Use a Reason-Act-Observe loop: Reason plans or revises the next NVDA action without "
        "calling tools; Act is the only stage that calls a tool; Observe uses its result before "
        "the next Reason step. Reason intentionally has no tool schemas, but NVDA tools are live and "
        "available in the immediately following Act stage. In Reason, name exactly one next executable "
        "tool call; never claim that you cannot operate NVDA, give a human instructions, or ask a human "
        "to execute or observe anything. Use only NVDA observations as evidence. Report every directly observed "
        "accessibility barrier immediately with report_barrier, including its description, "
        "expected behavior, actual behavior, executed reproduction steps, and evidence. "
        "In every Act turn, make exactly one tool call and wait for its observation before the next "
        "Reason step. Complete by calling "
        "complete_solve_task with the task-local status and summary."
    )


def make_solve_task_completion_tool() -> Tool:
    """Build the structured completion sink for one task attempt."""

    def complete_solve_task(status: str, summary: str) -> str:
        """Record the final status and summary for this task attempt."""
        return "solve task completed"

    return Tool(
        name="complete_solve_task",
        description="Complete this task attempt with its status and a concise summary.",
        tool_function=complete_solve_task,
    )


def build_retrospective_prompt(task: WorkflowTask, solve_task_history: list[Message]) -> str:
    """Build the read-only candidate-analysis contract for a completed task."""
    return (
        "Analyze the completed solve-task history without taking actions.\n"
        f"Task: {task['description']}\n"
        f"Solve-task history:\n{_format_history(solve_task_history)}\n\n"
        "Use a Reason-Act-Observe loop: Reason analyzes or revises the next candidate without "
        "calling tools; Act is the only stage that calls a structured sink; Observe uses that "
        "result before the next Reason step. Identify only unreported suspected conditions that need targeted checking. "
        "Return candidates only. Do not report a confirmed barrier. For each candidate, call "
        "create_candidate with one description and verification brief. In every action turn, "
        "make exactly one tool call. Create at most one candidate in that call, then wait for "
        "its observation before the next analysis iteration. When no further candidates remain, "
        "call complete_retrospective without candidate values."
    )


def make_candidate_creation_tool() -> Tool:
    """Build the structured sink for one retrospective candidate."""

    def create_candidate(description: str, verification_brief: str) -> str:
        """Record one candidate and its targeted verification brief."""
        return "candidate created"

    return Tool(
        name="create_candidate",
        description="Create one candidate with a description and verification brief.",
        tool_function=create_candidate,
    )


def make_retrospective_completion_tool() -> Tool:
    """Build the structured completion sink for retrospective analysis."""

    def complete_retrospective() -> str:
        """Record that retrospective analysis has no further candidates."""
        return "retrospective completed"

    return Tool(
        name="complete_retrospective",
        description="Complete retrospective analysis without candidate values. Do not report confirmed barriers.",
        tool_function=complete_retrospective,
    )


def build_verify_prompt(task: WorkflowTask, candidate_reference: int, candidate: Candidate) -> str:
    """Build the NVDA-only contract for verifying one candidate."""
    return (
        "Use NVDA observations to verify exactly one suspected condition.\n"
        f"Task: {task['description']}\n"
        f"Candidate {candidate_reference}: {candidate['description']}\n"
        f"Verification brief: {candidate['verification_brief']}\n\n"
        "Use a Reason-Act-Observe loop: Reason plans or revises the next NVDA action without "
        "calling tools; Act is the only stage that calls a tool; Observe uses its result before "
        "the next Reason step. Reason intentionally has no tool schemas, but NVDA tools are live and "
        "available in the immediately following Act stage. In Reason, name exactly one next executable "
        "tool call; never claim that you cannot operate NVDA, give a human instructions, or ask a human "
        "to execute or observe anything. You operate NVDA directly through the available tools. Never ask a human to operate "
        "NVDA or the browser, capture Speech Viewer output, or provide observations. Do not "
        "investigate unrelated conditions. In every action turn, make exactly one tool call; "
        "never return an action turn without a tool call. Wait for its observation before making "
        "another tool call in a new action turn. If the next action is unclear, call "
        "get_speech_log or get_focus_info for the next observation. Complete by calling "
        "complete_verification with confirmed or discarded status and supporting "
        "NVDA evidence."
    )


def make_verify_completion_tool() -> Tool:
    """Build the structured completion sink for one candidate verification."""

    def complete_verification(
        status: str,
        evidence: str,
        description: str = "",
        expected_behavior: str = "",
        actual_behavior: str = "",
        reproduction_steps: list | None = None,
    ) -> str:
        """Record the conclusion and supporting evidence for one candidate."""
        return "verification completed"

    return Tool(
        name="complete_verification",
        description=(
            "Complete verification with status 'confirmed' or 'discarded' and "
            "supporting NVDA evidence. A confirmed outcome must "
            "also provide the barrier description, expected behavior, actual behavior, "
            "executed reproduction steps, and NVDA evidence."
        ),
        tool_function=complete_verification,
    )


def build_report_enrichment_prompt(barrier: Barrier) -> str:
    """Build the DevTools-only contract for enriching one confirmed barrier."""
    return (
        "Gather implementation context for this confirmed barrier.\n"
        f"Description: {barrier['description']}\n"
        f"Expected behavior: {barrier['expected_behavior']}\n"
        f"Actual behavior: {barrier['actual_behavior']}\n"
        f"Evidence: {barrier['evidence']}\n\n"
        "Use a Reason-Act-Observe loop: Reason plans or revises the next DevTools inspection "
        "without calling tools; Act is the only stage that calls a tool; Observe uses its result "
        "before the next Reason step. Provide implementation context, a remediation target, and a suggested fix. "
        "Do not alter the confirmed barrier. Complete by calling "
        "complete_report_enrichment."
    )


def make_report_enrichment_completion_tool() -> Tool:
    """Build the structured completion sink for one barrier enrichment."""

    def complete_report_enrichment(
        title: str,
        implementation_context: str,
        remediation_target: str,
        suggested_fix: str,
    ) -> str:
        """Record developer-oriented context without changing the barrier."""
        return "report enrichment completed"

    return Tool(
        name="complete_report_enrichment",
        description=(
            "Complete one confirmed-barrier enrichment with a title, implementation "
            "context, remediation target, and suggested fix."
        ),
        tool_function=complete_report_enrichment,
    )


def _format_history(history: list[Message]) -> str:
    entries: list[str] = []
    for message in history:
        entries.append(f"{message['name']}: {message['content']}")
        entries.extend(
            f"{call['tool']['name']}: {call['arguments']}"
            for call in message.get("tool_calls", [])
        )
    return "\n".join(entries)