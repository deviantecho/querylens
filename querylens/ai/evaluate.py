"""Execution-based local generation evaluation with explicit baseline ablations."""

import json
import math
import time
from datetime import datetime, timezone
from importlib.resources import files

from querylens.errors import QueryError


def benchmark():
    return json.loads(
        files("querylens.ai").joinpath("data", "sql_benchmark.json").read_text(encoding="utf-8")
    )


def same_result(actual, expected, ordered=False):
    if (
        actual["truncated"]
        or expected["truncated"]
        or len(actual["columns"]) != len(expected["columns"])
    ):
        return False
    left, right = actual["rows"], expected["rows"]
    if len(left) != len(right):
        return False
    if not ordered:
        left, right = sorted(left, key=str), sorted(right, key=str)
    for a, b in zip(left, right, strict=True):
        for x, y in zip(a, b, strict=True):
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                if not math.isclose(x, y, rel_tol=1e-6, abs_tol=0.02):
                    return False
            elif x != y:
                return False
    return True


def wilson(successes, total):
    if not total:
        return [0, 0]
    z, p = 1.96, successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [round(max(0, center - half), 4), round(min(1, center + half), 4)]


def run(workbench, include_local=True, limit=None):
    dataset = benchmark()
    cases = dataset["cases"][:limit] if limit else dataset["cases"]
    variants = [("exact_examples", "examples", False), ("trained_intent", "intent", False)]
    if include_local:
        variants += [("local_no_retrieval", "local", False), ("local_retrieval", "local", True)]
    references = {
        case["id"]: workbench._run(workbench.planner.compile(case["sql"]).executable_sql)
        for case in cases
    }
    report = {
        "created": datetime.now(timezone.utc).isoformat(),
        "provenance": dataset["provenance"],
        "model_version": workbench.planner.registry.fingerprint,
        "classifier_training_hash": workbench.ai.report["training_hash"],
        "repair_enabled": False,
        "model_file": workbench.ai.llm.path.name if include_local else None,
        "answerable_count": len(cases),
        "variants": [],
    }
    for name, backend, retrieval in variants:
        predictions = []
        for case in cases:
            start = time.perf_counter()
            record = {
                "id": case["id"],
                "question": case["question"],
                "correct": False,
                "valid_sql": False,
                "executed": False,
            }
            try:
                plan = workbench.plan(
                    case["question"], backend=backend, retrieval=retrieval, repair=False
                )
                record.update(sql=plan["sql"], valid_sql=True, trace=plan["ai_trace"])
                result = workbench._run(plan["planned_sql"])
                record.update(
                    executed=True,
                    result=result,
                    correct=same_result(result, references[case["id"]], case["ordered"]),
                )
            except QueryError as error:
                record["error"] = str(error)
            record["latency_ms"] = round((time.perf_counter() - start) * 1000, 2)
            predictions.append(record)
            print(
                f"{name}: {case['id']}: {'correct' if record['correct'] else 'incorrect/abstained'} ({record['latency_ms'] / 1000:.1f}s)",
                flush=True,
            )
        refusal_predictions = []
        for case in dataset["refusal_cases"]:
            try:
                plan = workbench.plan(
                    case["question"], backend=backend, retrieval=retrieval, repair=False
                )
                refusal_predictions.append({"id": case["id"], "refused": False, "sql": plan["sql"]})
            except QueryError as error:
                refusal_predictions.append(
                    {"id": case["id"], "refused": True, "reason": str(error)}
                )
        correct = sum(r["correct"] for r in predictions)
        variant = {
            "name": name,
            "count": len(predictions),
            "correct": correct,
            "execution_accuracy": round(correct / len(predictions), 4),
            "accuracy_95pct_wilson": wilson(correct, len(predictions)),
            "sql_validity_rate": round(
                sum(r["valid_sql"] for r in predictions) / len(predictions), 4
            ),
            "mean_latency_ms": round(
                sum(r["latency_ms"] for r in predictions) / len(predictions), 2
            ),
            "refusals": refusal_predictions,
            "predictions": predictions,
        }
        report["variants"].append(variant)
    output = workbench.data_dir / "reports"
    output.mkdir(exist_ok=True)
    (output / "ai-evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
