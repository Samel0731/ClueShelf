"""Sample real saves into a private golden set for you to label. Reads the database; never writes to it.

    python scripts/export_golden.py                 # 20 per platform into data/golden (untracked)

Then open data/golden/saves.jsonl and, for each line:
  1. fix "topics" so the first entry is the main topic (the pre-filled value is the model's own
     answer, so leaving it unchanged only measures the model against itself);
  2. set "reviewed" to true. Unreviewed lines are skipped by `scripts/eval.py classify`.
Add your own search questions to data/golden/queries.jsonl, one per line:
  {"id": "q01", "query": "大阪燒肉", "relevant": ["<save id>", ...], "kind": "real"}
"""
import argparse
import json
from pathlib import Path
import random
import sys

from sqlalchemy import select

from clueshelf.database import database_url, make_engine, session_factory
from clueshelf.models import Save
from clueshelf.search import effective_topics
from clueshelf.service import OWNER
from clueshelf.taxonomy_models import Taxon

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--per-platform", type=int, default=20)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=ROOT / "data/golden")
    args = parser.parse_args()
    target = args.out / "saves.jsonl"
    if target.exists():
        print(f"{target} already exists; refusing to overwrite your labels. Move it or pass another --out.", file=sys.stderr)
        return 1
    engine = make_engine(database_url())
    chooser = random.Random(args.seed)
    lines = []
    with session_factory(engine)() as session:
        catalog = [{"name": item.name, "description": item.description} for item in session.scalars(select(Taxon).where(Taxon.owner_id == OWNER, Taxon.kind == "topic", Taxon.archived.is_(False), Taxon.merged_into.is_(None)).order_by(Taxon.name))]
        for platform in ("youtube", "instagram", "threads"):
            candidates = [save for save in session.scalars(select(Save).where(Save.owner_id == OWNER, Save.platform == platform, Save.duplicate_of.is_(None)).order_by(Save.id)) if save.author_text.strip()]
            picked = chooser.sample(candidates, min(args.per_platform, len(candidates)))
            print(f"{platform}: {len(picked)} of {len(candidates)} saves with text")
            for save in picked:
                source = save.source or {}
                comments = source.get("comments", []) if platform == "threads" else []
                lines.append({"id": save.id, "platform": platform, "original_title": source.get("original_title", save.title), "author_text": save.author_text, "comments": comments, "topics": effective_topics(save), "places": [], "reviewed": False})
    engine.dispose()
    args.out.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines), encoding="utf-8")
    (args.out / "topics.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    queries = args.out / "queries.jsonl"
    if not queries.exists():
        queries.write_text("", encoding="utf-8")
    print(f"Wrote {len(lines)} saves to {target}. Label them, then run:\n  python scripts/eval.py classify --golden {args.out} --out reports/local")
    return 0


if __name__ == "__main__":
    sys.exit(main())
