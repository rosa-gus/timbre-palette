-- Bound daily hydration-admission accounting to today's rows, not the full history.
CREATE INDEX IF NOT EXISTS idx_snapshot_hydration_created
    ON snapshot_hydration_jobs(created_at, target_kind);
