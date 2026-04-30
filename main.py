"""LinkedIn HR Job Application Agent — Orchestrator"""
import argparse
import asyncio
import json
import logging
import os
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

LOG_FILE = "run_log.txt"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ─── Email summary ────────────────────────────────────────────────────────────

def send_summary(stats: dict):
    sender = os.getenv("GMAIL_USER")
    password = os.getenv("GMAIL_APP_PASSWORD")
    recipient = os.getenv("SUMMARY_EMAIL_TO") or sender
    if not sender or not password:
        log.warning("GMAIL_USER / GMAIL_APP_PASSWORD not set — skipping summary email")
        return

    body = (
        f"LinkedIn Job Bot — Daily Summary\n"
        f"{'─' * 40}\n"
        f"Date         : {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"Scraped      : {stats.get('scraped', 0)}\n"
        f"Qualified    : {stats.get('qualified', 0)}\n"
        f"Applied      : {stats.get('applied', 0)}\n"
        f"Failed       : {stats.get('failed', 0)}\n"
        f"Skipped      : {stats.get('skipped', 0)}\n"
        f"{'─' * 40}\n"
        f"Full details in tracker.json and Google Sheets.\n"
    )

    msg = MIMEText(body)
    msg["Subject"] = (
        f"[JobBot] {stats.get('applied', 0)} applied — "
        f"{datetime.now().strftime('%b %d')}"
    )
    msg["From"] = sender
    msg["To"] = recipient

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
            srv.login(sender, password)
            srv.sendmail(sender, recipient, msg.as_string())
        log.info(f"Summary email sent to {recipient}")
    except Exception as e:
        log.error(f"Email failed: {e}")


# ─── Pipeline ─────────────────────────────────────────────────────────────────

def divider(label: str):
    log.info("─" * 50)
    log.info(f"  {label}")
    log.info("─" * 50)


async def run_pipeline(skip_scrape: bool = False, skip_apply: bool = False) -> dict:
    stats: dict = {}

    # Phase 1 — Scrape
    if not skip_scrape:
        divider("PHASE 1 — Scrape")
        from scraper import run_scraper
        jobs = await run_scraper()
        stats["scraped"] = len(jobs)
        log.info(f"Scraped {len(jobs)} jobs")
    else:
        log.info("Skipping scrape — using existing jobs_raw.json")
        try:
            with open("jobs_raw.json") as f:
                stats["scraped"] = len(json.load(f))
        except FileNotFoundError:
            stats["scraped"] = 0

    # Phase 2 — AI Tailor
    divider("PHASE 2 — AI Tailor")
    from ai_tailor import tailor_all_jobs
    qualified = tailor_all_jobs()
    stats["qualified"] = len(qualified)
    log.info(f"Tailored {len(qualified)} qualified jobs")

    # Phase 3 — Push scraped jobs to Google Sheets for review
    divider("PHASE 3 — Sync Jobs to Google Sheets (Job Pipeline tab)")
    try:
        from logger import sync_scraped_to_sheets
        sync_scraped_to_sheets()
    except Exception as e:
        log.error(f"Sheets job sync failed: {e}")

    # Phase 4 — Apply
    if not skip_apply:
        divider("PHASE 4 — Apply")
        from applier import run_applier
        apply_stats = await run_applier()
        stats.update(apply_stats)

        # Phase 5 — Log applied jobs
        divider("PHASE 5 — Sync Applications to Google Sheets")
        try:
            from logger import sync_tracker_to_sheets
            sync_tracker_to_sheets()
        except Exception as e:
            log.error(f"Sheets applied sync failed: {e}")
    else:
        log.info("Skipping apply phase — review jobs in the 'Job Pipeline' tab in Google Sheets")

    divider("DONE")
    log.info(json.dumps(stats, indent=2))
    send_summary(stats)
    return stats


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="LinkedIn HR Job Application Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                          Full pipeline (scrape → tailor → apply → log)
  python main.py --scrape-only            Scrape + tailor only, don't apply yet
  python main.py --apply-only             Skip scrape, tailor + apply existing jobs_raw.json
  python main.py --prep "Infosys"         Generate interview prep for Infosys
  python main.py --prep "Tata Consultancy Services"
  python main.py --log                    Sync tracker.json to Google Sheets only
        """,
    )
    parser.add_argument(
        "--scrape-only",
        action="store_true",
        help="Scrape & tailor; do not apply",
    )
    parser.add_argument(
        "--apply-only",
        action="store_true",
        help="Skip scrape; tailor & apply from existing jobs_raw.json",
    )
    parser.add_argument(
        "--prep",
        metavar="COMPANY",
        help="Generate interview prep for the named company",
    )
    parser.add_argument(
        "--log",
        action="store_true",
        help="Sync tracker.json to Google Sheets and exit",
    )

    args = parser.parse_args()

    if args.prep:
        from prep_coach import generate_prep
        path = generate_prep(args.prep)
        print(f"\nSaved: {path}")
        return

    if args.log:
        from logger import sync_scraped_to_sheets, sync_tracker_to_sheets
        sync_scraped_to_sheets()
        sync_tracker_to_sheets()
        return

    asyncio.run(
        run_pipeline(
            skip_scrape=args.apply_only,
            skip_apply=args.scrape_only,
        )
    )


if __name__ == "__main__":
    main()
