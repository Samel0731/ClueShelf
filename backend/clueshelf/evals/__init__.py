"""Offline quality evaluation over a fixed golden set. Never touches the user's own database."""
import json
from pathlib import Path

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"


def load(name, directory=None):
    path = Path(directory or GOLDEN_DIR) / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
