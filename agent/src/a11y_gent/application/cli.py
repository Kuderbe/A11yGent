"""Create identical command-line interfaces for independently structured agents."""

import asyncio
import os
from collections.abc import Callable

import typer
from dotenv import load_dotenv

from a11y_gent.application.execution import execute
from a11y_gent.application.program import AgentProgram
from a11y_gent.config import RunConfig, build_task
from a11y_gent.observability import LogLevel

load_dotenv()


def build_app(program: AgentProgram) -> typer.Typer:
    app = typer.Typer(
        add_completion=False,
        help=f"Run the {program.id} A11yGent agent on a task.",
    )

    @app.command()
    def run(
        url: str = typer.Option(..., help="URL of the page/app under test."),
        goal: str | None = typer.Option(None, help="Optional user task; omitting it runs discovery."),
        success_hint: str | None = typer.Option(
            None, help="Optional note describing what 'done' looks like."
        ),
        model: str = typer.Option("gpt-5-mini", envvar="A11Y_GENT_MODEL", help="LLM model name."),
        nvda_mcp_url: str = typer.Option(
            "http://127.0.0.1:8765/mcp",
            envvar="A11Y_GENT_MCP_URL",
            help="URL of the NVDA MCP bridge (its tools drive the agent).",
        ),
        discovery_instructions: str | None = typer.Option(
            None, help="Optional guidance and permitted test data for task discovery."
        ),
        devtools_mcp_url: str = typer.Option(
            "http://127.0.0.1:9222/mcp",
            envvar="A11Y_GENT_DEVTOOLS_MCP_URL",
            help="URL of the Chrome DevTools MCP endpoint.",
        ),
        discovery_max_steps: int = typer.Option(
            150,
            help="Combined DevTools interaction limit for discovery and report enrichment.",
        ),
        nvda_max_steps: int = typer.Option(
            150,
            help="Independent NVDA interaction limit for each task attempt and candidate verification.",
        ),
        retrospective_max_iterations: int = typer.Option(
            20,
            min=1,
            help="Maximum candidate-creation iterations for each retrospective analysis.",
        ),
        report_out: str | None = typer.Option(
            None, help="Optional path for the Markdown report."
        ),
        resume: str | None = typer.Option(
            None, help="Optional SQLite checkpoint path to resume."
        ),
        out: str = typer.Option("trajectory.jsonl", help="Where to write the trajectory JSONL."),
        log_level: LogLevel = typer.Option(
            LogLevel.MINIMAL,
            help="Log detail: minimal, info, verbose, or debug.",
        ),
        log_file: str | None = typer.Option(
            None, help="Optional log-file template; supports <TIMESTAMP> and <RUN_ID>."
        ),
    ) -> None:
        config = RunConfig(
            application_url=url,
            task=build_task(url, goal, success_hint) if goal is not None else None,
            model=model,
            openai_base_url=os.environ["A11Y_GENT_OPENAI_BASE_URL"],
            openai_api_key=os.environ["A11Y_GENT_OPENAI_API_KEY"],
            nvda_mcp_url=nvda_mcp_url,
            trajectory_path=out,
            log_level=log_level,
            log_file_template=log_file,
            discovery_instructions=discovery_instructions,
            devtools_mcp_url=devtools_mcp_url,
            discovery_max_steps=discovery_max_steps,
            nvda_max_steps=nvda_max_steps,
            retrospective_max_iterations=retrospective_max_iterations,
            report_path=report_out,
            resume_path=resume,
        )
        result = asyncio.run(execute(config, program))
        if hasattr(result, "save_to_file"):
            print("Report:", config.report_path or "a UTC-timestamped Markdown file")
        else:
            print("Verdict:", result["verdict"])

    return app


def main_for(program: AgentProgram) -> Callable[[], None]:
    app = build_app(program)

    def main() -> None:
        app()

    return main