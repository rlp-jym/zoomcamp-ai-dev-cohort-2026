# Engineering Challenges

## Render 512MB OOM Limits and DuckDB Memory Allocation

**Symptom.** Validation runs on Render intermittently returned `502 Bad Gateway`
under load. The app process was being killed during the DuckDB scan rather than
raising a normal Python exception.

**Cause.** Render's Starter container has 512MB of total memory. That budget has
to cover Python, FastAPI/uvicorn, the Postgres connection pool, downloaded
Parquet cache files, buffered query results, and DuckDB itself. DuckDB's
`memory_limit` is only one part of that total. A `300MB` limit with `2` threads
left too little headroom and pushed the container over the edge.

**What we tried.** The 12-month demo window, local Parquet cache, and batched
rule execution reduced the runtime substantially. Raising DuckDB to `300MB` and
using two threads made the warm-cache run faster, but it was not stable on the
512MB container.

**Stable configuration.** The final settings are:

- DuckDB `memory_limit = '200MB'`
- `DUCKDB_THREADS = 1`
- 12-month deterministic scan window
- Local scenario Parquet cache
- Batched validation/reconciliation execution

This yields roughly a 35-45 second run on Render. That is the stable maximum for
this container size and is acceptable for the demo; the progress bar gives the
user feedback while the pipeline runs.

**Do not raise these values without increasing the Render plan.** More memory or
threads may make local benchmarking faster, but they make the deployed app
unstable. Stability takes priority over shaving a few seconds off the demo.

## Workarounds

This table is the delta record for [`tasks.md`](tasks.md): the major changes
made after the original build tracker, and the commits that carry them.

| Challenge | Workaround | Evidence |
|---|---|---|
| Render 512 MB OOM / 502s | 12-month window, DuckDB `200MB` / 1 thread, local Parquet cache, batched rules | `dbad70e`, `b1fe627`, `0fb328b` |
| 5-year dataset caused Render 502s | Cut to a 12-month window; validate only the trailing window | `9bea1c9`, `dbad70e` |
| Telemetry grew past the free Postgres tier | Metric interval 60s → 300s, drop body-send spans, 30-day retention, add metrics panel | `7c2c9e4`, `90dd64d` |
| Chart threads bled across datasets | Dataset-scoped anchors: `chart-*--<dataset>` | `f242f16`, `a2aecf5` |
| Stacked areas blended into one color | Opaque fills with matching borders | `a2aecf5` |
| Dataset selector did not refresh | `datasets-changed` event + HTMX refresh | `3d6b52f` |
| Scenarios added little demo value | Hide nav entry; keep route | `b65e585` |
| Controller missing from fresh traces | Run verification shortly after boot (+90s) | `61547b2` |
| Seeds were too random to discuss | Fixed 101 neutral / 102 bullish / 103 bearish, 12 months | `6f769c5`, `eb87b04` |
| Dashboard order hid the variance story | Reorder charts; group variance bridges | `7b706dc` |
| Header scrolled away | Sticky topbar, wrap on narrow screens | `e35be5c` |
| Audit/Observability looked dataset-scoped | Mark both app-wide; hide dataset selector | `87b0eaa` |
| Persona actions looked unavailable | Show actions to all; disable with the required persona label | `093cbc4`, `78ec3d3` |
