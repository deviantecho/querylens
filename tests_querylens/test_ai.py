import json
import sys
from types import SimpleNamespace

import pytest

from querylens.ai.evaluate import benchmark, run, same_result, wilson
from querylens.ai.intent import load, rows, train
from querylens.ai.local_llm import LocalLLM, messages
from querylens.ai.retrieval import corpus, get_retriever
from querylens.catalog import normalize
from querylens.errors import QueryError
from querylens.service import Workbench


@pytest.fixture(scope="module")
def ai_workbench(tmp_path_factory):
    return Workbench(tmp_path_factory.mktemp("ai-workbench"))


def test_question_splits_are_disjoint_and_cover_all_nine_intents():
    parts = {split: {normalize(q) for q, _ in rows(split)} for split in ["train", "dev", "test"]}
    assert not parts["train"] & parts["dev"]
    assert not parts["train"] & parts["test"]
    assert not parts["dev"] & parts["test"]
    assert len({label for _, label in rows("train")}) == 9
    assert len(parts["train"]) == len(rows("train"))


def test_retrieval_indexes_only_training_questions():
    retriever = get_retriever()
    indexed = {normalize(d["title"]) for d in retriever.documents if d["kind"] == "example"}
    held_out = {normalize(q) for q, _ in rows("dev") + rows("test")}
    held_out |= {normalize(c["question"]) for c in benchmark()["cases"]}
    assert indexed == {normalize(q) for q, _ in rows("train")}
    assert not indexed & held_out
    retrieved = retriever.search("Revenue from Mobile orders with cancelled status")
    assert any(d["id"] == "channels" for d in retrieved)
    assert len({d["intent"] for d in retrieved if d["kind"] == "example"}) == 3


def test_trained_classifier_and_abstention_are_measured(ai_workbench):
    evaluation = ai_workbench.ai.report["evaluation"]
    assert evaluation["test_count"] == 36
    assert evaluation["accuracy"] > 0.6
    assert evaluation["ood_count"] == 12
    assert not ai_workbench.ai.router.predict("Top 3 customers")["accepted"]
    assert not ai_workbench.ai.router.predict("Forecast revenue for 2027")["accepted"]
    accepted = ai_workbench.ai.router.predict("Who are our top five customers by net sales?")
    assert accepted["accepted"] and accepted["intent"] == "customers"


def test_saved_model_roundtrip_and_corrupt_artifact_retraining(tmp_path):
    first, metadata = train(tmp_path)
    second, loaded_metadata = load(tmp_path)
    assert first.predict("Compare revenue across regions") == second.predict(
        "Compare revenue across regions"
    )
    assert metadata["training_hash"] == loaded_metadata["training_hash"]
    (tmp_path / "intent.joblib").write_bytes(b"corrupt, never deserialize this")
    restored, _ = load(tmp_path)
    assert restored.predict("Compare revenue across regions")["intent"] == "regions"


def test_intent_backend_answers_new_wording_with_provenance(ai_workbench):
    plan = ai_workbench.plan(
        "Which five customer accounts are worth the most in sales?", backend="intent"
    )
    assert plan["ai_trace"]["intent"] == "customers"
    assert plan["ai_trace"]["accepted"]
    assert ai_workbench.execute(plan["id"])["row_count"] == 5


def test_intent_backend_abstains_on_filtered_requests(ai_workbench):
    with pytest.raises(QueryError, match="abstained"):
        ai_workbench.plan("Revenue for January only", backend="intent")


@pytest.mark.parametrize("backend", [[], {}, 0, "remote-unconfigured"])
def test_invalid_backend_is_a_request_error(ai_workbench, backend):
    with pytest.raises(QueryError, match="Choose local"):
        ai_workbench.plan("Total revenue", backend=backend)


def test_rag_prompt_uses_retrieved_examples_and_baseline_does_not():
    context = get_retriever().search("Monthly revenue")
    with_rag = messages("Monthly revenue", context, retrieval=True)
    without_rag = messages("Monthly revenue", context, retrieval=False)
    assert "RETRIEVED BUSINESS CONTEXT" in with_rag[0]["content"]
    assert "RETRIEVED BUSINESS CONTEXT" not in without_rag[0]["content"]
    assert "SCHEMA" in without_rag[0]["content"]


def test_local_model_structured_output_and_token_budget(tmp_path, monkeypatch):
    (tmp_path / "models").mkdir()
    from querylens.model_download import FILENAME

    (tmp_path / "models" / FILENAME).touch()
    captured = {}

    class FakeModel:
        def __init__(self, **kwargs):
            captured["options"] = kwargs

        def create_chat_completion(self, **kwargs):
            captured["request"] = kwargs
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "sql": "SELECT SUM(net_revenue) FROM orders",
                                    "explanation": "Revenue",
                                }
                            )
                        },
                    }
                ],
                "usage": {"completion_tokens": 12},
            }

    monkeypatch.setitem(sys.modules, "llama_cpp", SimpleNamespace(Llama=FakeModel))
    result = LocalLLM(tmp_path).generate("Total revenue", [])
    assert result["sql"].startswith("SELECT")
    assert result["trace"]["usage"]["completion_tokens"] == 12
    assert captured["options"]["n_gpu_layers"] == 0
    assert captured["request"]["max_tokens"] == 384
    assert captured["request"]["response_format"]["type"] == "json_object"


def test_invalid_generated_sql_is_repaired_once_and_still_reviewed(ai_workbench, monkeypatch):
    calls = []

    def draft(question, documents, retrieval=True, repair=None):
        calls.append(repair)
        sql = (
            "SELECT missing_column FROM orders"
            if not repair
            else "SELECT SUM(net_revenue) FROM orders"
        )
        return {
            "sql": sql,
            "explanation": "Revenue",
            "trace": {"backend": "local", "repaired": repair is not None},
        }

    monkeypatch.setattr(ai_workbench.ai.llm, "generate", draft)
    plan = ai_workbench.plan("What was our net revenue?", backend="local")
    assert len(calls) == 2
    assert [a["valid"] for a in plan["ai_trace"]["attempts"]] == [False, True]
    assert plan["ai_trace"]["repaired"] is True
    result = ai_workbench.execute(plan["id"])
    assert abs(result["rows"][0][0] - 810152.78) < 0.02


def test_unsafe_model_output_cannot_execute(ai_workbench, monkeypatch):
    monkeypatch.setattr(
        ai_workbench.ai.llm,
        "generate",
        lambda *a, **kw: {
            "sql": "DROP TABLE orders",
            "explanation": "Invalid",
            "trace": {"backend": "local"},
        },
    )
    with pytest.raises(QueryError, match="SELECT"):
        ai_workbench.plan("Drop orders", backend="local", repair=False)


def test_execution_comparison_ignores_aliases_but_detects_wrong_values():
    actual = {"columns": ["different_alias"], "rows": [[10.0]], "truncated": False}
    expected = {"columns": ["net_revenue"], "rows": [[10.0]], "truncated": False}
    assert same_result(actual, expected)
    expected["rows"] = [[20.0]]
    assert not same_result(actual, expected)
    assert wilson(0, 12)[0] == 0
    assert wilson(12, 12)[1] == 1


def test_baseline_benchmark_saves_full_predictions(ai_workbench):
    report = run(ai_workbench, include_local=False)
    assert [v["name"] for v in report["variants"]] == ["exact_examples", "trained_intent"]
    assert report["answerable_count"] == 12
    assert report["repair_enabled"] is False
    assert all(len(v["predictions"]) == 12 for v in report["variants"])
    assert (ai_workbench.data_dir / "reports" / "ai-evaluation.json").exists()
    assert ai_workbench.ai.status()["generation_evaluation"]["answerable_count"] == 12


def test_data_card_does_not_claim_real_user_traffic():
    assert "synthetic" in corpus()["provenance"].lower()
