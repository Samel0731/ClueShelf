"""Repeatable phase-one checks. Uses only temporary databases for backend tests."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def main():
    env = {**os.environ, "NEXT_TELEMETRY_DISABLED": "1"}
    subprocess.run([str(PYTHON), "-m", "pytest", "backend/tests", "-q", "--basetemp=work/pytest"], cwd=ROOT, env=env, check=True)
    subprocess.run(["node", "node_modules/typescript/bin/tsc", "--noEmit"], cwd=ROOT / "frontend", env=env, check=True)
    subprocess.run(["node", "node_modules/next/dist/bin/next", "build"], cwd=ROOT / "frontend", env=env, check=True)


if __name__ == "__main__":
    main()
