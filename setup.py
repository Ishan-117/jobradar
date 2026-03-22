#!/usr/bin/env python3
"""
JobRadar — One-time setup
Run this once to parse your resume and generate profile.json.
Re-run it any time your resume changes.

Usage:
    python setup.py
    python setup.py --resume path/to/resume.pdf
"""

import argparse
import json
import os
import sys
from pathlib import Path

import anthropic
import pdfplumber


PROFILE_PATH = Path(__file__).parent / "profile.json"


# ── Resume text extraction ──────────────────────────────────

def extract_text_from_pdf(pdf_path):
    """Extract all text from a PDF using pdfplumber."""
    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    full_text = "\n\n".join(text_parts)
    if not full_text.strip():
        print("Error: Could not extract any text from the PDF.")
        print("Make sure it's not a scanned image — pdfplumber needs selectable text.")
        sys.exit(1)
    return full_text


# ── Claude-powered profile extraction ───────────────────────

def parse_resume_with_claude(resume_text):
    """Send resume text to Claude and get structured profile data back."""
    client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY env var

    prompt = f"""Extract the following from this resume and return ONLY valid JSON, no markdown fences, no explanation:

{{
  "skills": ["list of technical and soft skills found"],
  "titles": ["job titles held or being targeted"],
  "target_role": "the single best job title to search for, based on their most recent role and career trajectory",
  "experience_years": <integer, total years of professional experience>,
  "education": "highest degree and field, e.g. BSc Computer Science",
  "summary": "one sentence profile summary for job matching"
}}

Rules:
- For skills, include programming languages, frameworks, tools, methodologies, and relevant soft skills.
- For titles, include both titles the person has held AND titles they appear to be targeting.
- For target_role, pick the single most relevant job title to search job boards with. Base it on their most recent experience and apparent career direction. Keep it general enough to get good results (e.g. "Software Engineer" not "Senior Full Stack React/Node Engineer"). Just the title, no seniority prefix.
- If experience years are unclear, estimate from the date ranges on the resume.
- Keep the summary factual and concise — it will be used to match against job descriptions.

Resume text:
{resume_text}"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = message.content[0].text.strip()

    # Strip markdown fences if Claude adds them despite instructions
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1]
    if response_text.endswith("```"):
        response_text = response_text.rsplit("```", 1)[0]
    response_text = response_text.strip()

    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        print("Error: Claude returned invalid JSON. Raw response:")
        print(response_text)
        sys.exit(1)


# ── Interactive setup ────────────────────────────────────────

def collect_user_info(resume_path=None):
    """Prompt the user for name, email, location, and resume path."""
    print("\n╔══════════════════════════════════════╗")
    print("║     JobRadar — One-time setup        ║")
    print("╚══════════════════════════════════════╝\n")

    name = input("  Your name: ").strip()
    if not name:
        print("  Name is required.")
        sys.exit(1)

    email = input("  Your email address: ").strip()
    if not email or "@" not in email:
        print("  A valid email is required.")
        sys.exit(1)

    location = input("  Target location (city, country, or continent): ").strip()
    if not location:
        print("  Location is required.")
        sys.exit(1)

    if not resume_path:
        resume_path = input("  Path to your resume PDF: ").strip()
    if not resume_path or not Path(resume_path).exists():
        print(f"  File not found: {resume_path}")
        sys.exit(1)

    return name, email, location, resume_path


def main():
    parser = argparse.ArgumentParser(description="JobRadar setup — parse your resume")
    parser.add_argument("--resume", type=str, help="Path to resume PDF")
    args = parser.parse_args()

    # Check for API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set.")
        print("  export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    # Collect info
    name, email, location, resume_path = collect_user_info(args.resume)

    # Extract text
    print(f"\n  Extracting text from {resume_path}...")
    resume_text = extract_text_from_pdf(resume_path)
    print(f"  Extracted {len(resume_text):,} characters from {resume_path}")

    # Parse with Claude
    print("  Parsing resume with Claude...")
    parsed = parse_resume_with_claude(resume_text)

    # Build profile
    profile = {
        "name": name,
        "email": email,
        "location": location,
        "target_role": parsed.get("target_role", "Software Engineer"),
        "skills": parsed.get("skills", []),
        "titles": parsed.get("titles", []),
        "experience_years": parsed.get("experience_years", 0),
        "education": parsed.get("education", ""),
        "summary": parsed.get("summary", ""),
    }

    # Save
    with open(PROFILE_PATH, "w") as f:
        json.dump(profile, f, indent=2)

    # Confirm
    print(f"\n  Profile saved to {PROFILE_PATH}\n")
    print(f"  Name:        {profile['name']}")
    print(f"  Email:       {profile['email']}")
    print(f"  Location:    {profile['location']}")
    print(f"  Target role: {profile['target_role']}")
    print(f"  Skills:      {', '.join(profile['skills'][:8])}{'...' if len(profile['skills']) > 8 else ''}")
    print(f"  Titles:      {', '.join(profile['titles'])}")
    print(f"  Experience:  {profile['experience_years']} years")
    print(f"  Education:   {profile['education']}")
    print(f"  Summary:     {profile['summary'][:80]}...")
    print(f"\n  Next step: test with `python daily_scout.py`\n")


if __name__ == "__main__":
    main()
