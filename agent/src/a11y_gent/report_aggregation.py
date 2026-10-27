"""Derive aggregate barriers from completed report enrichments."""

from a11y_gent.model.workflow import AggregateBarrier, TaskResult
from a11y_gent.model.workflow_runtime import EnrichmentSubstate


def derive_aggregate_barriers(
    final_results: list[TaskResult], enrichment_states: list[EnrichmentSubstate]
) -> list[AggregateBarrier]:
    """Group cross-task occurrences with one shared remediation."""
    task_numbers = [result["task"]["number"] for result in final_results for _ in result["verdict"]["barriers"]]
    groups: dict[tuple[str, str], list[EnrichmentSubstate]] = {}
    for state in enrichment_states:
        enrichment = state["enrichment"]
        remediation_target = enrichment["remediation_target"]
        suggested_fix = enrichment["suggested_fix"]
        if "error" not in enrichment and remediation_target and suggested_fix:
            groups.setdefault((remediation_target, suggested_fix), []).append(state)

    aggregates = []
    for (_, remediation), states in groups.items():
        task_occurrences = {task_numbers[state["barrier_reference"]] for state in states}
        if len(task_occurrences) > 1:
            aggregates.append(
                {
                    "title": states[0]["enrichment"]["title"],
                    "barrier_references": [state["barrier_reference"] for state in states],
                    "remediation": remediation,
                }
            )
    return aggregates