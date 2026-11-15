"""Probe only the three user-supplied public links; do not write application data."""
import json
import sys

from clueshelf.extraction import extract

SOURCES = {
    "youtube": "https://www.youtube.com/watch?v=hHBnlKxEAxo",
    "instagram": "https://www.instagram.com/reel/De6RyzOBGKB/",
    "threads": "https://www.threads.com/share/BqxzBtGVUK/",
}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    report = []
    for platform, url in SOURCES.items():
        result = extract(platform, url)
        report.append({"platform": platform, "url": url, "status": result.status, "title": result.original_title, "author_chars": len(result.author_text), "comments": len(result.comments), "comments_ranking": result.comments_ranking, "fetched_count": result.fetched_count, "reason": result.reason, "canonical_url": result.canonical_url})
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
