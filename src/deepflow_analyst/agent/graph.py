"""LangGraph StateGraph with intent triage + HITL clarification.

Replaces the straight-line pipeline with a branching graph:

                  ┌── write       ──→ write_rejected ──→ END
    question →  intent
                  ├── ambiguous  ──→ clarify (interrupt) ──┐
                  │                       ↑                │
                  └── read                └─── resume ─────┘ (loops back to intent)
                   │
                   ▼
              writer → reviewer → executor → insight → END

HITL hooks:
  - write intent (delete / update / drop / insert) short-circuits before any
    SQL is generated or executed. The caller gets a rejection message.
  - clarify() calls LangGraph's `interrupt()` so the graph pauses and
    returns a clarifying question; when resumed with `Command(resume=answer)`
    the user's answer is appended to the question and flow continues.

State is per-thread via MemorySaver. W8 teaching swaps to PostgresSaver
by changing one line.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from ..llm_client import chat
from . import pipeline


class AgentState(TypedDict, total=False):
    question: str
    intent_type: str  # "read" | "write" | "ambiguous"
    intent_reason: str
    clarification_question: str | None
    clarified: bool  # True once the user has answered a clarification
    draft_sql: str
    reviewed_sql: str
    columns: list[str]
    rows: list[list[Any]]
    answer: str
    status: str  # "ok" | "error" | "write_rejected"
    error: str | None


INTENT_SYSTEM_PROMPT = (
    "You triage natural-language questions for a read-only PostgreSQL analytics agent.\n"
    "Return a JSON object with keys:\n"
    '  "intent_type": one of "read" | "write" | "ambiguous"\n'
    '  "reason": a short explanation\n'
    '  "clarification_question": question to ask user (only when ambiguous, else null)\n'
    "\n"
    "Rules:\n"
    "- 'read' is the DEFAULT. Choose it unless you have strong evidence otherwise.\n"
    "- 'write' = user clearly asks to delete / update / insert / modify / drop / truncate.\n"
    "- 'ambiguous' = the question is missing a crucial fact that materially changes the SQL\n"
    "  (e.g. '销量' could be quantity or revenue; '最好' could be highest-priced or most-sold).\n"
    "  Do NOT flag ambiguous just for tie-break ordering or format preferences.\n"
    "\n"
    "- `clarification_question` MUST be written in the SAME language as the user's question\n"
    "  (中文问题用中文澄清，English questions use English).\n"
    "\n"
    "Output ONLY the JSON object — no markdown fences, no prose.\n"
)


async def _classify_intent(question: str) -> dict[str, Any]:
    messages = [
        {"role": "system", "content": INTENT_SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    raw = (await chat(messages)).strip()
    raw = re.sub(r"^\s*```(?:json)?\s*", "", raw, flags=re.IGNORECASE).strip()
    raw = re.sub(r"\s*```\s*$", "", raw).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "intent_type": "read",
            "reason": "parser fallback",
            "clarification_question": None,
        }
    t = parsed.get("intent_type", "read")
    if t not in ("read", "write", "ambiguous"):
        t = "read"
    return {
        "intent_type": t,
        "reason": str(parsed.get("reason", "")),
        "clarification_question": parsed.get("clarification_question"),
    }


async def intent_node(state: AgentState) -> dict[str, Any]:
    if state.get("clarified"):
        return {"intent_type": "read", "intent_reason": "post-clarification"}
    decision = await _classify_intent(state["question"])
    return {
        "intent_type": decision["intent_type"],
        "intent_reason": decision["reason"],
        "clarification_question": decision.get("clarification_question"),
    }


def route_after_intent(state: AgentState) -> str:
    t = state.get("intent_type", "read")
    if t == "write":
        return "write_rejected"
    if t == "ambiguous":
        return "clarify"
    return "writer"


def write_rejected_node(state: AgentState) -> dict[str, Any]:
    reason = state.get("intent_reason", "write operation detected")
    return {
        "status": "write_rejected",
        "answer": f"这是一个只读分析系统，已拒绝写入/修改类请求。识别原因：{reason}",
        "error": None,
    }


def clarify_node(state: AgentState) -> dict[str, Any]:
    q = state.get("clarification_question") or "请提供更多上下文。"
    user_answer = interrupt({"clarification_question": q})
    combined_q = f"{state['question']}\n\n[用户澄清] {user_answer}"
    return {"question": combined_q, "clarified": True}


async def writer_node(state: AgentState) -> dict[str, Any]:
    draft = await pipeline.generate_sql(state["question"])
    pipeline.validate_sql(draft)
    return {"draft_sql": draft}


async def reviewer_node(state: AgentState) -> dict[str, Any]:
    reviewed = await pipeline.review_sql(state["question"], state["draft_sql"])
    pipeline.validate_sql(reviewed)
    reviewed = pipeline.ensure_limit(reviewed)
    return {"reviewed_sql": reviewed}


def executor_node(state: AgentState) -> dict[str, Any]:
    try:
        columns, rows = pipeline.execute_sql(state["reviewed_sql"])
        return {"columns": columns, "rows": rows}
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}


async def insight_node(state: AgentState) -> dict[str, Any]:
    if state.get("status") == "error":
        return {}
    answer = await pipeline.interpret(
        state["question"],
        state["reviewed_sql"],
        state["columns"],
        state["rows"],
    )
    return {"answer": answer, "status": "ok"}


def _build_graph() -> Any:
    g = StateGraph(AgentState)
    g.add_node("intent", intent_node)
    g.add_node("clarify", clarify_node)
    g.add_node("write_rejected", write_rejected_node)
    g.add_node("writer", writer_node)
    g.add_node("reviewer", reviewer_node)
    g.add_node("executor", executor_node)
    g.add_node("insight", insight_node)

    g.set_entry_point("intent")
    g.add_conditional_edges(
        "intent",
        route_after_intent,
        {"writer": "writer", "clarify": "clarify", "write_rejected": "write_rejected"},
    )
    g.add_edge("clarify", "intent")
    g.add_edge("write_rejected", END)
    g.add_edge("writer", "reviewer")
    g.add_edge("reviewer", "executor")
    g.add_edge("executor", "insight")
    g.add_edge("insight", END)

    return g.compile(checkpointer=MemorySaver())


graph = _build_graph()


@dataclass
class GraphResult:
    status: str
    thread_id: str
    answer: str = ""
    sql: str | None = None
    columns: list[str] | None = None
    rows: list[list[Any]] | None = None
    row_count: int | None = None
    clarification_question: str | None = None
    error: str | None = None


async def run(
    question: str | None = None,
    thread_id: str | None = None,
    resume_input: str | None = None,
) -> GraphResult:
    """Run (or resume) the agent graph.

    - New conversation: pass `question`; `thread_id` is auto-generated.
    - Resume after a clarification interrupt: pass `thread_id` and `resume_input`
      (the user's answer to the last clarification question).
    """
    if thread_id is None:
        thread_id = str(uuid.uuid4())
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}

    if resume_input is not None:
        await graph.ainvoke(Command(resume=resume_input), config=config)
    else:
        if not question:
            return GraphResult(
                status="error",
                thread_id=thread_id,
                error="question is required for a new conversation",
            )
        await graph.ainvoke({"question": question}, config=config)

    snapshot = graph.get_state(config)

    if snapshot.next:
        q_for_user: str | None = None
        for task in snapshot.tasks:
            for intr in task.interrupts:
                val = intr.value
                if isinstance(val, dict) and "clarification_question" in val:
                    q_for_user = val["clarification_question"]
                    break
            if q_for_user:
                break
        return GraphResult(
            status="awaiting_clarification",
            thread_id=thread_id,
            clarification_question=q_for_user,
        )

    final = snapshot.values
    rows = final.get("rows")
    return GraphResult(
        status=final.get("status", "ok"),
        thread_id=thread_id,
        answer=final.get("answer", ""),
        sql=final.get("reviewed_sql"),
        columns=final.get("columns"),
        rows=rows,
        row_count=len(rows) if rows is not None else None,
        error=final.get("error"),
    )
