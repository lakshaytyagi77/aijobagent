"""Interview Preparation Coach — generates STAR answers and company research"""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import anthropic
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

PREP_DIR = Path("prep")
CONFIG_FILE = "config.json"
TRACKER_FILE = "tracker.json"

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


# ─── Helpers ──────────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return json.load(f)


def ask_claude(prompt: str, max_tokens: int = 3500) -> str:
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        system=(
            "You are an expert interview coach for HR professionals. "
            "Write in a clear, practical, human voice. No fluff."
        ),
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def get_resume_text() -> str:
    config = load_config()
    pdf_path = config.get("resume_path", "resume.pdf")
    if not os.path.exists(pdf_path):
        return (
            "HR professional with 5+ years of experience in talent acquisition, "
            "performance management, employee engagement, and HR strategy."
        )
    try:
        import PyPDF2
        with open(pdf_path, "rb") as f:
            return "\n".join(p.extract_text() or "" for p in PyPDF2.PdfReader(f).pages)[:2500]
    except Exception:
        return "HR professional with 5+ years of experience."


def get_job_context(company_name: str) -> dict:
    if not os.path.exists(TRACKER_FILE):
        return {}
    with open(TRACKER_FILE) as f:
        tracker = json.load(f)
    name_lower = company_name.lower()
    for data in tracker.values():
        if name_lower in data.get("company", "").lower():
            return data
    return {}


# ─── Company research ─────────────────────────────────────────────────────────

def _fetch_wikipedia(company: str) -> str:
    try:
        api = (
            "https://en.wikipedia.org/w/api.php"
            f"?action=opensearch&search={requests.utils.quote(company)}&limit=1&format=json"
        )
        titles = requests.get(api, timeout=8).json()[1]
        if not titles:
            return ""
        page_url = f"https://en.wikipedia.org/wiki/{requests.utils.quote(titles[0])}"
        soup = BeautifulSoup(requests.get(page_url, timeout=8).text, "html.parser")
        output = soup.find("div", {"class": "mw-parser-output"})
        if not output:
            return ""
        paras = [p.get_text() for p in output.find_all("p", recursive=False)[:3] if p.get_text().strip()]
        return "Wikipedia summary:\n" + " ".join(paras)[:1400]
    except Exception:
        return ""


def _fetch_linkedin_about(company: str) -> str:
    try:
        slug = re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-")
        url = f"https://www.linkedin.com/company/{slug}/about/"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        soup = BeautifulSoup(r.text, "html.parser")
        el = soup.find("p", {"class": re.compile(r"description", re.I)})
        return f"LinkedIn About:\n{el.get_text().strip()[:800]}" if el else ""
    except Exception:
        return ""


def fetch_company_info(company: str) -> str:
    parts = [s for s in (_fetch_wikipedia(company), _fetch_linkedin_about(company)) if s]
    return "\n\n".join(parts) or f"No public data found for '{company}' — research manually before the interview."


# ─── Prep generation ──────────────────────────────────────────────────────────

def generate_prep(company_name: str) -> str:
    print(f"[*] Researching {company_name}…")
    company_info = fetch_company_info(company_name)
    resume_text = get_resume_text()
    job_ctx = get_job_context(company_name)
    role = job_ctx.get("title", "HR role")

    prompt = f"""Create a complete interview prep guide for an HR professional.

COMPANY: {company_name}
ROLE: {role}

COMPANY INFORMATION (from public sources):
{company_info}

CANDIDATE BACKGROUND:
{resume_text}

─────────────────────────────────────────
Write the following sections in markdown:

## Company Overview
3-4 bullets covering what the company does, its scale, and any culture signals visible from public info.

## Why This Company — Talking Points
2-3 specific, non-generic reasons the candidate can cite. Reference something real from the company info above.

## 10 STAR Interview Q&A

Format each as:
**Q: [Question]**
*S:* [Situation — brief, 1-2 sentences]
*T:* [Task — what was needed]
*A:* [Action — what they specifically did, 2-3 sentences]
*R:* [Result — measurable outcome]

Cover:
1. Tell me about yourself (not STAR — a 90-second pitch)
2. Why do you want to work here?
3. Describe a conflict you resolved between employees
4. A time you improved a broken HR process
5. Your most challenging hire
6. How you handled a poor-performing team member
7. A time you drove cultural change
8. How you balance strategic and operational HR work
9. A data-driven HR decision you made
10. Where you see yourself in 3 years

Make each answer sound like a real person talking — not a textbook. Include plausible metrics.

## 5 Smart Questions to Ask the Interviewer
Not "what's the culture like?" — strategic, curious questions that show depth.

## Watch-Outs
2-3 things to probe to avoid walking into a bad situation (e.g. high attrition, unclear CHRO mandate, no HR tech stack).

─────────────────────────────────────────
Be specific and practical. This person is about to walk into a real interview."""

    content = ask_claude(prompt, max_tokens=4000)

    PREP_DIR.mkdir(exist_ok=True)
    safe = re.sub(r"[^\w\-]", "_", company_name)
    out_path = PREP_DIR / f"{safe}_prep.md"
    out_path.write_text(
        f"# Interview Prep: {company_name} — {role}\n"
        f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n\n"
        + content,
        encoding="utf-8",
    )

    print(f"[+] Saved → {out_path}")
    return str(out_path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python prep_coach.py <Company Name>")
        sys.exit(1)
    generate_prep(" ".join(sys.argv[1:]))
