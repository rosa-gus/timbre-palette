"""Generate SQL to detach enrichment jobs from stale work units.

This tool only emits SQL. Review the output and execute it explicitly against
the intended D1 database after the corrected enrichment Worker is deployed.
"""

from __future__ import annotations

import argparse


def build_sql(*, limit: int | None = None) -> str:
    target = """SELECT jobs.job_key
FROM enrichment_jobs AS jobs
WHERE jobs.status = 'pending'
  AND jobs.dispatch_status = 'pending'
  AND jobs.work_unit_key IS NOT NULL
  AND (
      NOT EXISTS (
          SELECT 1
          FROM enrichment_work_units AS units
          WHERE units.work_key = jobs.work_unit_key
      )
      OR jobs.generation <> (
          SELECT units.generation
          FROM enrichment_work_units AS units
          WHERE units.work_key = jobs.work_unit_key
      )
  )
ORDER BY jobs.updated_at, jobs.id"""
    if limit is not None:
        target += f" LIMIT {limit}"

    return f"""-- Remove stale memberships first. The update below is rerunnable
-- if either statement has to be retried after an independent D1 failure.
DELETE FROM enrichment_work_unit_items
WHERE job_key IN ({target});

UPDATE enrichment_jobs
SET status = 'pending',
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
    last_error = NULL,
    dispatch_error = NULL,
    updated_at = datetime('now')
WHERE job_key IN ({target});

UPDATE enrichment_work_units
SET item_count = (
        SELECT COUNT(*)
        FROM enrichment_work_unit_items AS items
        WHERE items.work_unit_id = enrichment_work_units.id
    ),
    updated_at = datetime('now')
WHERE item_count <> (
    SELECT COUNT(*)
    FROM enrichment_work_unit_items AS items
    WHERE items.work_unit_id = enrichment_work_units.id
);
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        help="maximum number of stale jobs to repair; omit to repair all",
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    print(build_sql(limit=args.limit), end="")


if __name__ == "__main__":
    main()
