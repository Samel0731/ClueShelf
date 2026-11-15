import math

import numpy as np
import pytest

from clueshelf import embeddings


def test_pooling_ignores_padding_and_normalizes():
    hidden = np.array([[[3.0, 0.0], [0.0, 4.0], [100.0, 100.0]]])
    attention = np.array([[1, 1, 0]])
    result = embeddings.mean_pool(hidden, attention)
    assert result[0].tolist() == pytest.approx([0.6, 0.8])


def test_missing_model_is_offline_error(tmp_path, monkeypatch):
    monkeypatch.setattr(embeddings, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(embeddings, "_runtime", None)
    assert not embeddings.is_available()
    with pytest.raises(embeddings.EmbeddingUnavailable, match="尚未安裝"):
        embeddings.embed(["冷凍備餐料理"], "query")


def test_empty_batch_needs_no_model():
    assert embeddings.embed([], "passage") == []


def test_prefixes_batch_limit_and_normalized_dimensions(monkeypatch):
    calls = []

    class Encoding:
        ids = [0, 1]
        attention_mask = [1, 1]
        type_ids = [0, 0]

    class Tokenizer:
        def encode_batch(self, texts):
            calls.append(texts)
            return [Encoding() for _ in texts]

    class Input:
        def __init__(self, name):
            self.name = name

    class Session:
        def get_inputs(self):
            return [Input("input_ids"), Input("attention_mask")]

        def run(self, _, inputs):
            return [np.ones((len(inputs["input_ids"]), 2, 384), dtype=np.float32)]

    monkeypatch.setattr(embeddings, "_runtime", (Session(), Tokenizer()))
    result = embeddings.embed(["日本語"] * 10, "query")
    assert [len(batch) for batch in calls] == [8, 2]
    assert all(text == "query: 日本語" for batch in calls for text in batch)
    assert len(result) == 10 and len(result[0]) == 384
    assert math.sqrt(sum(x*x for x in result[0])) == pytest.approx(1.0)


def test_invalid_kind_is_rejected():
    with pytest.raises(ValueError):
        embeddings.embed(["text"], "other")


@pytest.mark.skipif(not embeddings.is_available(), reason="local E5 model is not installed")
def test_real_chinese_query_ranks_japanese_recipe_first():
    query = embeddings.embed(["冷凍備餐料理"], "query")[0]
    passages = embeddings.embed([
        "忙しい平日のための冷凍作り置きレシピ。豆腐と豚肉を使って簡単に調理します。",
        "札幌で行われた歌手のライブ演奏。人気の曲を歌います。",
        "PythonでLLMのサーバーを構築する方法。",
    ], "passage")
    scores = [sum(a*b for a, b in zip(query, passage)) for passage in passages]
    assert scores[0] > max(scores[1:])
