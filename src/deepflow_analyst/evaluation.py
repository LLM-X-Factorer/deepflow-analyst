"""Execution Accuracy evaluation against the golden dataset.

Runs the agent pipeline on each NL question, executes both the generated
SQL and the `expected_sql`, and compares result sets.

CLI entry point is exposed via pyproject.toml as ``deepflow-eval``.
Environment knobs:

* ``EVAL_DATASET``   path to JSONL dataset (default: tests/golden/golden_dataset.jsonl)
* ``EVAL_THRESHOLD`` minimum accuracy to pass (default: 0.50)
* ``EVAL_LIMIT``     process only the first N cases (handy for smoke tests)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text

from . import db
from .agent import pipeline

_ORDER_BY_RE = re.compile(r"\border\s+by\b", re.IGNORECASE)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = REPO_ROOT / "tests" / "golden" / "golden_dataset.jsonl"
DEFAULT_REPORT = REPO_ROOT / "evaluation_report.md"


@dataclass
class CaseResult:
    id: str
    question: str
    difficulty: str
    generated_sql: str
    expected_sql: str
    passed: bool
    error: str | None = None
    row_count_actual: int = 0
    row_count_expected: int = 0


def load_dataset(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cases.append(json.loads(line))
    return cases


def _canonical_row(row: Any) -> tuple[str, ...]:
    # Stringify everything so Decimal(1.23) == float(1.23), datetime == isoformat etc.
    return tuple("NULL" if v is None else str(v) for v in row)


def _execute(sql: str) -> list[tuple[str, ...]]:
    with db.engine.connect() as conn:
        rows = conn.execute(text(sql)).fetchall()
    return [_canonical_row(r) for r in rows]


def _has_order_by(sql: str) -> bool:
    return bool(_ORDER_BY_RE.search(sql))


def results_equal(
    rows_actual: Sequence[Sequence[Any]],
    rows_expected: Sequence[Sequence[Any]],
    order_sensitive: bool,
) -> bool:
    if len(rows_actual) != len(rows_expected):
        return False
    actual = [tuple(r) for r in rows_actual]
    expected = [tuple(r) for r in rows_expected]
    if order_sensitive:
        return actual == expected
    return sorted(actual) == sorted(expected)


async def evaluate_one(case: dict[str, Any]) -> CaseResult:
    """Evaluate one case through the full Writer → Reviewer → Executor chain.

    Previously this only ran the Writer, so any measured gain after adding
    the Reviewer was invisible (or worse, indistinguishable from LLM noise).
    Now the SQL that gets executed is identical to what production runs,
    which is the whole point of an evaluation harness.
    """
    expected_sql = case["expected_sql"]
    try:
        draft = await pipeline.generate_sql(case["question"])
        pipeline.validate_sql(draft)
        reviewed = await pipeline.review_sql(case["question"], draft)
        pipeline.validate_sql(reviewed)
        # Use a generous LIMIT so legitimate large result sets aren't truncated.
        generated = pipeline.ensure_limit(reviewed, default=1000)
        actual_rows = _execute(generated)
        expected_rows = _execute(expected_sql)
        passed = results_equal(
            actual_rows, expected_rows, order_sensitive=_has_order_by(expected_sql)
        )
        return CaseResult(
            id=case["id"],
            question=case["question"],
            difficulty=case["difficulty"],
            generated_sql=generated,
            expected_sql=expected_sql,
            passed=passed,
            row_count_actual=len(actual_rows),
            row_count_expected=len(expected_rows),
        )
    except Exception as e:
        return CaseResult(
            id=case["id"],
            question=case["question"],
            difficulty=case["difficulty"],
            generated_sql="",
            expected_sql=expected_sql,
            passed=False,
            error=f"{type(e).__name__}: {e}",
        )


def render_report(results: list[CaseResult], threshold: float) -> str:
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    accuracy = passed / total if total else 0.0
    verdict = "✅ PASS" if accuracy >= threshold else "❌ FAIL"

    by_diff: dict[str, list[CaseResult]] = {}
    for r in results:
        by_diff.setdefault(r.difficulty, []).append(r)

    lines: list[str] = [
        "# Evaluation Report · Execution Accuracy",
        "",
        f"- **Accuracy**: {passed}/{total} = **{accuracy:.1%}**",
        f"- **Threshold**: {threshold:.1%}",
        f"- **Verdict**: {verdict}",
        "",
        "## Breakdown by difficulty",
        "",
        "| Difficulty | Passed | Total | Rate |",
        "|------------|--------|-------|------|",
    ]
    for diff in ("easy", "medium", "hard"):
        group = by_diff.get(diff, [])
        if not group:
            continue
        p = sum(1 for r in group if r.passed)
        t = len(group)
        lines.append(f"| {diff} | {p} | {t} | {p / t:.0%} |")
    lines += ["", "## Case details", ""]

    for r in results:
        status = "✅" if r.passed else "❌"
        lines.append(f"### {status} `{r.id}` · {r.difficulty} — {r.question}")
        lines.append("")
        lines.append(f"rows: actual={r.row_count_actual} · expected={r.row_count_expected}")
        if r.error:
            lines.append("")
            lines.append(f"**Error**: `{r.error}`")
        if r.generated_sql:
            lines.append("")
            lines.append("<details><summary>Generated SQL</summary>")
            lines.append("")
            lines.append(f"```sql\n{r.generated_sql}\n```")
            lines.append("")
            lines.append("</details>")
        lines.append("")
        lines.append("<details><summary>Expected SQL</summary>")
        lines.append("")
        lines.append(f"```sql\n{r.expected_sql}\n```")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    return "\n".join(lines)


async def run(
    dataset_path: Path,
    threshold: float,
    limit: int | None = None,
) -> tuple[float, str]:
    cases = load_dataset(dataset_path)
    if limit is not None:
        cases = cases[:limit]
    results: list[CaseResult] = []
    for i, case in enumerate(cases, 1):
        print(
            f"[{i}/{len(cases)}] {case['id']} · {case['difficulty']} · {case['question'][:40]}",
            flush=True,
        )
        r = await evaluate_one(case)
        tag = "✓" if r.passed else ("!" if r.error else "✗")
        print(
            f"   {tag} rows actual={r.row_count_actual} expected={r.row_count_expected} {r.error or ''}",
            flush=True,
        )
        results.append(r)

    accuracy = (sum(1 for r in results if r.passed) / len(results)) if results else 0.0
    report = render_report(results, threshold)
    return accuracy, report


def cli() -> int:
    dataset_path = Path(os.environ.get("EVAL_DATASET", str(DEFAULT_DATASET)))
    threshold = float(os.environ.get("EVAL_THRESHOLD", "0.50"))
    limit_raw = os.environ.get("EVAL_LIMIT")
    limit = int(limit_raw) if limit_raw else None

    if not dataset_path.exists():
        print(f"dataset missing: {dataset_path}", file=sys.stderr)
        return 2

    accuracy, report = asyncio.run(run(dataset_path, threshold, limit))

    print()
    print(report)

    DEFAULT_REPORT.write_text(report)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        Path(summary_path).write_text(report)

    return 0 if accuracy >= threshold else 1


if __name__ == "__main__":
    sys.exit(cli())
