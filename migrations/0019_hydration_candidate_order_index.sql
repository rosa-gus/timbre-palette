-- The hydrator asks for the oldest open job every cron tick.  The previous
-- indexes grouped jobs by status/shard, but did not support the snapshot join
-- and creation-order LIMIT together, so completed jobs were scanned and a
-- temporary sort was built on every invocation.
--
-- Keep this index partial: completed jobs are never candidates and should not
-- contribute to the recurring read path or to index storage.
CREATE INDEX IF NOT EXISTS idx_snapshot_hydration_open_order
    ON snapshot_hydration_jobs(snapshot_version, created_at, id)
    WHERE status != 'complete';
