"""Render deterministic per-task Markdown report sections."""

from datetime import UTC, datetime
from pathlib import Path

from a11y_gent.model.workflow import ExecutionError, TaskResult
from a11y_gent.model.workflow import VerificationOutcomeStatus
from a11y_gent.model.workflow_runtime import EnrichmentSubstate, VerificationSubstate
from a11y_gent.report_aggregation import derive_aggregate_barriers


def render_task_markdown_sections(
    final_results: list[TaskResult],
    verification_states: list[VerificationSubstate],
    enrichment_states: list[EnrichmentSubstate],
    execution_errors: list[ExecutionError],
) -> str:
    """Render task outcomes and their supporting report details."""
    return "\n\n".join(_render_task_sections(final_results, verification_states, enrichment_states, execution_errors)) + "\n\n" + _scope_caveat() + "\n"


def render_markdown_report(
    final_results: list[TaskResult],
    verification_states: list[VerificationSubstate],
    enrichment_states: list[EnrichmentSubstate],
    discovery_incomplete: bool,
    discovery_max_steps: int,
    nvda_max_steps: int,
) -> str:
    """Render the complete deterministic Markdown report."""
    barrier_numbers = {reference: reference + 1 for reference, _ in enumerate(_barriers(final_results))}
    candidate_numbers = {
        (state["task"]["number"], state["candidate_reference"]): number
        for number, state in enumerate(_unverified_states(verification_states), start=1)
    }
    discovery = "Incomplete; tested tasks may not cover all ordinary-user goals." if discovery_incomplete else "Complete."
    header = "\n".join(
        [
            "# Accessibility assessment report",
            "",
            f"- **Discovery:** {discovery}",
            f"- **Limits:** {discovery_max_steps} DevTools interactions; {nvda_max_steps} NVDA interactions per task attempt and candidate verification.",
        ]
    )
    sections = _render_task_sections(
        final_results,
        verification_states,
        enrichment_states,
        _execution_errors(verification_states),
        barrier_numbers,
        candidate_numbers,
    )
    no_findings = _render_no_findings(final_results)
    report_sections = [header]
    if no_findings is not None:
        report_sections.append(no_findings)
    report_sections.extend([*sections, _render_aggregates(derive_aggregate_barriers(final_results, enrichment_states)), _scope_caveat()])
    return "\n\n".join(report_sections) + "\n"


def write_markdown_report(
    markdown: str, report_path: str | None, now: datetime | None = None, directory: str | Path = "."
) -> Path:
    """Write a report to an explicit path or a UTC-named default path."""
    if report_path is None:
        timestamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
        path = Path(directory) / f"a11y-report-{timestamp}.md"
    else:
        path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    return path


def _render_task_sections(
    final_results, verification_states, enrichment_states, execution_errors, barrier_numbers=None, candidate_numbers=None
):
    enrichments = {state["barrier_reference"]: state["enrichment"] for state in enrichment_states}
    barrier_reference = 0
    sections = []
    for result in final_results:
        task = result["task"]
        verdict = result["verdict"]
        barriers = []
        for barrier in verdict["barriers"]:
            enrichment = enrichments.get(barrier_reference)
            barriers.append(_render_barrier(task["number"], barrier, enrichment, barrier_numbers.get(barrier_reference) if barrier_numbers else None))
            barrier_reference += 1
        candidates = [
            _render_candidate(state, candidate_numbers.get((task["number"], state["candidate_reference"])) if candidate_numbers else None)
            for state in verification_states
            if state["task"]["number"] == task["number"]
            and state["outcome"]["status"]
            in (VerificationOutcomeStatus.UNVERIFIED_BUDGET_EXHAUSTED, VerificationOutcomeStatus.UNVERIFIED_EXECUTION_ERROR)
        ]
        errors = [_render_error(error, candidate_numbers) for error in execution_errors if error["task_number"] == task["number"]]
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
    return sections


def _render_barrier(task_number, barrier, enrichment, barrier_number=None):
    title = enrichment["title"] if enrichment is not None else barrier["description"]
    suggested_fix = enrichment["suggested_fix"] if enrichment is not None else "manual investigation"
    steps = "\n".join(f"  {number}. {step}" for number, step in enumerate(barrier["reproduction_steps"], start=1))
    lines = [
        f"#### {'Barrier ' + str(barrier_number) + ': ' if barrier_number is not None else ''}{title}",
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


def _barriers(final_results):
    return [barrier for result in final_results for barrier in result["verdict"]["barriers"]]


def _render_candidate(state: VerificationSubstate, candidate_number=None) -> str:
    outcome = state["outcome"]
    status = outcome["status"].value.replace("unverified_", "unverified: ").replace("_", " ")
    return "\n".join(
        [
            f"#### Candidate {candidate_number if candidate_number is not None else state['candidate_reference'] + 1}: {state['candidate']['description']}",
            "",
            f"- **Status:** {status}",
            f"- **Evidence:** {outcome['evidence']}",
            f"- **Runtime reference:** {state['candidate_reference']}",
        ]
    )


def _render_error(error: ExecutionError, candidate_numbers=None) -> str:
    candidate = ""
    if "candidate_reference" in error:
        number = candidate_numbers.get((error["task_number"], error["candidate_reference"])) if candidate_numbers else None
        candidate = f" (candidate {number if number is not None else error['candidate_reference'] + 1})"
    return f"- **{error['phase'].capitalize()}{candidate}:** {error['message']}"


def _unverified_states(verification_states):
    return sorted(
        [
            state
            for state in verification_states
            if state["outcome"]["status"]
            in (VerificationOutcomeStatus.UNVERIFIED_BUDGET_EXHAUSTED, VerificationOutcomeStatus.UNVERIFIED_EXECUTION_ERROR)
        ],
        key=lambda state: (state["task"]["number"], state["candidate_reference"]),
    )


def _render_aggregates(aggregates) -> str:
    if not aggregates:
        return "## Common remediations\n\nNone."
    sections = []
    for aggregate in aggregates:
        references = ", ".join(str(reference + 1) for reference in aggregate["barrier_references"])
        sections.append("\n".join([f"### {aggregate['title']}", "", f"- **Barriers:** {references}", f"- **Suggested fix:** {aggregate['remediation']}"]))
    return "## Common remediations\n\n" + "\n\n".join(sections)


def _execution_errors(verification_states):
    return [state["outcome"]["execution_error"] for state in verification_states if "execution_error" in state["outcome"]]


def _render_no_findings(final_results) -> str | None:
    if _barriers(final_results):
        return None
    tasks = ", ".join(f"{result['task']['number']:02d} {result['task']['description']}" for result in final_results)
    return "\n".join(["## No confirmed barriers", "", "No confirmed barriers were found in the tested tasks.", f"- **Tested tasks:** {tasks}"])


def _scope_caveat() -> str:
    return "\n".join(
        [
            "## Scope caveat",
            "",
            "This assessment covers the listed tasks with an NVDA screen-reader profile in newly opened browser windows. "
            "It is not a complete accessibility audit or certification; browser-profile state may persist between task windows.",
        ]
    )