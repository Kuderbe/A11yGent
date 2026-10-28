"""Prompt and completion contracts for workflow phases."""

from a11y_gent.model.tool import Tool
from a11y_gent.model.message import Message
from a11y_gent.model.verdict import Barrier
from a11y_gent.model.workflow import Candidate, WorkflowTask


_DISCOVERY_EXAMPLE = """Example flow:
1. Reason 1 (assistant): I need the page structure before identifying ordinary-user tasks.
   Act (assistant): {"tool_calls": [{"id": "discovery-1", "name": "<available_devtools_tool>", "arguments": {}}]}
   Observe (tool): {"reference_id": "discovery-1", "content": "Product list with Cart navigation."}
2. Reason 2 (assistant): I need the available product actions.
   Act (assistant): {"tool_calls": [{"id": "discovery-2", "name": "<available_devtools_tool>", "arguments": {}}]}
   Observe (tool): {"reference_id": "discovery-2", "content": "Each product has an Add to cart button."}
3. Reason 3 (assistant): I need evidence that Cart leads to checkout.
   Act (assistant): {"tool_calls": [{"id": "discovery-3", "name": "<available_devtools_tool>", "arguments": {}}]}
   Observe (tool): {"reference_id": "discovery-3", "content": "Cart contains a Checkout button."}
4. Reason 4 (assistant): I need to confirm that checkout has a user-visible completion state.
   Act (assistant): {"tool_calls": [{"id": "discovery-4", "name": "<available_devtools_tool>", "arguments": {}}]}
   Observe (tool): {"reference_id": "discovery-4", "content": "Checkout can lead to an order confirmation."}
5. Reason 5 (assistant): I have enough evidence for distinct tasks and must now end Discovery.
   Act (assistant): {"tool_calls": [{"id": "discovery-5", "name": "complete_discovery", "arguments": {"task_descriptions": ["Browse products.", "Add a product to the cart.", "Complete checkout."], "incomplete": false}}]}
   Observe (tool): {"reference_id": "discovery-5", "content": "discovery completed"}
Discovery ends with complete_discovery. Do not continue exploring after its observation."""

_SOLVE_TASK_EXAMPLE = """Example flow:
1. Reason 1 (assistant): I need the current document focus before navigating.
   Act (assistant): {"tool_calls": [{"id": "solve-1", "name": "get_focus_info", "arguments": {}}]}
   Observe (tool): {"reference_id": "solve-1", "content": "{\\"role\\": \\"DOCUMENT\\", \\"name\\": \\"Notes - Toolbar\\"}"}
2. Reason 2 (assistant): I need a clean speech window for task evidence.
   Act (assistant): {"tool_calls": [{"id": "solve-2", "name": "clear_speech_log", "arguments": {}}]}
   Observe (tool): {"reference_id": "solve-2", "content": "speech log cleared"}
3. Reason 3 (assistant): I need to find the next button in the focused document.
   Act (assistant): {"tool_calls": [{"id": "solve-3", "name": "send_key", "arguments": {"gesture": "b"}}]}
   Observe (tool): {"reference_id": "solve-3", "content": "{\\"ok\\": true, \\"gesture\\": \\"b\\"}"}
4. Reason 4 (assistant): I need the spoken result of the navigation action.
   Act (assistant): {"tool_calls": [{"id": "solve-4", "name": "get_last_spoken", "arguments": {}}]}
   Observe (tool): {"reference_id": "solve-4", "content": "{\\"entry\\": {\\"text\\": \\"button Save note\\"}}"}
5. Reason 5 (assistant): The Save note button is identified, so I need to activate it.
   Act (assistant): {"tool_calls": [{"id": "solve-5", "name": "send_key", "arguments": {"gesture": "enter"}}]}
   Observe (tool): {"reference_id": "solve-5", "content": "{\\"ok\\": true, \\"gesture\\": \\"enter\\"}"}
6. Reason 6 (assistant): I need the NVDA result after activation.
   Act (assistant): {"tool_calls": [{"id": "solve-6", "name": "get_last_spoken", "arguments": {}}]}
   Observe (tool): {"reference_id": "solve-6", "content": "{\\"entry\\": {\\"text\\": \\"Note saved.\\"}}"}
7. Reason 7 (assistant): NVDA confirms the goal, so I must end Solve task.
   Act (assistant): {"tool_calls": [{"id": "solve-7", "name": "complete_solve_task", "arguments": {"status": "succeeded", "summary": "NVDA announced Note saved. after activating Save note."}}]}
   Observe (tool): {"reference_id": "solve-7", "content": "solve task completed"}
Solve task ends with complete_solve_task. Do not take more task actions after its observation."""

_RETROSPECTIVE_EXAMPLE = """Example flow:
1. Reason 1 (assistant): The history shows an action without observed result feedback, so it supports a candidate.
   Act (assistant): {"tool_calls": [{"id": "retro-1", "name": "create_candidate", "arguments": {"description": "Result feedback may not be announced.", "verification_brief": "Activate the control and inspect NVDA speech for result feedback."}}]}
   Observe (tool): {"reference_id": "retro-1", "content": "candidate created"}
2. Reason 2 (assistant): I need to consider whether focus after that action is a distinct unreported condition.
   Act (assistant): {"tool_calls": [{"id": "retro-2", "name": "create_candidate", "arguments": {"description": "Focus may not move to the result.", "verification_brief": "Activate the control, then inspect NVDA focus and speech."}}]}
   Observe (tool): {"reference_id": "retro-2", "content": "candidate created"}
3. Reason 3 (assistant): I need to consider the clarity of the observed status separately.
   Act (assistant): {"tool_calls": [{"id": "retro-3", "name": "create_candidate", "arguments": {"description": "The status message may be unclear.", "verification_brief": "Repeat the action and inspect the exact NVDA announcement."}}]}
   Observe (tool): {"reference_id": "retro-3", "content": "candidate created"}
4. Reason 4 (assistant): A further unreported suspected condition is distinct from the existing candidates.
   Act (assistant): {"tool_calls": [{"id": "retro-4", "name": "create_candidate", "arguments": {"description": "A newly identified condition requires targeted NVDA checking.", "verification_brief": "Use only NVDA observations and keyboard actions to check this condition."}}]}
   Observe (tool): {"reference_id": "retro-4", "content": "candidate created"}
5. Reason 5 (assistant): No further unreported suspected condition is grounded in the history, so I must end Retrospective.
   Act (assistant): {"tool_calls": [{"id": "retro-5", "name": "complete_retrospective", "arguments": {}}]}
   Observe (tool): {"reference_id": "retro-5", "content": "retrospective completed"}
Retrospective ends with complete_retrospective. Never use it to confirm a barrier."""

_VERIFY_EXAMPLE = """Example flow:
1. Reason 1 (assistant): I need the current focus before following the verification brief.
   Act (assistant): {"tool_calls": [{"id": "verify-1", "name": "get_focus_info", "arguments": {}}]}
   Observe (tool): {"reference_id": "verify-1", "content": "{\\"role\\": \\"BUTTON\\", \\"name\\": \\"Save note\\"}"}
2. Reason 2 (assistant): I need a clean speech window for the candidate test.
   Act (assistant): {"tool_calls": [{"id": "verify-2", "name": "clear_speech_log", "arguments": {}}]}
   Observe (tool): {"reference_id": "verify-2", "content": "speech log cleared"}
3. Reason 3 (assistant): The candidate concerns feedback after activation, so I should activate the focused button.
   Act (assistant): {"tool_calls": [{"id": "verify-3", "name": "send_key", "arguments": {"gesture": "enter"}}]}
   Observe (tool): {"reference_id": "verify-3", "content": "{\\"ok\\": true, \\"gesture\\": \\"enter\\"}"}
4. Reason 4 (assistant): I need the NVDA evidence produced by activation.
   Act (assistant): {"tool_calls": [{"id": "verify-4", "name": "get_speech_log", "arguments": {}}]}
   Observe (tool): {"reference_id": "verify-4", "content": "{\\"entries\\": [{\\"text\\": \\"Note saved.\\"}], \\"count\\": 1}"}
5. Reason 5 (assistant): The expected feedback was announced, so the candidate is unsupported and I must end Verify.
   Act (assistant): {"tool_calls": [{"id": "verify-5", "name": "complete_verification", "arguments": {"status": "discarded", "evidence": "NVDA announced Note saved. after activation."}}]}
   Observe (tool): {"reference_id": "verify-5", "content": "verification completed"}
Verify ends with complete_verification. If the evidence instead confirms the candidate, use status confirmed plus description, expected_behavior, actual_behavior, and complete-sentence reproduction_steps."""

_REPORT_ENRICHMENT_EXAMPLE = """Example flow:
1. Reason 1 (assistant): I need the relevant page structure for the confirmed barrier.
   Act (assistant): {"tool_calls": [{"id": "enrich-1", "name": "<available_devtools_tool>", "arguments": {}}]}
   Observe (tool): {"reference_id": "enrich-1", "content": "Toolbar contains an icon-only action button."}
2. Reason 2 (assistant): I need the button attributes that can supply its accessible name.
   Act (assistant): {"tool_calls": [{"id": "enrich-2", "name": "<available_devtools_tool>", "arguments": {}}]}
   Observe (tool): {"reference_id": "enrich-2", "content": "The button has no text, aria-label, or aria-labelledby value."}
3. Reason 3 (assistant): I need the component context to identify a narrow remediation target.
   Act (assistant): {"tool_calls": [{"id": "enrich-3", "name": "<available_devtools_tool>", "arguments": {}}]}
   Observe (tool): {"reference_id": "enrich-3", "content": "The button belongs to the toolbar action component."}
4. Reason 4 (assistant): I need to confirm whether a nearby visible label can be referenced.
   Act (assistant): {"tool_calls": [{"id": "enrich-4", "name": "<available_devtools_tool>", "arguments": {}}]}
   Observe (tool): {"reference_id": "enrich-4", "content": "No visible text label is associated with the button."}
5. Reason 5 (assistant): I have enough developer-facing context and must end enrichment without changing the barrier.
   Act (assistant): {"tool_calls": [{"id": "enrich-5", "name": "complete_report_enrichment", "arguments": {"title": "Unnamed toolbar action", "implementation_context": "An icon-only toolbar button has no text or ARIA naming attribute.", "remediation_target": "toolbar action component", "suggested_fix": "Provide an accessible name with visible text, aria-label, or aria-labelledby."}}]}
   Observe (tool): {"reference_id": "enrich-5", "content": "report enrichment completed"}
Report enrichment ends with complete_report_enrichment. Do not change the confirmed barrier."""


def build_discovery_prompt(url: str, instructions: str | None = None) -> str:
    """Build the DevTools-only contract for ordinary-user task discovery."""
    instruction_block = f"\nInstructions: {instructions}" if instructions else ""
    return (
        "Identify meaningful, distinct ordinary-user tasks for this application.\n"
        f"Application URL: {url}{instruction_block}\n\n"
        "Use a Reason-Act-Observe loop: Reason concisely assesses the available evidence and revises the "
        "exploration plan without calling tools; Act makes exactly one structured tool call; Observe uses "
        "its result before the next Reason step. Completion is an ordinary Action and has an Observation. "
        "Explore only as needed to understand ordinary-user goals. Do not make accessibility findings. Complete by calling complete_discovery with short, "
        "numbered task descriptions in their intended execution order.\n\n"
        f"{_DISCOVERY_EXAMPLE}"
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
        "Use a Reason-Act-Observe loop: Reason concisely assesses available NVDA evidence and revises the "
        "plan without calling tools; Act makes exactly one structured tool call; Observe uses its result before "
        "the next Reason step. Tool calls belong in Act. Return concise plain text rather than textual "
        "tool-call, XML, JSON, or code markup in Reason. Never claim that you cannot operate NVDA, give a human instructions, or ask a human "
        "to execute or observe anything. Use only NVDA observations as evidence. "
        "The task document is already focused when this phase starts. Keep navigation within that document "
        "using screen-reader browse-mode and page controls; do not use F6, the address bar, tab search, or "
        "other browser-chrome controls. Browser-chrome or different-page observations are not task evidence "
        "and must not be investigated. Report every directly observed "
        "accessibility barrier immediately with report_barrier, including its description, "
        "expected behavior, actual behavior, executed reproduction steps, and evidence. "
        "In every Act turn, make exactly one tool call and wait for its observation before the next "
        "Reason step. Completion is an ordinary Action and has an Observation. Complete by calling "
        "complete_solve_task with status 'succeeded' when NVDA evidence confirms the task goal, or 'failed' "
        "only when the task cannot be completed. Do not use succeeded_with_avoidable_difficulty here: final "
        "task status is derived later from confirmed barriers. Include a concise evidence-grounded summary.\n\n"
        f"{_SOLVE_TASK_EXAMPLE}"
    )


def make_solve_task_completion_tool() -> Tool:
    """Build the structured completion sink for one task attempt."""

    def complete_solve_task(status: str, summary: str) -> str:
        """Record the final status and summary for this task attempt."""
        return "solve task completed"

    return Tool(
        name="complete_solve_task",
        description=(
            "Complete this task attempt with status 'succeeded' after observed task completion or 'failed' "
            "only when it cannot be completed, plus a concise evidence-grounded summary."
        ),
        tool_function=complete_solve_task,
    )


def build_retrospective_prompt(task: WorkflowTask, solve_task_history: list[Message]) -> str:
    """Build the read-only candidate-analysis contract for a completed task."""
    return (
        "Analyze the completed solve-task history without taking actions.\n"
        f"Task: {task['description']}\n"
        f"Solve-task history:\n{_format_history(solve_task_history)}\n\n"
        "Identify only unreported suspected conditions that need targeted checking. Return candidates only. Do not report a confirmed barrier. For each candidate, call "
        "create_candidate with one description and an NVDA-only verification brief. The brief may use "
        "only the available NVDA observations and keyboard actions; never request DOM, DevTools, browser "
        "accessibility-inspector, or human checks. Create at most one candidate per iteration. When no further candidates remain, "
        "call complete_retrospective without candidate values.\n\n"
        f"{_RETROSPECTIVE_EXAMPLE}"
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
        "Use a Reason-Act-Observe loop: Reason concisely assesses available NVDA evidence and revises the "
        "plan without calling tools; Act makes exactly one structured tool call; Observe uses its result before "
        "the next Reason step. Tool calls belong in Act. Never claim that you cannot operate NVDA, give a human instructions, or ask a human "
        "to execute or observe anything. You operate NVDA directly through the available tools. Treat the "
        "verification brief as NVDA-only: ignore any instruction to inspect page source or a browser "
        "accessibility inspector because those capabilities are unavailable in this phase. Never ask a human to operate "
        "NVDA or the browser, capture Speech Viewer output, or provide observations. "
        "The task document remains focused from Solve. Keep navigation within that document using screen-reader "
        "browse-mode and page controls; do not use F6, the address bar, tab search, or other browser-chrome "
        "controls. Browser-chrome or different-page observations are not candidate evidence and must not be "
        "investigated. Do not "
        "investigate unrelated conditions. In every action turn, make exactly one tool call; "
        "never return an action turn without a tool call. Wait for its observation before making "
        "another tool call in a new action turn. Completion is an ordinary Action and has an Observation. If the next action is unclear, call "
        "get_speech_log or get_focus_info for the next observation. Complete by calling "
        "complete_verification with confirmed or discarded status and supporting NVDA evidence. "
        "A confirmed completion must also provide description, expected_behavior, actual_behavior, "
        "and a non-empty reproduction_steps list. Write a few concise, high-level, complete-sentence steps "
        "for actions actually performed during verification: for example, navigate to the control, activate it, "
        "then observe the missing feedback. Do not split a sentence into words or characters, enumerate every "
        "keystroke, or include unperformed steps. Use discarded when the evidence does not support "
        "a complete confirmed barrier.\n\n"
        f"{_VERIFY_EXAMPLE}"
    )


def make_verify_completion_tool() -> Tool:
    """Build the structured completion sink for one candidate verification."""

    def complete_verification(
        status: str,
        evidence: str,
        description: str = "",
        expected_behavior: str = "",
        actual_behavior: str = "",
        reproduction_steps: list[str] = None,
    ) -> str:
        """Record the conclusion and supporting evidence for one candidate."""
        return "verification completed"

    return Tool(
        name="complete_verification",
        description=(
            "Complete verification with status 'confirmed' or 'discarded' and "
            "supporting NVDA evidence. A confirmed outcome must "
            "also provide the barrier description, expected behavior, actual behavior, "
            "a few complete-sentence high-level reproduction steps actually performed, and NVDA evidence. "
            "Never provide individual characters, words, or one entry per keystroke as reproduction steps."
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
        "Use a Reason-Act-Observe loop: Reason concisely assesses the available evidence and revises the "
        "DevTools plan without calling tools; Act makes exactly one structured tool call; Observe uses its "
        "result before the next Reason step. Completion is an ordinary Action and has an Observation. Provide implementation context, a remediation target, and a suggested fix. "
        "Do not alter the confirmed barrier. Complete by calling "
        "complete_report_enrichment.\n\n"
        f"{_REPORT_ENRICHMENT_EXAMPLE}"
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