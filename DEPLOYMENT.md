# QueryLens deployment and operation

Documentation reviewed: **5 November 2026 (IST)**.

**[Live demo](https://querylens-deviantecho.onrender.com)** ·
**[GitHub repository](https://github.com/deviantecho/querylens)**

## Current deployment

| Setting | Current value |
| --- | --- |
| Public URL | `https://querylens-deviantecho.onrender.com` |
| Render display name | `querylens` |
| Runtime / region / plan | Python 3.11 / Singapore / Free |
| Source | `deviantecho/querylens`, branch `main` |
| Build | `pip install . && python -m querylens --train-ml` |
| Start | `python -m querylens.hosted` |
| Bind address | `0.0.0.0`, platform-supplied `PORT` (default 10000) |
| Live inference | Trained intent classifier and fixed examples; SQL editor also available |
| Model-generation results in AI Lab | Saved CPU-local Qwen experiment copied at startup |
| Readiness | Active service uses TCP checks; `/healthz` is also available |

The service was created directly through Render, not through a managed Blueprint.
[`render.yaml`](render.yaml) is a reusable configuration for the same application;
it also declares the optional HTTP health-check path `/healthz`. Editing that file
does not itself apply infrastructure settings to the current directly created
service. The display name is distinct from the public hostname: renaming a
service did not rename its assigned address. The previous demo deployment was
retired after the branded hostname was verified.

The service is linked to GitHub with automatic deploys enabled. A normal commit
to `main` rebuilds the app. Documentation-only commits can use `[skip render]`
to leave the working deployment unchanged while GitHub Actions still verifies
the repository. See [Render deploy behavior](https://render.com/docs/deploys).

## What visitors can use

The hosted app includes the dashboard, business definitions, classifier and
example modes, SQL drafting/review/execution, CSV export, query history, and
AI Lab. Its entry point forces intent mode and the public API rejects Qwen and
Ollama generation requests. Filters and custom aggregations can be written in
the SQL editor; the classifier covers nine unfiltered report types.

Visitors can also import a CSV or XLSX orders sheet through **Your shop data**.
Column matching and totals must be checked before switching to a temporary,
session-owned shop. See [UPLOAD_GUIDE.md](UPLOAD_GUIDE.md) for formats, defaults,
privacy, limits, and the complete API flow. Imported shop data is not used for
training; the benchmark reports remain sample-data experiments.

Qwen's 1.12 GB model file cannot fit in the free instance's 512 MB RAM. Use
[the local setup](README.md#local-ai-setup) for actual Qwen generation, with or
without retrieved context. The public AI Lab displays saved local Qwen scores;
it does not run that benchmark in the browser or on the free server.

Render's free service can sleep after 15 idle minutes, with a cold start of
about a minute on the next visit. Storage is ephemeral and free usage limits
apply. See [free-service details](https://render.com/docs/free) and
[compute plans](https://render.com/docs/compute-plans). No paid model API is used.

## Deploy another copy

1. Fork or push the source repository to your GitHub account.
2. Create a Render **Python web service** from your connected GitHub repository.
3. Select the **Free** plan, Python 3.11, and an appropriate region. The checked-in
   `.python-version` selects the Python 3.11 patch line.
4. Use the build/start commands in the table above and the non-secret environment
   variables from `render.yaml`. No API key or model download is required.
5. Optionally configure `/healthz` as the HTTP health-check path; otherwise the
   service uses Render's default TCP readiness checks.
6. Deploy, wait for Render's `live` status, then open the assigned HTTPS URL.
7. Check bootstrap, draft/review/execute a classifier question, try filtered SQL,
   and inspect AI Lab before sharing the new link.

When using the Blueprint instead, update its repository/name for your copy and
review Render's proposed resource changes before applying it. The resulting
hostname is assigned by Render and is not guaranteed by the display name.

## Environment variables

| Variable | Scope and behavior |
| --- | --- |
| `PORT` | Hosted listener port; defaults to 10000. Local CLI uses `--port`, default 8766. |
| `RENDER_EXTERNAL_HOSTNAME` | Preferred public Host allowlist entry, supplied by Render. |
| `QUERYLENS_PUBLIC_HOST` | Fallback hostname for another HTTPS host when Render's hostname variable is absent; provide a hostname, not a URL. |
| `QUERYLENS_DATA_DIR` | Runtime data directory; defaults to `.querylens/` relative to the working directory. Local CLI also accepts `--data-dir`. |
| `QUERYLENS_MODE` | Local default: `auto`, `local`, `intent`, `examples`, or `ollama`. Hosted entry point always sets `intent`. |
| `QUERYLENS_GGUF` | Local GGUF file path; defaults to the models folder under the application's data directory. |
| `QUERYLENS_MODEL` | Installed Ollama model name for local use; the adapter calls loopback port 11434. |
| `OPENBLAS_NUM_THREADS`, `OMP_NUM_THREADS`, `MKL_NUM_THREADS` | Set to `1` by hosted startup before importing scientific libraries. |
| `PYTHONUNBUFFERED` | Set to `1` in the deployment configuration for timely startup logs. |

`RENDER_EXTERNAL_HOSTNAME` takes precedence over `QUERYLENS_PUBLIC_HOST`. The
current entry point permits one public hostname; adding a custom domain requires
an intentional allowlist change as well as provider DNS/TLS configuration.
Do not disable the Host check to work around a domain mismatch.

The model downloader has its own `--directory` argument and does not use
`QUERYLENS_DATA_DIR`. For a custom local data directory, download into that
directory's `models/` subfolder or configure `QUERYLENS_GGUF` explicitly.

## Sessions, retention, and query limits

| Boundary | Public behavior |
| --- | --- |
| Browser session | Random server-held session; Secure, HttpOnly, SameSite=Strict `__Host-querylens-session` cookie |
| POST protection | Per-session `X-QueryLens-Token`; exact allowed Host; matching Origin when present |
| Plan ownership | Only the browser session that drafted a plan can execute it |
| Inactive-session expiry | One hour; sessions can also be evicted at the 128-session capacity |
| Per-session retention | Up to 20 reviewed plans and 50 recent history entries in memory |
| Runtime SQLite retention | Public pruning retains at most 2048 records in each of the plans/audit tables |
| POST request budget | 20 per session and 120 across the process per rolling minute |
| Concurrent planning/execution | One operation; excess requests receive HTTP 429 |
| Upload capacity | Eight temporary upload workspaces, including pending previews, per process |
| SQL execution | Read-only DuckDB, external access disabled, one database thread, 128 MB database memory limit |
| Execution deadline / output cap | Five-second interrupt timer; at most 200 returned rows |
| Input bounds | Normally 24,000-byte JSON; file inspection 2,800,000 bytes; column validation 64,000 bytes; question 1,000 characters; SQL 12,000 characters |

The 128 MB limit belongs to DuckDB, not the entire Python process. HTTP request
threads and application libraries have separate overhead. This is a bounded
portfolio demonstration, not a load-tested production service.

Public history is separate between sessions but temporary. Restarting the
process loses in-memory ownership/history; free-host restarts or redeploys can
also erase runtime files. Expiry, eviction, or pruning can require a new draft.
There are no user accounts or durable multi-tenant workspaces. Session controls
do not turn the app into an identity provider. Uploads use a distinct temporary
warehouse/history directory and separate business context. Reset, normal server
shutdown, and session cleanup remove it; expiry cleanup runs when sessions are
next accessed. A restart ends access and free-host storage is ephemeral.
Keep original exports. Another tab with the same cookie shares the workspace.

Local mode keeps its existing loopback listener, per-process POST token, 256 MB
DuckDB memory limit, two database threads, and persisted SQLite plans/history.
The row limit and execution interrupt timer apply in both modes. Local uploaded
shops are temporary and shared by browsers connected to that running local
server. Uploaded history is separate from retained local sample-shop history.
Changing or removing the dataset invalidates reviewed HTTP plans.

## HTTP API

All JSON replies use `Cache-Control: no-store`. Public API clients must retain
the HTTPS session cookie from bootstrap and send its token for POST requests.

| Method and path | Purpose |
| --- | --- |
| `GET /healthz` | Fast process-readiness response: `{"status":"ok"}`. Does not create a browser session. |
| `GET /api/bootstrap` | Dashboard, schema, examples, default mode, request token; creates/reuses a public session. |
| `GET /api/ai/status` | Classifier metrics, retrieval provenance, and any saved generation report. |
| `GET /api/history` | Current session's recent history; returns an empty list without a public session. |
| `POST /api/plan` | Validate a classifier/example draft or supplied SQL, compile models, bind-check, and store a reviewed-plan candidate. |
| `POST /api/execute` | Execute the caller's stored plan after review; public callers must own the plan. |
| `POST /api/import/inspect` | Read a bounded CSV/XLSX file and return worksheet/header/preview information. |
| `POST /api/import/statuses` | List the selected status column's values for explicit mapping. |
| `POST /api/import/validate` | Validate every row, report issues, and prepare a totals preview. |
| `POST /api/import/commit` | Activate only the caller's checked server-held import snapshot. |
| `POST /api/import/cancel` | Discard a pending preview, keeping the active shop. |
| `POST /api/import/reset` | Remove the current upload and return to the sample shop. |

A classifier planning body:

```json
{"question":"Compare revenue across regions","backend":"intent","retrieval":true}
```

For manual SQL, include `question` and `sql`; execution uses the returned plan's
`id` as `{"plan_id":"<reviewed-plan-id>"}`. CSV export is created in the browser
from the returned result, rather than through a separate export endpoint.

Request errors return HTTP 400; invalid Host/token/Origin returns 403; unknown
paths return 404; rate/concurrency limits return 429 with `Retry-After: 10`;
unexpected server errors return 500. A request budget can remain exhausted
longer than the first retry interval.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Slow first visit | Allow the free service to wake; inspect Render status if it fails to become healthy. |
| Hostname rejected | Use the exact assigned HTTPS hostname; verify the allowed-host environment setting. |
| Refresh/token or missing-plan error | Refresh/bootstrap, then draft and review a new plan in the same browser session. |
| HTTP 429 | Wait for the active query or rolling request budget to clear. |
| Filtered question abstained | Use manual SQL or the local Qwen setup; the live classifier supports unfiltered report types. |
| Qwen unavailable | Expected on the free demo; install the optional runtime/weights locally. |
| No saved generation results locally | Run the full local benchmark; a baseline-only run saves only two variants. |
| History lost after restart | Expected for the public demonstration; use local mode for local persisted history. |

For application checks, see [VALIDATION.md](VALIDATION.md). For model-quality
interpretation and the original reports, see [MODEL_CARD.md](MODEL_CARD.md) and
[reports/README.md](reports/README.md).
