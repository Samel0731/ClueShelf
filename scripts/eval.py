"""Score search and classification against the golden set and write JSON + Markdown reports.

    python scripts/eval.py search --gate 0.8          # CPU only; used as the CI quality gate
    python scripts/eval.py classify --models qwen3:4b,gemma3:4b   # needs a running Ollama

Use --golden to point at a private set (same file names) and --out reports/local to keep it untracked.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile

import httpx

from clueshelf import ai, evals
from clueshelf.evals import classification, retrieval

ROOT = Path(__file__).resolve().parents[1]


def percent(value):
    return f"{value * 100:.1f}%"


def search_markdown(report):
    lines = ["# Search evaluation", "", f"{report['saves']} golden saves, {len(report['queries'])} queries, k={report['k']}. Source text only; no AI summary or tags are indexed.", ""]
    if report["semantic_skipped"]:
        lines += ["Embedding model not installed: semantic and hybrid modes were skipped.", ""]
    else:
        lines += [f"Embedding model: `{report['embedding_model']}` @ `{report['embedding_revision'][:8]}` (ONNX, CPU).", ""]
    k = report["k"]
    lines += [f"| Mode | Hit@{k} | Recall@{k} | MRR | p50 ms | p95 ms |", "|---|---|---|---|---|---|"]
    for mode, values in report["modes"].items():
        lines.append(f"| {mode} | {percent(values[f'hit@{k}'])} | {percent(values[f'recall@{k}'])} | {values['mrr']:.3f} | {values['latency_ms_p50']} | {values['latency_ms_p95']} |")
    modes = list(report["modes"])
    lines += ["", "Rank of the first relevant save per query (– = not returned):", "", "| Query | Kind | " + " | ".join(modes) + " |", "|---|---|" + "---|" * len(modes)]
    for query in report["queries"]:
        lines.append(f"| {query['query']} | {query['kind']} | " + " | ".join(str(query["first_relevant_rank"][mode] or "–") for mode in modes) + " |")
    return "\n".join(lines) + "\n"


def classify_markdown(reports):
    lines = ["# Classification evaluation", "", f"Prompt `{reports[0]['prompt_version']}`, {reports[0]['metrics']['total']} golden saves. Primary accuracy = the expected main topic is among the predicted topics. Failed calls count as wrong.", "", "| Model | Primary acc. | Exact set | Micro F1 | Failures | p50 s | p95 s |", "|---|---|---|---|---|---|---|"]
    for report in reports:
        metrics, latency = report["metrics"], report["latency_seconds"]
        timing = [f"{latency[key]:.2f}" if latency[key] is not None else "–" for key in ("p50", "p95")]
        lines.append(f"| {report['model']} | {percent(metrics['primary_accuracy'])} | {percent(metrics['exact_match'])} | {metrics['micro']['f1']:.3f} | {metrics['failed']}/{metrics['total']} | {timing[0]} | {timing[1]} |")
    for report in reports:
        lines += ["", f"## {report['model']}", "", "| Topic | Precision | Recall | F1 | Support |", "|---|---|---|---|---|"]
        for topic, values in report["metrics"]["per_topic"].items():
            lines.append(f"| {topic} | {percent(values['precision'])} | {percent(values['recall'])} | {values['f1']:.3f} | {values['support']} |")
        misses = [row for row in report["rows"] if row["predicted"] is None or row["expected"][0] not in row["predicted"]]
        if misses:
            lines += ["", "Missed primary topic:", ""]
            lines += [f"- `{row['id']}` expected {row['expected']}, got {row['predicted'] if row['predicted'] is not None else 'call failed'}" for row in misses]
    return "\n".join(lines) + "\n"


def write(out, name, data, markdown):
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / f"{name}.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"Wrote {out / name}.json and .md", flush=True)


def run_search(args):
    saves, queries = evals.load("saves.jsonl", args.golden), evals.load("queries.jsonl", args.golden)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as workdir:
        report = retrieval.run(saves, queries, workdir)
    write(args.out, "eval-search", report, search_markdown(report))
    if args.gate is not None:
        if report["semantic_skipped"]:
            print("Gate needs the embedding model; run scripts/setup_search.py first.", file=sys.stderr)
            return 2
        score = report["modes"]["hybrid"][f"hit@{report['k']}"]
        if score < args.gate:
            print(f"FAILED gate: hybrid hit@{report['k']} {score:.3f} < {args.gate}", file=sys.stderr)
            return 1
        print(f"Passed gate: hybrid hit@{report['k']} {score:.3f} >= {args.gate}")
    return 0


def run_classify(args):
    models = [name.strip() for name in args.models.split(",") if name.strip()]
    try:
        installed = {item["name"] for item in httpx.get("http://127.0.0.1:11434/api/tags", timeout=3, trust_env=False).json().get("models", [])}
    except (httpx.HTTPError, ValueError):
        print("Ollama is not reachable on 127.0.0.1:11434. Start it (scripts/dev.py or scripts/serve_ai.py) and retry.", file=sys.stderr)
        return 2
    missing = [name for name in models if name not in installed]
    if missing:
        print(f"Models not pulled in Ollama: {', '.join(missing)}", file=sys.stderr)
        return 2
    saves = evals.load("saves.jsonl", args.golden)
    reports = []
    for name in models:
        print(f"Classifying {len(saves)} saves with {name}...", flush=True)
        reports.append(classification.run(saves, model=name))
    write(args.out, "eval-classify", reports, classify_markdown(reports))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("suite", choices=("search", "classify"))
    parser.add_argument("--golden", type=Path, default=None, help="directory with saves.jsonl and queries.jsonl")
    parser.add_argument("--out", type=Path, default=ROOT / "reports")
    parser.add_argument("--gate", type=float, default=None, help="search: fail when hybrid hit@5 is below this")
    parser.add_argument("--models", default=ai.MODEL, help="classify: comma-separated Ollama model names")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    return run_search(args) if args.suite == "search" else run_classify(args)


if __name__ == "__main__":
    sys.exit(main())
