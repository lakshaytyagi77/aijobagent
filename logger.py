"""Google Sheets Application Logger"""
import json
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

TRACKER_FILE = "tracker.json"

HEADERS = [
    "Date Applied", "Company", "Job Title", "Location", "JD Summary",
    "Fit Score", "Resume Version", "Application Status", "Notes",
    "Interview Date", "Interview Prep Done",
]

# RGB floats for row background colours
STATUS_COLORS = {
    "applied":   {"red": 0.56, "green": 0.93, "blue": 0.56},  # green
    "interview": {"red": 1.00, "green": 0.95, "blue": 0.40},  # yellow
    "rejected":  {"red": 1.00, "green": 0.40, "blue": 0.40},  # red
    "offer":     {"red": 0.53, "green": 0.81, "blue": 0.98},  # blue
    "failed":    {"red": 0.90, "green": 0.90, "blue": 0.90},  # grey
}


# ─── Sheet connection ─────────────────────────────────────────────────────────

def get_sheet():
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
            "Download it from Google Cloud Console → IAM → Service Accounts."
        )

    creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)
    gc = gspread.authorize(creds)

    sheet_id = os.getenv("GOOGLE_SHEETS_ID")
    if not sheet_id:
        raise EnvironmentError("Set GOOGLE_SHEETS_ID in .env")

    spreadsheet = gc.open_by_key(sheet_id)
    try:
        return spreadsheet.worksheet("Applications")
    except Exception:
        sheet = spreadsheet.add_worksheet(title="Applications", rows=1000, cols=len(HEADERS) + 2)
        return sheet


def ensure_headers(sheet):
    existing = sheet.row_values(1)
    if existing == HEADERS:
        return
    sheet.insert_row(HEADERS, 1)
    sheet.format(
        f"A1:{chr(ord('A') + len(HEADERS) - 1)}1",
        {
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
            "backgroundColor": {"red": 0.18, "green": 0.18, "blue": 0.18},
        },
    )


# ─── Logging ──────────────────────────────────────────────────────────────────

def log_application(job_id: str, data: dict):
    sheet = get_sheet()
    ensure_headers(sheet)

    row = [
        (data.get("applied_at") or datetime.now().isoformat())[:10],
        data.get("company", ""),
        data.get("title", ""),
        data.get("location", ""),
        (data.get("jd_summary") or "")[:200],
        str(data.get("fit_score", "")),
        "v1",
        data.get("status", "applied"),
        "",   # Notes
        "",   # Interview Date
        "No", # Prep Done
    ]
    sheet.append_row(row, value_input_option="USER_ENTERED")

    status = data.get("status", "applied").lower()
    color = STATUS_COLORS.get(status, STATUS_COLORS["applied"])
    last = len(sheet.get_all_values())
    sheet.format(
        f"A{last}:{chr(ord('A') + len(HEADERS) - 1)}{last}",
        {"backgroundColor": color},
    )
    print(f"  [+] Logged: {data.get('title')} @ {data.get('company')}")


def update_status(company: str, new_status: str, interview_date: str = ""):
    """Call this manually to update a row after an interview is scheduled."""
    sheet = get_sheet()
    records = sheet.get_all_records()
    for i, row in enumerate(records, start=2):
        if company.lower() in row.get("Company", "").lower():
            sheet.update_cell(i, HEADERS.index("Application Status") + 1, new_status)
            if interview_date:
                sheet.update_cell(i, HEADERS.index("Interview Date") + 1, interview_date)
            color = STATUS_COLORS.get(new_status.lower(), STATUS_COLORS["applied"])
            sheet.format(
                f"A{i}:{chr(ord('A') + len(HEADERS) - 1)}{i}",
                {"backgroundColor": color},
            )
            print(f"  [+] Updated {company} → {new_status}")
            return
    print(f"  [!] Company '{company}' not found in sheet")


def sync_tracker_to_sheets():
    """Push all tracker.json entries that aren't yet in Sheets."""
    if not os.path.exists(TRACKER_FILE):
        print("[!] tracker.json not found")
        return

    with open(TRACKER_FILE) as f:
        tracker = json.load(f)

    sheet = get_sheet()
    ensure_headers(sheet)

    try:
        existing_keys = set()
        for row in sheet.get_all_records():
            key = f"{row.get('Company','')}|{row.get('Job Title','')}"
            existing_keys.add(key)
    except Exception:
        existing_keys = set()

    count = 0
    for job_id, data in tracker.items():
        key = f"{data.get('company','')}|{data.get('title','')}"
        if key in existing_keys:
            continue
        try:
            log_application(job_id, data)
            count += 1
        except Exception as e:
            print(f"  [!] Log error for {job_id}: {e}")

    print(f"\n[+] Synced {count} new entries to Google Sheets")


if __name__ == "__main__":
    sync_tracker_to_sheets()
