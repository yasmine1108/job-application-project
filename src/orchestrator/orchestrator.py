"""
Orchestrator -- runs in its own minimal venv (json + subprocess only, no
langchain, no playwright). Drives the AI-env and scraper-env subprocesses
by calling each venv's own python interpreter directly, passing JSON via
stdin/stdout. This is the piece your future agent loop calls.

Set these to the actual venv paths on your machine / server.
"""

import json
import subprocess
import sys
from pathlib import Path

AI_VENV_PYTHON = Path("/path/to/ai-venv/bin/python")
SCRAPER_VENV_PYTHON = Path("/path/to/scraper-venv/bin/python")

REPO_ROOT = Path("/path/to/your/repo")  # so `-m src.ai_env.generate_letter_cli` resolves


def _run_in_venv(python_path: Path, module: str, payload: dict) -> dict:
    proc = subprocess.run(
        [str(python_path), "-m", module],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"{module} failed (exit {proc.returncode}).\n"
            f"stderr:\n{proc.stderr}\nstdout:\n{proc.stdout}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{module} did not return valid JSON.\nstdout was:\n{proc.stdout}") from e


def generate_cover_letter_via_subprocess(
    candidate: dict,
    match_result: dict,
    job_offer: dict,
    company: str,
    job_description: str | None,
    min_score: float = 0.5,
) -> str | None:
    result = _run_in_venv(
        AI_VENV_PYTHON,
        "src.ai_env.generate_letter_cli",
        {
            "candidate": candidate,
            "match_result": match_result,
            "job_offer": job_offer,
            "company": company,
            "job_description": job_description,
            "min_score": min_score,
        },
    )
    return result["cover_letter"]


def auto_apply_via_subprocess(
    job_url: str,
    candidate: dict,
    candidate_id: str,
    cv_path: str,
    cover_letter: str | None,
    applications_log_path: str,
    dry_run: bool = True,
) -> dict:
    return _run_in_venv(
        SCRAPER_VENV_PYTHON,
        "src.scraper_env.apply_cli",
        {
            "job_url": job_url,
            "candidate": candidate,
            "candidate_id": candidate_id,
            "cv_path": cv_path,
            "cover_letter": cover_letter,
            "applications_log_path": applications_log_path,
            "dry_run": dry_run,
        },
    )


def apply_to_job(
    job_url: str,
    candidate: dict,
    candidate_id: str,
    match_result: dict,
    job_offer: dict,
    company: str,
    job_description: str | None,
    cv_path: str,
    applications_log_path: str,
    dry_run: bool = True,
) -> dict:
    """The single call an agent/GUI would invoke per job. Sequences both envs."""
    cover_letter = generate_cover_letter_via_subprocess(
        candidate=candidate,
        match_result=match_result,
        job_offer=job_offer,
        company=company,
        job_description=job_description,
    )
    return auto_apply_via_subprocess(
        job_url=job_url,
        candidate=candidate,
        candidate_id=candidate_id,
        cv_path=cv_path,
        cover_letter=cover_letter,
        applications_log_path=applications_log_path,
        dry_run=dry_run,
    )


if __name__ == "__main__":
    # example manual invocation
    with open(sys.argv[1]) as f:
        args = json.load(f)
    print(json.dumps(apply_to_job(**args), indent=2))
