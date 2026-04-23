"""End-to-end query pipeline: NL question → SQL → execution → interpretation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from ..db import engine
from ..llm_client import chat

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


async def generate_sql(question: str) -> str:
    messages = [
        {"role": "system", "content": SQL_SYSTEM_PROMPT},
        {"role": "user", "content": question},
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


async def run(question: str) -> QueryResult:
    sql = await generate_sql(question)
    validate_sql(sql)
    sql = ensure_limit(sql)
    columns, rows = execute_sql(sql)
    answer = await interpret(question, sql, columns, rows)
    return QueryResult(
        sql=sql,
        columns=columns,
        rows=rows,
        row_count=len(rows),
        answer=answer,
    )
