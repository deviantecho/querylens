# QueryLens changelog

## 5 November 2026 — Version 0.4.0 — Guided shop spreadsheet upload

- Added a three-stage CSV/XLSX flow: choose a worksheet, match columns and
  statuses, then compare checked totals before importing. Included an example CSV.
- Added explicit date, number-format, and currency choices; row-level validation;
  duplicate-order/customer-conflict checks; bounded parsing; and formula rejection.
- Added temporary uploaded shops with independent warehouses and history,
  anonymous public-session isolation, preview expiry/capacity controls, reset,
  and stale-plan invalidation when the dataset changes.
- Made dashboard dates, arbitrary-length monthly charts, currency labels, and
  business context follow the uploaded data. Reports requiring absent dimensions
  explain the missing field rather than returning an invented breakdown.
- Reused the existing trained intent model without training on uploaded orders.
  Optional local Qwen/Ollama prompts receive uploaded business context.
- Fixed SQLite history connections remaining open after transaction contexts,
  enabling immediate removal of temporary shop files on Windows.
- Added 31 tests; all 97 application tests and all nine sample analytical
  regression cases passed locally. Existing saved model experiments are unchanged.

## 5 November 2026 — Current documentation and public demo

- Published the canonical demo at
  [querylens-deviantecho.onrender.com](https://querylens-deviantecho.onrender.com)
  and linked it from the GitHub website field and README. The prior demo
  deployment was retired after migration.
- Documented the distinction between live hosted classifier inference and
  optional local Qwen/Ollama generation. Public AI Lab Qwen scores are saved
  local experiments.
- Refreshed the README, model card, validation guide, and measured-results guide.
  Added deployment/API operation documentation and this changelog.
- Recorded 66 passing application tests, nine passing independent analytical
  regression cases, and verified HTTPS drafting/execution on the branded URL.
- Clarified runtime limits, session expiry/retention, cold starts, report
  reproduction, and the exact archived model provenance. Original benchmark
  JSON outputs remain intact.

## 5 November 2026 — Public hosting support

- Added `querylens.hosted` for Render's free Python service, using the platform
  port, explicit public hostname, classifier mode, and one-thread scientific
  library settings.
- Added anonymous browser sessions with per-session request tokens, owned plans,
  separate history, expiry, request budgets, bounded storage, and one concurrent
  planning/execution operation.
- Added public Host/Origin checks, `/healthz`, a startup dashboard cache, a
  128 MB DuckDB execution limit, and hosted-mode UI explanations.
- Added four public-demo tests to the existing 62-test suite and retained
  `.querylens/`, credentials, weights, databases, and caches outside Git.

## 5 November 2026 — Local AI and standalone analytics

- Implemented a declarative business-model registry with calculated-field
  dependency ordering/cycle detection and a scope-aware SQL AST compiler.
- Added deterministic synthetic commerce data, DuckDB read-only execution,
  reviewed plans, local SQLite history, charts, SQL inspection, and CSV export.
- Trained a calibrated word/character TF-IDF intent classifier with explicit
  train/dev/test and unsupported-question splits, abstention, and artifact checks.
- Integrated pretrained CPU-local Qwen GGUF inference, sparse context retrieval,
  structured output, a bounded validation-error repair, and an optional local
  Ollama adapter.
- Added AI Lab and execution-based generation ablations, retaining all outputs,
  failures, sample counts, latency, intervals, and pretrained-model provenance.
- Published the standalone MIT-licensed application, tests, CI workflow,
  screenshots, and reports in
  [deviantecho/querylens](https://github.com/deviantecho/querylens).

The application package is version **0.4.0**. These entries describe the
implemented changes; they do not imply additional versioned releases or new
benchmark runs. See [VALIDATION.md](VALIDATION.md) for evidence and
[reports/README.md](reports/README.md) for measured model results.
