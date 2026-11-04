# QueryLens

An independent analytics workbench that turns business questions into reviewable
SQL, consistent revenue metrics, and inspectable results.

QueryLens combines a declarative business-model registry, a scope-aware SQL
compiler, trained NLP routing, local language-model generation, and a complete
browser workflow. Inference runs on your computer without a hosted API.

**[Try the live demo](https://querylens-deviantecho.onrender.com)**

The hosted demo includes the trained intent classifier, SQL workbench, CSV
exports, and AI Lab. Qwen generation runs in the local version. The first visit
after inactivity may take about a minute to start.

## Quick start

Requires Python 3.11 or later.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m querylens
```

On macOS/Linux, activate with `source .venv/bin/activate` instead. Open
http://127.0.0.1:8766. Alternatively, `uv run python -m querylens` creates an
environment and runs the application. The first run creates local synthetic
data in `.querylens/`; the warehouse and history are excluded from version control.

![QueryLens workspace](screenshot.png)

## Features

- Revenue dashboard, monthly trends, channel analysis, and CSV exports.
- Declarative models mapping business names to physical tables.
- Calculated fields with dependency ordering and cycle detection.
- SQL compilation using ASTs and scope resolution, including joins, aliases,
  CTEs, model-shadowing CTE names, and UNION queries.
- A model-definition fingerprint attached to each reviewed plan.
- Business-context retrieval, nine offline example questions, and a SQL editor.
- A supervised intent classifier with calibrated probabilities and abstention.
- CPU-local Qwen text-to-SQL inference through llama.cpp, with structured JSON.
- TF-IDF/cosine retrieval of business definitions and training examples.
- An AI Lab with held-out classifier scores and generation ablation results.
- Draft, validate, review, execute, and audit workflow with stored plans.
- Read-only execution, disabled external data access, query deadlines, memory
  limits, bounded results, and local request protection.
- Independent analytical regression checks and application/API tests.

## Architecture

```text
Browser
  -> question + retrieved business context
  -> trained intent classifier or local language model
       retrieve schema, rules, and relevant training examples
       generate structured SQL + explanation
  -> read-only SQL AST validation
  -> QueryLens model compiler
       resolve model tables in SQL scopes
       order calculated fields by dependency
       generate typed model projections as CTEs
       preserve aliases and existing user CTEs
       attach model fingerprint
  -> DuckDB EXPLAIN validation
  -> at most one validation-error repair for local generation
  -> stored plan / human review
  -> read-only DuckDB execution
  -> results, CSV export, SQLite history
```

The application-specific compiler and model registry are implemented in this
repository. sqlglot supplies SQL parsing and AST primitives; DuckDB supplies the
database engine. Python's standard library provides the HTTP server and SQLite
history storage. The browser client uses JavaScript and CSS without a frontend
framework.

## Business models

The model definitions live in `querylens/models.json`. For example:

```json
"net_revenue": {
  "type": "DOUBLE",
  "expression": "CASE WHEN status = 'completed' THEN gross_amount - refund_amount ELSE 0.0 END"
}
```

Calculated fields may reference other fields of the same model. The registry
checks those references, rejects cycles, and computes a valid evaluation order.
Its compiler creates nested projections for calculated dependencies and inserts
the required model CTEs before the user's existing CTEs. Identifying tables by
scope avoids rewriting a user CTE that happens to have the same name as a model.

This is a small application-specific modeling layer, not a universal SQL planner.
DuckDB remains responsible for database binding, optimization, and execution.

## Dataset and metrics

The demo creates 2,376 synthetic orders and 48 synthetic customers covering 2025,
using seed 42. All money is USD; there is no real customer information.

| Metric | Definition |
| --- | --- |
| Net revenue | Gross amount minus refund amount for completed orders; zero for cancelled orders |
| Completed orders | Orders with status `completed` |
| Average order value | Net revenue divided by completed-order count |
| Refund rate | Refunded dollars divided by gross dollars for completed orders, multiplied by 100 |

Synthetic monetary values are stored as doubles. The independent regression
oracle uses Python Decimal aggregations and a small numerical tolerance; the
application is not an accounting ledger.

## Local AI setup

The trained intent classifier runs after the basic install. On first launch,
the application fits it from the bundled training split and saves its model,
checksum, and report under `.querylens/ai/`. It recognizes nine unfiltered report
intents; it does not generate arbitrary SQL. Confidence thresholds and scope
checks reject many uncertain or unsupported requests; the model card and saved
evaluation also document incorrect accepted cases.

For language-model generation, install the CPU runtime and download the public
Qwen2.5-Coder-1.5B-Instruct Q4_K_M weights (about 1.12 GB):

```powershell
python -m pip install llama-cpp-python==0.3.36 --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
python -m querylens.model_download
python -m querylens
```

The downloader pins the resolved repository revision and verifies the published
SHA-256 checksum. Model weights are local, ignored by Git, and never included in
the project source archive. Internet access is needed for initial setup;
generation itself is offline. There is no API key or per-query fee.

The default backend automatically selects the local language model when available,
otherwise the trained classifier. The UI allows switching between those modes
and the fixed example library. `QUERYLENS_MODE=local|intent|examples|ollama` can
set an explicit default; `QUERYLENS_GGUF` selects another local GGUF file.

The language model receives schema and retrieved context, produces structured
SQL, and passes through AST/binder validation. A failed draft may receive one
repair attempt using the validation error. Every accepted draft still needs
human review. Inference details record its model, tokens, latency, retrieval
setting, and SQL attempts. No model-generated confidence score is claimed.

An existing local Ollama installation is still supported using `QUERYLENS_MODEL`
with its installed model name; this integration calls only loopback.

See [MODEL_CARD.md](MODEL_CARD.md) for training data, limitations, evaluation
methodology, and the distinction between the trained classifier and pretrained LLM.

## Verification

```sh
python -m pytest
ruff check querylens tests_querylens
ruff format --check querylens tests_querylens
python -m querylens --eval
python -m querylens --train-ml
python -m querylens --ai-eval --skip-llm
python -m querylens --ai-eval
```

The nine analytical regression cases compare actual compiled-query results with
independent Python calculations of raw records, rather than comparing SQL text.
Compiler tests exercise field dependencies, cycles, scope collisions, aliases,
joins, UNIONs, reserved identifiers, and repeatability.

`--train-ml` reports classifier accuracy, macro F1, selective coverage/accuracy,
out-of-scope rejection, per-class scores, and a confusion matrix. The classifier
uses 108 training, 27 development, and 36 test questions, plus separate
development/test unsupported-question sets. The threshold is selected using
development data only.

`--ai-eval` compares exact examples, the trained intent router, local generation
without retrieval, and local generation with retrieval. Twelve held-out
answerable questions are scored by result values against reference SQL; three
additional questions check refusal behavior. Automatic repair is disabled in
this comparison. The report includes generated SQL, errors, execution accuracy,
SQL validity, latency, counts, and 95% Wilson intervals. Small synthetic test
sets do not establish production accuracy.

View saved results in AI Lab. Reproducible reports are also retained under
`reports/` after verification. Full runs save current output to
`.querylens/reports/ai-evaluation.json`. `--eval-limit` is for debugging and the
report discloses the actual case count.

![QueryLens AI Lab](ai-lab.png)

## Source map

```text
querylens/
  models.json       Declarative business models
  modeling.py       Registry, expression validation, dependency DAG, projections
  planner.py        Scope-aware model expansion and compiler trace
  catalog.py        Business rules and example question library
  dataset.py        Deterministic synthetic warehouse
  policy.py         SQL query boundary
  provider.py       Example and local-model generation adapters
  model_download.py Pinned model download and checksum verification
  ai/               Training, local inference, retrieval, and ablation evaluation
  service.py        Planning, review, execution, history, dashboard
  server.py         Loopback API and static assets
  evaluation.py     Independent analytical result checks
  static/           Browser interface, charts, CSV export
tests_querylens/    Compiler, application, and API tests
.github/workflows/ci.yml
MODEL_CARD.md      Model design, methodology, and limitations
reports/           Measured results and pretrained-model provenance
VALIDATION.md      Verification scope and observed behavior
```

## Deployment scope

The default application is a single-user local demonstration. It binds to
`127.0.0.1` and checks Host headers plus a per-process token for POST requests.

`render.yaml` defines an optional public demonstration on Render's **free**
Python web-service plan. It runs `python -m querylens.hosted`, binds to the
platform port, and permits only the configured public hostname. The live demo
supports the trained classifier, fixed examples, SQL editor, CSV export, and
AI Lab. Qwen's 1.12 GB weights do not fit the free instance's 512 MB RAM;
LLM generation remains a local feature. AI Lab clearly labels saved local-model
experiments separately from live classifier inference.

Anonymous demo sessions use Secure/HttpOnly/SameSite cookies, separate request
tokens, session-scoped plans/history, one-hour inactivity expiry, bounded
storage, and request/concurrency limits. DuckDB has a 128 MB execution memory
limit in hosted mode. The dataset contains only deterministic synthetic records.
History resets on restarts; this is not an account-based multi-user product.
Render's free service sleeps after 15 idle minutes, so the first visit may take
about a minute to start. Its free usage limits apply.

It currently uses a fixed commerce schema. Hosted authentication, custom-source
ingestion, scheduled ETL, and multi-tenant permissions are not implemented. A
successful query regression suite is not a measurement of LLM accuracy or
production scalability.

## License

Application source is MIT licensed. Runtime dependencies retain their own
licenses: DuckDB, sqlglot, scikit-learn, and llama-cpp-python are third-party
libraries. The Qwen language-model weights are pretrained by their publisher,
under their own Apache-2.0 license; this project does not claim to have trained
or fine-tuned that language model.
