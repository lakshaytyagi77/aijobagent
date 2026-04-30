# AI Job Agent — LinkedIn Automation for HR Professionals

An end-to-end, AI-powered LinkedIn job application system built for senior HR professionals. The agent scrapes targeted job listings, scores each role for fit, generates tailored resumes and cover letters using Claude AI, auto-applies via LinkedIn Easy Apply or email, logs every application to Google Sheets, and produces interview prep guides on demand.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        main.py  (Orchestrator)                  │
│   scrape → score → tailor → apply → log → prep                 │
└────────┬──────────┬──────────┬──────────┬──────────┬───────────┘
         │          │          │          │          │
    scraper.py  ai_tailor.py  applier.py logger.py prep_coach.py
         │          │          │          │          │
    Playwright   Claude API  Playwright  gspread   Claude API
    (Chromium)  (Anthropic)  (Chromium)  (Sheets)  + Wikipedia
```

### Module Breakdown

| File | Role | Key Dependencies |
|------|------|-----------------|
| `scraper.py` | Logs into LinkedIn, searches job listings, extracts JD text, Easy Apply flag, company, location | Playwright, python-dotenv |
| `ai_tailor.py` | Scores JD fit (0–100), generates tailored resume bullets, cover letter, STAR-format screening answers | Anthropic Claude, PyPDF2 |
| `applier.py` | Fills and submits Easy Apply forms; falls back to email for external postings; takes confirmation screenshots | Playwright, smtplib |
| `logger.py` | Pushes every application to a colour-coded Google Sheet; supports live status updates (applied → interview → offer) | gspread, oauth2client |
| `prep_coach.py` | Fetches company info, generates 10 STAR Q&As and 5 smart interviewer questions, saves as Markdown | Anthropic Claude, BeautifulSoup |
| `main.py` | CLI orchestrator with `--scrape-only`, `--apply-only`, `--prep`, `--log` flags; sends daily email summary | All modules |
| `config.json` | Target job titles, locations, keywords, daily apply limit, minimum fit score | — |

---

## Features

- **Human-like browser behaviour** — random mouse jitter, natural scroll, per-character typing delays, randomised pauses between actions
- **Anti-detection** — `webdriver` property masked, realistic User-Agent, non-headless mode by default
- **Smart fit scoring** — Claude evaluates keyword overlap, seniority match, domain fit, and location compatibility
- **AI writing that sounds human** — cover letters with varied sentence structure, concrete metrics, no buzzwords (synergy, leverage, circle back)
- **STAR-format answers** — screening question responses grounded in the candidate's actual resume
- **Google Sheets dashboard** — colour-coded rows (green = applied, yellow = interview, red = rejected, blue = offer)
- **Daily email summary** — scraped / qualified / applied / failed counts delivered to your inbox
- **Interview prep on demand** — company research + 10 STAR answers + 5 smart questions saved as a Markdown file

---

## Prerequisites

- Python 3.12+
- A LinkedIn account
- Anthropic API key (console.anthropic.com)
- Gmail account with App Password enabled
- Google Cloud service account with Sheets + Drive API access (for logging)

---

## Installation

```bash
# 1. Clone the repo
git clone https://github.com/lakshaytyagi77/aijobagent.git
cd aijobagent

# 2. Install dependencies
pip install playwright beautifulsoup4 anthropic gspread oauth2client PyPDF2 python-dotenv requests

# 3. Install Playwright browser
python -m playwright install chromium

# 4. Copy and fill the environment template
copy .env.example .env
# Edit .env with your credentials (see Configuration below)

# 5. Add your resume
# Place your resume as resume.pdf in the project root

# 6. (Optional) Add Google service account
# Place service_account.json in the project root
```

---

## Configuration

### `.env`

```env
# LinkedIn — use session cookie (preferred) OR email+password
LINKEDIN_SESSION_COOKIE=     # Value of the li_at cookie from your browser
LINKEDIN_EMAIL=              # Your LinkedIn email
LINKEDIN_PASSWORD=           # Your LinkedIn password

# AI Engine
ANTHROPIC_API_KEY=           # From console.anthropic.com

# Gmail (application emails + daily summary)
GMAIL_USER=                  # your@gmail.com
GMAIL_APP_PASSWORD=          # Gmail App Password (not your account password)
SUMMARY_EMAIL_TO=            # Where to send the daily report

# Applicant details (used to fill application forms)
APPLICANT_NAME=              # Your full name
APPLICANT_PHONE=             # e.g. +91 9876543210

# Google Sheets tracker
GOOGLE_SHEETS_ID=            # ID from your Sheet URL
GOOGLE_SERVICE_ACCOUNT_JSON= # Path to service account JSON (default: service_account.json)
```

> **Getting the `li_at` cookie:** Open LinkedIn in Chrome → F12 → Application tab → Cookies → `www.linkedin.com` → copy the value of `li_at`.

### `config.json`

```json
{
  "job_titles": ["HR Manager", "HR Business Partner", "Senior HR Executive"],
  "experience_years": 5,
  "location_preference": ["India", "Remote", "Hybrid"],
  "keywords_to_match": ["HRBP", "talent management", "performance management"],
  "daily_apply_limit": 10,
  "min_fit_score": 65,
  "resume_path": "resume.pdf",
  "headless": false
}
```

| Key | Description |
|-----|-------------|
| `job_titles` | Search queries sent to LinkedIn Jobs |
| `min_fit_score` | Jobs below this score (0–100) are skipped |
| `daily_apply_limit` | Hard cap on applications per run |
| `headless` | `false` = visible browser (recommended); `true` = background |

---

## Usage

```bash
# Full pipeline: scrape → score → tailor → apply → log to Sheets → email summary
python main.py

# Scrape and tailor only — review jobs before applying
python main.py --scrape-only

# Skip scrape, apply from existing jobs_raw.json
python main.py --apply-only

# Generate interview prep for a specific company
python main.py --prep "Infosys"
python main.py --prep "Tata Consultancy Services"

# Sync tracker.json to Google Sheets only
python main.py --log
```

### Windows Scheduler (daily automation)

Use `run.bat` with Windows Task Scheduler to run the full pipeline every morning:

```
Action: Start a Program
Program: C:\Users\<you>\linkedin-job-agent\run.bat
Trigger: Daily at 08:00
```

---

## Output Files

| File / Folder | Contents |
|---------------|----------|
| `jobs_raw.json` | All scraped jobs with title, company, JD text, Easy Apply flag |
| `tailored/<company>_<role>.json` | Per-job tailored bullets, cover letter, screening answers |
| `tracker.json` | Applied jobs with status, timestamps, fit scores |
| `screenshots/` | Confirmation page screenshots for each application |
| `prep/<company>_prep.md` | Interview prep guide (STAR answers, company overview, smart questions) |
| `run_log.txt` | Full timestamped pipeline log |

---

## Google Sheets Tracker

The sheet is auto-created on first run with these columns:

| Date Applied | Company | Job Title | Location | JD Summary | Fit Score | Resume Version | Application Status | Notes | Interview Date | Interview Prep Done |
|---|---|---|---|---|---|---|---|---|---|---|

Row colours update automatically as status changes:

- **Green** — Applied
- **Yellow** — Interview scheduled
- **Red** — Rejected
- **Blue** — Offer received

To update a status manually from Python:

```python
from logger import update_status
update_status("Infosys", "interview", interview_date="2026-05-10")
```

---

## How the AI Scoring Works

Claude evaluates each job description against the candidate's resume across four dimensions:

| Dimension | Weight |
|-----------|--------|
| Keyword / skill overlap | 30 pts |
| Seniority match | 25 pts |
| Domain / industry fit | 25 pts |
| Location compatibility | 20 pts |

Jobs scoring below `min_fit_score` (default 65) are skipped entirely.

---

## Security Notes

- **Never commit `.env`** — it is in `.gitignore`
- **Never commit `service_account.json`** — also in `.gitignore`
- **Never commit `resume.pdf`** — contains personal data, also excluded
- LinkedIn session cookies expire periodically — update `LINKEDIN_SESSION_COOKIE` when login fails

---

## Project Structure

```
aijobagent/
├── main.py              # Orchestrator + CLI
├── scraper.py           # LinkedIn scraper (Playwright)
├── ai_tailor.py         # Resume + cover letter AI engine
├── applier.py           # Application submission engine
├── logger.py            # Google Sheets integration
├── prep_coach.py        # Interview prep generator
├── config.json          # Job search configuration
├── .env.example         # Environment variable template
├── run.bat              # Windows Task Scheduler entry point
├── tailored/            # AI-generated application content (gitignored)
├── screenshots/         # Confirmation screenshots (gitignored)
└── prep/                # Interview prep guides (gitignored)
```

---

## Roadmap

- [ ] Multi-platform support (Naukri.com, Indeed, Internshala)
- [ ] Resume PDF regeneration with tailored bullets (via ReportLab)
- [ ] Telegram / WhatsApp daily summary notifications
- [ ] Fit score trend dashboard
- [ ] Auto-schedule follow-up emails 7 days post-application

---

## License

MIT
