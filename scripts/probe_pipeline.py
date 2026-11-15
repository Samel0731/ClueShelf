"""Run the three user-approved sample collections through the live local API."""
import json
from pathlib import Path
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
IDS = {"hHBnlKxEAxo", "De6RyzOBGKB", "De9rEnPEhuQ", "share:BqxzBtGVUK"}


def main():
    with httpx.Client(base_url="http://127.0.0.1:8000/api/v1", timeout=10, trust_env=False) as client:
        deadline = time.monotonic() + 300
        while True:
            try:
                tags = httpx.get("http://127.0.0.1:11434/api/tags", timeout=3, trust_env=False).json()
                if any(item["name"] == "qwen3:4b" for item in tags.get("models", [])):
                    break
            except (httpx.HTTPError, ValueError):
                pass
            if time.monotonic() >= deadline:
                raise SystemExit("Qwen3 model is not ready; run scripts/pull_model.py first.")
            time.sleep(2)
        saves = [item for item in client.get("/saves").json() if item["content_id"] in IDS and not item["duplicate_of"]]
        if len(saves) != 3:
            raise SystemExit("Add the three sample links in the UI before running this probe.")
        report = []
        for item in saves:
            url = f"/saves/{item['id']}"
            response = client.post(url + "/analyze", json={"version": item["version"]})
            response.raise_for_status()
            deadline = time.monotonic() + 210
            while True:
                current = client.get(url).json()
                if current["status"] not in {"queued", "processing"}:
                    break
                if time.monotonic() >= deadline:
                    raise SystemExit("Live processing did not finish within the probe deadline.")
                time.sleep(1)
            report.append({"platform": current["platform"], "url": current["url"], "extraction_status": current["extraction_status"], "ai_status": current["ai_status"], "author_chars": len(current["author_text"]), "comments": len((current["source"] or {}).get("comments", [])), "display_title": current["title"], "analysis": current["analysis"], "ai_error": current["ai_error"]})
            print(f"{current['platform']}: {current['ai_status']}", flush=True)
        output = ROOT / "outputs/phase-two-validation.json"
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if any(item["ai_status"] != "complete" for item in report):
            raise SystemExit(f"Some model results unavailable; inspect {output}")
        print(f"Saved live validation: {output}", flush=True)


if __name__ == "__main__":
    main()
