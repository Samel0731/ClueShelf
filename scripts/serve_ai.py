"""Run the project-local Ollama server on loopback only."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    executable = ROOT / "data" / "ollama" / "ollama.exe"
    if not executable.exists():
        raise SystemExit("Run scripts/setup_ai.py first, or use an existing Ollama installation.")
    env = {**os.environ, "OLLAMA_HOST": "127.0.0.1:11434", "OLLAMA_MODELS": str(ROOT / "data" / "ollama-models"), "OLLAMA_CONTEXT_LENGTH": "8192", "OLLAMA_NO_CLOUD": "1"}
    try:
        subprocess.run([str(executable), "serve"], cwd=ROOT, env=env, check=True)
    except KeyboardInterrupt:
        pass
