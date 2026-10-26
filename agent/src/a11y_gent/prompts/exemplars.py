"""Few-shot exemplars for the screen-reader agent.

A short message history illustrating the reason-then-act rhythm: a
reasoning-only turn, an action turn, an observation, and finally a verdict.
Prepended to the live conversation as in-context examples.

The action/observation turns are narrated text rather than real tool-call
messages, to stay decoupled from concrete tool signatures; the system prompt
tells the model to act via the actual tools.
"""

from a11y_gent.model.message import Message, MessageOrigin


def few_shot_exemplars() -> list[Message]:
    """Return the few-shot example messages to prepend to the conversation."""
    return [
        {
            "origin": MessageOrigin.USER,
            "name": "example_task",
            "content": (
                "EXAMPLE (for format only). Task: on a demo page, activate the "
                "'Subscribe' button."
            ),
        },
        {
            "origin": MessageOrigin.ASSISTANT,
            "name": "assistant",
            "content": (
                "Thought: I have not observed the page yet. I'll look for "
                "buttons using NVDA quick-nav 'b' and then read what NVDA "
                "announces. Next action: press 'b'."
            ),
        },
        {
            "origin": MessageOrigin.ASSISTANT,
            "name": "assistant",
            "content": "Action: press the 'b' key, then read the speech log.",
        },
        {
            "origin": MessageOrigin.USER,
            "name": "observation",
            "content": (
                "Observation: NVDA announced 'clickable' with no name, role, or "
                "state."
            ),
        },
        {
            "origin": MessageOrigin.ASSISTANT,
            "name": "assistant",
            "content": (
                "Thought: The control NVDA landed on is 'clickable' with no "
                "accessible name and no button role, so a screen-reader user "
                "cannot tell it is the Subscribe button nor operate it reliably. "
                "That is a barrier and it blocks the task. Next action: report "
                "the barrier."
            ),
        },
        {
            "origin": MessageOrigin.ASSISTANT,
            "name": "assistant",
            "content": (
                "Action: call report_barrier (description: Subscribe control "
                "has no name/role; expected behavior: NVDA announces the "
                "Subscribe button; actual behavior: NVDA said only 'clickable'; "
                "reproduction steps: quick-nav to the control; evidence: NVDA "
                "said only 'clickable')."
            ),
        },
        {
            "origin": MessageOrigin.USER,
            "name": "observation",
            "content": "Observation: barrier recorded.",
        },
        {
            "origin": MessageOrigin.ASSISTANT,
            "name": "assistant",
            "content": (
                "Thought: The only actionable control for this task is not "
                "operable via the screen reader, so the task is blocked. Next "
                "action: report the verdict."
            ),
        },
        {
            "origin": MessageOrigin.ASSISTANT,
            "name": "assistant",
            "content": (
                "Action: call report_verdict with status 'failed' and a short "
                "summary."
            ),
        },
    ]
