"""Run the checkpointed phased assessment workflow."""

import json
from pathlib import Path

from a11y_gent.application.program import RunContext
from a11y_gent.model.assessment_report import AssessmentReport
from a11y_gent.workflow_runtime import (
    WorkflowDependencies,
    create_initial_workflow_state,
    create_workflow_run,
    resume_workflow_run,
)


class BaselineV2:
    """The executable baseline using the phased task-assessment workflow."""

    id = "baseline-v2"
    uses_phased_workflow = True

    async def run(self, context: RunContext) -> AssessmentReport:
        """Execute the workflow and return its complete report."""
        resuming = _is_resuming(context)
        dependencies = _dependencies(context)
        run = await _workflow_run(context, dependencies, resuming)
        try:
            state = await run.invoke(
                None if resuming else _initial_state(context)
            )
        finally:
            await run.close()
        report = AssessmentReport.from_workflow_state(
            state,
            context.discovery_max_steps,
            context.max_steps,
        )
        report.save_to_file(context.report_path)
        return report


def _dependencies(context: RunContext) -> WorkflowDependencies:
    if (
        context.workflow_config is None
        or context.solve_llm is None
        or context.retrospective_llm is None
        or context.verification_llm is None
        or context.devtools_llm is None
        or context.nvda_tools is None
        or context.devtools_tools is None
    ):
        raise RuntimeError("Phased workflow context is incomplete")
    return WorkflowDependencies(
        solve_llm=context.solve_llm,
        solve_model=context.model,
        retrospective_llm=context.retrospective_llm,
        retrospective_model=context.model,
        retrospective_max_iterations=context.workflow_config.retrospective_max_iterations,
        verification_llm=context.verification_llm,
        verification_model=context.model,
        nvda_tools=context.nvda_tools,
        nvda_max_steps=context.max_steps,
        enrichment_llm=context.devtools_llm,
        enrichment_model=context.model,
        devtools_tools=context.devtools_tools,
        devtools_max_steps=context.discovery_max_steps,
        navigator=context.navigator,
    )


async def _workflow_run(context: RunContext, dependencies: WorkflowDependencies, resuming: bool):
    config = context.workflow_config
    if not resuming:
        return await create_workflow_run(config, context.run_id, dependencies)
    metadata_path = Path(config.resume_path).with_suffix(".metadata.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    return await resume_workflow_run(config.resume_path, metadata["checkpoint_id"], dependencies)


def _is_resuming(context: RunContext) -> bool:
    if context.workflow_config.resume_path is None:
        return False
    return Path(context.workflow_config.resume_path).with_suffix(".metadata.json").exists()


def _initial_state(context: RunContext):
    if context.workflow_tasks is None:
        raise RuntimeError("New phased workflow runs require selected tasks")
    return {
        **create_initial_workflow_state(context.workflow_tasks),
        "discovery_state": {"incomplete": context.discovery_incomplete},
    }