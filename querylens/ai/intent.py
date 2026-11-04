"""A calibrated, supervised NLP baseline for nine unfiltered report intents."""

import hashlib
import json
import re
import time
from pathlib import Path

import joblib
import sklearn
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import FeatureUnion, Pipeline

from querylens.ai.retrieval import corpus, training_hash


def scope_supported(question):
    text = question.lower()
    top = re.search(r"\btop\s+(\d+)\b", text)
    if top and int(top.group(1)) != 5:
        return False
    return not re.search(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december|quarter|q[1-4]|202[0-46-9]|forecast|predict|only|except|profit|tax|email|salary|salaries|delete|erase|drop)\b",
        text,
    )


def rows(split):
    return [(q, label) for label, spec in corpus()["intents"].items() for q in spec[split]]


def fit():
    data = rows("train")
    features = FeatureUnion(
        [
            ("word", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)),
            ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)),
        ],
        transformer_weights={"word": 1.0, "char": 0.5},
    )
    estimator = Pipeline(
        [
            ("features", features),
            ("classifier", LogisticRegression(C=6, max_iter=1000, random_state=42)),
        ]
    )
    model = CalibratedClassifierCV(
        estimator, method="sigmoid", cv=StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
    )
    model.fit([q for q, _ in data], [label for _, label in data])
    return model


def select_threshold(model):
    dev = rows("dev")
    questions = [q for q, _ in dev] + corpus()["dev_ood"]
    probabilities = model.predict_proba(questions)
    best = (0, 0.99, 0.0)
    for threshold in [i / 100 for i in range(25, 96, 5)]:
        for margin in [0.0, 0.1, 0.2]:
            correct = wrong = rejected_ood = 0
            for i, probability in enumerate(probabilities):
                ranked = sorted(probability, reverse=True)
                accepted = (
                    scope_supported(questions[i])
                    and ranked[0] >= threshold
                    and ranked[0] - ranked[1] >= margin
                )
                predicted = model.classes_[probability.argmax()]
                if i < len(dev):
                    correct += accepted and predicted == dev[i][1]
                    wrong += accepted and predicted != dev[i][1]
                else:
                    wrong += accepted
                    rejected_ood += not accepted
            precision = correct / (correct + wrong) if correct + wrong else 0
            if precision >= 0.95 and rejected_ood == len(corpus()["dev_ood"]):
                candidate = (correct, threshold, margin)
                if candidate[0] > best[0]:
                    best = candidate
    return {
        "probability": best[1],
        "margin": best[2],
        "selection": "Maximize accepted correct dev questions subject to >=95% selective precision and rejection of all dev OOD questions. Test split never tunes thresholds.",
    }


class IntentRouter:
    def __init__(self, model, threshold):
        self.model = model
        self.threshold = threshold

    def predict(self, question):
        probabilities = self.model.predict_proba([question])[0]
        ranked = probabilities.argsort()[::-1]
        p, second = float(probabilities[ranked[0]]), float(probabilities[ranked[1]])
        accepted = (
            scope_supported(question)
            and p >= self.threshold["probability"]
            and p - second >= self.threshold["margin"]
        )
        return {
            "intent": str(self.model.classes_[ranked[0]]),
            "probability": round(p, 4),
            "margin": round(p - second, 4),
            "accepted": bool(accepted),
            "threshold": self.threshold["probability"],
            "alternatives": [
                {
                    "intent": str(self.model.classes_[i]),
                    "probability": round(float(probabilities[i]), 4),
                }
                for i in ranked[:3]
            ],
        }


def evaluate(router):
    data = rows("test")
    labels = [label for _, label in data]
    predictions = [router.predict(q) for q, _ in data]
    predicted = [p["intent"] for p in predictions]
    accepted = [i for i, p in enumerate(predictions) if p["accepted"]]
    correct = sum(predicted[i] == labels[i] for i in accepted)
    ood = [router.predict(q) for q in corpus()["test_ood"]]
    return {
        "test_count": len(data),
        "accuracy": round(float(accuracy_score(labels, predicted)), 4),
        "macro_f1": round(float(f1_score(labels, predicted, average="macro")), 4),
        "coverage": round(len(accepted) / len(data), 4),
        "selective_accuracy": round(correct / len(accepted), 4) if accepted else None,
        "ood_count": len(ood),
        "ood_rejection_rate": round(sum(not p["accepted"] for p in ood) / len(ood), 4),
        "labels": list(router.model.classes_),
        "confusion_matrix": confusion_matrix(
            labels, predicted, labels=router.model.classes_
        ).tolist(),
        "per_class": classification_report(labels, predicted, output_dict=True, zero_division=0),
        "predictions": [
            {"question": q, "expected": label, **p}
            for (q, label), p in zip(data, predictions, strict=True)
        ],
        "ood_predictions": [
            {"question": q, **p} for q, p in zip(corpus()["test_ood"], ood, strict=True)
        ],
    }


def train(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    model = fit()
    threshold = select_threshold(model)
    router = IntentRouter(model, threshold)
    path = directory / "intent.joblib"
    joblib.dump({"model": model, "threshold": threshold}, path)
    manifest = {
        "training_hash": training_hash(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "sklearn_version": sklearn.__version__,
        "train_count": len(rows("train")),
        "dev_count": len(rows("dev")),
        "test_count": len(rows("test")),
        "threshold": threshold,
        "training_ms": round((time.perf_counter() - started) * 1000, 2),
        "evaluation": evaluate(router),
        "provenance": corpus()["provenance"],
    }
    (directory / "intent-report.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return router, manifest


def load(directory):
    directory = Path(directory)
    path = directory / "intent.joblib"
    report = directory / "intent-report.json"
    if path.exists() and report.exists():
        metadata = json.loads(report.read_text(encoding="utf-8"))
        if (
            metadata["training_hash"] == training_hash()
            and metadata["sklearn_version"] == sklearn.__version__
            and hashlib.sha256(path.read_bytes()).hexdigest() == metadata["sha256"]
        ):
            # This path is generated by this application, not uploaded model data.
            saved = joblib.load(path)
            return IntentRouter(saved["model"], saved["threshold"]), metadata
    return train(directory)
