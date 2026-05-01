"""Airtable Application Logger"""
import json
import os
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

TRACKER_FILE = "tracker.json"
JOBS_RAW_FILE = "jobs_raw.json"
TAILORED_DIR = Path("tailored")

AIRTABLE_PAT = os.getenv("AIRTABLE_PAT", "")
BASE_ID = os.getenv("AIRTABLE_BASE_ID", "")
PIPELINE_TABLE = "Job Pipeline"
APPLIED_TABLE = "Applications"


# ─── API helpers ──────────────────────────────────────────────────────────────

def _headers() -> dict:
    if not AIRTABLE_PAT:
        raise EnvironmentError("AIRTABLE_PAT not set in .env")
    return {
        "Authorization": f"Bearer {AIRTABLE_PAT}",
        "Content-Type": "application/json",
    }


def _url(table: str) -> str:
    return f"https://api.airtable.com/v0/{BASE_ID}/{requests.utils.quote(table)}"


def _existing_keys(table: str) -> set:
    """Return set of 'Company|Job Title' strings already in the table."""
    keys = set()
    offset = None
    while True:
        params = {"fields[]": ["Company", "Job Title"], "pageSize": 100}
        if offset:
            params["offset"] = offset
        r = requests.get(_url(table), headers=_headers(), params=params)
        if not r.ok:
            break
        data = r.json()
        for rec in data.get("records", []):
            f = rec.get("fields", {})
            keys.add(f"{f.get('Company','')}|{f.get('Job Title','')}")
        offset = data.get("offset")
        if not offset:
            break
    return keys


def _create_record(table: str, fields: dict) -> bool:
    r = requests.post(
        _url(table),
        headers=_headers(),
        json={"fields": fields},
    )
    if not r.ok:
        print(f"  [!] Airtable error: {r.status_code} {r.text[:200]}")
    return r.ok


def _update_record(table: str, record_id: str, fields: dict) -> bool:
    r = requests.patch(
        f"{_url(table)}/{record_id}",
        headers=_headers(),
        json={"fields": fields},
    )
    return r.ok


def _find_record_id(table: str, company: str) -> str | None:
    params = {
        "filterByFormula": f'SEARCH(LOWER("{company.lower()}"), LOWER({{Company}}))',
        "maxRecords": 1,
    }
    r = requests.get(_url(table), headers=_headers(), params=params)
    if r.ok:
        records = r.json().get("records", [])
        if records:
            return records[0]["id"]
    return None


# ─── Job Pipeline (all scraped jobs) ──────────────────────────────────────────

def sync_scraped_to_sheets():
    """Push all jobs from jobs_raw.json + tailored/ into Airtable Job Pipeline."""

    tailored_map: dict = {}
    if TAILORED_DIR.exists():
        for f in TAILORED_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                key = f"{data.get('company','')}|{data.get('title','')}"
                tailored_map[key] = data
            except Exception:
                pass

    raw_jobs: list = []
    if os.path.exists(JOBS_RAW_FILE):
        with open(JOBS_RAW_FILE) as f:
            raw_jobs = json.load(f)

    if not raw_jobs and not tailored_map:
        print("[!] No jobs found. Run the scraper first: python main.py --scrape-only")
        return

    existing = _existing_keys(PIPELINE_TABLE)
    count = 0

    for job in raw_jobs:
        company = job.get("company", "")
        title   = job.get("title", "")
        key     = f"{company}|{title}"

        if key in existing:
            continue

        tailored   = tailored_map.get(key, {})
        fit_score  = tailored.get("fit_score") or job.get("fit_score")
        cover_done = bool(tailored)
        status     = job.get("status", "new")
        review     = "Skip" if status == "skipped_low_score" else "Pending Review"

        fields = {
            "Date Scraped":       (job.get("date_scraped") or datetime.now().isoformat())[:10],
            "Company":            company,
            "Job Title":          title,
            "Location":           job.get("location", ""),
            "Easy Apply":         bool(job.get("easy_apply")),
            "JD Summary":         (job.get("jd_text") or "")[:500],
            "Apply URL":          job.get("apply_url", ""),
            "Cover Letter Ready": cover_done,
            "Review Status":      review,
        }
        if fit_score is not None:
            fields["Fit Score"] = int(fit_score)

        if _create_record(PIPELINE_TABLE, fields):
            existing.add(key)
            count += 1
            print(f"  [+] {title} @ {company}  (score={fit_score or 'N/A'})")

    print(f"\n[+] Added {count} jobs to Airtable → Job Pipeline")


# ─── Applications (applied jobs) ──────────────────────────────────────────────

def sync_tracker_to_sheets():
    """Push applied jobs from tracker.json into Airtable Applications."""
    if not os.path.exists(TRACKER_FILE):
        print("[!] tracker.json not found — no applications recorded yet")
        return

    with open(TRACKER_FILE) as f:
        tracker = json.load(f)

    if not tracker:
        print("[!] tracker.json is empty — no applications yet")
        return

    existing = _existing_keys(APPLIED_TABLE)
    count = 0

    for job_id, data in tracker.items():
        company = data.get("company", "")
        title   = data.get("title", "")
        key     = f"{company}|{title}"

        if key in existing:
            continue

        fields = {
            "Date Applied":        (data.get("applied_at") or datetime.now().isoformat())[:10],
            "Company":             company,
            "Job Title":           title,
            "Location":            data.get("location", ""),
            "Easy Apply":          bool(data.get("easy_apply")),
            "Application Status":  data.get("status", "Applied").capitalize(),
        }
        fit = data.get("fit_score")
        if fit is not None:
            fields["Fit Score"] = int(fit)

        if _create_record(APPLIED_TABLE, fields):
            existing.add(key)
            count += 1
            print(f"  [+] {title} @ {company}")

    print(f"\n[+] Synced {count} applications to Airtable → Applications")


def log_application(job_id: str, data: dict):
    """Log a single application immediately after submission."""
    fields = {
        "Date Applied":        (data.get("applied_at") or datetime.now().isoformat())[:10],
        "Company":             data.get("company", ""),
        "Job Title":           data.get("title", ""),
        "Location":            data.get("location", ""),
        "Easy Apply":          bool(data.get("easy_apply")),
        "Application Status":  data.get("status", "Applied").capitalize(),
    }
    fit = data.get("fit_score")
    if fit is not None:
        fields["Fit Score"] = int(fit)

    if _create_record(APPLIED_TABLE, fields):
        print(f"  [+] Logged: {data.get('title')} @ {data.get('company')}")


def update_status(company: str, new_status: str, interview_date: str = ""):
    """Update application status for a company in the Applications table."""
    record_id = _find_record_id(APPLIED_TABLE, company)
    if not record_id:
        print(f"  [!] '{company}' not found in Applications")
        return
    fields = {"Application Status": new_status.capitalize()}
    if interview_date:
        fields["Interview Date"] = interview_date
    if _update_record(APPLIED_TABLE, record_id, fields):
        print(f"  [+] Updated {company} → {new_status}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--applied":
        sync_tracker_to_sheets()
    else:
        sync_scraped_to_sheets()
        sync_tracker_to_sheets()
