from palette_api.tools.repair_enrichment_work_units import build_sql


def test_repair_sql_targets_only_generation_mismatches() -> None:
    sql = build_sql(limit=50)

    assert "jobs.generation <>" in sql
    assert "jobs.status = 'pending'" in sql
    assert "jobs.dispatch_status = 'pending'" in sql
    assert "LIMIT 50" in sql
    assert "BEGIN" not in sql
    assert "COMMIT" not in sql
