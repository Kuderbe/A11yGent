"""Checkpointed supergraph for the task-assessment workflow."""

import json
from dataclasses import dataclass
from operator import add
from pathlib import Path
from typing import Annotated

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from a11y_gent.adaptor.llm_client import LlmClient
from a11y_gent.config import RunConfig
from a11y_gent.model.workflow_runtime import (
    RetrospectiveSubstate,
    VerificationSubstate,
    WorkflowRuntimeState,
    replace_retrospective_states,
)
from a11y_gent.model.tool import Tool
from a11y_gent.prompts import make_retrospective_completion_tool, make_verify_completion_tool
from a11y_gent.task_retrospective import RetrospectiveState, build_retrospective_graph
from a11y_gent.task_verification import (
    VerificationState,
    build_verification_graph,
    initial_verification_state,
)


@dataclass(frozen=True)
class WorkflowDependencies:
    """Injected phase capabilities used while building the supergraph."""

    retrospective_llm: LlmClient
    retrospective_model: str
    verification_llm: LlmClient
    verification_model: str
    nvda_tools: list[Tool]
    nvda_max_steps: int


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
                allowed_msgpack_modules=[
                    ("a11y_gent.model.message", "MessageOrigin"),
                    ("a11y_gent.model.workflow", "VerificationOutcomeStatus"),
                ]
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
    """Build the supergraph with embedded phase graphs and one checkpoint owner."""
    graph = StateGraph(WorkflowRuntimeState)
    graph.add_node("retrospective", _retrospective_subgraph(dependencies))
    graph.add_node("verification", _verification_subgraph(dependencies))
    graph.add_conditional_edges(START, _initial_sends, ["retrospective", "verification"])
    graph.add_conditional_edges("retrospective", _verification_sends, ["verification", END])
    graph.add_conditional_edges("verification", _verification_sends, ["verification", END])
    return graph.compile(checkpointer=checkpointer)


def _retrospective_sends(state: WorkflowRuntimeState) -> list[Send]:
    return [
        Send("retrospective", retrospective_state)
        for retrospective_state in state["retrospective_states"]
        if not _retrospective_completed(retrospective_state)
    ]


def _initial_sends(state: WorkflowRuntimeState) -> list[Send]:
    retrospective_sends = _retrospective_sends(state)
    return retrospective_sends or _verification_sends(state)


def _retrospective_subgraph(dependencies: WorkflowDependencies):
    child_graph = build_retrospective_graph(
        dependencies.retrospective_llm,
        make_retrospective_completion_tool(),
        dependencies.retrospective_model,
    )
    adapter = StateGraph(RetrospectiveSubgraphState)
    adapter.add_node("phase", child_graph)
    adapter.add_node("collect", _collect_retrospective_state)
    adapter.add_edge(START, "phase")
    adapter.add_edge("phase", "collect")
    adapter.add_edge("collect", END)
    return adapter.compile()


def _verification_sends(state: WorkflowRuntimeState) -> list[Send]:
    completed = {
        (verification["task"]["number"], verification["candidate_reference"])
        for verification in state["verification_states"]
    }
    for retrospective_state in sorted(state["retrospective_states"], key=lambda state: state["task"]["number"]):
        task = retrospective_state["task"]
        for candidate_reference, candidate in enumerate(retrospective_state["candidates"]):
            if (task["number"], candidate_reference) not in completed:
                return [
                    Send(
                        "verification",
                        initial_verification_state(task, candidate_reference, candidate),
                    )
                ]
    return []


def _retrospective_completed(state: RetrospectiveSubstate) -> bool:
    return any(
        call["tool"]["name"] == "complete_retrospective"
        for message in state["history"]
        for call in message.get("tool_calls", [])
    )


def _verification_subgraph(dependencies: WorkflowDependencies):
    child_graph = build_verification_graph(
        dependencies.verification_llm,
        dependencies.verification_model,
        dependencies.nvda_max_steps,
        [*dependencies.nvda_tools, make_verify_completion_tool()],
    )
    adapter = StateGraph(VerificationSubgraphState)
    adapter.add_node("phase", child_graph)
    adapter.add_node("collect", _collect_verification_state)
    adapter.add_edge(START, "phase")
    adapter.add_edge("phase", "collect")
    adapter.add_edge("collect", END)
    return adapter.compile()


class RetrospectiveSubgraphState(RetrospectiveState):
    """Retrospective state with its supergraph output channel."""

    retrospective_states: Annotated[list[RetrospectiveSubstate], replace_retrospective_states]


class VerificationSubgraphState(VerificationState):
    """Verification state with its supergraph output channel."""

    verification_states: Annotated[list[VerificationSubstate], add]


def _collect_retrospective_state(state: RetrospectiveSubgraphState) -> dict:
    return {
        "retrospective_states": [
            {
                "task": state["task"],
                "solve_task_history": state["solve_task_history"],
                "history": state["history"],
                "candidates": state["candidates"],
            }
        ]
    }


def _collect_verification_state(state: VerificationSubgraphState) -> dict:
    if state["outcome"] is None:
        raise RuntimeError("Verification must produce an outcome before collection")
    return {
        "verification_states": [
            {
                "task": state["task"],
                "candidate_reference": state["candidate_reference"],
                "candidate": state["candidate"],
                "history": state["history"],
                "outcome": state["outcome"],
            },
        ]
    }


def _checkpoint_path(config: RunConfig) -> Path:
    trajectory_path = Path(config.trajectory_path)
    return trajectory_path.with_name(f"{trajectory_path.stem}.workflow.sqlite")