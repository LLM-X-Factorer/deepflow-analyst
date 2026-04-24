from pathlib import Path
from typing import Any

import pytest

from deepflow_analyst import evaluation
from deepflow_analyst.evaluation import CaseResult


def test_canonical_row_normalizes_types() -> None:
    from datetime import datetime
    from decimal import Decimal

    row = (1, "hello", Decimal("1.23"), None, datetime(2026, 4, 23))
    canon = evaluation._canonical_row(row)
    assert canon == ("1", "hello", "1.23", "NULL", "2026-04-23 00:00:00")


def test_has_order_by_detects_any_case() -> None:
    assert evaluation._has_order_by("SELECT 1 ORDER BY x")
    assert evaluation._has_order_by("select 1 order by x")
    assert evaluation._has_order_by("SELECT 1\n  ORDER  BY  x")  # whitespace
    assert not evaluation._has_order_by("SELECT 1 GROUP BY x")


def test_results_equal_empty_sets() -> None:
    assert evaluation.results_equal([], [], order_sensitive=True)
    assert evaluation.results_equal([], [], order_sensitive=False)


def test_results_equal_length_mismatch() -> None:
    assert not evaluation.results_equal([("a",)], [("a",), ("b",)], order_sensitive=False)


def test_results_equal_order_sensitive() -> None:
    a = [("a",), ("b",)]
    b = [("b",), ("a",)]
    assert not evaluation.results_equal(a, b, order_sensitive=True)
    assert evaluation.results_equal(a, b, order_sensitive=False)


def test_results_equal_identical() -> None:
    rows = [("a", "1"), ("b", "2")]
    assert evaluation.results_equal(rows, rows, order_sensitive=True)
    assert evaluation.results_equal(rows, rows, order_sensitive=False)


def test_load_dataset_skips_comments_and_blanks(tmp_path: Path) -> None:
    path = tmp_path / "d.jsonl"
    path.write_text(
        "\n"
        "# leading comment\n"
        '{"id":"x1","question":"q1","expected_sql":"SELECT 1","difficulty":"easy"}\n'
        "\n"
        '{"id":"x2","question":"q2","expected_sql":"SELECT 2","difficulty":"medium"}\n'
    )
    cases = evaluation.load_dataset(path)
    assert [c["id"] for c in cases] == ["x1", "x2"]


def test_render_report_structure() -> None:
    results = [
        CaseResult(
            id="e01",
            question="Q1",
            difficulty="easy",
            generated_sql="SELECT 1",
            expected_sql="SELECT 1",
            passed=True,
            row_count_actual=1,
            row_count_expected=1,
        ),
        CaseResult(
            id="m01",
            question="Q2",
            difficulty="medium",
            generated_sql="",
            expected_sql="SELECT 2",
            passed=False,
            error="ValueError: bad SQL",
        ),
    ]
    report = evaluation.render_report(results, threshold=0.6)
    assert "Accuracy" in report
    assert "1/2" in report
    assert "50.0%" in report
    assert "❌ FAIL" in report
    assert "`e01`" in report
    assert "`m01`" in report
    assert "ValueError: bad SQL" in report
    assert "easy" in report
    assert "medium" in report


def test_render_report_passes_above_threshold() -> None:
    results = [
        CaseResult(
            id=f"e{i}",
            question="Q",
            difficulty="easy",
            generated_sql="SELECT 1",
            expected_sql="SELECT 1",
            passed=True,
            row_count_actual=1,
            row_count_expected=1,
        )
        for i in range(5)
    ]
    report = evaluation.render_report(results, threshold=0.5)
    assert "✅ PASS" in report


def test_bundled_golden_dataset_parses() -> None:
    """The checked-in dataset must always be valid JSONL with the expected schema."""
    cases = evaluation.load_dataset(evaluation.DEFAULT_DATASET)
    assert cases, "golden dataset should not be empty"
    required = {"id", "question", "expected_sql", "difficulty"}
    for c in cases:
        missing = required - c.keys()
        assert not missing, f"case {c.get('id')} missing fields: {missing}"
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "duplicate ids in golden dataset"


@pytest.mark.asyncio
async def test_evaluate_one_handles_mocked_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """With a mocked LLM and real DB (if available), verify the pass path."""
    from deepflow_analyst import db as _db

    if not _db.ping():
        pytest.skip("postgres not reachable")

    from deepflow_analyst.agent import pipeline as _pipeline

    async def fake_chat(messages: list[dict[str, str]], **_kwargs: Any) -> str:
        return "SELECT COUNT(*) FROM artist"

    monkeypatch.setattr(_pipeline, "chat", fake_chat)

    case = {
        "id": "synthetic",
        "question": "artists total",
        "expected_sql": "SELECT COUNT(*) FROM artist",
        "difficulty": "easy",
    }
    r = await evaluation.evaluate_one(case)
    assert r.passed
    assert r.row_count_actual == 1 == r.row_count_expected
