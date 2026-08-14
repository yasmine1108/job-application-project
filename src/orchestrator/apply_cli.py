"""
Entry point for the scraper environment (playwright). Runs as a subprocess
launched with the scraper venv's python interpreter.

Deliberately imports NOTHING from src.models / src.matcher / src.models_job --
plain dict access only, so this environment never needs the AI stack's
pydantic version (or langchain, or anything else from that venv).

Contract: reads one JSON object from stdin, writes one JSON object to stdout.

Usage (from the orchestrator, in a different venv):
    /path/to/scraper-venv/bin/python -m src.scraper_env.apply_cli < input.json > output.json
"""

import json
import sys

from playwright.sync_api import sync_playwright

from src.scraper_env.application_log import ApplicationLog, save_application_log


def auto_apply(page, job_url: str, candidate: dict, cv_path: str, cover_letter: str, dry_run: bool) -> dict:
    print(f"Attempting to auto-apply for job: {job_url}")
    page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
    apply_button = page.get_by_role("button", name="Postuler maintenant")
    apply_button.wait_for(state="visible", timeout=10000)
    apply_button.click()

    fullname_field = page.get_by_role("textbox", name="name")
    email_field = page.get_by_role("textbox", name="email")
    phone_field = page.get_by_role("textbox", name="phone")
    file_input = page.query_selector('input[type="file"]')
    cover_letter_field = page.get_by_role("textbox", name="comments")

    personal = candidate["personal_information"]
    if fullname_field.input_value().strip() == "":
        fullname_field.fill(personal["full_name"])
    if email_field.input_value().strip() == "":
        email_field.fill(personal["email"])
    if phone_field.input_value().strip() == "":
        phone_field.fill(personal["phone"])
    file_input.set_input_files(cv_path)
    cover_letter_field.fill(cover_letter or "")

    payload = {
        "job_url": job_url,
        "name": fullname_field.input_value(),
        "email": email_field.input_value(),
        "phone": phone_field.input_value(),
        "cv_path": cv_path,
        "cover_letter": cover_letter,
    }

    submit_button = page.get_by_role("button", name="Envoyer la candidature")
    submit_button.wait_for(state="visible", timeout=10000)

    if dry_run:
        print(f"[DRY RUN] Not submitting. Payload for {job_url}:\n{payload}")
        submitted = False
    else:
        submit_button.click()
        page.wait_for_load_state("networkidle")
        submitted = True

    return {"payload": payload, "submitted": submitted}


def main() -> None:
    raw_input = json.load(sys.stdin)

    job_url = raw_input["job_url"]
    candidate = raw_input["candidate"]  # plain dict, not CandidateProfile
    cv_path = raw_input["cv_path"]
    cover_letter = raw_input.get("cover_letter")
    dry_run = raw_input.get("dry_run", True)
    candidate_id = raw_input["candidate_id"]
    applications_log_path = raw_input["applications_log_path"]

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        result = auto_apply(page, job_url, candidate, cv_path, cover_letter, dry_run)
        browser.close()

    log = ApplicationLog(
        job_url=job_url,
        candidate_id=candidate_id,
        dry_run=dry_run,
        submitted=result["submitted"],
        payload=result["payload"],
    )
    save_application_log(applications_log_path, log)

    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
