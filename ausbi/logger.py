"""Registro append-only local (JSONL). Rastreabilidade de turnos e custo (O9)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class TurnLogger:
    def __init__(self, runtime_dir: str, log_file: str):
        self.path = Path(runtime_dir) / log_file
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, record: dict) -> None:
        record = {"ts": datetime.now(timezone.utc).isoformat(), **record}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
