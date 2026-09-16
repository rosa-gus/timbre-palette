"""Generate a guarded SQL replay for retry-exhausted enrichment jobs.

This tool only emits SQL. Review the output and execute it explicitly against
the intended D1 database after the new enrichment Worker is deployed.
"""

from __future__ import annotations

import argparse


def build_sql(
    *, reason: str, limit: int | None, include_recovery_units: bool = False
) -> str:
    predicate = (
        "status = 'terminal' AND terminal_reason_code = "
        + _literal(reason)
    )
    target = (
        f"SELECT job_key FROM enrichment_jobs WHERE {predicate} "
        "ORDER BY updated_at, id"
    )
    if limit is not None:
        target += f" LIMIT {limit}"
    sql = f"""-- Remove old work-unit membership before clearing work_unit_key. The old
-- Queue message remains harmless: its generation becomes stale after replay.
DELETE FROM enrichment_work_unit_items
WHERE job_key IN ({target});

UPDATE enrichment_jobs
SET generation = generation + 1,
    status = 'pending',
    attempts = 0,
    processing_attempts = 0,
    dispatch_attempts = 0,
    dispatch_status = 'pending',
    next_dispatch_at = NULL,
    dispatch_lease_until = NULL,
    processing_lease_until = NULL,
    work_unit_key = NULL,
    terminal_reason_code = NULL,
    terminal_detail = NULL,
    dispatch_error = NULL,
    updated_at = datetime('now')
WHERE job_key IN ({target});
"""
    if not include_recovery_units:
        return sql

    unit_target = (
        "SELECT work_key FROM enrichment_work_units "
        "WHERE status = 'recovery_required' "
        "ORDER BY updated_at, id"
    )
    if limit is not None:
        unit_target += f" LIMIT {limit}"
    return sql + f"""

-- Reopen explicitly quarantined work units. Completed items remain completed;
-- only unfinished items become pending in the new generation.
UPDATE enrichment_jobs
SET generation = generation + 1,
    status = CASE
        WHEN status IN ('completed', 'ambiguous', 'terminal') THEN status
        ELSE 'pending'
    END,
    attempts = 0,
    processing_attempts = 0,
    dispatch_attempts = 0,
    dispatch_status = CASE
        WHEN status IN ('completed', 'ambiguous', 'terminal') THEN 'none'
        ELSE 'pending'
    END,
    next_dispatch_at = NULL,
    dispatch_lease_until = NULL,
    processing_lease_until = NULL,
    terminal_reason_code = CASE
        WHEN status IN ('completed', 'ambiguous', 'terminal')
            THEN terminal_reason_code
        ELSE NULL
    END,
    terminal_detail = CASE
        WHEN status IN ('completed', 'ambiguous', 'terminal')
            THEN terminal_detail
        ELSE NULL
    END,
    dispatch_error = NULL,
    updated_at = datetime('now')
WHERE work_unit_key IN ({unit_target});

UPDATE enrichment_work_units
SET generation = generation + 1,
    status = 'pending',
    attempts = 0,
    processing_attempts = 0,
    last_error = NULL,
    completed_at = NULL,
    dispatch_status = 'pending',
    dispatch_attempts = 0,
    next_dispatch_at = NULL,
    dispatch_lease_until = NULL,
    queued_at = NULL,
    processing_lease_until = NULL,
    terminal_reason_code = NULL,
    terminal_detail = NULL,
    dispatch_error = NULL,
    updated_at = datetime('now')
WHERE work_key IN ({unit_target});
"""


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reason",
        default="retry_exhausted",
        help="terminal_reason_code to replay (default: retry_exhausted)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="maximum number of jobs to replay; omit to replay all matching jobs",
    )
    parser.add_argument(
        "--include-recovery-units",
        action="store_true",
        help="also reopen work units quarantined by the v3 DLQ consumer",
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    print(
        build_sql(
            reason=args.reason,
            limit=args.limit,
            include_recovery_units=args.include_recovery_units,
        ),
        end="",
    )


if __name__ == "__main__":
    main()
