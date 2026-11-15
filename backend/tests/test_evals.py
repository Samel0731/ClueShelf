from collections import Counter

import pytest

from clueshelf import ai, evals
from clueshelf.evals import classification, retrieval
from clueshelf.evals.metrics import classification_metrics, percentile, retrieval_metrics


def test_golden_set_is_balanced_and_self_consistent():
    saves, queries = evals.load("saves.jsonl"), evals.load("queries.jsonl")
    ids = [save["id"] for save in saves]
    assert len(ids) == len(set(ids)) == 60
    assert Counter(save["platform"] for save in saves) == {"youtube": 20, "instagram": 20, "threads": 20}
    assert all(save["topics"] and set(save["topics"]) <= ai.TOPICS for save in saves)
    assert {topic for save in saves for topic in save["topics"]} == ai.TOPICS
    assert len(queries) == 20
    assert all(query["relevant"] and set(query["relevant"]) <= set(ids) for query in queries)


def test_classification_metrics_count_failures_as_wrong():
    rows = [
        {"expected": ["餐廳", "旅遊"], "predicted": ["餐廳"]},
        {"expected": ["食譜"], "predicted": ["其他"]},
        {"expected": ["音樂"], "predicted": None},
        {"expected": ["程式"], "predicted": ["程式"]},
    ]
    result = classification_metrics(rows)
    assert result["primary_accuracy"] == 0.5
    assert result["exact_match"] == 0.25
    assert result["failed"] == 1 and result["failure_rate"] == 0.25
    assert result["per_topic"]["餐廳"] == {"precision": 1.0, "recall": 1.0, "f1": 1.0, "support": 1}
    assert result["per_topic"]["其他"]["precision"] == 0.0
    assert result["per_topic"]["音樂"]["recall"] == 0.0
    assert result["micro"]["precision"] == pytest.approx(2 / 3)
    assert result["micro"]["recall"] == pytest.approx(2 / 5)


def test_retrieval_metrics_and_percentile():
    rows = [
        {"relevant": ["a", "b"], "ranked": ["x", "a", "y", "z", "w", "b"]},
        {"relevant": ["c"], "ranked": ["x", "y", "z", "w", "v", "c"]},
        {"relevant": ["d"], "ranked": []},
    ]
    result = retrieval_metrics(rows, k=5)
    assert result["hit@5"] == pytest.approx(1 / 3)
    assert result["recall@5"] == pytest.approx(0.5 / 3)
    assert result["mrr"] == pytest.approx((1 / 2 + 1 / 6) / 3)
    assert percentile([], 0.5) is None
    assert percentile([3, 1, 2, 4], 0.5) == 2
    assert percentile([3, 1, 2, 4], 0.95) == 4


def test_classification_runner_passes_model_and_records_failures():
    seen = []

    def fake(title, text, comments, *, model=None):
        seen.append((model, [comment.source_id for comment in comments]))
        if "失敗" in text:
            raise ai.AIUnavailable("down")
        return ai.Analysis(suggested_title="x", summary="", topics=["餐廳"], tags=["拉麵"])

    saves = [
        {"id": "a", "platform": "threads", "author_text": "拉麵", "comments": [{"source_id": "r1", "text": "推", "likes": 1}], "topics": ["餐廳"]},
        {"id": "b", "platform": "youtube", "author_text": "失敗", "topics": ["音樂"]},
    ]
    report = classification.run(saves, model="candidate", analyze=fake)
    assert seen == [("candidate", ["r1"]), ("candidate", [])]
    assert report["model"] == "candidate" and report["prompt_version"] == ai.PROMPT_VERSION
    assert report["metrics"]["primary_accuracy"] == 0.5 and report["metrics"]["failed"] == 1
    assert report["rows"][1]["predicted"] is None
    assert report["latency_seconds"]["successful_calls"] == 1


def test_keyword_retrieval_over_golden_set_without_models(tmp_path, monkeypatch):
    monkeypatch.setattr(retrieval.embeddings, "is_available", lambda: False)
    report = retrieval.run(evals.load("saves.jsonl"), evals.load("queries.jsonl"), tmp_path)
    assert report["semantic_skipped"] and list(report["modes"]) == ["keyword"]
    ranks = {query["id"]: query["first_relevant_rank"]["keyword"] for query in report["queries"]}
    assert ranks["q01"] == 1 and ranks["q02"] == 1
    assert ranks["q03"] == 1  # A spaceless sentence falls back to partial matching.
    assert ranks["q04"] is None  # 燒肉 vs 焼肉: cross-script needs semantic search.
