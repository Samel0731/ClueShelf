"""Run the production classifier over the golden saves and score its topics."""
import time

from .. import ai
from ..extraction import Comment
from .metrics import classification_metrics, percentile


def run(saves, *, model=None, analyze=ai.analyze):
    """Uses the same prompt, schema and options as the worker; only the model name may differ."""
    rows, latencies = [], []
    for save in saves:
        comments = [Comment(source_id=item["source_id"], text=item["text"], likes=item.get("likes")) for item in save.get("comments", [])]
        started = time.perf_counter()
        try:
            result = analyze(save.get("original_title", ""), save["author_text"], comments, model=model)
            predicted, tags, error = list(result.topics), list(result.tags), None
        except ai.AIUnavailable as failure:
            predicted, tags, error = None, [], str(failure.__cause__ or failure)[:200]
        elapsed = time.perf_counter() - started
        if predicted is not None:
            latencies.append(elapsed)
        rows.append({"id": save["id"], "platform": save["platform"], "lang": save.get("lang"), "expected": save["topics"], "predicted": predicted, "tags": tags, "seconds": round(elapsed, 3), "error": error})
    return {
        "model": model or ai.MODEL,
        "prompt_version": ai.PROMPT_VERSION,
        "options": ai.OPTIONS,
        "metrics": classification_metrics(rows),
        "latency_seconds": {"p50": percentile(latencies, 0.5), "p95": percentile(latencies, 0.95), "successful_calls": len(latencies)},
        "rows": rows,
    }
