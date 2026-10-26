"""Durable phase-local state for the task-assessment workflow."""

import json
from pathlib import Path

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from a11y_gent.config import RunConfig
from a11y_gent.model.workflow import WorkflowPhase
from a11y_gent.model.workflow_runtime import WorkflowProvenance, WorkflowRuntimeState


class WorkflowRun:
    """A checkpointed workflow run with isolated contexts for each phase."""

    def __init__(
        self,
        checkpoint_path: Path,
        checkpoint_id: str,
        connection: aiosqlite.Connection,
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
        self._graph = _build_graph(self._checkpointer)

    async def record_phase_context(
        self,
        phase: WorkflowPhase,
        context: object,
        task_number: int | None = None,
        candidate_reference: int | None = None,
    ) -> None:
        """Persist one phase-local context and its chronological provenance."""
        values = await self._state_values()
        input_state: WorkflowRuntimeState = {
            "phase_contexts": values["phase_contexts"],
            "pending_phase": phase.value,
            "pending_context": context,
            "pending_task_number": task_number,
            "pending_candidate_reference": candidate_reference,
        }
        await self._graph.ainvoke(input_state, self.thread_config)
        self._append_provenance(phase, task_number, candidate_reference)

    async def phase_context(
        self,
        phase: WorkflowPhase,
        task_number: int | None = None,
        candidate_reference: int | None = None,
    ) -> object | None:
        """Return only the context persisted for ``phase``."""
        return (await self._state_values())["phase_contexts"].get(
            _context_key(phase.value, task_number, candidate_reference)
        )

    @property
    def provenance(self) -> list[WorkflowProvenance]:
        """Return chronological phase updates for this workflow run."""
        if not self.provenance_path.exists():
            return []
        return [
            json.loads(line)
            for line in self.provenance_path.read_text(encoding="utf-8").splitlines()
        ]

    @property
    def thread_config(self) -> dict:
        """Return the LangGraph configuration identifying this run's checkpoints."""
        return {"configurable": {"thread_id": self.checkpoint_id}}

    @property
    def checkpointer(self) -> AsyncSqliteSaver:
        """Return the SQLite checkpointer shared by workflow stages."""
        return self._checkpointer

    def phase_thread_config(self, phase: WorkflowPhase) -> dict:
        """Return the checkpoint identity for one isolated workflow stage."""
        return {
            "configurable": {
                "thread_id": self.checkpoint_id,
                "checkpoint_ns": phase.value,
            }
        }

    @property
    def metadata_path(self) -> Path:
        """Return the non-secret resume metadata path for this run."""
        return self.checkpoint_path.with_name(f"{self.checkpoint_path.stem}.metadata.json")

    @property
    def provenance_path(self) -> Path:
        """Return the append-only chronological provenance log path."""
        return self.checkpoint_path.with_name(f"{self.checkpoint_path.stem}.provenance.jsonl")

    async def close(self) -> None:
        """Close the SQLite connection backing this run."""
        await self._connection.close()

    async def _state_values(self) -> WorkflowRuntimeState:
        snapshot = await self._graph.aget_state(self.thread_config)
        if snapshot.values:
            return snapshot.values
        return {"phase_contexts": {}, "pending_phase": "", "pending_context": None,
                "pending_task_number": None, "pending_candidate_reference": None}

    def _append_provenance(
        self,
        phase: WorkflowPhase,
        task_number: int | None,
        candidate_reference: int | None,
    ) -> None:
        record = {
            "run_id": self.checkpoint_id,
            "phase": phase.value,
            "task_number": task_number,
            "candidate_reference": candidate_reference,
        }
        with self.provenance_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")


async def create_workflow_run(config: RunConfig, run_id: str) -> WorkflowRun:
    """Create a new run with a stable checkpoint identity derived from ``run_id``."""
    checkpoint_path = Path(config.resume_path) if config.resume_path else _checkpoint_path(config)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    connection = await aiosqlite.connect(checkpoint_path)
    run = WorkflowRun(checkpoint_path, run_id, connection)
    run.metadata_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "checkpoint_id": run.checkpoint_id,
                "checkpoint_path": str(run.checkpoint_path),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return run


async def resume_workflow_run(checkpoint_path: str | Path, checkpoint_id: str) -> WorkflowRun:
    """Reopen a run's SQLite checkpoint by its persisted identity."""
    path = Path(checkpoint_path)
    return WorkflowRun(path, checkpoint_id, await aiosqlite.connect(path))


async def resume_workflow_run_from_metadata(metadata_path: str | Path) -> WorkflowRun:
    """Reopen the workflow run identified by non-secret resume metadata."""
    metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
    return await resume_workflow_run(metadata["checkpoint_path"], metadata["checkpoint_id"])


def _checkpoint_path(config: RunConfig) -> Path:
    trajectory_path = Path(config.trajectory_path)
    return trajectory_path.with_name(f"{trajectory_path.stem}.workflow.sqlite")


def _build_graph(checkpointer: AsyncSqliteSaver):
    graph = StateGraph(WorkflowRuntimeState)
    graph.add_node("record_phase_context", _record_phase_context)
    graph.add_edge(START, "record_phase_context")
    graph.add_edge("record_phase_context", END)
    return graph.compile(checkpointer=checkpointer)


def _record_phase_context(state: WorkflowRuntimeState) -> WorkflowRuntimeState:
    contexts = dict(state["phase_contexts"])
    contexts[
        _context_key(
            state["pending_phase"],
            state["pending_task_number"],
            state["pending_candidate_reference"],
        )
    ] = state["pending_context"]
    return {**state, "phase_contexts": contexts}


def _context_key(
    phase: str, task_number: int | None, candidate_reference: int | None
) -> str:
    parts = [phase]
    if task_number is not None:
        parts.append(f"task-{task_number}")
    if candidate_reference is not None:
        parts.append(f"candidate-{candidate_reference}")
    return ":".join(parts)