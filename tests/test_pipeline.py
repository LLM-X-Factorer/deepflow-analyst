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
async def test_generate_sql_injects_retrieved_examples(monkeypatch: pytest.MonkeyPatch) -> None:
    """With RAG enabled the Writer system prompt carries EXAMPLES section."""
    from deepflow_analyst import settings as _settings

    monkeypatch.setattr(_settings.settings, "rag_enabled", True)
    monkeypatch.setattr(_settings.settings, "rag_top_k", 2)

    seen: dict[str, str] = {}

    async def fake_chat(messages: list[dict[str, str]], **_kwargs: Any) -> str:
        seen["system"] = messages[0]["content"]
        return "SELECT 1"

    monkeypatch.setattr(pipeline, "chat", fake_chat)
    await pipeline.generate_sql("每个国家累计消费最多的客户")
    assert "EXAMPLES" in seen["system"]
    assert "Q:" in seen["system"] and "SQL:" in seen["system"]


@pytest.mark.asyncio
async def test_generate_sql_skips_examples_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from deepflow_analyst import settings as _settings

    monkeypatch.setattr(_settings.settings, "rag_enabled", False)

    seen: dict[str, str] = {}

    async def fake_chat(messages: list[dict[str, str]], **_kwargs: Any) -> str:
        seen["system"] = messages[0]["content"]
        return "SELECT 1"

    monkeypatch.setattr(pipeline, "chat", fake_chat)
    await pipeline.generate_sql("随便一个问题")
    assert "EXAMPLES" not in seen["system"]


def test_result_vote_key_order_insensitive() -> None:
    k1 = pipeline._result_vote_key(["n"], [["a"], ["b"]])
    k2 = pipeline._result_vote_key(["n"], [["b"], ["a"]])
    assert k1 == k2


def test_result_vote_key_distinguishes_rows() -> None:
    assert pipeline._result_vote_key(["n"], [["a"]]) != pipeline._result_vote_key(["n"], [["b"]])
    assert pipeline._result_vote_key(["n"], [["a"]]) != pipeline._result_vote_key(["m"], [["a"]])
    # None is canonicalized to "NULL" — same as literal string "NULL" collides,
    # but that's intentional and acceptable for voting.


@pytest.mark.asyncio
async def test_generate_reviewed_sql_single_shot_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from deepflow_analyst import settings as _settings

    monkeypatch.setattr(_settings.settings, "sample_size", 1)
    calls: list[dict[str, Any]] = []

    async def fake_chat(
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        **_kwargs: Any,
    ) -> str:
        calls.append({"temperature": temperature})
        return "SELECT 1 AS n"

    monkeypatch.setattr(pipeline, "chat", fake_chat)

    sql = await pipeline.generate_reviewed_sql("ping")
    assert sql.startswith("SELECT 1")
    # Exactly 2 LLM calls: writer + reviewer, both at default temp (None → temp=0).
    assert len(calls) == 2
    assert all(c["temperature"] is None for c in calls)


@pytest.mark.asyncio
async def test_generate_reviewed_sql_majority_vote(monkeypatch: pytest.MonkeyPatch) -> None:
    """3 samples → 2 agree, 1 disagrees → majority wins."""
    from deepflow_analyst import settings as _settings

    monkeypatch.setattr(_settings.settings, "sample_size", 3)
    monkeypatch.setattr(_settings.settings, "sample_temperature", 0.5)

    writer_outputs = iter(
        [
            "SELECT 1 AS n",  # sample 1: writer
            "SELECT 1 AS n",  # sample 2: writer (same result set)
            "SELECT 2 AS n",  # sample 3: writer (different result set)
        ]
    )

    async def fake_chat(
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        **_kwargs: Any,
    ) -> str:
        system = messages[0]["content"]
        if "SQL reviewer" in system:
            # Reviewer echoes the candidate verbatim.
            return messages[-1]["content"].split("Candidate SQL:\n", 1)[-1].strip()
        return next(writer_outputs)

    monkeypatch.setattr(pipeline, "chat", fake_chat)

    def fake_execute(sql: str) -> tuple[list[str], list[list[Any]]]:
        if "1 AS n" in sql or "1 as n" in sql.lower():
            return ["n"], [[1]]
        return ["n"], [[2]]

    monkeypatch.setattr(pipeline, "execute_sql", fake_execute)

    sql = await pipeline.generate_reviewed_sql("ignored")
    # Winner must be from the 2/3 majority group.
    assert "1" in sql and "2" not in sql


@pytest.mark.asyncio
async def test_generate_reviewed_sql_sampling_falls_back_to_successful(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When candidates fail validation/execute, voting still picks from survivors."""
    from deepflow_analyst import settings as _settings

    monkeypatch.setattr(_settings.settings, "sample_size", 3)

    writer_outputs = iter(
        [
            "DROP TABLE customer",  # sample 1: fails validation
            "SELECT 42 AS n",  # sample 2: ok
            "SELECT 42 AS n",  # sample 3: ok
        ]
    )

    async def fake_chat(
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        **_kwargs: Any,
    ) -> str:
        system = messages[0]["content"]
        if "SQL reviewer" in system:
            return messages[-1]["content"].split("Candidate SQL:\n", 1)[-1].strip()
        return next(writer_outputs)

    monkeypatch.setattr(pipeline, "chat", fake_chat)
    monkeypatch.setattr(pipeline, "execute_sql", lambda sql: (["n"], [[42]]))

    sql = await pipeline.generate_reviewed_sql("ignored")
    assert "42" in sql


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

    async def fake_chat(messages: list[dict[str, str]], **_kwargs: Any) -> str:
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

    async def fake_chat(messages: list[dict[str, str]], **_kwargs: Any) -> str:
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
