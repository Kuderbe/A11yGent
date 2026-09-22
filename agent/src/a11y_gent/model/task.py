"""The user task the agent tries to complete under a screen-reader profile."""

from typing import NotRequired, TypedDict


class Task(TypedDict):
    """A single accessibility test task.

    ``url``          - the page/app the task is performed on.
    ``goal``         - natural-language user story (e.g. "Sign up for an
                       account", "Buy the first product in the list").
    ``success_hint`` - optional note describing what "done" looks like, given
                       to the agent to help it decide when to report a verdict.
    """

    url: str
    goal: str
    success_hint: NotRequired[str]
