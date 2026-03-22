#!/usr/bin/env python3
"""
JobRadar — Daily Scout
Fetches fresh job listings, scores them against your profile using Claude,
and sends you a clean email digest.

Usage:
    python daily_scout.py              # Normal run
    python daily_scout.py --dry-run    # Skip sending email, print to console

Requires environment variables:
    ANTHROPIC_API_KEY   — Claude API key
    GMAIL_APP_PASSWORD  — Gmail app password (not your regular password)
    ADZUNA_APP_ID       — Adzuna API app ID
    ADZUNA_APP_KEY      — Adzuna API app key
"""

import argparse
import json
import os
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import anthropic
import requests

from config import (
    ADZUNA_COUNTRY_MAP,
    CITY_COUNTRY_MAP,
    INCLUDE_INTERNSHIPS,
    INCLUDE_REMOTE,
    MAX_EMAIL_JOBS,
    MAX_RESULTS_PER_SOURCE,
    MIN_SCORE,
    WORK_TYPE,
)

PROFILE_PATH = Path(__file__).parent / "profile.json"


# ── Load profile ─────────────────────────────────────────────

def load_profile():
    """Load profile.json or exit with a helpful message."""
    if not PROFILE_PATH.exists():
        print("Error: profile.json not found. Run setup.py first.")
        sys.exit(1)
    with open(PROFILE_PATH) as f:
        return json.load(f)


# ── Location resolution ──────────────────────────────────────

def resolve_adzuna_countries(location):
    """Map a location string to one or more Adzuna country codes."""
    loc_lower = location.lower().strip()

    # Direct country/continent match
    if loc_lower in ADZUNA_COUNTRY_MAP:
        result = ADZUNA_COUNTRY_MAP[loc_lower]
        return result if isinstance(result, list) else [result]

    # City match
    if loc_lower in CITY_COUNTRY_MAP:
        return [CITY_COUNTRY_MAP[loc_lower]]

    # Fuzzy: check if location contains a known key
    for key, code in ADZUNA_COUNTRY_MAP.items():
        if key in loc_lower or loc_lower in key:
            return code if isinstance(code, list) else [code]

    # Default to broad search
    print(f"  Warning: Could not map '{location}' to Adzuna country codes.")
    print(f"  Defaulting to GB. Edit ADZUNA_COUNTRY_MAP in config.py to add yours.")
    return ["gb"]


# ── Adzuna API ───────────────────────────────────────────────

def fetch_adzuna_jobs(
    query: str,
    country_code: str,
    location: str,
    app_id: str,
    app_key: str,
    max_results: int = 50,
):
    """Fetch jobs from Adzuna API for a single country."""
    url = f"https://api.adzuna.com/v1/api/jobs/{country_code}/search/1"
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "results_per_page": min(max_results, 50),
        "what": query,
        "content-type": "application/json",
        "sort_by": "date",
        "max_days_old": 3,  # Only recent postings
    }

    # Add location filter for city-level searches
    loc_lower = location.lower().strip()
    if loc_lower in CITY_COUNTRY_MAP:
        params["where"] = location

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        print(f"  Warning: Adzuna API error for {country_code}: {e}")
        return []

    jobs = []
    for item in data.get("results", []):
        jobs.append({
            "source": "adzuna",
            "title": item.get("title", "").strip(),
            "company": item.get("company", {}).get("display_name", "Unknown"),
            "location": item.get("location", {}).get("display_name", ""),
            "description": item.get("description", "")[:500],
            "apply_url": item.get("redirect_url", ""),
            "posted_date": item.get("created", "")[:10],
            "salary_min": item.get("salary_min"),
            "salary_max": item.get("salary_max"),
            "type": "job",
        })
    return jobs


def fetch_all_adzuna_jobs(profile):
    """Fetch jobs (and optionally internships) from Adzuna across all target countries."""
    app_id = os.environ.get("ADZUNA_APP_ID", "")
    app_key = os.environ.get("ADZUNA_APP_KEY", "")
    if not app_id or not app_key:
        print("  Warning: ADZUNA_APP_ID or ADZUNA_APP_KEY not set. Skipping Adzuna.")
        return []

    target_role = profile.get("target_role", "Software Engineer")
    countries = resolve_adzuna_countries(profile["location"])
    all_jobs = []

    per_country = max(10, MAX_RESULTS_PER_SOURCE // len(countries))

    for code in countries:
        print(f"  Fetching from Adzuna ({code.upper()})...")
        jobs = fetch_adzuna_jobs(
            target_role, code, profile["location"], app_id, app_key, per_country,
        )
        all_jobs.extend(jobs)

        # Internships
        if INCLUDE_INTERNSHIPS:
            intern_jobs = fetch_adzuna_jobs(
                f"{target_role} internship", code, profile["location"],
                app_id, app_key, per_country // 2,
            )
            for j in intern_jobs:
                j["type"] = "internship"
            all_jobs.extend(intern_jobs)

    print(f"  Adzuna: {len(all_jobs)} listings fetched")
    return all_jobs


# ── Remotive API ─────────────────────────────────────────────

def fetch_remotive_jobs(profile):
    """Fetch remote jobs from Remotive (free, no API key)."""
    if not INCLUDE_REMOTE:
        return []

    target_role = profile.get("target_role", "Software Engineer")
    url = "https://remotive.com/api/remote-jobs"
    params = {"search": target_role, "limit": MAX_RESULTS_PER_SOURCE}

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        print(f"  Warning: Remotive API error: {e}")
        return []

    jobs = []
    for item in data.get("jobs", []):
        title = item.get("title", "")
        job_type = "internship" if "intern" in title.lower() else "job"

        # Skip internships if not wanted
        if job_type == "internship" and not INCLUDE_INTERNSHIPS:
            continue

        jobs.append({
            "source": "remotive",
            "title": title.strip(),
            "company": item.get("company_name", "Unknown"),
            "location": item.get("candidate_required_location", "Remote"),
            "description": item.get("description", "")[:500],
            "apply_url": item.get("url", ""),
            "posted_date": item.get("publication_date", "")[:10],
            "salary_min": None,
            "salary_max": None,
            "type": job_type,
        })

    print(f"  Remotive: {len(jobs)} listings fetched")
    return jobs


# ── Deduplication ────────────────────────────────────────────

def deduplicate(jobs):
    """Remove duplicate listings based on normalised title + company."""
    seen = set()
    unique = []
    for job in jobs:
        key = (job["title"].lower().strip(), job["company"].lower().strip())
        if key not in seen:
            seen.add(key)
            unique.append(job)
    removed = len(jobs) - len(unique)
    if removed:
        print(f"  Deduplicated: removed {removed} duplicates")
    return unique


# ── Claude matching ──────────────────────────────────────────

def score_jobs_with_claude(profile, jobs):
    """Send profile + jobs to Claude for semantic scoring."""
    if not jobs:
        return []

    client = anthropic.Anthropic()

    # Build a compact listing summary for Claude
    listings_text = ""
    for i, job in enumerate(jobs):
        salary = ""
        if job.get("salary_min") and job.get("salary_max"):
            salary = f" | Salary: {job['salary_min']}–{job['salary_max']}"
        elif job.get("salary_min"):
            salary = f" | Salary: from {job['salary_min']}"

        listings_text += (
            f"\n[{i}] {job['title']} at {job['company']}"
            f" | {job['location']}{salary}"
            f" | Type: {job['type']}"
            f" | Posted: {job['posted_date']}"
            f"\nDescription: {job['description'][:300]}\n"
        )

    profile_text = (
        f"Name: {profile['name']}\n"
        f"Target location: {profile['location']}\n"
        f"Skills: {', '.join(profile['skills'])}\n"
        f"Target titles: {', '.join(profile['titles'])}\n"
        f"Experience: {profile['experience_years']} years\n"
        f"Education: {profile['education']}\n"
        f"Summary: {profile['summary']}\n"
        f"Work type preference: {WORK_TYPE}"
    )

    prompt = f"""You are a job matching assistant. Score each listing against the candidate profile.

CANDIDATE PROFILE:
{profile_text}

JOB LISTINGS:
{listings_text}

INSTRUCTIONS:
- Score each listing 0–100 based on: skill overlap, title relevance, location match, experience level fit.
- Treat "job" and "internship" types as separate categories — do not penalise internships for lacking seniority.
- Only return listings scoring {MIN_SCORE} or above.
- Rank highest first within each category (jobs first, then internships).
- For each match, provide a 2–3 sentence description summarised from the listing.
- If the listing mentions a deadline or closing date, include it. Otherwise set deadline to null.

Return ONLY valid JSON (no markdown fences), as an array:
[
  {{
    "index": <int, the [N] index from above>,
    "type": "job" or "internship",
    "title": "...",
    "company": "...",
    "location": "...",
    "description": "2–3 sentence summary",
    "deadline": "YYYY-MM-DD or null",
    "score": <int 0–100>,
    "posted_date": "YYYY-MM-DD"
  }}
]

If no listings score above {MIN_SCORE}, return an empty array: []"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = message.content[0].text.strip()

    # Strip markdown fences
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1]
    if response_text.endswith("```"):
        response_text = response_text.rsplit("```", 1)[0]
    response_text = response_text.strip()

    try:
        scored = json.loads(response_text)
    except json.JSONDecodeError:
        print("  Error: Claude returned invalid JSON for scoring.")
        print(f"  Raw response: {response_text[:500]}")
        return []

    # Attach apply_url from original listings
    for match in scored:
        idx = match.get("index", -1)
        if 0 <= idx < len(jobs):
            match["apply_url"] = jobs[idx]["apply_url"]
        else:
            match["apply_url"] = ""

    # Split and cap
    job_matches = [m for m in scored if m.get("type") == "job"]
    intern_matches = [m for m in scored if m.get("type") == "internship"]

    job_matches.sort(key=lambda x: x.get("score", 0), reverse=True)
    intern_matches.sort(key=lambda x: x.get("score", 0), reverse=True)

    combined = job_matches[:MAX_EMAIL_JOBS] + intern_matches[:MAX_EMAIL_JOBS]
    return combined


# ── Email formatting ─────────────────────────────────────────

def format_email_html(profile, matches):
    """Build a clean HTML email digest."""
    today = datetime.now(timezone.utc).strftime("%d %B %Y")
    name = profile["name"].split()[0]  # First name

    job_matches = [m for m in matches if m.get("type") == "job"]
    intern_matches = [m for m in matches if m.get("type") == "internship"]
    total = len(matches)

    def job_card(match: dict):
        score = match.get("score", 0)
        score_color = "#16a34a" if score >= 80 else "#d97706" if score >= 65 else "#6b7280"
        deadline = match.get("deadline")
        posted = match.get("posted_date", "")

        deadline_html = ""
        if deadline:
            deadline_html = f'<tr><td style="padding:2px 0;color:#6b7280;font-size:13px;">Deadline</td><td style="padding:2px 0 2px 12px;font-size:13px;">{deadline}</td></tr>'
        elif posted:
            try:
                posted_dt = datetime.strptime(posted, "%Y-%m-%d")
                days_ago = (datetime.now() - posted_dt).days
                if days_ago >= 5:
                    deadline_html = f'<tr><td style="padding:2px 0;color:#6b7280;font-size:13px;">Posted</td><td style="padding:2px 0 2px 12px;font-size:13px;">⚠ {days_ago} days ago — apply soon</td></tr>'
            except ValueError:
                pass

        return f"""
        <div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:16px;margin-bottom:12px;">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                <div>
                    <div style="font-size:16px;font-weight:600;color:#111827;">{match.get('title', '')}</div>
                    <div style="font-size:14px;color:#6b7280;margin-top:2px;">{match.get('company', '')} · {match.get('location', '')}</div>
                </div>
                <div style="background:{score_color};color:white;border-radius:16px;padding:2px 10px;font-size:13px;font-weight:600;white-space:nowrap;">{score}%</div>
            </div>
            <div style="font-size:13px;color:#374151;margin-top:10px;line-height:1.5;">{match.get('description', '')}</div>
            <table style="margin-top:8px;">
                {deadline_html}
            </table>
            <a href="{match.get('apply_url', '#')}" style="display:inline-block;margin-top:10px;background:#2563eb;color:white;text-decoration:none;padding:6px 16px;border-radius:6px;font-size:13px;font-weight:500;">Apply →</a>
        </div>"""

    # Build sections
    jobs_section = ""
    if job_matches:
        jobs_section = f"""
        <div style="margin-top:24px;">
            <div style="font-size:14px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:1px;border-bottom:2px solid #e5e7eb;padding-bottom:6px;margin-bottom:16px;">
                Jobs ({len(job_matches)})
            </div>
            {''.join(job_card(m) for m in job_matches)}
        </div>"""

    internships_section = ""
    if intern_matches:
        internships_section = f"""
        <div style="margin-top:24px;">
            <div style="font-size:14px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:1px;border-bottom:2px solid #e5e7eb;padding-bottom:6px;margin-bottom:16px;">
                Internships ({len(intern_matches)})
            </div>
            {''.join(job_card(m) for m in intern_matches)}
        </div>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#ffffff;margin:0;padding:0;">
<div style="max-width:600px;margin:0 auto;padding:24px;">
    <div style="text-align:center;margin-bottom:24px;">
        <div style="font-size:22px;font-weight:700;color:#111827;">🎯 JobRadar</div>
        <div style="font-size:13px;color:#9ca3af;margin-top:4px;">{today}</div>
    </div>

    <div style="font-size:15px;color:#374151;margin-bottom:8px;">
        Hi {name},
    </div>
    <div style="font-size:15px;color:#374151;margin-bottom:20px;">
        {"Here are today's top matches based on your profile. You decide what to apply to." if total > 0 else "No strong matches found today. I'll keep looking tomorrow."}
    </div>

    {jobs_section}
    {internships_section}

    <div style="margin-top:32px;padding-top:16px;border-top:1px solid #e5e7eb;font-size:12px;color:#9ca3af;text-align:center;">
        To update your preferences, edit config.py and push to GitHub.<br>
        To stop receiving emails, disable the GitHub Actions workflow.
    </div>
</div>
</body>
</html>"""

    return html


def format_email_plain(profile, matches):
    """Build a plain text fallback."""
    today = datetime.now(timezone.utc).strftime("%d %B %Y")
    name = profile["name"].split()[0]
    job_matches = [m for m in matches if m.get("type") == "job"]
    intern_matches = [m for m in matches if m.get("type") == "internship"]

    lines = [
        f"JobRadar — {today}",
        f"\nHi {name},\n",
    ]

    if not matches:
        lines.append("No strong matches found today. I'll keep looking tomorrow.\n")
        return "\n".join(lines)

    lines.append("Here are today's top matches:\n")

    if job_matches:
        lines.append(f"━━━ JOBS ({len(job_matches)}) ━━━\n")
        for m in job_matches:
            lines.append(f"  {m.get('title', '')}")
            lines.append(f"  {m.get('company', '')} · {m.get('location', '')}")
            lines.append(f"  {m.get('description', '')}")
            if m.get("deadline"):
                lines.append(f"  Deadline: {m['deadline']}")
            lines.append(f"  Match: {m.get('score', 0)}%")
            lines.append(f"  Apply: {m.get('apply_url', '')}")
            lines.append("")

    if intern_matches:
        lines.append(f"━━━ INTERNSHIPS ({len(intern_matches)}) ━━━\n")
        for m in intern_matches:
            lines.append(f"  {m.get('title', '')}")
            lines.append(f"  {m.get('company', '')} · {m.get('location', '')}")
            lines.append(f"  {m.get('description', '')}")
            if m.get("deadline"):
                lines.append(f"  Deadline: {m['deadline']}")
            lines.append(f"  Match: {m.get('score', 0)}%")
            lines.append(f"  Apply: {m.get('apply_url', '')}")
            lines.append("")

    return "\n".join(lines)


# ── Email sending ────────────────────────────────────────────

def send_email(profile, matches):
    """Send the digest via Gmail SMTP."""
    email = profile["email"]
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not gmail_password:
        print("  Error: GMAIL_APP_PASSWORD not set.")
        sys.exit(1)

    target_role = profile.get("target_role", "Software Engineer")
    total = len(matches)
    today = datetime.now(timezone.utc).strftime("%d %B %Y")
    subject = f"🎯 {total} new opportunities — {target_role} · {today}"
    if total == 0:
        subject = f"JobRadar — No strong matches today · {today}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email
    msg["To"] = email

    msg.attach(MIMEText(format_email_plain(profile, matches), "plain"))
    msg.attach(MIMEText(format_email_html(profile, matches), "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(email, gmail_password)
            server.send_message(msg)
        print(f"  Email sent to {email}")
    except smtplib.SMTPException as e:
        print(f"  Error sending email: {e}")
        sys.exit(1)


# ── Main ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="JobRadar daily scout")
    parser.add_argument("--dry-run", action="store_true", help="Print digest to console instead of emailing")
    args = parser.parse_args()

    print("\n  JobRadar — Daily Scout")
    print("  " + "─" * 36)

    # Load profile
    profile = load_profile()
    target_role = profile.get("target_role", "Software Engineer")
    print(f"  Profile: {profile['name']} | {profile['location']} | {target_role}")
    print(f"  Skills: {len(profile['skills'])} detected")

    # Fetch jobs
    print(f"\n  Fetching {target_role} listings...\n")
    all_jobs = []
    all_jobs.extend(fetch_all_adzuna_jobs(profile))
    all_jobs.extend(fetch_remotive_jobs(profile))

    if not all_jobs:
        print("  No listings found from any source.")
        if not args.dry_run:
            send_email(profile, [])
        return

    # Deduplicate
    all_jobs = deduplicate(all_jobs)
    print(f"\n  Total unique listings: {len(all_jobs)}")

    # Score with Claude
    print("  Scoring with Claude...\n")
    matches = score_jobs_with_claude(profile, all_jobs)

    job_count = len([m for m in matches if m.get("type") == "job"])
    intern_count = len([m for m in matches if m.get("type") == "internship"])
    print(f"  Matches: {job_count} jobs, {intern_count} internships (score >= {MIN_SCORE})")

    # Send or print
    if args.dry_run:
        print("\n  ── DRY RUN (email preview) ──\n")
        print(format_email_plain(profile, matches))
    else:
        print("\n  Sending email digest...")
        send_email(profile, matches)

    print("\n  Done.\n")


if __name__ == "__main__":
    main()
