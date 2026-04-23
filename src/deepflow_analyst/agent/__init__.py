"""Agent orchestration.

`run` is the production entry point — it's the LangGraph StateGraph with
intent triage and HITL clarification (see `graph.py`).

`pipeline.run` is kept for tests and the evaluation harness, which exercise
a simpler straight-line Writer → Reviewer → Executor → Insight flow without
the HITL indirection.
"""

from .graph import GraphResult, run
from .pipeline import QueryResult

__all__ = ["GraphResult", "QueryResult", "run"]
