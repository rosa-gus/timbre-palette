# Backend protection

The production TypeScript API protects Last.fm and hydration using local visitor limits and globally coordinated admission. `ResourceGuard` has separate named instances for Last.fm, hydration admission, and the shared D1 budget. Its state uses SQLite Durable Object storage.

## Defaults

| Protection | Default | Configuration |
| --- | --- | --- |
| Last.fm requests per IP and Cloudflare location | 60/minute, tracks and metadata combined | `LASTFM_VISITOR_LIMITER` binding |
| Hydration requests per IP and location | 6/minute | `HYDRATION_VISITOR_LIMITER` binding |
| Evidence/catalog requests per IP and location | 120/minute per resource group | `D1_VISITOR_LIMITER` binding |
| Global Last.fm refill rate | 120/minute, initial burst of 10 | `LASTFM_GLOBAL_PER_MINUTE`, `LASTFM_GLOBAL_BURST` |
| Simultaneous Last.fm calls | 8 | `LASTFM_MAX_CONCURRENT` |
| Last.fm calls per UTC day | 5,000 | `LASTFM_DAILY_CALL_LIMIT` |
| Shared D1 rows read per UTC day | 4,000,000 | `D1_DAILY_READ_BUDGET` |
| Shared D1 rows written per UTC day | 70,000 | `D1_DAILY_WRITE_BUDGET` |
| Shared D1 execution reservations per UTC day | 5,000 | Fixed safety cap |
| New hydration work units per UTC day | 360 | `HYDRATION_DAILY_NEW_UNITS` |
| Outstanding hydration work units in active snapshot | 720 | `HYDRATION_MAX_PENDING_UNITS` |
| Hydration admission requests per UTC day | 1,000 | Fixed safety cap |

The visitor limits are approximate and local; shared IPs, such as mobile networks, share their allowance. Only Cloudflare's trusted `CF-Connecting-IP` is used; missing addresses use a shared fallback. Global limits are enforced by Durable Objects, not the local rate-limit binding. A full analysis uses at most five Last.fm requests and four evidence batches. None of the defaults represents a Last.fm capacity guarantee.

Numeric environment settings can reduce budgets. Code clamps D1 budgets to at most 4 million reads and 70 thousand writes, new hydration work to 360 units, and the queue to 720 units. Invalid settings fall back to defaults. Refill and burst follow token-bucket semantics, rather than a strict fixed minute window.

## Last.fm pressure and recovery

Calls time out after ten seconds, including response-body reading, and upstream bodies are capped at 1 MiB. HTTP `429` or JSON error `29` opens a global sixty-second circuit cooldown. Five consecutive provider failures also open the circuit; a missing profile is not a provider failure. After cooldown, only one recovery probe is allowed. A failed probe extends cooldown; a successful probe restores admissions. Earlier successful requests cannot close a newer cooldown. Expiring, persisted fifteen-second permits prevent abandoned calls from occupying concurrency forever. There are no automatic upstream retries.

## Hydration admission

Each recording/artist target counts as one work unit. A track counts as two because the hydrator may create a recording job. All newly created jobs, including hydrator follow-up jobs, contribute to daily accounting; this deliberately overestimates some work. The insertion statement materializes its inputs and counts before writing, then admits the whole new batch only if both budgets fit. Existing targets are acknowledged with `inserted: 0` even when new work is refused.

Admissions are serialized without an unbounded waiting queue: overlapping requests receive `503 hydration_busy`. Only active snapshots are accepted. A daily admission/work-budget refusal waits until midnight UTC; a backlog refusal suggests retrying after two minutes. The browser keeps a valid report if hydration is refused. The hydrator still processes one target per two-minute cron; admission limits do not increase its throughput.

## D1 accounting and its limits

Every runtime D1 execution reserves 50,000 read rows per statement and 5,000 write rows per potentially mutating statement before contacting D1. Batch reservations scale with statement count. Successful executions refund unused headroom based on D1 metadata, including index writes. A failed operation retains its entire reservation; missing metadata or a query exceeding its reservation stops further D1 admissions for that day. Guard outages refuse work rather than bypassing accounting. Resetting or deleting the guard's durable state discards the recorded usage and invalidates accounting for the current day.

The application's planned daily D1 budget is 4 million rows read and 70 thousand rows written, shared by the API and hydrator. Reservations are conservative estimates, not a proven bound on arbitrary SQL execution: a full scan can exceed its reservation before metadata is returned.

Runtime accounting covers the API and hydrator, but not SQL executed through Wrangler, publication scripts, migrations, or the dashboard, nor usage before the guards were activated. These operations require separate usage accounting. The pending-queue cap does not bound the lifetime size of completed jobs or materialized catalog data.

Admission controls reduce accepted work, but rejected traffic can still consume Worker and Durable Object requests and reads. Responses served from Workers Cache also consume requests. Infrastructure usage therefore remains relevant even when expensive application operations are refused.

R2 reads retain the existing daily/monthly limits. The hydrator now derives the monthly accounting period from UTC rather than a stale configuration value. R2 publication/storage and external operations are outside this runtime read counter. If a D1 quota pause leaves a processing lease open, the hydrator can reclaim it after expiry, including its final attempt, without exceeding the five-attempt counter; actual failures still become terminal.

## Activation

1. Activation at the beginning of a UTC day aligns runtime accounting with the daily budget reset. Earlier usage requires separate accounting.
2. D1 migration `0020_hydration_admission_usage.sql` adds the admission-accounting index. Creating the index consumes D1 resources outside runtime accounting.
3. The API is deployed first. Its `resource-guard-v1` Wrangler migration creates the SQLite-backed class and its binding.
4. The hydrator is deployed next. Its `RESOURCE_GUARD` binding refers to the class in `timbre-palette-api`. Both runtimes use the same `d1-daily-v1` identity. Environments sharing a database also need shared accounting.
5. The frontend messages are deployed with monitoring of `request_protected`, `lastfm_circuit_open`, `d1_usage`, `d1_reservation_exceeded`, `d1_accounting_uncertain`, and `hydrator_paused` events. Unexpected reservation overruns require query and index review.

Tests run with `yarn test:api` in the Workers runtime, apply the real migrations to an isolated D1 database, and mock all external fetches. CI also type-checks the API, hydrator, and browser.

References: [Rate Limiting API](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/), [D1 metadata](https://developers.cloudflare.com/d1/worker-api/return-object/), [SQLite-backed Durable Object storage](https://developers.cloudflare.com/durable-objects/api/sqlite-storage-api/).
