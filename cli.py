#!/usr/bin/env python3
"""
CLI batch runner — same engine as the Streamlit app, no UI.
Useful for headless/scheduled runs (e.g. a GitHub Actions workflow) once the
app version has been validated.

Usage:
    export GROQ_API_KEY="your_key_here"
    python cli.py --input raw_leads.csv --output reviewed_leads.csv --niche fishing_charter
"""

import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path

from groq import Groq
from playwright.async_api import async_playwright

from engine.niches import NICHE_PROFILES, DEFAULT_NICHE
from engine.pipeline import OUTPUT_FIELDS, run_lead

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


async def run(input_csv: str, output_csv: str, niche_key: str, check_speed: bool, screenshot_dir: Path):
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        print("ERROR: GROQ_API_KEY is not set. export GROQ_API_KEY=... or add it to .env")
        sys.exit(1)

    if not Path(input_csv).exists():
        print(f"ERROR: '{input_csv}' not found.")
        sys.exit(1)

    with open(input_csv, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        leads = [row for row in reader if row.get("Company Name") or row.get("Website")]

    print(f"Loaded {len(leads)} lead(s) from '{input_csv}' — niche: {NICHE_PROFILES[niche_key].label}")
    screenshot_dir.mkdir(exist_ok=True, parents=True)

    groq_client = Groq(api_key=groq_key)
    rows = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            for idx, lead in enumerate(leads, 1):
                company = lead.get("Company Name", "").strip()
                website = lead.get("Website", "").strip()
                print(f"\n[{idx}/{len(leads)}] {company} — {website}")
                row = await run_lead(
                    browser=browser, groq_client=groq_client, company=company, website=website,
                    idx=idx, niche_key=niche_key, screenshot_dir=screenshot_dir, check_speed=check_speed,
                )
                status = row.get("Lead Status", "")
                print(f"  -> {status} (score {row.get('Overall Score', '')}) {row.get('Error', '')}")
                rows.append(row)
        finally:
            await browser.close()

    with open(output_csv, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    pursue = sum(1 for r in rows if r.get("Lead Status") == "Pursue")
    print(f"\nDone. {len(rows)} processed, {pursue} marked Pursue. Saved to '{output_csv}'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="raw_leads.csv")
    parser.add_argument("--output", default="reviewed_leads.csv")
    parser.add_argument("--niche", default=DEFAULT_NICHE, choices=list(NICHE_PROFILES.keys()))
    parser.add_argument("--check-speed", action="store_true")
    parser.add_argument("--screenshot-dir", default="screenshots")
    args = parser.parse_args()
    asyncio.run(run(args.input, args.output, args.niche, args.check_speed, Path(args.screenshot_dir)))
