"""
Orchestrator -- runs in the LangGraph env. Its only cross-env dependency is
shelling out to the worker venv (everything else: SeleniumBase/Playwright,
google-genai, groq, langchain-core, pydantic models, matching, cover letter
generation, applying). One process boundary total.

A LangGraph node/tool that needs to "apply to a job" calls apply_to_job()
below -- it never imports Playwright or your provider SDKs directly.
"""

import json
import subprocess
from pathlib import Path

WORKER_VENV_PYTHON = Path("/path/to/worker-venv/bin/python")  # last_test_env, in your naming
REPO_ROOT = Path("/agent_project")  # adjust to your repo root if needed


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
    min_score: float = 0.5,
) -> dict:
    payload = {
        "job_url": job_url,
        "candidate": candidate,
        "candidate_id": candidate_id,
        "match_result": match_result,
        "job_offer": job_offer,
        "company": company,
        "job_description": job_description,
        "cv_path": cv_path,
        "applications_log_path": applications_log_path,
        "dry_run": dry_run,
        "min_score": min_score,
    }

    proc = subprocess.run(
        [str(WORKER_VENV_PYTHON), "-m", "src.worker_cli"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"worker_cli failed (exit {proc.returncode}).\nstderr:\n{proc.stderr}\nstdout:\n{proc.stdout}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"worker_cli did not return valid JSON.\nstdout was:\n{proc.stdout}") from e
