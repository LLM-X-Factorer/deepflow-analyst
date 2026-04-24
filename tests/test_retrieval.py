from deepflow_analyst import evaluation, retrieval


def test_tokenize_cjk_unigram_and_bigram() -> None:
    tokens = retrieval._tokenize("销售曲风")
    assert "销" in tokens and "售" in tokens and "曲" in tokens and "风" in tokens
    assert "销售" in tokens and "售曲" in tokens and "曲风" in tokens


def test_tokenize_latin_words() -> None:
    tokens = retrieval._tokenize("Rock music 2024")
    assert "rock" in tokens
    assert "music" in tokens
    assert "2024" in tokens


def test_tokenize_drops_punctuation() -> None:
    # Neither ? nor spaces nor punctuation should survive as tokens.
    tokens = retrieval._tokenize("曲目数？ !!")
    assert all(t not in tokens for t in ["?", "？", " ", "!"])


def test_example_bank_retrieves_similar_distinct_on() -> None:
    bank = retrieval.get_default_bank()
    # Per-group-top questions should surface at least one DISTINCT ON precedent
    # in top-K. The exact ranking depends on BM25 IDF on a tiny corpus, so
    # don't overspecify which entry wins — just that the pattern is represented.
    hits = bank.top_k("每个国家累计消费最多的客户", k=3)
    assert hits, "no retrieval results"
    assert any("DISTINCT ON" in ex.sql.upper() for ex in hits), (
        f"no DISTINCT ON precedent in top-K: {[ex.question for ex in hits]}"
    )


def test_example_bank_retrieves_self_join() -> None:
    bank = retrieval.get_default_bank()
    hits = bank.top_k("员工和直属经理的名字", k=2)
    assert hits
    # At least one of the top hits should be a self-join on employee.
    assert any("employee m" in ex.sql.lower() or "employee e" in ex.sql.lower() for ex in hits)


def test_example_bank_empty_query_returns_empty() -> None:
    bank = retrieval.get_default_bank()
    assert bank.top_k("", k=3) == []
    assert bank.top_k("?!", k=3) == []


def test_example_bank_top_k_zero_returns_empty() -> None:
    bank = retrieval.get_default_bank()
    assert bank.top_k("销售", k=0) == []


def test_format_examples_block_shape() -> None:
    examples = [
        retrieval.Example(question="Q1", sql="SELECT 1"),
        retrieval.Example(question="Q2", sql="SELECT 2"),
    ]
    block = retrieval.format_examples_block(examples)
    assert "Q: Q1" in block
    assert "SQL: SELECT 1" in block
    assert "Q: Q2" in block
    assert "SQL: SELECT 2" in block
    # Two entries separated by blank line.
    assert "SELECT 1\n\nQ:" in block


def test_bank_independent_of_golden_dataset() -> None:
    """No question in the few-shot bank may exactly match a golden question.

    Overlap would leak ground-truth SQL into the Writer's prompt during
    evaluation and inflate the accuracy score dishonestly.
    """
    bank_questions = {ex.question for ex in retrieval.load_examples()}
    golden = evaluation.load_dataset(evaluation.DEFAULT_DATASET)
    golden_questions = {c["question"] for c in golden}
    overlap = bank_questions & golden_questions
    assert not overlap, f"few-shot bank leaks into golden dataset: {overlap}"


def test_bank_has_coverage_for_hard_patterns() -> None:
    """At least one bank entry for each hard structural pattern we failed on."""
    sqls = [ex.sql.upper() for ex in retrieval.load_examples()]
    assert any("DISTINCT ON" in s for s in sqls), "missing DISTINCT ON precedent"
    assert any("LEFT JOIN EMPLOYEE" in s or "EMPLOYEE M" in s for s in sqls), (
        "missing self-join precedent"
    )
    assert any("IS NULL" in s for s in sqls), "missing anti-join precedent"
    # Multi-join chain — at least one 4-way+ join in the bank.
    assert any(s.count(" JOIN ") >= 3 for s in sqls), "missing multi-join chain precedent"
