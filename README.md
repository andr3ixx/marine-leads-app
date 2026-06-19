# Marine Outreach Lead Engine

CSV in → visit each site → screenshot desktop + mobile → detect tech stack →
crawl for contact details → score the lead (niche-aware) → draft outreach →
CSV out. Now wrapped in a small web app for upload/review/export.

## What changed from the v1 script

- **Niche profiles** (`engine/niches.py`) — `fishing_charter` and
  `general_charter` for now, each with its own scoring weights and outreach
  voice. New niches can be added later without touching anything else.
- **Visual AI review** — screenshots (desktop *and* mobile) are sent straight
  to Groq's vision model alongside the page text, so design quality (the
  biggest lever per the brief) is part of the actual scoring, not an
  afterthought.
- **Contact discovery** (`engine/contacts.py`) — crawls the homepage plus a
  few likely internal pages (contact/about/team/etc.), pulls mailto links,
  visible and obfuscated emails, phones, and socials, classifies each email,
  and flags anything that needs manual verification before sending.
- **Weighted lead scoring** (`engine/scoring.py`) — combines sub-scores using
  the weighting from the brief (visual 35% / inquiry flow 20% / local SEO 15%
  / technical 10% / commercial 10% / trust 10%) into one overall score, and a
  Pursue / Maybe / Skip / Manual review status.
- **Optional page speed check** via PageSpeed Insights — off by default,
  reported in plain language rather than raw Lighthouse jargon.
- **Richer output CSV** — matches the field list from the brief (scores per
  dimension, email + confidence + source, phone, social links, screenshot
  paths, recommended offer, etc.)
- **A small web app** (`app.py`, Streamlit) — upload a CSV, pick a niche, run
  it, review results grouped by status, edit inline, export.

The original CLI workflow still exists (`cli.py`) for headless/batch runs —
same engine, no UI, useful if you ever want to run this on a schedule.

## Local setup

```bash
pip install -r requirements.txt
playwright install chromium
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # then add your real GROQ_API_KEY
streamlit run app.py
```

Or for the no-UI batch version:

```bash
export GROQ_API_KEY="your_key_here"
python cli.py --input raw_leads.csv --output reviewed_leads.csv --niche fishing_charter
```

## Deploying for free: GitHub + Streamlit Community Cloud

This is the path I'd recommend over Firebase Hosting or Hostinger shared
hosting — neither of those can run Python/Playwright at all (Firebase Hosting
is static-files-only; Hostinger shared hosting doesn't support installing
Python packages). Streamlit Community Cloud deploys straight from a GitHub
repo and is free, and Playwright does run there with two adjustments already
baked into this repo:

1. **Push this repo to GitHub.**
   ```bash
   git add .
   git commit -m "Marine lead engine v2"
   git remote add origin https://github.com/<your-username>/<repo-name>.git
   git push -u origin main
   ```
   A public repo is the simplest path on the free tier. If you'd rather keep
   it private, Streamlit Cloud does support deploying private repos for
   individual accounts too — check the current limits on your account when
   you connect it, since this changes from time to time.

2. **Go to [share.streamlit.io](https://share.streamlit.io)**, sign in with
   GitHub, and click "New app." Point it at your repo, branch `main`, file
   `app.py`.

3. **Add your secrets.** In the app's settings → Secrets, paste:
   ```toml
   GROQ_API_KEY = "your_real_key"
   GOOGLE_PSI_API_KEY = ""
   ```

4. **Deploy.** First boot will be slow (installing the system packages from
   `packages.txt` plus the Chromium binary via the in-app install hook) — give
   it a few minutes.

### Why the two pins matter

- `requirements.txt` pins `playwright==1.49.0`. Newer Playwright releases
  expect system libraries that Streamlit Cloud's Debian image doesn't ship.
  If you move this to your own VPS or a Docker-based host later, you can
  drop the pin.
- The app calls `playwright install chromium` at runtime (cached, so it only
  happens once per container) because Streamlit Cloud has no other post-deploy
  hook to fetch browser binaries.

### Free tier limits to plan around

- **1GB RAM.** A headless Chromium instance plus the Python process isn't
  huge, but it isn't nothing either — this is why the app processes leads
  **one at a time**, not in parallel. Don't try to "speed it up" by running
  multiple browser contexts concurrently on the free tier; you'll hit the
  memory ceiling and the app will crash with a resource-limit error.
- **No background jobs.** The app blocks while a batch runs. For the 20-100
  lead batches in scope right now that's fine; if you eventually want to kick
  off a 200-lead run and walk away, that's a sign to move to something with
  real background workers (Cloud Run, a VPS with a queue) — not a Streamlit
  Cloud problem to solve.
- **Container sleeps when idle**, and local files (screenshots) don't persist
  across restarts. That's fine for a review-then-export workflow; it's not a
  place to store anything long-term.

## If you outgrow this

The brief's own roadmap already says not to build a CRM, Gmail integration,
or full SaaS dashboard yet — agreed. If this gets used heavily enough that
Streamlit Cloud's limits start to bite (longer batches, more concurrent
users, needing results to persist), the next step is Google Cloud Run (still
free at the volumes described in the success-test section: 100-200 leads) with
the screenshots/results stored in Cloud Storage/Firestore instead of local
disk — not a rewrite, just swapping where state lives.

## Repo structure

```
engine/
  niches.py        # niche profiles: scoring weights + AI prompt language
  scraper.py        # Playwright: desktop + mobile screenshots, contact-page crawl
  contacts.py        # email/phone/social extraction + classification
  tech_stack.py        # tech fingerprinting (carried over from v1)
  speed.py        # optional PageSpeed Insights check
  ai_analysis.py        # Groq vision call -> structured LeadAnalysis
  scoring.py        # weighted score -> Pursue/Maybe/Skip/Manual review
  pipeline.py        # orchestrates all of the above into one output row
app.py        # Streamlit app
cli.py        # headless batch runner, same engine
tests/        # unit tests for the pure-logic pieces (no network needed)
```
