# Enrichment Reliability

D1 is the source of truth for enrichment jobs; the Queue provides delivery.
The producer creates the job and its outbox entry in the same logical
operation. If publication fails, the scheduled sweep finds the outbox entry
and retries it. Retries and duplicate deliveries are expected and must remain
safe.

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
failed entries, expired leases, and queued messages without confirmation after
the safety window.

## Message contract

Messages use one strict schema. A recording contains the required fields:

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

## Failure handling

Network errors, invalid MusicBrainz responses, unexpected exceptions, and D1
failures during processing are transient. The consumer records `failed` and
retries with exponential backoff and deterministic jitter. After the configured
delivery limit, the Queue moves the message to
`timbre-palette-enrichment-dlq`; the DLQ consumer records
`terminal_reason_code = retry_exhausted`.

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

Run `yarn dev:api` to start the producer and consumer against the local D1 in
`.wrangler/state`. `yarn dev:api:mock` uses fixtures and does not start the
consumer. The queue producer is configured in `wrangler.jsonc`; the consumer is
configured in `wrangler.enricher.jsonc`.

Jobs with `status = pending`, `dispatch_status = queued`, and
`processing_attempts = 0` were published but have not started processing. A
report refresh does not republish them; the enrichment Worker's scheduled
handler performs recovery.

To trigger recovery locally, stop `yarn dev:api`, then run:

```sh
yarn dev:enrichment:recover
curl --fail 'http://localhost:8788/cdn-cgi/local/scheduled?cron=*+*+*+*+*'
```

Recovery respects `next_dispatch_at`, limits each invocation to 20 eligible
jobs, and uses a five-minute post-publication confirmation window. Do not run
both local sessions against the same storage. Production runs the scheduled
recovery every minute.

Alias migrations do not reprocess existing candidates or rewrite evidence;
legacy maintenance must be explicit and separate.

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
```

Structured logs use these events: `enrichment_dispatched`,
`enrichment_dispatch_failed`, `enrichment_retry`,
`enrichment_dead_lettered`, `enrichment_stale_message`, and
`enrichment_outbox_sweep`.
