"""
Application logging.

Every auto_apply attempt -- dry-run or real -- gets logged here. Logs are
append-only (unlike MatchResult, which replaces per job_url): a job can be
attempted more than once, and you want the full history, not just the
latest attempt, especially while dry_run testing is ongoing.
"""

import json
from datetime import datetime
from pathlib import Path

import pytz
from pydantic import BaseModel, Field


class ApplicationLog(BaseModel):
    job_url: str
    candidate_id: str
    dry_run: bool
    submitted: bool
    payload: dict
    cover_letter_source: str | None = None  # "generated" | "manual" | "none"
    applied_at: datetime = Field(default_factory=lambda: datetime.now(pytz.UTC))


def load_application_logs(output_path: str | Path, candidate_id: str | None = None) -> list[ApplicationLog]:
    output_path = Path(output_path)
    if not output_path.exists():
        return []
    try:
        with output_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        return []

    logs = [ApplicationLog.model_validate(r) for r in data.get("applications", [])]
    if candidate_id is not None:
        logs = [l for l in logs if l.candidate_id == candidate_id]
    return logs


def save_application_log(output_path: str | Path, log: ApplicationLog) -> None:
    """Append a single log entry, preserving every existing entry (all candidates)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    existing: list[ApplicationLog] = []
    if output_path.exists():
        try:
            with output_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            existing = [ApplicationLog.model_validate(r) for r in data.get("applications", [])]
        except json.JSONDecodeError:
            pass

    existing.append(log)

    payload = {"applications": [l.model_dump(mode="json") for l in existing]}
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4, ensure_ascii=False)