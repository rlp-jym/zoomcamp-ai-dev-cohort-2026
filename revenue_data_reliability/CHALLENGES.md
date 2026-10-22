# Engineering Challenges

## Render 512MB OOM Limits vs. DuckDB Memory Allocation

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
reviewer feedback while the pipeline runs.

**Do not raise these values without increasing the Render plan.** More memory or
threads may make local benchmarking faster, but they make the deployed app
unstable. Stability takes priority over shaving a few seconds off the demo.
