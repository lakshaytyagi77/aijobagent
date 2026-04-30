"""LinkedIn Job Scraper — Playwright-based with human-like behaviour"""
import asyncio
import json
import os
import random
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

CONFIG_FILE = "config.json"
JOBS_RAW_FILE = "jobs_raw.json"
TRACKER_FILE = "tracker.json"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return json.load(f)


def load_tracker() -> dict:
    if os.path.exists(TRACKER_FILE):
        with open(TRACKER_FILE) as f:
            return json.load(f)
    return {}


async def human_delay(min_s: float = 2.0, max_s: float = 5.0):
    await asyncio.sleep(random.uniform(min_s, max_s))


async def slow_scroll(page, distance: int = 700, steps: int = 10):
    per = distance // steps
    for _ in range(steps):
        await page.evaluate(f"window.scrollBy(0, {per})")
        await asyncio.sleep(random.uniform(0.08, 0.25))


async def jitter_mouse(page, cx: int, cy: int):
    for _ in range(random.randint(2, 4)):
        await page.mouse.move(
            cx + random.randint(-25, 25),
            cy + random.randint(-15, 15),
        )
        await asyncio.sleep(random.uniform(0.04, 0.12))


# ─── Auth ─────────────────────────────────────────────────────────────────────

async def login_cookies(context, page) -> bool:
    li_at = os.getenv("LINKEDIN_SESSION_COOKIE", "").strip()
    if not li_at:
        return False
    try:
        await context.add_cookies([{
            "name": "li_at",
            "value": li_at,
            "domain": ".linkedin.com",
            "path": "/",
            "httpOnly": True,
            "secure": True,
        }])
        await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=60000)
        await human_delay(2, 3)
        return "feed" in page.url or "/mynetwork/" in page.url
    except Exception as e:
        print(f"[!] Cookie auth failed: {e}")
        await context.clear_cookies()
        return False


async def login_credentials(context, page) -> bool:
    email = os.getenv("LINKEDIN_EMAIL")
    password = os.getenv("LINKEDIN_PASSWORD")
    if not email or not password:
        raise EnvironmentError("Set LINKEDIN_EMAIL / LINKEDIN_PASSWORD in .env")

    await context.clear_cookies()
    await page.goto("about:blank")
    await human_delay(1, 2)
    await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=60000)
    await human_delay(2, 3)

    def is_logged_in(url: str) -> bool:
        return any(x in url for x in ("/feed", "/mynetwork", "/jobs", "/messaging", "/notifications"))

    if is_logged_in(page.url):
        return True

    # Challenge page before we even type — wait for user to resolve it
    if "checkpoint" in page.url or "challenge" in page.url:
        print("[!] LinkedIn is showing a security challenge in the browser window.")
        print("    Complete it there, then press Enter here.")
        input("Press Enter once you can see the LinkedIn feed…")
        await human_delay(2, 3)
        return is_logged_in(page.url)

    # Normal login form — type credentials
    try:
        await page.wait_for_selector("#username", timeout=15000)
    except Exception:
        print("[!] Login form not found. Log in manually in the browser window, then press Enter.")
        input("Press Enter once you can see the LinkedIn feed…")
        await human_delay(2, 3)
        return is_logged_in(page.url)

    for ch in email:
        await page.type("#username", ch)
        await asyncio.sleep(random.uniform(0.05, 0.14))
    await human_delay(0.4, 0.9)
    for ch in password:
        await page.type("#password", ch)
        await asyncio.sleep(random.uniform(0.04, 0.11))
    await human_delay(0.3, 0.8)
    await page.click('[type="submit"]')
    await human_delay(4, 7)

    # Post-login challenge (OTP, CAPTCHA, etc.)
    if "checkpoint" in page.url or "challenge" in page.url:
        print("[!] Security checkpoint after login — complete it in the browser window.")
        input("Press Enter once you can see the LinkedIn feed…")
        await human_delay(2, 3)

    return is_logged_in(page.url)


async def login(context, page) -> bool:
    print("[*] Logging in…")
    if await login_cookies(context, page):
        print("[+] Logged in via cookies")
        return True
    result = await login_credentials(context, page)
    if result:
        print("[+] Logged in via credentials")
    return result


# ─── Extraction ───────────────────────────────────────────────────────────────

async def get_job_id(url: str) -> str:
    if "currentJobId=" in url:
        return url.split("currentJobId=")[1].split("&")[0]
    if "/jobs/view/" in url:
        return url.split("/jobs/view/")[1].rstrip("/").split("?")[0].split("/")[0]
    return f"local_{int(time.time() * 1000)}"


async def safe_text(page, selector: str, default: str = "") -> str:
    el = await page.query_selector(selector)
    if not el:
        return default
    return (await el.inner_text()).strip()


async def extract_job(page) -> dict | None:
    await human_delay(1.5, 3.0)
    try:
        job_id = await get_job_id(page.url)

        title = await safe_text(
            page,
            "h1.t-24, h1.jobs-unified-top-card__job-title, "
            ".job-details-jobs-unified-top-card__job-title h1",
        )
        company = await safe_text(
            page,
            ".jobs-unified-top-card__company-name a, "
            ".job-details-jobs-unified-top-card__company-name a",
        )
        location = await safe_text(
            page,
            ".jobs-unified-top-card__bullet:first-child, "
            ".job-details-jobs-unified-top-card__primary-description-without-tagline",
        )

        jd_el = await page.query_selector(
            ".jobs-description__content .jobs-box__html-content, "
            ".jobs-description-content__text, "
            ".jobs-description"
        )
        jd_text = (await jd_el.inner_text()).strip() if jd_el else ""

        apply_btn = await page.query_selector(
            ".jobs-apply-button--top-card, .jobs-s-apply button"
        )
        easy_apply = False
        if apply_btn:
            easy_apply = "Easy Apply" in (await apply_btn.inner_text())

        return {
            "job_id": job_id,
            "title": title or "Unknown",
            "company": company or "Unknown",
            "location": location or "Unknown",
            "jd_text": jd_text[:4000],
            "apply_url": page.url,
            "easy_apply": easy_apply,
            "date_scraped": datetime.now().isoformat(),
            "status": "new",
        }
    except Exception as e:
        print(f"  [!] Extract error: {e}")
        return None


# ─── Search ───────────────────────────────────────────────────────────────────

async def scrape_search(
    page, title: str, location: str, applied_ids: set, seen_ids: set
) -> list:
    results = []
    q = title.replace(" ", "%20")
    loc = location.replace(" ", "%20")
    url = (
        f"https://www.linkedin.com/jobs/search/?keywords={q}"
        f"&location={loc}&f_TPR=r604800&sortBy=DD"
    )
    await page.goto(url, wait_until="domcontentloaded")
    await human_delay(3, 5)

    for _ in range(4):
        await slow_scroll(page)
        await human_delay(0.8, 1.5)

    cards = await page.query_selector_all(
        "li.jobs-search-results__list-item, li.scaffold-layout__list-item"
    )
    print(f"  {len(cards)} listings for '{title}' in '{location}'")

    for i, card in enumerate(cards[:20]):
        try:
            bbox = await card.bounding_box()
            if bbox:
                await jitter_mouse(
                    page,
                    int(bbox["x"] + bbox["width"] / 2),
                    int(bbox["y"] + bbox["height"] / 2),
                )
            await card.click()
            await page.wait_for_selector(
                "h1.t-24, h1.jobs-unified-top-card__job-title, "
                ".job-details-jobs-unified-top-card__job-title h1",
                timeout=8000,
            )

            job = await extract_job(page)
            if not job:
                continue
            if job["job_id"] in applied_ids:
                print(f"    [skip] already applied: {job['title']}")
                continue
            if job["job_id"] in seen_ids:
                continue

            seen_ids.add(job["job_id"])
            results.append(job)
            tag = "EasyApply" if job["easy_apply"] else "External"
            print(f"    [+] {job['title']} @ {job['company']} ({tag})")

        except Exception as e:
            print(f"    [!] card {i}: {e}")

        await human_delay(1.5, 3.5)

    return results


# ─── Main ─────────────────────────────────────────────────────────────────────

async def run_scraper() -> list:
    config = load_config()
    tracker = load_tracker()
    applied_ids = set(tracker.keys())
    seen_ids: set = set()
    all_jobs: list = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=config.get("headless", False),
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="en-US",
        )
        await context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        page = await context.new_page()

        try:
            if not await login(context, page):
                raise RuntimeError("LinkedIn login failed — check credentials in .env")

            for job_title in config["job_titles"]:
                for loc in config["location_preference"]:
                    print(f"\n[*] {job_title} | {loc}")
                    jobs = await scrape_search(page, job_title, loc, applied_ids, seen_ids)
                    all_jobs.extend(jobs)
                    await human_delay(8, 15)
        finally:
            await browser.close()

    Path(JOBS_RAW_FILE).write_text(json.dumps(all_jobs, indent=2, ensure_ascii=False))
    print(f"\n[+] {len(all_jobs)} new jobs → {JOBS_RAW_FILE}")
    return all_jobs


if __name__ == "__main__":
    asyncio.run(run_scraper())
