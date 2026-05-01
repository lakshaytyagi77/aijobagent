"""LinkedIn Application Automation Engine"""
import asyncio
import json
import os
import random
import re
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright, Page

load_dotenv()

TAILORED_DIR = Path("tailored")
TRACKER_FILE = "tracker.json"
SCREENSHOTS_DIR = Path("screenshots")
CONFIG_FILE = "config.json"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return json.load(f)


def load_tracker() -> dict:
    if os.path.exists(TRACKER_FILE):
        with open(TRACKER_FILE) as f:
            return json.load(f)
    return {}


def save_tracker(tracker: dict):
    with open(TRACKER_FILE, "w") as f:
        json.dump(tracker, f, indent=2)


def load_tailored_jobs() -> list:
    jobs = []
    for path in TAILORED_DIR.glob("*.json"):
        with open(path) as f:
            jobs.append(json.load(f))
    return jobs


async def human_delay(min_s=1.5, max_s=4.0):
    await asyncio.sleep(random.uniform(min_s, max_s))


async def slow_type(page: Page, selector: str, text: str):
    el = await page.query_selector(selector)
    if not el:
        return
    await el.click()
    await el.fill("")
    for ch in text:
        await page.keyboard.type(ch)
        await asyncio.sleep(random.uniform(0.02, 0.07))


# ─── Answer matching ──────────────────────────────────────────────────────────

def best_answer(question_text: str, qa_map: dict) -> str:
    q_lower = question_text.lower()
    best, best_score = "", 0
    for q, a in qa_map.items():
        words = set(q.lower().split())
        hits = sum(1 for w in words if w in q_lower and len(w) > 3)
        if hits > best_score:
            best, best_score = a, hits

    if best_score >= 2:
        return best

    # Hard-coded fallbacks for common field types
    if re.search(r"\byears.{0,20}experience\b", q_lower):
        return "5"
    if "notice period" in q_lower or "notice" in q_lower:
        return "30 days"
    if "salary" in q_lower or "ctc" in q_lower or "compensation" in q_lower:
        return "Open to discussion based on role scope"
    if re.search(r"\bauthori[sz]ed\b|\bwork.{0,10}permit\b", q_lower):
        return "Yes"
    if "sponsor" in q_lower:
        return "No"
    if "relocat" in q_lower:
        return "Yes"
    return ""


# ─── Easy Apply flow ──────────────────────────────────────────────────────────

async def handle_easy_apply(page: Page, job: dict, config: dict) -> bool:
    resume_path = Path(config.get("resume_path", "resume.pdf")).resolve()
    cover_letter = job.get("cover_letter", "")
    qa = job.get("screening_answers", {})
    applicant_phone = os.getenv("APPLICANT_PHONE", "")

    try:
        btn = await page.query_selector(
            ".jobs-apply-button--top-card, .jobs-s-apply button"
        )
        if not btn:
            return False
        await btn.click()
        await human_delay(2, 3)

        for step in range(12):
            await human_delay(0.8, 1.5)

            # Submit button — final step
            submit = await page.query_selector(
                "button[aria-label='Submit application'], "
                "button[data-control-name='submit_unify']"
            )
            if submit:
                await submit.click()
                await human_delay(2, 3)
                print("    [+] Submitted via Easy Apply")
                return True

            # Phone field
            phone_el = await page.query_selector(
                "input[id*='phoneNumber'], input[name*='phone']"
            )
            if phone_el and applicant_phone:
                await phone_el.fill(applicant_phone)

            # Resume upload
            file_input = await page.query_selector("input[type='file']")
            if file_input and resume_path.exists():
                await file_input.set_input_files(str(resume_path))
                await human_delay(1, 2)

            # Cover letter textarea
            cl_el = await page.query_selector(
                "textarea[id*='cover'], textarea[name*='cover']"
            )
            if cl_el and cover_letter:
                await cl_el.fill(cover_letter[:2000])

            # Screening questions
            containers = await page.query_selector_all(
                ".jobs-easy-apply-form-element, .fb-form-element"
            )
            for container in containers:
                q_text = (await container.inner_text()).strip()
                answer = best_answer(q_text, qa)

                # Number / text input
                input_el = await container.query_selector(
                    "input[type='text'], input[type='number']"
                )
                if input_el:
                    if answer:
                        await input_el.fill(answer[:200])
                    continue

                # Textarea
                ta = await container.query_selector("textarea")
                if ta:
                    if answer:
                        await ta.fill(answer[:1000])
                    continue

                # Dropdown
                sel = await container.query_selector("select")
                if sel:
                    options = await sel.query_selector_all("option")
                    if len(options) > 1:
                        await sel.select_option(index=1)
                    continue

                # Yes/No radio — prefer Yes
                yes = await container.query_selector(
                    "input[type='radio'][value='Yes'], "
                    "input[type='radio'][value='yes'], "
                    "input[type='radio'][value='true']"
                )
                if yes:
                    await yes.click()

            # Next / Review
            next_btn = await page.query_selector(
                "button[aria-label='Continue to next step'], "
                "button[aria-label='Review your application'], "
                "button.artdeco-button--primary:not([disabled])"
            )
            if next_btn:
                await next_btn.click()
                await human_delay(1.5, 3)

        return False

    except Exception as e:
        print(f"    [!] Easy Apply error: {e}")
        return False


# ─── Email application ────────────────────────────────────────────────────────

def apply_by_email(job: dict) -> bool:
    sender = os.getenv("GMAIL_USER")
    app_password = os.getenv("GMAIL_APP_PASSWORD")
    if not sender or not app_password:
        print("    [!] Gmail not configured in .env")
        return False

    match = re.search(
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
        job.get("jd_text", ""),
    )
    if not match:
        print("    [!] No recruiter email in JD — skipping email route")
        return False

    recipient = match.group(0)
    name = os.getenv("APPLICANT_NAME", "Candidate")
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = f"Application: {job['title']} — {name}"
    msg.attach(MIMEText(job.get("cover_letter", "Please find my application attached."), "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
            srv.login(sender, app_password)
            srv.sendmail(sender, recipient, msg.as_string())
        print(f"    [+] Email sent to {recipient}")
        return True
    except Exception as e:
        print(f"    [!] Email send failed: {e}")
        return False


# ─── Per-job orchestration ────────────────────────────────────────────────────

async def apply_job(page: Page, job: dict, config: dict, tracker: dict) -> bool:
    job_id = job["job_id"]
    if job_id in tracker:
        print(f"  [skip] {job['title']} @ {job['company']}")
        return False

    print(f"\n  Applying: {job['title']} @ {job['company']}  (score={job.get('fit_score',0)})")

    if job.get("easy_apply"):
        await page.goto(job["apply_url"], wait_until="domcontentloaded")
        await human_delay(3, 5)
        success = await handle_easy_apply(page, job, config)
    else:
        success = apply_by_email(job)

    if success:
        SCREENSHOTS_DIR.mkdir(exist_ok=True)
        fname = re.sub(r"\W+", "_", f"{job['company']}_{job['title']}_{job_id}") + ".png"
        try:
            await page.screenshot(path=str(SCREENSHOTS_DIR / fname))
        except Exception:
            pass

    tracker[job_id] = {
        "title": job["title"],
        "company": job["company"],
        "location": job.get("location", ""),
        "apply_url": job.get("apply_url", ""),
        "fit_score": job.get("fit_score", 0),
        "easy_apply": job.get("easy_apply", False),
        "status": "applied" if success else "failed",
        "applied_at": datetime.now().isoformat(),
        "jd_summary": job.get("jd_text", "")[:300],
    }
    save_tracker(tracker)
    return success


# ─── Main ─────────────────────────────────────────────────────────────────────

async def run_applier(daily_limit: int = None) -> dict:
    config = load_config()
    limit = daily_limit or config.get("daily_apply_limit", 10)
    tracker = load_tracker()

    jobs = load_tailored_jobs()
    jobs.sort(key=lambda j: j.get("fit_score", 0), reverse=True)
    stats = {"applied": 0, "failed": 0, "skipped": 0}

    async with async_playwright() as p:
        headless = os.getenv("HEADLESS", "").lower() in ("true", "1") or config.get("headless", False)
        browser = await p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
        )
        await context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        page = await context.new_page()

        try:
            li_at = os.getenv("LINKEDIN_SESSION_COOKIE", "").strip()
            if li_at:
                await context.add_cookies([{
                    "name": "li_at",
                    "value": li_at,
                    "domain": ".linkedin.com",
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                }])
            await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=60000)
            await human_delay(2, 4)

            for job in jobs:
                if stats["applied"] >= limit:
                    print(f"\n[*] Daily limit ({limit}) reached")
                    break

                result = await apply_job(page, job, config, tracker)
                if result:
                    stats["applied"] += 1
                elif job["job_id"] in tracker:
                    stats["skipped"] += 1
                else:
                    stats["failed"] += 1

                await human_delay(12, 22)

        finally:
            await browser.close()

    print(f"\n[+] Applied={stats['applied']}  Failed={stats['failed']}  Skipped={stats['skipped']}")
    return stats


if __name__ == "__main__":
    asyncio.run(run_applier())
