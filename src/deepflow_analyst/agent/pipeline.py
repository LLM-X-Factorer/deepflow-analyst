"""End-to-end query pipeline organized as a 4-role multi-agent architecture.

Roles (CrewAI-style, no framework dependency):
  1. SQL Writer     (LLM)    question      → initial SQL
  2. SQL Reviewer   (LLM)    SQL + question → refined SQL (critic loop)
  3. SQL Executor   (Python) SQL            → (columns, rows)
                    Pure Python is intentional: validation and DB I/O are
                    deterministic steps that would only burn tokens if
                    handed to an LLM.
  4. Insight Agent  (LLM)    results        → Chinese explanation

CrewAI itself isn't imported: for a fixed 4-step sequential pipeline, its
planner would cost more tokens than it saves. W6 teaching materials note
that swapping this out for `crewai.Crew(process=Process.sequential)` is
mechanical; the pattern — not the framework — is what matters.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from ..db import engine
from ..llm_client import chat
from ..retrieval import format_examples_block, get_default_bank
from ..settings import settings

CHINOOK_SCHEMA = """\
Tables (PostgreSQL, all identifiers are lowercase and unquoted):

artist (artist_id PK, name)
album (album_id PK, title, artist_id FK→artist)
track (track_id PK, name, album_id FK→album, media_type_id FK→media_type,
       genre_id FK→genre, composer, milliseconds, bytes, unit_price numeric)
genre (genre_id PK, name)
media_type (media_type_id PK, name)
playlist (playlist_id PK, name)
playlist_track (playlist_id FK→playlist, track_id FK→track)
customer (customer_id PK, first_name, last_name, company, address, city,
          state, country, postal_code, phone, fax, email,
          support_rep_id FK→employee)
employee (employee_id PK, first_name, last_name, title,
          reports_to FK→employee, birth_date, hire_date, address, city,
          state, country, postal_code, phone, fax, email)
invoice (invoice_id PK, customer_id FK→customer, invoice_date,
         billing_address, billing_city, billing_state, billing_country,
         billing_postal_code, total numeric)
invoice_line (invoice_line_id PK, invoice_id FK→invoice,
              track_id FK→track, unit_price numeric, quantity)
"""

SQL_SYSTEM_PROMPT = (
    "You generate SQL for a PostgreSQL database.\n"
    "RULES:\n"
    "1. Return ONLY a single SELECT statement. Never write "
    "INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE.\n"
    "2. Use only tables and columns from the provided schema.\n"
    "3. If the user question does not specify a limit, append LIMIT 100.\n"
    "4. SELECT only the columns the user explicitly asked for — do NOT add extra\n"
    "   id columns or helper columns unless the user requested them.\n"
    "5. When the query uses ORDER BY, append a deterministic tie-breaker column\n"
    "   (typically a primary key like `artist_id`, `track_id`, or a unique name)\n"
    "   so the result ordering is stable across runs. Example:\n"
    "   `ORDER BY revenue DESC, customer_id` instead of `ORDER BY revenue DESC`.\n"
    "6. Output ONLY SQL. No markdown fences, no comments, no explanation.\n\n"
    "SCHEMA:\n" + CHINOOK_SCHEMA
)

SQL_REVIEW_SYSTEM_PROMPT = (
    "You are a senior SQL reviewer for a PostgreSQL data analyst product.\n"
    "You will receive a user question and a candidate SELECT statement.\n"
    "Check specifically:\n"
    "- Does the SELECT list match ONLY the columns the user asked for?\n"
    "  (Flag extra id columns, extra helper columns, missing requested columns.)\n"
    "- If ORDER BY is present, does it include a deterministic tie-breaker\n"
    "  (primary key or unique column) so the ordering is stable?\n"
    "- Are JOIN types semantically right (INNER vs LEFT vs anti-join)?\n"
    "- Is LIMIT appropriate for the question?\n"
    "- Are aggregations and GROUP BY columns consistent?\n"
    "\n"
    "If the query is correct, return it UNCHANGED.\n"
    "If the query has issues, return the FIXED version.\n"
    "Output ONLY SQL — no markdown fences, no explanation, no preamble.\n\n"
    "SCHEMA:\n" + CHINOOK_SCHEMA
)


INTERPRET_SYSTEM_PROMPT = (
    "你是一位数据分析师助手，用简体中文向非技术同事解读查询结果。\n"
    "要求：\n"
    "- 2-4 句话，100 字以内\n"
    "- 直接引用数据里的具体数字或名称\n"
    "- 若结果为 0 行，说明 '没有找到符合条件的数据'\n"
    "- 不要重复 SQL 本身\n"
)

FORBIDDEN_KEYWORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "TRUNCATE",
    "CREATE",
    "GRANT",
    "REVOKE",
)


@dataclass
class QueryResult:
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    answer: str


def _strip_markdown(sql: str) -> str:
    """Remove ```sql fences the LLM may add despite instructions."""
    sql = re.sub(r"^\s*```(?:sql)?\s*\n?", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\n?```\s*$", "", sql)
    return sql.strip().rstrip(";").strip()


def validate_sql(sql: str) -> None:
    """Allow only a single SELECT/WITH statement; reject DML/DDL."""
    upper = sql.upper().strip()
    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        raise ValueError("Only SELECT/WITH queries are allowed.")
    for kw in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{kw}\b", upper):
            raise ValueError(f"Forbidden keyword {kw!r} detected in SQL.")


def ensure_limit(sql: str, default: int = 100) -> str:
    if re.search(r"\blimit\b\s+\d+", sql, flags=re.IGNORECASE):
        return sql
    return f"{sql}\nLIMIT {default}"


def _jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return str(v)


def execute_sql(sql: str) -> tuple[list[str], list[list[Any]]]:
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        columns = list(result.keys())
        rows = [[_jsonable(v) for v in row] for row in result.fetchall()]
    return columns, rows


def _build_writer_system_prompt(question: str) -> str:
    """Assemble the Writer system prompt, optionally with retrieved examples.

    X · few-shot RAG: when enabled, prepend a small block of similar solved
    question→SQL pairs drawn from the local BM25 example bank. The bank is
    tiny (~25 entries) and independent of the golden dataset, so this only
    burns a few hundred extra tokens per call while giving the LLM concrete
    precedent for hard structural patterns.
    """
    if not settings.rag_enabled or settings.rag_top_k <= 0:
        return SQL_SYSTEM_PROMPT
    try:
        bank = get_default_bank()
    except Exception:
        # Bank missing/corrupt: fail open to the zero-shot prompt rather
        # than blocking query generation on a retrieval infra problem.
        return SQL_SYSTEM_PROMPT
    examples = bank.top_k(question, k=settings.rag_top_k)
    if not examples:
        return SQL_SYSTEM_PROMPT
    return (
        SQL_SYSTEM_PROMPT + "\n\nEXAMPLES (similar solved problems — study the patterns,\n"
        "do not copy literally unless the question genuinely matches):\n\n"
        + format_examples_block(examples)
    )


async def generate_sql(question: str, temperature: float | None = None) -> str:
    """Role 1 · SQL Writer Agent.

    ``temperature`` is an override only used by the Z stability-sampling
    path. Default (``None``) keeps the deterministic temp=0 behavior and
    forwards no temperature kwarg, so legacy call sites and test mocks
    without the kwarg keep working.
    """
    messages = [
        {"role": "system", "content": _build_writer_system_prompt(question)},
        {"role": "user", "content": question},
    ]
    if temperature is None:
        raw = await chat(messages)
    else:
        raw = await chat(messages, temperature=temperature)
    return _strip_markdown(raw)


async def review_sql(question: str, candidate_sql: str) -> str:
    """Role 2 · SQL Reviewer Agent (critic loop).

    Returns either the original SQL unchanged or a refined version.
    """
    messages = [
        {"role": "system", "content": SQL_REVIEW_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"User question: {question}\n\nCandidate SQL:\n{candidate_sql}",
        },
    ]
    raw = await chat(messages)
    return _strip_markdown(raw)


async def interpret(
    question: str,
    sql: str,
    columns: list[str],
    rows: list[list[Any]],
) -> str:
    preview = rows[:20]
    user_msg = (
        f"用户问题：{question}\n\n"
        f"执行的 SQL：{sql}\n\n"
        f"列名：{columns}\n"
        f"结果行数：{len(rows)}\n"
        f"前 20 行数据：{preview}"
    )
    messages = [
        {"role": "system", "content": INTERPRET_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    return (await chat(messages)).strip()


async def _writer_review_once(question: str, writer_temp: float | None) -> str:
    draft = await generate_sql(question, temperature=writer_temp)
    validate_sql(draft)
    reviewed = await review_sql(question, draft)
    validate_sql(reviewed)
    return ensure_limit(reviewed, default=1000)


def _result_vote_key(columns: list[str], rows: list[list[Any]]) -> tuple[Any, ...]:
    """Canonical key for result-level majority voting.

    Uses multiset semantics (sorted stringified rows) so two candidates that
    return the same rows in different orders are grouped together. This is
    the right equivalence class for self-consistency — if downstream cares
    about ORDER BY, it can still fail the ordering check on the winner.
    """
    canonical = tuple(tuple("NULL" if v is None else str(v) for v in row) for row in rows)
    return (tuple(columns), tuple(sorted(canonical)))


async def generate_reviewed_sql(question: str) -> str:
    """Writer → Reviewer with optional Z-style majority voting.

    * ``settings.sample_size <= 1`` (default): single-shot, temp=0.
    * ``settings.sample_size > 1``: Writer is sampled N times at
      ``sample_temperature`` (for diversity), each candidate is reviewed at
      temp=0 and executed against the live DB, and the SQL whose result set
      is the majority is returned. Ties: first encountered wins.

    Executing every candidate is intentional — result-level voting is what
    absorbs surface-form variation between equivalent queries. Writer
    candidates that fail validation or review are dropped; only candidates
    with a successful execution participate in the vote.
    """
    n = max(1, settings.sample_size)
    if n == 1:
        return await _writer_review_once(question, writer_temp=None)

    temp = settings.sample_temperature
    candidates = await asyncio.gather(
        *(_writer_review_once(question, writer_temp=temp) for _ in range(n)),
        return_exceptions=True,
    )

    groups: dict[tuple[Any, ...], str] = {}
    tallies: dict[tuple[Any, ...], int] = {}
    first_successful: str | None = None
    for c in candidates:
        if isinstance(c, BaseException):
            continue
        try:
            cols, rows = execute_sql(c)
        except Exception:
            continue
        if first_successful is None:
            first_successful = c
        key = _result_vote_key(cols, rows)
        tallies[key] = tallies.get(key, 0) + 1
        groups.setdefault(key, c)  # keep first SQL seen for this result set

    if not tallies:
        raise RuntimeError("All sampled SQL candidates failed to execute")

    winner_key = max(tallies, key=lambda k: tallies[k])
    return groups[winner_key]


async def run(question: str) -> QueryResult:
    """Orchestrate the 4-role pipeline.

    Writer → Reviewer → Executor → Insight. Each arrow validates that
    the SQL remains a safe SELECT; the reviewer can rewrite it but
    cannot smuggle in a forbidden statement. With ``sample_size > 1``,
    the Writer→Reviewer step is a self-consistency ensemble.
    """
    final_sql = await generate_reviewed_sql(question)
    columns, rows = execute_sql(final_sql)
    answer = await interpret(question, final_sql, columns, rows)

    return QueryResult(
        sql=final_sql,
        columns=columns,
        rows=rows,
        row_count=len(rows),
        answer=answer,
    )
