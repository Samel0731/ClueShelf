"""Start the local application and stop its children together."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from migrate import upgrade

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def main():
    for port in (3000, 8000):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                raise SystemExit(f"Port {port} is in use. Stop its owner before starting ClueShelf.")
    if not PYTHON.exists() or not (ROOT / "frontend/node_modules/next").exists():
        raise SystemExit("Install backend and frontend dependencies first. See README.md.")
    upgrade()
    node = shutil.which("node")
    if node is None:
        raise SystemExit("Node.js is required.")
    commands = [
        [str(PYTHON), "-m", "uvicorn", "clueshelf.api:app", "--host", "127.0.0.1", "--port", "8000", "--no-access-log"],
        [str(PYTHON), "-m", "clueshelf.worker", "--lane", "io"],
        [str(PYTHON), "-m", "clueshelf.worker", "--lane", "ai"],
        [str(PYTHON), "-m", "clueshelf.youtube_sync", "worker"],
        [str(PYTHON), "-m", "clueshelf.video_worker"],
        [str(PYTHON), "-m", "clueshelf.indexer"],
        [node, "frontend/node_modules/next/dist/bin/next", "dev", "frontend", "--hostname", "127.0.0.1", "--port", "3000"],
    ]
    if (ROOT / "data/ollama/ollama.exe").exists():
        with socket.socket() as sock:
            sock.settimeout(1)
            if sock.connect_ex(("127.0.0.1", 11434)) != 0:
                commands.insert(0, [str(PYTHON), "scripts/serve_ai.py"])
    children = []
    try:
        for command in commands:
            children.append(subprocess.Popen(command, cwd=ROOT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
        print("ClueShelf: http://127.0.0.1:3000 | API: http://127.0.0.1:8000/docs", flush=True)
        while True:
            for child in children:
                code = child.poll()
                if code is not None:
                    raise SystemExit(f"A ClueShelf service stopped with code {code}.")
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for child in reversed(children):
            if child.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    child.terminate()
                child.wait(timeout=10)


if __name__ == "__main__":
    main()
