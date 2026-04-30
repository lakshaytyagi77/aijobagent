"""AI Resume & Cover Letter Tailoring Engine — powered by Claude"""
import json
import os
import re
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

load_dotenv()

JOBS_RAW_FILE = "jobs_raw.json"
TAILORED_DIR = Path("tailored")
CONFIG_FILE = "config.json"

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


# ─── Helpers ──────────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return json.load(f)


def extract_resume_text(pdf_path: str) -> str:
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"Resume not found at '{pdf_path}' — see RESUME_PLACEHOLDER.txt")
    if PyPDF2 is None:
        raise ImportError("PyPDF2 not installed — run: pip install PyPDF2")
    pages = []
    with open(pdf_path, "rb") as f:
        for page in PyPDF2.PdfReader(f).pages:
            pages.append(page.extract_text() or "")
    return "\n".join(pages)


def safe_filename(*parts: str) -> str:
    name = "_".join(parts)
    return re.sub(r"[^\w\-]", "_", name)[:60]


def ask_claude(prompt: str, max_tokens: int = 2000) -> str:
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        system=(
            "You are an expert HR career coach who writes in a natural, human voice. "
            "Never use corporate buzzwords like synergy, leverage, or circle back."
        ),
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


# ─── Scoring ──────────────────────────────────────────────────────────────────

def score_fit(resume_text: str, job: dict, config: dict) -> tuple[int, str]:
    prompt = f"""You are a senior HR recruiter evaluating a resume against a job description.

RESUME:
{resume_text[:2500]}

JOB TITLE: {job['title']}
COMPANY: {job['company']}
JD:
{job['jd_text'][:2000]}

CANDIDATE CONTEXT: {config['experience_years']}+ years HR experience, strong in: {', '.join(config['keywords_to_match'])}

Score the fit 0-100. Weigh:
- Keyword/skill overlap (30 pts)
- Seniority match (25 pts)
- Domain/industry fit (25 pts)
- Location compatibility (20 pts)

Return ONLY valid JSON: {{"score": <integer>, "reason": "<one sentence>"}}"""

    try:
        raw = ask_claude(prompt, max_tokens=120)
        data = json.loads(raw)
        return int(data["score"]), data.get("reason", "")
    except Exception:
        return 50, "Score unavailable"


# ─── Content Generation ───────────────────────────────────────────────────────

def generate_bullets(resume_text: str, job: dict) -> list[str]:
    prompt = f"""Rewrite 5 resume bullet points for an HR professional targeting this specific role.

RESUME:
{resume_text[:2500]}

ROLE: {job['title']} at {job['company']}
JD:
{job['jd_text'][:1800]}

Rules:
- Strong action verbs: Led, Built, Drove, Cut, Launched, Designed
- Specific numbers where plausible: headcount, percentages, timeframes
- Mirror key JD phrases naturally — don't copy verbatim
- No buzzwords: synergy, leverage, circle back, utilize
- Each bullet 15–25 words

Return ONLY a JSON array of 5 strings."""

    try:
        return json.loads(ask_claude(prompt, max_tokens=500))
    except Exception as e:
        print(f"  [!] Bullet error: {e}")
        return []


def generate_cover_letter(resume_text: str, job: dict) -> str:
    prompt = f"""Write a cover letter for an HR job application. It must read like a real person wrote it — not a corporate template.

RESUME CONTEXT:
{resume_text[:2000]}

ROLE: {job['title']}
COMPANY: {job['company']}
JD:
{job['jd_text'][:1500]}

Structure:
- Para 1 (opener): Don't start "I am writing to…" — open with a direct, confident hook
- Para 2 (body): Connect 2-3 specific experiences to the role's needs. Include at least one concrete metric.
- Para 3 (close): Genuine interest in this company specifically + clear ask for an interview

Style rules:
- First person, 380-420 words total
- Varied sentence lengths — mix short punchy lines with longer ones
- Address: "Dear Hiring Manager,"
- Sign off: "Warm regards,"
- Do NOT use: passionate, dynamic, results-driven, synergy, leverage, journey, impactful

Write ONLY the letter body."""

    return ask_claude(prompt, max_tokens=700)


def generate_screening_answers(resume_text: str, job: dict) -> dict:
    questions = [
        "Tell me about yourself",
        "Why do you want to work at this company?",
        "Describe a time you resolved a workplace conflict",
        "What is your approach to talent acquisition?",
        "Tell me about a time you improved employee engagement",
        "Describe a successful HR initiative you led",
        "How do you handle underperforming employees?",
        "What is your experience with performance management?",
        "Why are you leaving your current role?",
        "Where do you see yourself in 5 years?",
    ]

    prompt = f"""You are an experienced HR professional answering interview questions. Sound natural, not scripted.

RESUME:
{resume_text[:2000]}

ROLE: {job['title']} at {job['company']}

Answer each question. For behavioural ones use STAR (Situation, Task, Action, Result).
- 100-180 words per answer
- Use real-sounding specifics: team sizes, % improvements, time periods
- Vary your openers: "When I was at…", "One situation that comes to mind…", "Early in my career…"
- Don't over-polish — a slightly conversational tone is better than stiff professionalism

QUESTIONS:
{json.dumps(questions, indent=2)}

Return ONLY a JSON object with questions as keys and answers as values."""

    try:
        return json.loads(ask_claude(prompt, max_tokens=2800))
    except Exception as e:
        print(f"  [!] Screening answer error: {e}")
        return {}


# ─── Main ─────────────────────────────────────────────────────────────────────

def tailor_all_jobs() -> list:
    config = load_config()
    min_score = config.get("min_fit_score", 65)
    resume_text = extract_resume_text(config.get("resume_path", "resume.pdf"))
    TAILORED_DIR.mkdir(exist_ok=True)

    with open(JOBS_RAW_FILE) as f:
        jobs = json.load(f)

    qualified = []
    for job in jobs:
        if job.get("status") in ("applied", "skipped_low_score"):
            continue

        print(f"\n[*] {job['title']} @ {job['company']}")
        score, reason = score_fit(resume_text, job, config)
        job["fit_score"] = score
        print(f"    Score: {score}  ({reason})")

        if score < min_score:
            print(f"    [skip] below {min_score}")
            job["status"] = "skipped_low_score"
            continue

        print("    Generating tailored content…")
        bullets = generate_bullets(resume_text, job)
        cover_letter = generate_cover_letter(resume_text, job)
        qa = generate_screening_answers(resume_text, job)

        fname = safe_filename(job["company"], job["title"]) + ".json"
        output = {
            "job_id": job["job_id"],
            "title": job["title"],
            "company": job["company"],
            "location": job["location"],
            "fit_score": score,
            "easy_apply": job.get("easy_apply", False),
            "apply_url": job.get("apply_url", ""),
            "jd_text": job.get("jd_text", ""),
            "tailored_bullets": bullets,
            "cover_letter": cover_letter,
            "screening_answers": qa,
            "generated_at": datetime.now().isoformat(),
        }
        (TAILORED_DIR / fname).write_text(json.dumps(output, indent=2, ensure_ascii=False))
        print(f"    Saved → tailored/{fname}")
        qualified.append(job)

    with open(JOBS_RAW_FILE, "w") as f:
        json.dump(jobs, f, indent=2)

    print(f"\n[+] Tailored {len(qualified)}/{len(jobs)} jobs")
    return qualified


if __name__ == "__main__":
    tailor_all_jobs()
