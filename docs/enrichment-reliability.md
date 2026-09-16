# Enrichment Reliability

D1 is the source of truth for enrichment jobs and work units; the Queue
provides delivery. The API records demand and jobs but does not publish to the
Queue. The enrichment Worker publishes the D1 outbox once per grouped work
unit during its scheduled sweep. If publication fails, the sweep finds the
pending outbox entry and retries it. Retries and duplicate deliveries are
expected and must remain safe.

## State model

`enrichment_jobs.status` describes job processing:

- `pending`: created, awaiting publication or delivery;
- `processing`: leased by a delivery;
- `failed`: transient failure; eligible for retry;
- `completed`: resolved, with or without accepted claims;
- `ambiguous`: terminal but reviewable; no automatic retry;
- `terminal`: invalid message or exhausted retries.

`dispatch_status` describes publication only: `pending → sending → queued`,
with `failed` for publication errors. The scheduled sweep recovers pending and
failed entries and expired send leases. A `queued` row is not republished on a
timer: a successful Queue send is already durable, and delivery retries belong
to the Queue message.

`enrichment_work_units` groups up to ten jobs. Its `processing` lease protects
the whole group, while each job keeps its own status and processing lease. A
redelivery skips jobs that already reached a terminal state. A `busy` duplicate
is acknowledged instead of being retried, preventing duplicate deliveries from
consuming Queue reads and reaching the DLQ.

## Message contract

Legacy recording/release messages use schema version 2:

```json
{ "schema_version": 2, "job_key": "<sha256>", "generation": 1 }
```

An album release additionally identifies its target and processing stage:

```json
{
  "schema_version": 2,
  "job_key": "<sha256>",
  "generation": 1,
  "job_type": "release",
  "target_mbid": "<release-mbid>",
  "stage": "source"
}
```

The consumer resolves artist, title, and MBID from D1. Unknown fields,
unsupported schema versions, invalid keys, and generation mismatches are
rejected. An invalid message associated with a job makes that job terminal.

New outbox messages use schema version 3 and carry only the work-unit key:

```json
{ "schema_version": 3, "work_unit_key": "<sha256>", "generation": 1 }
```

## Failure handling

Network errors, invalid MusicBrainz responses, unexpected exceptions, and D1
failures during processing are transient. The consumer records `failed` on the
active job and work unit and retries the delivery with exponential backoff and
deterministic jitter. After the configured delivery limit, a v2 message keeps
the existing terminal job behavior; a v3 message is marked
`recovery_required` at the work-unit level so its jobs are not silently lost.
The original error is preserved in D1 and in the DLQ log event.

Ambiguous identity resolution ends the job as `ambiguous`. A resolved identity
with no accepted instrument claim ends it as `completed` with
`terminal_reason_code = no_accepted_instrument_claims`.

## Prepared album catalog

Migration `0009_prepared_album_catalog.sql` organizes album groups, releases,
and tracks, with separate `source_documents`, `credit_observations`,
`catalog_demand`, and `prepared_album_targets` tables. The versioned manifest
and import flow are documented in
[Catalog Architecture](catalog-architecture.md).

The scheduled planner creates pending editorial targets before recovering the
outbox. Each release is collected with its recordings and relations in one
grouped query; raw observations remain separate from published claims.
Programming and samples are not inferred as instruments. Vocal relations are
accepted only when they resolve to the explicit `voice` editorial alias.

## Local operation

Run `yarn dev:api` to start the API and consumer against the local D1 in
`.wrangler/state`. `yarn dev:api:mock` uses fixtures and does not start the
consumer. The Queue producer and consumer are configured only in
`wrangler.enricher.jsonc`.

Jobs with `status = pending`, `dispatch_status = queued`, and
`processing_attempts = 0` were published but have not started processing. A
report refresh does not republish them; the enrichment Worker's scheduled
handler performs recovery.

To trigger recovery locally, stop `yarn dev:api`, then run:

```sh
yarn dev:enrichment:recover
curl --fail 'http://localhost:8788/cdn-cgi/local/scheduled?cron=*+*+*+*+*'
```

Recovery plans one prepared album and dispatches up to six work units per
invocation. Each work unit contains at most ten jobs. There is no
post-publication confirmation timer; only failed sends and expired send leases
are recovered. Do not run both local sessions against the same storage.
Production runs the scheduled recovery every minute.

Alias migrations do not reprocess existing candidates or rewrite evidence;
legacy maintenance must be explicit and separate.

## Rollout

Apply migration `0015_enrichment_work_units.sql`, deploy the enrichment Worker,
and then deploy the API Worker. Do not replay the existing DLQ before the new
consumer is active. Validate a canary with the guarded tool in
`src/palette_api/tools/requeue_enrichment.py` using `--limit 20`; after the
Queue drains and the metrics remain stable, repeat without the limit if needed.

## Observability

Useful status queries include:

```sql
SELECT status, dispatch_status, COUNT(*) AS total
FROM enrichment_jobs
GROUP BY status, dispatch_status;

SELECT terminal_reason_code, COUNT(*) AS total
FROM enrichment_jobs
WHERE terminal_reason_code IS NOT NULL
GROUP BY terminal_reason_code
ORDER BY total DESC;

SELECT job_type, stage, status, COUNT(*) AS total
FROM enrichment_jobs
GROUP BY job_type, stage, status;

SELECT status, dispatch_status, COUNT(*) AS total
FROM enrichment_work_units
GROUP BY status, dispatch_status;

SELECT
    COUNT(*) AS total_units,
    SUM(item_count) AS total_jobs,
    SUM(dispatch_attempts - 1) AS extra_dispatches,
    SUM(processing_attempts - 1) AS extra_processing_attempts
FROM enrichment_work_units;
```

Structured logs use these events: `enrichment_started`,
`enrichment_processed`, `enrichment_dispatched`, `enrichment_dispatch_failed`,
`enrichment_retry`, `enrichment_dead_lettered`, `enrichment_stale_message`,
`enrichment_work_unit_dispatched`, `enrichment_work_unit_retry`,
`enrichment_work_unit_dead_lettered`, and `enrichment_outbox_sweep`.
MusicBrainz failures additionally emit
`musicbrainz_transport_error`, `musicbrainz_response_error`, or
`musicbrainz_upstream_error`.

Retry and upstream events include `job_key`, `message_id`, `job_type`,
`target_mbid`, `attempt`, `operation`, `reason_code`, and `duration_ms` when
available. HTTP failures also include `status_code` and
`retry_after_seconds`; response bodies and complete URLs are intentionally not
logged.
