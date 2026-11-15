"""Install a project-local Windows Ollama runtime from its official release."""
import os
from pathlib import Path
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "data" / "ollama"


def main():
    if os.name != "nt":
        raise SystemExit("Install Ollama from https://ollama.com/download on your platform.")
    executable = RUNTIME / "ollama.exe"
    if not executable.exists():
        RUNTIME.mkdir(parents=True, exist_ok=True)
        archive = RUNTIME / "runtime.zip"
        print("Downloading official Ollama Windows runtime. This may take several minutes.", flush=True)
        urllib.request.urlretrieve("https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.zip", archive)
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                target = (RUNTIME / member.filename).resolve()
                if not target.is_relative_to(RUNTIME.resolve()):
                    raise RuntimeError("Invalid archive path")
            bundle.extractall(RUNTIME)
        archive.unlink()
    print(f"Runtime ready: {executable}", flush=True)
    print("Start it with: .venv\\Scripts\\python.exe scripts/serve_ai.py", flush=True)


if __name__ == "__main__":
    main()
