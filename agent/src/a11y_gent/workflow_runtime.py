"""Checkpointed supergraph for the task-assessment workflow."""

import json
from dataclasses import dataclass
from pathlib import Path

import aiosqlite
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from a11y_gent.adaptor.llm_client import LlmClient
from a11y_gent.config import RunConfig
from a11y_gent.model.workflow_runtime import TaskPipelineState, WorkflowRuntimeState
from a11y_gent.prompts import make_retrospective_completion_tool
from a11y_gent.task_retrospective import build_retrospective_graph, initial_retrospective_state


@dataclass(frozen=True)
class WorkflowDependencies:
    """Injected phase capabilities used while building the supergraph."""

    retrospective_llm: LlmClient
    retrospective_model: str


class WorkflowRun:
    """One supergraph invocation context with one SQLite checkpointer."""

    def __init__(
        self,
        checkpoint_path: Path,
        checkpoint_id: str,
        connection: aiosqlite.Connection,
        dependencies: WorkflowDependencies,
    ):
        self.checkpoint_path = checkpoint_path.resolve()
        self.checkpoint_id = checkpoint_id
        self._connection = connection
        self._checkpointer = AsyncSqliteSaver(
            self._connection,
            serde=JsonPlusSerializer(
                allowed_msgpack_modules=[("a11y_gent.model.message", "MessageOrigin")]
            ),
        )
        self._graph = build_workflow_supergraph(dependencies, self._checkpointer)

    @property
    def thread_config(self) -> dict:
        """Return the stable identity for this workflow's checkpoints."""
        return {"configurable": {"thread_id": self.checkpoint_id}}

    @property
    def metadata_path(self) -> Path:
        """Return the non-secret file needed to reopen this workflow."""
        return self.checkpoint_path.with_suffix(".metadata.json")

    async def invoke(self, state: WorkflowRuntimeState) -> WorkflowRuntimeState:
        """Run the workflow supergraph with its sole checkpoint owner."""
        return await self._graph.ainvoke(state, self.thread_config)

    async def state(self) -> WorkflowRuntimeState:
        """Return the current durable superstate."""
        return (await self._graph.aget_state(self.thread_config)).values

    async def close(self) -> None:
        """Release the SQLite connection after workflow use."""
        await self._connection.close()


async def create_workflow_run(
    config: RunConfig, run_id: str, dependencies: WorkflowDependencies
) -> WorkflowRun:
    """Create a workflow run with a stable checkpoint identity."""
    checkpoint_path = Path(config.resume_path) if config.resume_path else _checkpoint_path(config)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    run = WorkflowRun(checkpoint_path, run_id, await aiosqlite.connect(checkpoint_path), dependencies)
    run.metadata_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "checkpoint_id": run.checkpoint_id,
                "checkpoint_path": str(run.checkpoint_path),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return run


async def resume_workflow_run(
    checkpoint_path: str | Path, checkpoint_id: str, dependencies: WorkflowDependencies
) -> WorkflowRun:
    """Reopen a workflow supergraph by its persisted identity."""
    path = Path(checkpoint_path)
    return WorkflowRun(path, checkpoint_id, await aiosqlite.connect(path), dependencies)


def build_workflow_supergraph(dependencies: WorkflowDependencies, checkpointer: AsyncSqliteSaver):
    """Build phase wrappers around child graphs that inherit ``checkpointer``."""
    graph = StateGraph(WorkflowRuntimeState)
    graph.add_node("retrospective", _retrospective_wrapper(dependencies))
    graph.add_edge(START, "retrospective")
    graph.add_edge("retrospective", END)
    return graph.compile(checkpointer=checkpointer)


def _retrospective_wrapper(dependencies: WorkflowDependencies):
    child_graph = build_retrospective_graph(
        dependencies.retrospective_llm,
        make_retrospective_completion_tool(),
        dependencies.retrospective_model,
    )

    async def retrospect_pipelines(
        state: WorkflowRuntimeState, config: RunnableConfig
    ) -> WorkflowRuntimeState:
        pipelines = [
            await _retrospect_pipeline(pipeline, child_graph, config)
            for pipeline in state["task_pipelines"]
        ]
        return {"task_pipelines": pipelines}

    return retrospect_pipelines


async def _retrospect_pipeline(
    pipeline: TaskPipelineState, child_graph, config: RunnableConfig
) -> TaskPipelineState:
    retrospective_state = pipeline["retrospective_state"]
    if retrospective_state["candidates"]:
        return pipeline
    state = await child_graph.ainvoke(
        initial_retrospective_state(pipeline["task"], pipeline["solve_task_state"]["history"]),
        config,
    )
    return {
        **pipeline,
        "retrospective_state": {
            "history": state["history"],
            "candidates": state["candidates"],
        },
    }


def _checkpoint_path(config: RunConfig) -> Path:
    trajectory_path = Path(config.trajectory_path)
    return trajectory_path.with_name(f"{trajectory_path.stem}.workflow.sqlite")