"""Pure metric functions; no model or database access."""
import math


def percentile(values, fraction):
    """Nearest-rank percentile; None for an empty sample."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def _prf(tp, fp, fn):
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1, "support": tp + fn}


def classification_metrics(rows):
    """rows: {"expected": [primary, ...], "predicted": [...] | None}. None means the model call failed.

    A failed call counts as wrong everywhere, so a model cannot look better by failing on hard items.
    """
    total = len(rows)
    failed = sum(row["predicted"] is None for row in rows)
    primary = sum(row["predicted"] is not None and row["expected"][0] in row["predicted"] for row in rows)
    exact = sum(row["predicted"] is not None and set(row["expected"]) == set(row["predicted"]) for row in rows)
    labels = sorted({label for row in rows for label in [*row["expected"], *(row["predicted"] or [])]})
    counts = {label: [0, 0, 0] for label in labels}
    for row in rows:
        expected, predicted = set(row["expected"]), set(row["predicted"] or [])
        for label in expected & predicted:
            counts[label][0] += 1
        for label in predicted - expected:
            counts[label][1] += 1
        for label in expected - predicted:
            counts[label][2] += 1
    micro = [sum(value[index] for value in counts.values()) for index in range(3)]
    return {
        "total": total,
        "failed": failed,
        "failure_rate": failed / total if total else 0.0,
        "primary_accuracy": primary / total if total else 0.0,
        "exact_match": exact / total if total else 0.0,
        "micro": _prf(*micro),
        "per_topic": {label: _prf(*value) for label, value in counts.items()},
    }


def retrieval_metrics(rows, k=5):
    """rows: {"relevant": [ids], "ranked": [ids in rank order]}."""
    total = len(rows)
    hits = recall = reciprocal = 0.0
    for row in rows:
        relevant = set(row["relevant"])
        top = row["ranked"][:k]
        hits += any(item in relevant for item in top)
        recall += len(relevant.intersection(top)) / len(relevant)
        first = next((rank for rank, item in enumerate(row["ranked"], start=1) if item in relevant), None)
        reciprocal += 1 / first if first else 0.0
    return {"queries": total, f"hit@{k}": hits / total if total else 0.0, f"recall@{k}": recall / total if total else 0.0, "mrr": reciprocal / total if total else 0.0}
