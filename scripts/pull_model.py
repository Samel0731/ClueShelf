"""Download the configured model through the local Ollama server."""
import json
import httpx

if __name__ == "__main__":
    progress = {}
    with httpx.Client(timeout=httpx.Timeout(900, connect=3), trust_env=False) as client:
        with client.stream("POST", "http://127.0.0.1:11434/api/pull", json={"model": "qwen3:4b", "stream": True}) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                item = json.loads(line)
                if item.get("error"):
                    raise SystemExit(item["error"])
                if item.get("total"):
                    percent = int(item.get("completed", 0) * 10 / item["total"]) * 10
                    key = item.get("digest", "")
                    if progress.get(key) != percent:
                        progress[key] = percent
                        print(f"Model layer {percent}%", flush=True)
                else:
                    print(item.get("status", ""), flush=True)
