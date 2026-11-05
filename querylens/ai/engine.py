"""AI routing, provenance, retrieval traces, and trained-model status."""

import json
import os
import time

from querylens import provider
from querylens.ai.intent import load
from querylens.ai.local_llm import LocalLLM, available
from querylens.ai.retrieval import get_retriever
from querylens.catalog import EXAMPLES, example_for
from querylens.errors import QueryError

BACKENDS = {"local", "intent", "examples", "ollama"}


class AIEngine:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.router, self.report = load(data_dir / "ai")
        self.retriever = get_retriever()
        self.llm = LocalLLM(data_dir)
        self.examples = {e["id"]: e for e in EXAMPLES}

    @property
    def default_backend(self):
        selected = os.environ.get("QUERYLENS_MODE", "auto")
        if selected == "auto":
            if os.environ.get("QUERYLENS_MODEL"):
                return "ollama"
            return "local" if available(self.data_dir) else "intent"
        return selected if selected in BACKENDS else "intent"

    def draft(
        self,
        question,
        backend=None,
        retrieval=True,
        repair=None,
        *,
        context_override=None,
        dataset=None,
    ):
        backend = self.default_backend if backend is None else backend
        if not isinstance(backend, str) or backend not in BACKENDS:
            raise QueryError("Choose local, intent, examples, or ollama inference.")
        if not isinstance(retrieval, bool):
            raise QueryError("retrieval must be true or false.")
        documents = (
            context_override if context_override is not None else self.retriever.search(question)
        )
        started = time.perf_counter()
        if backend == "local":
            options = {"dataset": dataset} if dataset else {}
            answer = self.llm.generate(question, documents, retrieval, repair, **options)
            answer["source"] = "Local LLM / Qwen2.5-Coder-1.5B"
        elif backend == "intent":
            prediction = self.router.predict(question)
            if not prediction["accepted"]:
                raise QueryError(
                    "The intent model abstained: this question is uncertain or outside its nine unfiltered report types. Try the local language model or write SQL."
                )
            answer = {
                "sql": self.examples[prediction["intent"]]["sql"],
                "source": "Local ML / calibrated intent classifier",
                "explanation": "A trained text classifier selected the approved "
                + prediction["intent"]
                + " report. This backend maps supported intents to SQL templates; it does not generate unrestricted SQL.",
                "trace": {
                    "backend": "intent",
                    "model": "TF-IDF + calibrated logistic regression",
                    **prediction,
                },
            }
        elif backend == "examples":
            example = example_for(question)
            if example is None:
                raise QueryError(
                    "Example mode supports the listed example questions. Choose the local LLM or trained intent model for new wording."
                )
            answer = {
                "sql": example["sql"],
                "source": "Bundled example",
                "explanation": "A fixed offline example, not a model-generated answer.",
                "trace": {"backend": "examples"},
            }
        else:
            if not os.environ.get("QUERYLENS_MODEL"):
                raise QueryError(
                    "Configure QUERYLENS_MODEL to use a separately installed local Ollama model."
                )
            options = {"rules": context_override} if context_override is not None else {}
            sql, source, explanation = provider.generate(question, documents, **options)
            answer = {
                "sql": sql,
                "source": source,
                "explanation": explanation,
                "trace": {"backend": "ollama"},
            }
        if not answer["sql"]:
            raise QueryError(answer["explanation"] or "Please make this question more specific.")
        answer["context"] = documents if retrieval else []
        answer["trace"]["retrieved_documents"] = len(documents) if retrieval else 0
        answer["trace"]["training_hash"] = self.report["training_hash"]
        answer["trace"]["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return answer

    def status(self):
        evaluation_path = self.data_dir / "reports" / "ai-evaluation.json"
        llm_report = (
            json.loads(evaluation_path.read_text(encoding="utf-8"))
            if evaluation_path.exists()
            else None
        )
        return {
            "default_backend": self.default_backend,
            "local_model_ready": available(self.data_dir),
            "local_model": self.llm.path.name,
            "runtime": "CPU-local llama.cpp",
            "intent_model": {
                "training_count": self.report["train_count"],
                "dev_count": self.report["dev_count"],
                "test_count": self.report["test_count"],
                "training_hash": self.report["training_hash"],
                "threshold": self.report["threshold"],
                "evaluation": self.report["evaluation"],
            },
            "retrieval": {
                "method": "TF-IDF word bigrams + cosine similarity",
                "documents": len(self.retriever.documents),
                "includes_test_questions": False,
            },
            "generation_evaluation": llm_report,
            "data_provenance": self.report["provenance"],
        }
