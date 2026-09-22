"""Prompt assembly for the screen-reader agent.

- :mod:`a11y_gent.prompts.system_prompt` - the system prompt describing the
  screen-reader profile, the reason-then-act rhythm, and how to finish.
- :mod:`a11y_gent.prompts.exemplars` - few-shot think/act/observe examples.
"""

from a11y_gent.prompts.exemplars import few_shot_exemplars
from a11y_gent.prompts.system_prompt import build_system_prompt

__all__ = ["build_system_prompt", "few_shot_exemplars"]
