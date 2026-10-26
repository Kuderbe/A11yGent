"""Prompt assembly for the screen-reader agent.

- :mod:`a11y_gent.prompts.system_prompt` - the system prompt describing the
  screen-reader profile, the reason-then-act rhythm, and how to finish.
- :mod:`a11y_gent.prompts.exemplars` - few-shot think/act/observe examples.
"""

from a11y_gent.prompts.exemplars import few_shot_exemplars
from a11y_gent.prompts.phase_prompts import (
    build_discovery_prompt,
    build_report_enrichment_prompt,
    build_retrospective_prompt,
    build_solve_task_prompt,
    build_verify_prompt,
    make_discovery_completion_tool,
    make_report_enrichment_completion_tool,
    make_retrospective_completion_tool,
    make_solve_task_completion_tool,
    make_verify_completion_tool,
)
from a11y_gent.prompts.system_prompt import build_system_prompt

__all__ = [
    "build_discovery_prompt",
    "build_report_enrichment_prompt",
    "build_retrospective_prompt",
    "build_solve_task_prompt",
    "build_system_prompt",
    "build_verify_prompt",
    "few_shot_exemplars",
    "make_discovery_completion_tool",
    "make_report_enrichment_completion_tool",
    "make_retrospective_completion_tool",
    "make_solve_task_completion_tool",
    "make_verify_completion_tool",
]
