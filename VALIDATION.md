# QueryLens validation

Documentation reviewed: **5 November 2026 (IST)**. Application package version:
**0.4.0**. The [live demo](https://querylens-deviantecho.onrender.com) uses the
public-mode implementation verified below.

## Automated checks

The current suite contains **97 tests**, including 31 spreadsheet-import tests
added to the previous 66-test compiler, workbench, AI, and public-demo suite.
All 97 passed locally on Python 3.11 / Windows. The independent analytical
regression command also passed **9/9** cases. The same checks run in
[GitHub Actions](https://github.com/deviantecho/querylens/actions/workflows/ci.yml)
on Python 3.11 / Ubuntu; the 0.4.0 upload implementation passed in
[this CI run](https://github.com/deviantecho/querylens/actions/runs/41978224920).
The earlier 66-test public-demo run remains
[available here](https://github.com/deviantecho/querylens/actions/runs/41915141740)
as historical evidence; it does not verify the new upload implementation.

| Area | Verification |
| --- | --- |
| Model compiler | Calculated-field dependencies, cycles, aliases, CTE scope collisions, joins, UNIONs, reserved identifiers, deterministic output |
| Query execution | Nine result comparisons against independent Decimal-based calculations, read-only storage, disabled external access, row caps, required reviewed plans |
| Supervised ML | Explicit disjoint splits, real classifier fitting/inference, abstention, artifact checksums, reload, corrupt-artifact recovery |
| Local generation integration | Structured responses, output budgets, one-attempt repair, unsafe SQL rejection, result comparison, saved evaluation shape |
| Retrieval | Training examples only, no indexed dev/test/SQL-benchmark questions, schema inclusion, distinct retrieved example intents |
| Local HTTP API | Bootstrap, plan/review/execute flow, request tokens, malformed requests, rejected SQL, history |
| Public HTTP API | Per-browser plan/history separation, token separation, Host/Origin checks, unavailable-model rejection, manual filtered SQL |
| Public session lifecycle | Request budget, plan cap, inactive-session expiry, session capacity, bounded SQLite records, required hostname |
| Spreadsheet input | CSV and worksheet-selected XLSX, Excel numeric/date cells, explicit locale/currency/status choices, malformed files, duplicate headers/orders, ZIP expansion and row limits, formula/error rejection |
| Uploaded data | Independently checked totals, invalid-row blocking, customer consistency, unavailable-field rejection, uploaded prompt context, failed replacement preservation |
| Uploaded workspace lifecycle | HTTP import/preview/commit/reset in both local and public modes, foreign-preview denial, private results, stale-plan rejection, expiry/capacity release, and actual temporary-file removal on Windows |

Ruff lint and formatting checks pass. JavaScript syntax was checked with
`node --check` for both `app.js` and `upload.js`. The CI workflow installs the package,
runs Ruff and pytest, then executes the nine-case analytical regression suite.
CI does not download Qwen weights or execute the real Qwen benchmark; model
adapters are simulated where necessary in unit tests. Real-model experiments
are separate evidence described below.

## Real model experiments

Local experiments used Python 3.11.9 / Windows, DuckDB 1.5.6, sqlglot 30.29.0,
scikit-learn 1.9.1, and llama-cpp-python 0.3.36. CPU inference used an Intel Core
i7-13700H with 16 GB system RAM and no GPU acceleration.

| Experiment | Recorded result |
| --- | --- |
| Classifier train / dev / test | 108 / 27 / 36 curated synthetic questions |
| Unsupported-question dev / test | 8 / 12 separate questions |
| Classifier test accuracy | 30/36 = 83.33%; macro F1 0.8361 |
| Accepted classifier coverage | 27/36 = 75.00% |
| Accuracy on accepted predictions | 26/27 = 96.30% |
| Test unsupported-question rejection | 12/12 |
| Qwen, no retrieval | 5/12 execution-correct; mean 9.02 s |
| Qwen, retrieved context | 10/12 execution-correct; mean 15.01 s |

The Qwen file's published SHA-256 was verified before inference. Both LLM
variants used the same twelve answerable questions and three additional
unsupported/write requests; automatic repair was disabled. The retrieval-assisted
accuracy has a 95% Wilson interval of 55.2%–95.3%. Pipeline rejection can include
SQL-validation failures and is not a standalone model-refusal accuracy score.

These are small curated experiments. Accepted classifier errors, incorrect LLM
SQL, latency, and case-level output remain in the [saved reports](reports/README.md).
The documentation refresh does not rerun or overwrite those experiments.

## Local browser verification

The local workflow was checked with actual Qwen drafting/execution, classifier
inference on different wording, SQL and inference provenance, AI Lab results,
and desktop/mobile layouts. The optional model runs on the local computer with
no hosted model API or per-query API charge.

The upload workflow was also exercised with an actual CSV file and a two-sheet
Excel workbook. Selecting the orders sheet and INR produced a checked preview
of net revenue 80, two completed orders, AOV 40, and refund rate 52.94%. Import
updated the reporting window to March–April 2024 and returned 80 from a trained
classifier query. HTTP integration tests verify reset and cross-session isolation.
The new cleanup tests caught and fixed SQLite connections remaining open after
their transaction context, which previously prevented Windows file removal.

## Public deployment verification

The current public URL was verified over HTTPS after deployment. Checks included:

- `/healthz`, application HTML/assets, bootstrap, and the public classifier mode.
- A paraphrased top-five-customer question producing a reviewed plan and five rows.
- Manual Web-channel revenue SQL returning USD 263,750.80.
- Separate browser sessions with private history and refusal to execute another
  session's plan, plus session-specific request tokens.
- AI Lab showing the trained classifier and all four saved generation variants.
- A real browser loading the new hostname and exposing the expected demo controls.
- Version 0.4.0 serving the upload client after Render deployment
  `dep-dbm1r66c6qcc73fnjgsg` became live at application commit `16c9302`.
- A real HTTPS upload/preview/import/intent-query/reset sequence using three
  synthetic INR orders dated March–April 2024. Preview and query both returned
  net revenue 80; AOV was 40. A separate session retained the sample-shop
  revenue of USD 810,152.78, and reset restored the caller's sample shop.
- The GitHub repository's website field pointing to the current public URL.

The free host runs the classifier, examples, and SQL editor. It does not run
Qwen or Ollama. Public UI text identifies the Qwen scores as saved local results.
The active service uses Render's free plan in Singapore; its configured TCP
readiness check is distinct from the available `/healthz` endpoint. The reusable
Blueprint also declares that HTTP endpoint for deployments created from it.

This verification is not a load test, uptime guarantee, external security audit,
or proof of general text-to-SQL accuracy. See [DEPLOYMENT.md](DEPLOYMENT.md) for
session retention, resource limits, cold starts, and the scope of the demo.

## Reproduce the checks

After installing `.[dev]`:

```sh
python -m pytest
ruff check querylens tests_querylens
ruff format --check querylens tests_querylens
node --check querylens/static/app.js
python -m querylens --eval
```

For model experiments, follow [MODEL_CARD.md](MODEL_CARD.md#reproduce).
