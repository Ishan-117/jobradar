# 🎯 JobRadar

A zero-cost personal job search tool. Upload your resume once, get a daily email digest of matching jobs — scored by Claude, delivered to your inbox.

**No server. No database. No frontend. Just a Python script and GitHub Actions.**

## How it works

1. You run `setup.py` once — it parses your resume with Claude and saves your profile
2. Every morning, GitHub Actions runs `daily_scout.py` automatically
3. It fetches fresh jobs from Adzuna + Remotive, scores them against your profile using Claude
4. You get a clean email digest with role, company, location, match score, and apply links

## Quick start

### 1. Get your API keys

You need four things:

| Key | Where to get it |
|---|---|
| **Anthropic API key** | [console.anthropic.com](https://console.anthropic.com/) |
| **Gmail app password** | [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) (requires 2FA) |
| **Adzuna App ID** | [developer.adzuna.com](https://developer.adzuna.com/) (free signup) |
| **Adzuna App Key** | Same as above |

### 2. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/jobradar.git
cd jobradar
pip install -r requirements.txt
```

### 3. Set environment variables

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
export ADZUNA_APP_ID=your_app_id
export ADZUNA_APP_KEY=your_app_key
```

### 4. Run setup (once)

```bash
python setup.py
```

This will ask for your name, email, location, and resume PDF path. It generates `profile.json`.

### 5. Test locally

```bash
# Dry run — prints to console instead of emailing
python daily_scout.py --dry-run

# Full run — sends the email
python daily_scout.py
```

### 6. Automate with GitHub Actions

1. Push this repo to GitHub
2. Go to **Settings → Secrets and variables → Actions**
3. Add these repository secrets:
   - `ANTHROPIC_API_KEY`
   - `GMAIL_APP_PASSWORD`
   - `ADZUNA_APP_ID`
   - `ADZUNA_APP_KEY`
4. **Important**: push your `profile.json` to the repo (it's gitignored by default — remove the line from `.gitignore` or use `git add -f profile.json`)
5. Go to **Actions** tab and enable the workflow
6. The workflow runs daily at 8:00 AM UTC. You can also trigger it manually.

## Configuration

Edit `config.py` to change:

```python
WORK_TYPE          = "any"                # "remote", "hybrid", "onsite", "any"
EXPERIENCE         = "mid-level"          # "entry", "mid-level", "senior"
MIN_SCORE          = 60                   # Match threshold (0–100)
INCLUDE_REMOTE     = True                 # Pull remote jobs from Remotive
INCLUDE_INTERNSHIPS = True                # Also search for internships
```

Your target role is automatically detected from your resume during `setup.py`. To change it, either re-run `setup.py` or edit the `target_role` field in `profile.json` directly.

## Cost

| Service | Cost |
|---|---|
| GitHub Actions | Free (2,000 min/month, script takes ~30s) |
| Adzuna API | Free (250 requests/day) |
| Remotive API | Free (unlimited) |
| Gmail SMTP | Free |
| Claude API | ~$0.01–0.03 per daily run |
| **Total** | **~$0.30–0.90/month** |

## File structure

```
jobradar/
├── setup.py              ← Run once: parses resume → saves profile.json
├── daily_scout.py        ← Run daily: fetches jobs → scores → emails you
├── config.py             ← Your preferences (role, location, thresholds)
├── requirements.txt      ← Python dependencies
├── profile.json          ← Auto-generated (gitignored)
├── resume.pdf            ← Your resume (gitignored)
├── .gitignore
├── README.md
└── .github/
    └── workflows/
        └── daily.yml     ← GitHub Actions cron job
```

## Troubleshooting

**"ANTHROPIC_API_KEY not set"**
→ Make sure you've exported the key or added it to GitHub Secrets.

**"Could not extract text from PDF"**
→ Your PDF might be a scanned image. pdfplumber needs selectable text. Try re-saving it from Google Docs or Word.

**"Adzuna API error"**
→ Check your App ID and Key. The free tier allows 250 requests/day.

**"Gmail SMTP error"**
→ You need a Gmail **app password**, not your regular password. Enable 2FA first, then generate one at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).

**"Could not map location"**
→ Edit `ADZUNA_COUNTRY_MAP` in `config.py` to add your country.
