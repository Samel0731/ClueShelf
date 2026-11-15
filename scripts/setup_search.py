"""Download official pinned multilingual E5 ONNX files for local CPU search."""
from pathlib import Path
import json

from clueshelf.embeddings import MODEL_DIR, MODEL_NAME, MODEL_REVISION, embed

ROOT = Path(__file__).resolve().parents[1]


def main():
    from huggingface_hub import snapshot_download
    print(f"Downloading {MODEL_NAME} for CPU semantic search.", flush=True)
    snapshot_download(repo_id=MODEL_NAME, revision=MODEL_REVISION, allow_patterns=["onnx/model.onnx", "tokenizer.json", "config.json"], local_dir=MODEL_DIR, cache_dir=ROOT / "data/huggingface-cache", max_workers=2)
    embed(["繁體中文與日本語的本地搜尋"], "query")
    (MODEL_DIR / "model-source.json").write_text(json.dumps({"model": MODEL_NAME, "revision": MODEL_REVISION, "dimensions": 384, "runtime": "onnxruntime CPU"}, indent=2), encoding="utf-8")
    print(f"Model ready in {MODEL_DIR}", flush=True)


if __name__ == "__main__":
    main()
