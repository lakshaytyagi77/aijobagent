"""Google Sheets Application Logger"""
import json
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

TRACKER_FILE = "tracker.json"
JOBS_RAW_FILE = "jobs_raw.json"
TAILORED_DIR = Path("tailored")

# Two tabs: one for all scraped jobs (review), one for applied jobs (tracker)
SCRAPED_HEADERS = [
    "Date Scraped", "Company", "Job Title", "Location", "Easy Apply",
    "Fit Score", "JD Summary", "Apply URL",
    "Cover Letter Ready", "Review Status", "Notes",
]

APPLIED_HEADERS = [
    "Date Applied", "Company", "Job Title", "Location", "Fit Score",
    "Easy Apply", "Application Status", "Notes",
    "Interview Date", "Interview Prep Done",
]

STATUS_COLORS = {
    "applied":          {"red": 0.56, "green": 0.93, "blue": 0.56},   # green
    "interview":        {"red": 1.00, "green": 0.95, "blue": 0.40},   # yellow
    "rejected":         {"red": 1.00, "green": 0.40, "blue": 0.40},   # red
    "offer":            {"red": 0.53, "green": 0.81, "blue": 0.98},   # blue
    "failed":           {"red": 0.90, "green": 0.90, "blue": 0.90},   # grey
    "pending review":   {"red": 1.00, "green": 1.00, "blue": 1.00},   # white
    "approved":         {"red": 0.85, "green": 0.96, "blue": 0.85},   # light green
    "skip":             {"red": 0.95, "green": 0.95, "blue": 0.95},   # light grey
}


# ─── Sheet connection ──────────────────────────────────────────────────────────

def _connect():
    try:
        import gspread
        from oauth2client.service_account import ServiceAccountCredentials
    except ImportError:
        raise ImportError("Run: pip install gspread oauth2client")

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "service_account.json")
    if not os.path.exists(creds_path):
        raise FileNotFoundError(
            f"Service account JSON not found at '{creds_path}'. "
            "Download from Google Cloud Console → IAM → Service Accounts."
        )
    creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)
    gc = gspread.authorize(creds)

    sheet_id = os.getenv("GOOGLE_SHEETS_ID")
    if not sheet_id:
        raise EnvironmentError("Set GOOGLE_SHEETS_ID in .env")

    return gc.open_by_key(sheet_id)


def _get_or_create_tab(spreadsheet, title: str, headers: list):
    try:
        sheet = spreadsheet.worksheet(title)
    except Exception:
        sheet = spreadsheet.add_worksheet(title=title, rows=2000, cols=len(headers) + 2)

    existing = sheet.row_values(1)
    if existing != headers:
        sheet.clear()
        sheet.insert_row(headers, 1)
        col_end = chr(ord("A") + len(headers) - 1)
        sheet.format(
            f"A1:{col_end}1",
            {
                "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                "backgroundColor": {"red": 0.13, "green": 0.13, "blue": 0.13},
            },
        )
    return sheet


def _color_row(sheet, row_idx: int, col_count: int, status: str):
    color = STATUS_COLORS.get(status.lower(), STATUS_COLORS["pending review"])
    col_end = chr(ord("A") + col_count - 1)
    sheet.format(f"A{row_idx}:{col_end}{row_idx}", {"backgroundColor": color})


def _existing_keys(sheet) -> set:
    try:
        return {
            f"{r.get('Company','')}|{r.get('Job Title','')}"
            for r in sheet.get_all_records()
        }
    except Exception:
        return set()


# ─── Scraped jobs → "Job Pipeline" tab ────────────────────────────────────────

def sync_scraped_to_sheets():
    """Push all jobs from jobs_raw.json + tailored/ into the 'Job Pipeline' tab."""
    spreadsheet = _connect()
    sheet = _get_or_create_tab(spreadsheet, "Job Pipeline", SCRAPED_HEADERS)
    existing = _existing_keys(sheet)

    # Merge jobs_raw with tailored data (tailored has cover letter + fit score)
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

    count = 0
    for job in raw_jobs:
        company = job.get("company", "")
        title = job.get("title", "")
        key = f"{company}|{title}"

        if key in existing:
            continue

        tailored = tailored_map.get(key, {})
        fit_score = tailored.get("fit_score") or job.get("fit_score", "")
        cover_ready = "Yes" if tailored else "No"
        status = job.get("status", "pending review")
        if status in ("skipped_low_score",):
            status = "skip"

        row = [
            (job.get("date_scraped") or datetime.now().isoformat())[:10],
            company,
            title,
            job.get("location", ""),
            "Yes" if job.get("easy_apply") else "No",
            str(fit_score) if fit_score != "" else "",
            (job.get("jd_text") or "")[:250],
            job.get("apply_url", ""),
            cover_ready,
            status if status not in ("new",) else "pending review",
            "",  # Notes — user fills this
        ]
        sheet.append_row(row, value_input_option="USER_ENTERED")
        last = len(sheet.get_all_values())
        _color_row(sheet, last, len(SCRAPED_HEADERS), status)
        existing.add(key)
        count += 1
        print(f"  [+] {title} @ {company}  (score={fit_score})")

    print(f"\n[+] Added {count} jobs to 'Job Pipeline' tab")


# ─── Applied jobs → "Applications" tab ────────────────────────────────────────

def sync_tracker_to_sheets():
    """Push applied jobs from tracker.json into the 'Applications' tab."""
    if not os.path.exists(TRACKER_FILE):
        print("[!] tracker.json not found — no applications recorded yet")
        return

    with open(TRACKER_FILE) as f:
        tracker = json.load(f)

    if not tracker:
        print("[!] tracker.json is empty — apply some jobs first")
        return

    spreadsheet = _connect()
    sheet = _get_or_create_tab(spreadsheet, "Applications", APPLIED_HEADERS)
    existing = _existing_keys(sheet)

    count = 0
    for job_id, data in tracker.items():
        key = f"{data.get('company','')}|{data.get('title','')}"
        if key in existing:
            continue
        try:
            row = [
                (data.get("applied_at") or datetime.now().isoformat())[:10],
                data.get("company", ""),
                data.get("title", ""),
                data.get("location", ""),
                str(data.get("fit_score", "")),
                "Yes" if data.get("easy_apply") else "No",
                data.get("status", "applied"),
                "",   # Notes
                "",   # Interview Date
                "No", # Prep Done
            ]
            sheet.append_row(row, value_input_option="USER_ENTERED")
            last = len(sheet.get_all_values())
            _color_row(sheet, last, len(APPLIED_HEADERS), data.get("status", "applied"))
            existing.add(key)
            count += 1
            print(f"  [+] {data.get('title')} @ {data.get('company')}")
        except Exception as e:
            print(f"  [!] Error logging {job_id}: {e}")

    print(f"\n[+] Synced {count} applications to 'Applications' tab")


def log_application(job_id: str, data: dict):
    """Log a single application immediately after it's submitted."""
    spreadsheet = _connect()
    sheet = _get_or_create_tab(spreadsheet, "Applications", APPLIED_HEADERS)
    row = [
        (data.get("applied_at") or datetime.now().isoformat())[:10],
        data.get("company", ""),
        data.get("title", ""),
        data.get("location", ""),
        str(data.get("fit_score", "")),
        "Yes" if data.get("easy_apply") else "No",
        data.get("status", "applied"),
        "",
        "",
        "No",
    ]
    sheet.append_row(row, value_input_option="USER_ENTERED")
    last = len(sheet.get_all_values())
    _color_row(sheet, last, len(APPLIED_HEADERS), data.get("status", "applied"))
    print(f"  [+] Logged: {data.get('title')} @ {data.get('company')}")


def update_status(company: str, new_status: str, interview_date: str = ""):
    """Manually update a row status in the Applications tab."""
    spreadsheet = _connect()
    sheet = _get_or_create_tab(spreadsheet, "Applications", APPLIED_HEADERS)
    records = sheet.get_all_records()
    for i, row in enumerate(records, start=2):
        if company.lower() in row.get("Company", "").lower():
            sheet.update_cell(i, APPLIED_HEADERS.index("Application Status") + 1, new_status)
            if interview_date:
                sheet.update_cell(i, APPLIED_HEADERS.index("Interview Date") + 1, interview_date)
            _color_row(sheet, i, len(APPLIED_HEADERS), new_status)
            print(f"  [+] Updated {company} → {new_status}")
            return
    print(f"  [!] '{company}' not found in Applications tab")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--applied":
        sync_tracker_to_sheets()
    else:
        sync_scraped_to_sheets()
        sync_tracker_to_sheets()
