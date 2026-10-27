"""Render deterministic per-task Markdown report sections."""

from a11y_gent.model.workflow import ExecutionError, TaskResult
from a11y_gent.model.workflow import VerificationOutcomeStatus
from a11y_gent.model.workflow_runtime import EnrichmentSubstate, VerificationSubstate


def render_task_markdown_sections(
    final_results: list[TaskResult],
    verification_states: list[VerificationSubstate],
    enrichment_states: list[EnrichmentSubstate],
    execution_errors: list[ExecutionError],
) -> str:
    """Render task outcomes and their supporting report details."""
    enrichments = {state["barrier_reference"]: state["enrichment"] for state in enrichment_states}
    barrier_reference = 0
    sections = []
    for result in final_results:
        task = result["task"]
        verdict = result["verdict"]
        barriers = []
        for barrier in verdict["barriers"]:
            enrichment = enrichments.get(barrier_reference)
            barriers.append(_render_barrier(task["number"], barrier, enrichment))
            barrier_reference += 1
        candidates = [
            _render_candidate(state)
            for state in verification_states
            if state["task"]["number"] == task["number"]
            and state["outcome"]["status"]
            in (VerificationOutcomeStatus.UNVERIFIED_BUDGET_EXHAUSTED, VerificationOutcomeStatus.UNVERIFIED_EXECUTION_ERROR)
        ]
        errors = [_render_error(error) for error in execution_errors if error["task_number"] == task["number"]]
        sections.append(
            "\n".join(
                [
                    f"## Task {task['number']:02d}: {task['description']}",
                    "",
                    f"- **URL:** {task['url']}",
                    f"- **Outcome:** {_outcome(verdict['status'].value)} — {verdict['summary']}",
                    "",
                    "### Confirmed barriers",
                    "",
                    "\n\n".join(barriers) if barriers else "None.",
                    "",
                    "### Unverified candidates",
                    "",
                    "\n\n".join(candidates) if candidates else "None.",
                    "",
                    "### Execution errors",
                    "",
                    "\n".join(errors) if errors else "None.",
                ]
            )
        )
    return "\n\n".join([*sections, _scope_caveat()]) + "\n"


def _render_barrier(task_number, barrier, enrichment):
    title = enrichment["title"] if enrichment is not None else barrier["description"]
    suggested_fix = enrichment["suggested_fix"] if enrichment is not None else "manual investigation"
    steps = "\n".join(f"  {number}. {step}" for number, step in enumerate(barrier["reproduction_steps"], start=1))
    lines = [
        f"#### {title}",
        "",
        f"- **Description:** {barrier['description']}",
        f"- **Expected behavior:** {barrier['expected_behavior']}",
        f"- **Actual behavior:** {barrier['actual_behavior']}",
    ]
    if enrichment is not None and enrichment["implementation_context"]:
        lines.append(f"- **Implementation context:** {enrichment['implementation_context']}")
    lines.extend(
        [
            "- **Steps to reproduce:**",
            steps,
            f"- **Suggested fix:** {suggested_fix}",
            f"- **Evidence:** {barrier['evidence']}",
            f"- **Provenance:** Task {task_number:02d}",
        ]
    )
    if enrichment is not None and "error" in enrichment:
        lines.append(f"- **Enrichment error:** {enrichment['error']}")
    return "\n".join(lines)


def _outcome(status: str) -> str:
    return status.replace("_", " ")


def _render_candidate(state: VerificationSubstate) -> str:
    outcome = state["outcome"]
    status = outcome["status"].value.replace("unverified_", "unverified: ").replace("_", " ")
    return "\n".join(
        [
            f"#### Candidate {state['candidate_reference'] + 1}: {state['candidate']['description']}",
            "",
            f"- **Status:** {status}",
            f"- **Evidence:** {outcome['evidence']}",
            f"- **Runtime reference:** {state['candidate_reference']}",
        ]
    )


def _render_error(error: ExecutionError) -> str:
    candidate = f" (candidate {error['candidate_reference'] + 1})" if "candidate_reference" in error else ""
    return f"- **{error['phase'].capitalize()}{candidate}:** {error['message']}"


def _scope_caveat() -> str:
    return "\n".join(
        [
            "## Scope caveat",
            "",
            "This assessment covers the listed tasks with an NVDA screen-reader profile in newly opened browser windows. "
            "It is not a complete accessibility audit or certification; browser-profile state may persist between task windows.",
        ]
    )