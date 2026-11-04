# Measured local AI results

These results come from actual local classifier training and CPU-local language
model inference on the bundled synthetic commerce warehouse. No hosted API was
used. The corpus is small and curated, so scores are demonstration results, not
production accuracy estimates.

## Trained intent classifier

108 training / 27 development / 36 held-out test questions, nine report intents.
There are also 8 dev and 12 test unsupported questions.

| Metric | Measured result |
| --- | --- |
| Held-out intent accuracy | 83.33% (30/36) |
| Macro F1 | 0.8361 |
| Accepted coverage | 75.00% (27/36) |
| Accuracy on accepted questions | 96.30% (26/27) |
| Test unsupported-question rejection | 100% (12/12) |

The threshold uses development data only. The test confusion matrix, per-class
metrics, individual predictions, model/library versions, and training-data hash
are in `intent-report.json`. Classifier routing is a bounded template-based
baseline; filtered questions in the SQL benchmark expose its limitations.

## Generated SQL: execution accuracy

All four variants received the same twelve answerable questions. Reference
results were obtained from pre-authored reference SQL. Row order is checked when
requested. Automatic repair was disabled for these comparisons.

| Variant | Correct / total | Execution accuracy | Valid SQL | Mean latency |
| --- | --- | --- | --- | --- |
| Exact example lookup | 0/12 | 0.00% | 0.00% | 1.38 ms |
| Trained intent router | 5/12 | 41.67% | 66.67% | 34.27 ms |
| Local LLM, no retrieval | 5/12 | 41.67% | 91.67% | 9.02 s |
| Local LLM, retrieved context | 10/12 | 83.33% | 91.67% | 15.01 s |

For the retrieval-assisted result, the 95% Wilson interval is approximately
55.2%–95.3%. That wide interval reflects the sample size. The comparison is a
descriptive single-run ablation, not proof of general or statistically established
improvement. Example/intent baselines have a narrower supported task scope.

The full report retains all outputs and failures in `ai-evaluation.json`. Two
retrieval-assisted cases failed: one used an unfiltered revenue numerator for a
Partner-only average, and another referenced the customer region without the
required join. Valid SQL can still be semantically wrong.

Three additional unsupported/write requests were checked separately. Pipeline
rejections include explicit model abstentions and SQL-validation failures; they
are not an independent model-refusal accuracy score. The no-retrieval model also
returned plausible-looking but wrong queries for unavailable profit/forecast data.

## Model and provenance

- Qwen2.5-Coder-1.5B-Instruct GGUF, Q4_K_M, pretrained public weights.
- CPU inference through llama-cpp-python 0.3.36, 8 threads, temperature 0, seed 42.
- Intel Core i7-13700H, 16 GB system RAM. No GPU acceleration was used.
- Published model SHA-256: `cc324af070c2ecbfd324a30884d2f951a7ff756aba85cb811a6ec436933bb046`.
- Pinned upstream revision and file details are in `model-manifest.json`.
- Training and evaluation datasets are in `querylens/ai/data/`; the test split is
  excluded from training and retrieval indexing.

See MODEL_CARD.md for methodology, limitations, and reproduction commands.
