# Local backend stress test

Run `yarn stress:api`. This manual suite uses the Workers runtime, native local rate-limit bindings, isolated D1 and SQLite Durable Objects, and a mocked Last.fm. It neither contacts production nor changes production limits. External HTTP requests are intercepted; only the simulated Last.fm endpoint is accepted.

Defaults are **250 requests per scenario**, **50 concurrent requests**, and **80 ms simulated Last.fm latency**. These are individual API requests, not complete user analyses. Customize a run:

```sh
STRESS_REQUESTS=500 STRESS_CONCURRENCY=100 STRESS_UPSTREAM_MS=150 yarn stress:api
```

`STRESS_REQUESTS` accepts 100–5,000; concurrency accepts 2–500; simulated latency accepts 1–1,000 ms. Configurations whose simulated upstream workload exceeds 30 seconds are rejected.

The terminal shows a summary. `.wrangler/stress-api-report.json` contains HTTP statuses, refusal codes, minimum/maximum `Retry-After` seconds per code, latency percentiles (including accepted-request p95), completed and accepted requests/second, upstream call count and peak concurrency, and D1 accounting deltas. `STRESS_OUTPUT` selects another local report path; the default file is overwritten on each run. `passed` indicates that protection assertions succeeded, not that every request was accepted.

The scenarios cover:

- Last.fm bursts from multiple IPs with the current protections, then with only the native visitor limiter. The comparison bypasses **all Last.fm shared guards inside the test**, including concurrency, daily admission and circuit controls; D1 and hydration guards remain active.
- A shared-IP burst, provider overload, a held recovery probe, and a successful request after recovery. The cooldown fixture is advanced without waiting a real minute.
- Concurrent hydration admissions and the persisted job count.
- Evidence requests against populated D1 tables, exhausted read and write budgets, and documentation/health availability during a read-budget pause.

The process exits unsuccessfully on unexpected responses, missing refusal delays, leaked permits, or violated admission assertions. Successful measurements and failed test status are retained in the report when available.

This is a local protection and contention test. It calls the real handler directly, uses synthetic catalog data, and does not reproduce network transport, edge distribution, production SQL size, scheduled hydrator processing, or the complete browser flow. Fixture setup is excluded from D1 accounting deltas. Refusal throughput can be much higher than accepted throughput; use accepted-request latency and refusal counts when interpreting results.
