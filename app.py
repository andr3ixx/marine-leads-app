"""
Streamlit front end for the lead engine.

Deliberately simple per the brief ("not a polished app yet" — but since this
round explicitly asked for an app, this is the minimum useful shape of one):
upload a CSV -> run -> review/edit in a table, grouped by lead status ->
export. Processes leads ONE AT A TIME (not concurrently) to stay inside
Streamlit Community Cloud's free 1GB RAM limit with a real browser involved.
"""

import asyncio
import io
import json
import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st
from groq import Groq
from playwright.async_api import async_playwright

from engine.niches import NICHE_PROFILES, DEFAULT_NICHE
from engine.pipeline import OUTPUT_FIELDS, run_lead

st.set_page_config(page_title="Marine Lead Engine", page_icon="⚓", layout="wide")


@st.cache_resource
def ensure_chromium_installed():
    """Streamlit Community Cloud has no post-deploy hook besides
    requirements.txt/packages.txt, so the Playwright browser binary itself
    has to be fetched at runtime. Cached so it only runs once per container
    lifetime, not on every script rerun."""
    import subprocess
    result = subprocess.run(
        ["playwright", "install", "chromium"],
        capture_output=True, text=True, timeout=300,
    )
    return result.returncode == 0, result.stdout + result.stderr


_chromium_ok, _chromium_log = ensure_chromium_installed()
if not _chromium_ok:
    st.error("Failed to install the Chromium browser binary. See logs below.")
    st.code(_chromium_log)
    st.stop()


STATUS_ORDER = ["Pursue", "Manual review", "Maybe", "Skip"]
STATUS_COLOR = {
    "Pursue": "🟢",
    "Maybe": "🟡",
    "Manual review": "🟠",
    "Skip": "⚪",
}


def get_groq_key() -> str:
    if "GROQ_API_KEY" in st.secrets:
        return st.secrets["GROQ_API_KEY"]
    return os.environ.get("GROQ_API_KEY", "")


def get_psi_key() -> str:
    if "GOOGLE_PSI_API_KEY" in st.secrets:
        return st.secrets["GOOGLE_PSI_API_KEY"]
    return os.environ.get("GOOGLE_PSI_API_KEY", "")


async def process_batch(leads, niche_key, check_speed, screenshot_dir, groq_key, progress_cb):
    os.environ["GOOGLE_PSI_API_KEY"] = get_psi_key()  # so engine.speed picks it up
    groq_client = Groq(api_key=groq_key)
    rows = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            for idx, lead in enumerate(leads, start=1):
                company = str(lead.get("Company Name", "")).strip()
                website = str(lead.get("Website", "")).strip()
                progress_cb(idx, len(leads), company)
                row = await run_lead(
                    browser=browser,
                    groq_client=groq_client,
                    company=company,
                    website=website,
                    idx=idx,
                    niche_key=niche_key,
                    screenshot_dir=screenshot_dir,
                    check_speed=check_speed,
                )
                rows.append(row)
        finally:
            await browser.close()
    return rows


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------- session state
if "results" not in st.session_state:
    st.session_state.results = []
if "screenshot_dir" not in st.session_state:
    st.session_state.screenshot_dir = tempfile.mkdtemp(prefix="leads_shots_")

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("⚓ Setup")
    niche_key = st.selectbox(
        "Niche profile",
        options=list(NICHE_PROFILES.keys()),
        format_func=lambda k: NICHE_PROFILES[k].label,
        index=list(NICHE_PROFILES.keys()).index(DEFAULT_NICHE),
        help="Scoring weights and outreach language change per niche.",
    )
    check_speed = st.checkbox(
        "Check page speed (PageSpeed Insights)",
        value=False,
        help="Optional, adds ~10-20s per lead. Needs GOOGLE_PSI_API_KEY in secrets for a usable quota.",
    )
    groq_key_input = st.text_input(
        "Groq API key",
        value=get_groq_key(),
        type="password",
        help="Stored in st.secrets on Streamlit Cloud, or paste it here for a local test run.",
    )
    st.caption("Free key: console.groq.com/keys")
    st.divider()
    st.caption(
        "Processes leads one at a time to stay under Streamlit Community Cloud's "
        "1GB free-tier memory limit. A batch of 50 leads will take a while — that's expected."
    )

st.title("Marine Outreach Lead Engine")
st.caption("CSV in → scrape, score, draft outreach → reviewed CSV out.")

# ---------------------------------------------------------------- upload
uploaded = st.file_uploader("Upload leads CSV (needs 'Company Name' and 'Website' columns)", type="csv")

leads_df = None
if uploaded is not None:
    leads_df = pd.read_csv(uploaded)
    missing = {"Company Name", "Website"} - set(leads_df.columns)
    if missing:
        st.error(f"CSV is missing required column(s): {', '.join(missing)}")
        leads_df = None
    else:
        st.success(f"Loaded {len(leads_df)} lead(s).")
        st.dataframe(leads_df.head(10), use_container_width=True)

run_clicked = st.button(
    "Run pipeline",
    type="primary",
    disabled=leads_df is None or not groq_key_input,
)
if leads_df is not None and not groq_key_input:
    st.warning("Add a Groq API key in the sidebar to run the pipeline.")

if run_clicked and leads_df is not None:
    leads = leads_df.to_dict("records")
    progress_bar = st.progress(0.0)
    status_text = st.empty()

    def progress_cb(idx, total, company):
        progress_bar.progress(idx / total)
        status_text.text(f"[{idx}/{total}] Processing {company}…")

    with st.spinner("Running pipeline — this can take a while for larger batches…"):
        rows = run_async(process_batch(
            leads, niche_key, check_speed,
            Path(st.session_state.screenshot_dir), groq_key_input, progress_cb,
        ))
    st.session_state.results = rows
    status_text.text(f"Done. Processed {len(rows)} lead(s).")

# ---------------------------------------------------------------- results
if st.session_state.results:
    results_df = pd.DataFrame(st.session_state.results)

    st.subheader("Results")
    counts = results_df["Lead Status"].value_counts()
    cols = st.columns(len(STATUS_ORDER))
    for col, status in zip(cols, STATUS_ORDER):
        col.metric(f"{STATUS_COLOR.get(status, '')} {status}", int(counts.get(status, 0)))

    tabs = st.tabs(["All"] + STATUS_ORDER)
    for tab, status_filter in zip(tabs, ["All"] + STATUS_ORDER):
        with tab:
            df_view = results_df if status_filter == "All" else results_df[results_df["Lead Status"] == status_filter]
            if df_view.empty:
                st.caption("No leads in this category.")
                continue

            edited = st.data_editor(
                df_view[[
                    "Company Name", "Website", "Lead Status", "Overall Score",
                    "Main Issue", "Best Outreach Angle", "Recommended Offer",
                    "Email Found", "Email Needs Verification", "Phone Found",
                    "Error",
                ]],
                use_container_width=True,
                num_rows="fixed",
                key=f"editor_{status_filter}",
            )

            for _, lead_row in df_view.iterrows():
                with st.expander(f"{lead_row['Company Name']} — {lead_row['Website']}"):
                    shot_cols = st.columns(2)
                    if lead_row.get("Desktop Screenshot Path") and Path(lead_row["Desktop Screenshot Path"]).exists():
                        shot_cols[0].image(lead_row["Desktop Screenshot Path"], caption="Desktop")
                    if lead_row.get("Mobile Screenshot Path") and Path(lead_row["Mobile Screenshot Path"]).exists():
                        shot_cols[1].image(lead_row["Mobile Screenshot Path"], caption="Mobile")

                    st.markdown("**Email draft**")
                    st.text_area(
                        "Email", value=lead_row.get("Email Draft", ""), height=160,
                        key=f"email_{lead_row['Company Name']}_{status_filter}", label_visibility="collapsed",
                    )

                    try:
                        talking_points = json.loads(lead_row.get("Video Talking Points") or "[]")
                    except json.JSONDecodeError:
                        talking_points = []
                    if talking_points:
                        st.markdown("**Loom talking points**")
                        for point in talking_points:
                            st.markdown(f"- {point}")

                    if lead_row.get("Verification Warnings"):
                        st.warning(lead_row["Verification Warnings"])
                    if lead_row.get("Error"):
                        st.error(lead_row["Error"])

    st.divider()
    csv_buffer = io.StringIO()
    results_df.to_csv(csv_buffer, index=False)
    st.download_button(
        "Download reviewed_leads.csv",
        data=csv_buffer.getvalue(),
        file_name="reviewed_leads.csv",
        mime="text/csv",
        type="primary",
    )
