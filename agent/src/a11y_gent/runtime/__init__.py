"""The agent runtime: the reason -> act -> observe loop.

- :func:`a11y_gent.runtime.graph.build_agent_graph` - the compiled loop.
- :func:`a11y_gent.runtime.termination.should_continue` - the stop condition.
"""

from a11y_gent.runtime.graph import build_agent_graph

__all__ = ["build_agent_graph"]
