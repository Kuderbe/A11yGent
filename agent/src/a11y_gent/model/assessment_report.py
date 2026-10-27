"""Complete deterministic report derived from workflow phase outputs."""

from dataclasses import dataclass
from pathlib import Path

from a11y_gent.model.workflow import TaskResult
from a11y_gent.model.workflow_runtime import EnrichmentSubstate, VerificationSubstate, WorkflowRuntimeState
from a11y_gent.report_aggregation import derive_aggregate_barriers
from a11y_gent.report_rendering import render_markdown_report, write_markdown_report


@dataclass(frozen=True)
class AssessmentReport:
    """The durable developer-facing outcome of a phased assessment."""

    final_results: list[TaskResult]
    verification_states: list[VerificationSubstate]
    enrichment_states: list[EnrichmentSubstate]
    discovery_incomplete: bool
    discovery_max_steps: int
    nvda_max_steps: int

    @classmethod
    def from_workflow_state(
        cls,
        state: WorkflowRuntimeState,
        discovery_max_steps: int,
        nvda_max_steps: int,
    ) -> "AssessmentReport":
        """Derive a report from the completed workflow state."""
        return cls(
            state["final_result_states"],
            state["verification_states"],
            state["enrichment_states"],
            bool(state["discovery_state"].get("incomplete", False)),
            discovery_max_steps,
            nvda_max_steps,
        )

    def to_markdown(self) -> str:
        """Return the report's deterministic Markdown representation."""
        return render_markdown_report(
            self.final_results,
            self.verification_states,
            self.enrichment_states,
            self.discovery_incomplete,
            self.discovery_max_steps,
            self.nvda_max_steps,
        )

    @property
    def execution_errors(self):
        """Return execution errors retained by verification outcomes."""
        return [
            state["outcome"]["execution_error"]
            for state in self.verification_states
            if "execution_error" in state["outcome"]
        ]

    @property
    def aggregates(self):
        """Return common remediations derived from successful enrichments."""
        return derive_aggregate_barriers(self.final_results, self.enrichment_states)

    def save_to_file(self, report_path: str | Path | None) -> Path:
        """Persist the deterministic Markdown representation."""
        return write_markdown_report(self.to_markdown(), str(report_path) if report_path is not None else None)