from palette_api.tools.requeue_enrichment import build_sql


def test_build_sql_omits_explicit_transaction_delimiters() -> None:
    sql = build_sql(reason="retry_exhausted", limit=20)

    assert "BEGIN" not in sql
    assert "COMMIT" not in sql
    assert "LIMIT 20" in sql


def test_build_sql_can_reopen_recovery_units_without_transaction_delimiters() -> None:
    sql = build_sql(
        reason="retry_exhausted",
        limit=20,
        include_recovery_units=True,
    )

    assert "BEGIN" not in sql
    assert "COMMIT" not in sql
    assert "status = 'recovery_required'" in sql
    assert "UPDATE enrichment_work_units" in sql
