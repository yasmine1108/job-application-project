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

class FieldFillLog(BaseModel):
    job_url: str
    candidate_id: str
    page: str  # "personal_info" | "cv" | "cover_letter" | "experience" | "education" | "additional_questions"
    field: str  # e.g. "first_name", "phone_country_code", "start_month"
    value: str | None = None
    status: str  # "filled" | "skipped" | "already_present" | "warning" | "error"
    note: str | None = None  # e.g. exception message, or why it was skipped
    logged_at: datetime = Field(default_factory=lambda: datetime.now(pytz.UTC))
 
 
def load_field_fill_logs(output_path: str | Path, candidate_id: str | None = None) -> list[FieldFillLog]:
    output_path = Path(output_path)
    if not output_path.exists():
        return []
    try:
        with output_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        return []
 
    logs = [FieldFillLog.model_validate(r) for r in data.get("field_fills", [])]
    if candidate_id is not None:
        logs = [l for l in logs if l.candidate_id == candidate_id]
    return logs
 
 
def save_field_fill_log(output_path: str | Path, log: FieldFillLog) -> None:
    """Append a single field-fill entry, preserving every existing entry.
    Same read-append-rewrite pattern as save_application_log -- called once
    per field, which is cheap given a form page has at most a handful of
    fields, and keeps the log durable even if the run crashes mid-page."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
 
    existing: list[FieldFillLog] = []
    if output_path.exists():
        try:
            with output_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            existing = [FieldFillLog.model_validate(r) for r in data.get("field_fills", [])]
        except json.JSONDecodeError:
            pass
 
    existing.append(log)
 
    payload = {"field_fills": [l.model_dump(mode="json") for l in existing]}
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4, ensure_ascii=False)
