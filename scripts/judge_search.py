"""Judge search quality on your real collection without knowing the answers in advance.

    python scripts/judge_search.py make     # run every query in all modes, write a sheet to tick
    python scripts/judge_search.py score    # after ticking, compare the modes

`make` reads data/golden/queries.txt (one question per line) and your database (read-only), pools
the top results of keyword, semantic and hybrid search, and writes data/golden/judgments.md.
Change `[ ]` to `[x]` on every result that really answers the question, then run `score`.
Results never shown in the sheet count as not relevant, so recall is unknown; the comparison
between modes is still fair because all three were pooled.
"""
import argparse
import json
from pathlib import Path
import re
import sys
import time

from clueshelf import embeddings
from clueshelf.database import database_url, make_engine, session_factory
from clueshelf.evals.metrics import percentile
from clueshelf.models import Save
from clueshelf.search import search
from clueshelf.service import OWNER

ROOT = Path(__file__).resolve().parents[1]
MODES = ("keyword", "semantic", "hybrid")
LINE = re.compile(r"^- \[( |x|X)\] `([^`]+)`")


def make(args):
    queries = [line.strip() for line in (args.dir / "queries.txt").read_text(encoding="utf-8").splitlines() if line.strip()]
    sheet = args.dir / "judgments.md"
    if sheet.exists() and "[x]" in sheet.read_text(encoding="utf-8").lower():
        print(f"{sheet} already has ticks; refusing to overwrite. Move it first.", file=sys.stderr)
        return 1
    if not embeddings.is_available():
        print("Embedding model missing; run scripts/setup_search.py.", file=sys.stderr)
        return 2
    engine = make_engine(database_url())
    meta = {"k": args.k, "queries": [], "latency_ms": {mode: [] for mode in MODES}}
    lines = ["# Search judgments", "", "Tick `[x]` for every result that really answers the question. Leave the rest.", ""]
    with session_factory(engine)() as session:
        meta["saves"] = session.query(Save).filter(Save.owner_id == OWNER, Save.duplicate_of.is_(None)).count()
        for number, query in enumerate(queries, start=1):
            rankings, snippets = {}, {}
            for mode in MODES:
                started = time.perf_counter()
                vector = embeddings.embed([query], "query")[0] if mode != "keyword" else None
                results = search(session, OWNER, query, mode=mode, limit=args.k, query_vector=vector)
                meta["latency_ms"][mode].append((time.perf_counter() - started) * 1000)
                rankings[mode] = [item["save_id"] for item in results]
                for item in results:
                    snippets.setdefault(item["save_id"], item["match_text"])
            meta["queries"].append({"id": f"q{number:02d}", "query": query, "rankings": rankings})
            lines += [f"## q{number:02d} {query}", ""]
            pooled = list(dict.fromkeys(save_id for mode in MODES for save_id in rankings[mode]))
            for save_id in pooled:
                save = session.get(Save, save_id)
                title = (save.title or save.author_text)[:70].replace("\n", " ")
                snippet = snippets[save_id][:90].replace("\n", " ")
                lines.append(f"- [ ] `{save_id}` {save.platform} | {title} | {snippet}")
            if not pooled:
                lines.append("(no results in any mode)")
            lines.append("")
        session.rollback()
    engine.dispose()
    sheet.write_text("\n".join(lines), encoding="utf-8")
    (args.dir / "judgments-meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {sheet} ({len(queries)} queries). Tick the relevant results, then run: python scripts/judge_search.py score")
    return 0


def score(args):
    meta = json.loads((args.dir / "judgments-meta.json").read_text(encoding="utf-8"))
    relevant, current = {}, None
    for line in (args.dir / "judgments.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            current = line.split()[1]
            relevant[current] = set()
        elif (match := LINE.match(line)) and match.group(1) != " ":
            relevant[current].add(match.group(2))
    k = meta["k"]
    answerable = [query for query in meta["queries"] if relevant.get(query["id"])]
    out = [f"# Search on the real collection", "", f"{meta['saves']} saves, {len(meta['queries'])} questions, {len(answerable)} with at least one result judged relevant. Pooled top-{k} judgments; unjudged results count as not relevant.", "", f"| Mode | Hit@{k} | Precision@{k} | MRR | p50 ms | p95 ms |", "|---|---|---|---|---|---|"]
    total = len(meta["queries"])
    for mode in MODES:
        hits = precision = reciprocal = 0.0
        for query in meta["queries"]:
            wanted, ranked = relevant.get(query["id"], set()), query["rankings"][mode]
            hits += any(item in wanted for item in ranked)
            precision += sum(item in wanted for item in ranked) / k
            first = next((rank for rank, item in enumerate(ranked, start=1) if item in wanted), None)
            reciprocal += 1 / first if first else 0.0
        latency = meta["latency_ms"][mode]
        out.append(f"| {mode} | {hits / total:.1%} | {precision / total:.1%} | {reciprocal / total:.3f} | {percentile(latency, 0.5):.0f} | {percentile(latency, 0.95):.0f} |")
    missing = [f"- {query['id']} {query['query']}" for query in meta["queries"] if not relevant.get(query["id"])]
    if missing:
        out += ["", "No relevant result in any mode:", "", *missing]
    report = "\n".join(out) + "\n"
    target = ROOT / "reports/local"
    target.mkdir(parents=True, exist_ok=True)
    (target / "eval-search-real.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("make", "score"))
    parser.add_argument("--dir", type=Path, default=ROOT / "data/golden")
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    return make(args) if args.command == "make" else score(args)


if __name__ == "__main__":
    sys.exit(main())
