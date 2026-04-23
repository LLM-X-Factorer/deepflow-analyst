"""Single-LLM agent pipeline (W6 E2E minimal version).

The full CrewAI 4-agent version, LangGraph orchestration, and HITL
come in later weeks — see 🎯课程规划/DeepFlow-Analyst-结业项目设计.md.
"""

from .pipeline import QueryResult, run

__all__ = ["QueryResult", "run"]
