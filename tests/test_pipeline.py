from typing import Any

import pytest

from deepflow_analyst import db as _db
from deepflow_analyst.agent import pipeline


def test_strip_markdown_plain() -> None:
    assert pipeline._strip_markdown("SELECT 1") == "SELECT 1"


def test_strip_markdown_fenced() -> None:
    assert pipeline._strip_markdown("```sql\nSELECT 1;\n```") == "SELECT 1"


def test_strip_markdown_trailing_semicolon() -> None:
    assert pipeline._strip_markdown("SELECT 1;   ") == "SELECT 1"


def test_validate_sql_accepts_select() -> None:
    pipeline.validate_sql("SELECT * FROM artist LIMIT 10")


def test_validate_sql_accepts_with() -> None:
    pipeline.validate_sql("WITH x AS (SELECT 1) SELECT * FROM x")


@pytest.mark.parametrize(
    "bad_sql",
    [
        "INSERT INTO artist VALUES (1, 'x')",
        "DELETE FROM artist",
        "UPDATE artist SET name='x'",
        "DROP TABLE customer",
        "SELECT * FROM artist; DROP TABLE customer",
        "ALTER TABLE artist ADD COLUMN foo int",
        "TRUNCATE artist",
    ],
)
def test_validate_sql_rejects_mutations(bad_sql: str) -> None:
    with pytest.raises(ValueError):
        pipeline.validate_sql(bad_sql)


def test_ensure_limit_adds_when_missing() -> None:
    sql = pipeline.ensure_limit("SELECT * FROM artist")
    assert "LIMIT 100" in sql


def test_ensure_limit_preserves_when_present() -> None:
    sql = pipeline.ensure_limit("SELECT * FROM artist LIMIT 5")
    assert "LIMIT 100" not in sql
    assert sql == "SELECT * FROM artist LIMIT 5"


def test_jsonable_primitives() -> None:
    assert pipeline._jsonable(None) is None
    assert pipeline._jsonable(42) == 42
    assert pipeline._jsonable("x") == "x"


def test_jsonable_decimal_and_datetime() -> None:
    from datetime import datetime
    from decimal import Decimal

    assert pipeline._jsonable(Decimal("1.23")) == 1.23
    assert pipeline._jsonable(datetime(2026, 4, 23, 12, 0)).startswith("2026-04-23")


@pytest.mark.asyncio
async def test_run_end_to_end_with_mocked_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    if not _db.ping():
        pytest.skip("postgres not reachable; integration test requires chinook loaded")

    # Three LLM calls in order: SQL Writer → SQL Reviewer → Insight.
    responses = iter(
        [
            "SELECT name FROM artist ORDER BY artist_id LIMIT 3",  # Writer
            "SELECT name FROM artist ORDER BY artist_id LIMIT 3",  # Reviewer (unchanged)
            "前三位艺人分别是 AC/DC、Accept、Aerosmith。",  # Insight
        ]
    )

    async def fake_chat(messages: list[dict[str, str]], model: str | None = None) -> str:
        return next(responses)

    monkeypatch.setattr(pipeline, "chat", fake_chat)

    result = await pipeline.run("列出前三位艺人")
    assert "SELECT name FROM artist" in result.sql
    assert result.row_count == 3
    assert len(result.rows) == 3
    assert "艺人" in result.answer


@pytest.mark.asyncio
async def test_run_rejects_injected_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    """An LLM emitting a forbidden statement disguised after a SELECT must be blocked."""

    async def fake_chat(messages: list[dict[str, str]], model: str | None = None) -> str:
        return "SELECT 1; DROP TABLE customer"

    monkeypatch.setattr(pipeline, "chat", fake_chat)

    with pytest.raises(ValueError, match="Forbidden"):
        await pipeline.run("anything")


def test_execute_sql_requires_db() -> None:
    """Live hit against chinook. Skip when DB unavailable (CI without services)."""
    if not _db.ping():
        pytest.skip("postgres not reachable")

    columns, rows = pipeline.execute_sql("SELECT COUNT(*) AS n FROM artist")
    assert columns == ["n"]
    assert rows[0][0] > 0


def test_execute_sql_result_cells_are_json_safe() -> None:
    if not _db.ping():
        pytest.skip("postgres not reachable")

    _, rows = pipeline.execute_sql("SELECT unit_price FROM track LIMIT 1")
    value: Any = rows[0][0]
    # Decimal would round-trip as float via our converter.
    assert isinstance(value, (int, float))
