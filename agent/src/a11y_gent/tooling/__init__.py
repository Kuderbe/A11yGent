"""Tools the agent itself provides (as opposed to external MCP/NVDA tools).

- :mod:`a11y_gent.tooling.verdict` - ``report_verdict``: terminate with a
  status and summary.
- :mod:`a11y_gent.tooling.barrier` - ``report_barrier``: log one barrier as it
  is observed.
- :mod:`a11y_gent.tooling.extract` - rebuild the typed Verdict / Barrier objects
  from the ``report_verdict`` / ``report_barrier`` calls in the history.

Both report_* tools are no-op sinks; their payload is the tool-call arguments.
"""
