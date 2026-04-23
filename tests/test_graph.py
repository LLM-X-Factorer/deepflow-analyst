"""Tests for the LangGraph orchestration + HITL paths.

Covers the three routing branches out of the intent node
(read / write-rejected / ambiguous-then-resume) with the LLM mocked,
so these run without API credits. The read-path and resume-path
tests need a live Postgres to reach the executor — they skip cleanly
when the DB is unreachable (e.g. in the backend CI job which has no
services block).
"""

from typing import Any

import pytest
from sqlalchemy import text

from deepflow_analyst import db as _db
from deepflow_analyst.agent import graph as _graph
from deepflow_analyst.agent import pipeline as _pipeline


def _db_reachable() -> bool:
    try:
        with _db.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_write_intent_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_classify(q: str) -> dict[str, Any]:
        return {
            "intent_type": "write",
            "reason": "用户要求删除数据",
            "clarification_question": None,
        }

    monkeypatch.setattr(_graph, "_classify_intent", fake_classify)

    result = await _graph.run(question="删除所有客户")
    assert result.status == "write_rejected"
    assert "只读" in result.answer
    assert result.sql is None
    assert result.rows is None
    assert result.thread_id


@pytest.mark.asyncio
async def test_read_intent_runs_full_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    if not _db_reachable():
        pytest.skip("postgres not reachable")

    async def fake_classify(q: str) -> dict[str, Any]:
        return {
            "intent_type": "read",
            "reason": "counting artists",
            "clarification_question": None,
        }

    async def fake_generate(q: str) -> str:
        return "SELECT COUNT(*) AS n FROM artist"

    async def fake_review(q: str, sql: str) -> str:
        return sql

    async def fake_interpret(q: str, sql: str, cols: list[str], rows: list[list[Any]]) -> str:
        return "共 N 位艺人。"

    monkeypatch.setattr(_graph, "_classify_intent", fake_classify)
    monkeypatch.setattr(_pipeline, "generate_sql", fake_generate)
    monkeypatch.setattr(_pipeline, "review_sql", fake_review)
    monkeypatch.setattr(_pipeline, "interpret", fake_interpret)

    result = await _graph.run(question="有多少艺人？")
    assert result.status == "ok"
    assert result.row_count == 1
    assert result.sql is not None and "LIMIT" in result.sql.upper()
    assert result.answer == "共 N 位艺人。"


@pytest.mark.asyncio
async def test_ambiguous_interrupts_then_resumes(monkeypatch: pytest.MonkeyPatch) -> None:
    if not _db_reachable():
        pytest.skip("postgres not reachable")

    async def fake_classify(q: str) -> dict[str, Any]:
        # Only called once: the first time with the original question.
        # After resume, the intent node short-circuits via `clarified=True`.
        return {
            "intent_type": "ambiguous",
            "reason": "销量含糊",
            "clarification_question": "你指的是销售数量还是销售金额？",
        }

    async def fake_generate(q: str) -> str:
        assert "销售数量" in q, "clarification answer should be merged into the question"
        return "SELECT SUM(quantity) AS units FROM invoice_line"

    async def fake_review(q: str, sql: str) -> str:
        return sql

    async def fake_interpret(q: str, sql: str, cols: list[str], rows: list[list[Any]]) -> str:
        return "销售数量总计 N。"

    monkeypatch.setattr(_graph, "_classify_intent", fake_classify)
    monkeypatch.setattr(_pipeline, "generate_sql", fake_generate)
    monkeypatch.setattr(_pipeline, "review_sql", fake_review)
    monkeypatch.setattr(_pipeline, "interpret", fake_interpret)

    first = await _graph.run(question="销量是多少？")
    assert first.status == "awaiting_clarification"
    assert first.clarification_question == "你指的是销售数量还是销售金额？"
    assert first.thread_id

    second = await _graph.run(thread_id=first.thread_id, resume_input="销售数量")
    assert second.status == "ok"
    assert second.thread_id == first.thread_id
    assert second.answer == "销售数量总计 N。"


@pytest.mark.asyncio
async def test_run_without_question_or_resume_returns_error() -> None:
    result = await _graph.run()
    assert result.status == "error"
    assert result.error is not None
    assert "question" in result.error.lower()
