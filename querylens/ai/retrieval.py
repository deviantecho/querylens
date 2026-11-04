"""TF-IDF cosine retrieval over schema, rules, and training examples only."""

import hashlib
import json
from functools import lru_cache
from importlib.resources import files

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

from querylens.catalog import EXAMPLES, RULES, SCHEMA


def corpus():
    return json.loads(
        files("querylens.ai").joinpath("data", "intents.json").read_text(encoding="utf-8")
    )


def training_hash():
    train = {label: records["train"] for label, records in corpus()["intents"].items()}
    return hashlib.sha256(json.dumps(train, sort_keys=True).encode()).hexdigest()


class Retriever:
    def __init__(self):
        self.documents = [{**r, "kind": "rule"} for r in RULES]
        self.documents.extend(
            {
                "id": "schema-" + name,
                "title": name + " schema",
                "text": json.dumps(spec),
                "kind": "schema",
            }
            for name, spec in SCHEMA.items()
        )
        examples = {e["id"]: e for e in EXAMPLES}
        for label, records in corpus()["intents"].items():
            for index, question in enumerate(records["train"]):
                self.documents.append(
                    {
                        "id": f"train-{label}-{index}",
                        "title": question,
                        "text": question,
                        "sql": examples[label]["sql"],
                        "intent": label,
                        "kind": "example",
                    }
                )
        self.vectorizer = TfidfVectorizer(
            ngram_range=(1, 2), sublinear_tf=True, stop_words="english"
        )
        self.matrix = self.vectorizer.fit_transform(
            d["title"] + " " + d["text"] for d in self.documents
        )

    def search(self, question, rules=3, examples=3):
        scores = linear_kernel(self.vectorizer.transform([question]), self.matrix).ravel()
        ranked = sorted(range(len(scores)), key=lambda i: (-scores[i], self.documents[i]["id"]))
        selected = [i for i in ranked if self.documents[i]["kind"] == "rule"][:rules]
        # The complete small schema is always available, even for an empty or novel query.
        selected += [i for i, d in enumerate(self.documents) if d["kind"] == "schema"]
        seen = set()
        for i in ranked:
            doc = self.documents[i]
            if doc["kind"] == "example" and doc["intent"] not in seen:
                selected.append(i)
                seen.add(doc["intent"])
                if len(seen) == examples:
                    break
        return [{**self.documents[i], "score": round(float(scores[i]), 4)} for i in selected]


@lru_cache(maxsize=1)
def get_retriever():
    return Retriever()
