# QueryLens 0.3 validation

The application was checked on Python 3.11.9 / Windows with DuckDB 1.5.6,
sqlglot 30.29.0, scikit-learn 1.9.1, and llama-cpp-python 0.3.36.

## Automated checks

All 62 collected tests were verified locally. The HTTP integration tests use
loopback sockets. Coverage includes compiler/API behavior plus trained-model
inference, explicit split separation, retrieval leakage checks, artifact
round-tripping and corrupt-model retraining, abstention, structured output,
one-attempt repair, unsafe SQL rejection, result comparison, evaluation storage,
and inference-mode request validation.

Ruff lint/format and JavaScript syntax checks passed. The GitHub Actions workflow
runs the application suite without downloading the optional language model.

## Real model experiments

The intent classifier was trained locally on 108 curated synthetic questions;
27 dev questions selected acceptance thresholds, and 36 test questions measured
classification. Held-out accuracy was 83.33%, macro F1 0.8361, accepted coverage
75%, and accepted-question accuracy 96.30%. All 12 test OOD questions were
rejected. These are small curated datasets, not production accuracy estimates.

The published Qwen GGUF was downloaded and its SHA-256 verified. Actual CPU-local
inference was run on twelve answerable benchmark questions and three additional
unsupported/write requests for each LLM setting. Execution accuracy was 5/12
without retrieval and 10/12 with retrieval. Mean answerable-case latency was
9.02 s and 15.01 s respectively. Automatic repair was disabled for this ablation.
Complete outputs, failures, intervals, and exact sample counts are in `reports/`.

The local model still makes semantic errors, including a wrongly filtered average.
SQL that compiles is not necessarily a correct answer. Human review remains part
of the application flow. Pretrained LLM inference is distinct from training the
project's supervised classifier.

## Browser verification

The local demo uses the model-backed backend by default when weights/runtime are
present. Browser verification covers real language-model drafting/execution,
trained-classifier inference on new wording, inference provenance, AI Lab
metrics/results, and desktop/mobile layout. Model inference runs locally with
no hosted API key or per-query API charge.

See README.md and MODEL_CARD.md for setup, reproduction commands, dataset
provenance, runtime limits, and interpretation of the saved results.
