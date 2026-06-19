"""
Digital Deckhand — Internal Lead CRM.

Scrape, score, manage, and close marine leads from one place.
Backed by a local SQLite store that persists across sessions.
"""

import asyncio
import base64
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
from engine.pipeline import OUTPUT_FIELDS, run_lead, regenerate_email
from engine import leads_store
from engine.leads_store import PIPELINE_STATUSES

# ---------------------------------------------------------------- page config
ASSETS = Path(__file__).parent / "assets"
FAVICON = str(ASSETS / "favicon.png")

st.set_page_config(
    page_title="Digital Deckhand CRM",
    page_icon=FAVICON,
    layout="wide",
)

# ---------------------------------------------------------------- session state
if "dark_mode" not in st.session_state:
    st.session_state.dark_mode = True
if "screenshot_dir" not in st.session_state:
    st.session_state.screenshot_dir = tempfile.mkdtemp(prefix="leads_shots_")
if "selected_website" not in st.session_state:
    st.session_state.selected_website = None
if "import_confirmed" not in st.session_state:
    st.session_state.import_confirmed = False

# ---------------------------------------------------------------- theme CSS
_FONTS = (
    "@import url('https://fonts.googleapis.com/css2?"
    "family=Inter:wght@400;500;600&family=Space+Grotesk:wght@500;600;700&display=swap');"
)

_BASE_CSS = """
*, body, [class*="css"] { font-family: 'Inter', sans-serif !important; }
h1, h2, h3, h4, h5, h6, [data-testid="stMetricValue"] {
    font-family: 'Space Grotesk', sans-serif !important;
    font-weight: 600 !important;
}
.block-container {
    padding-top: 1.2rem !important;
    padding-bottom: 1rem !important;
    max-width: 1280px !important;
}
[data-testid="stSidebar"] .block-container { padding-top: 0.5rem !important; }
section[data-testid="stSidebar"] > div:first-child { padding-top: 0.5rem !important; }
.stTabs [data-baseweb="tab-panel"] { padding-top: 0.75rem !important; }
[data-testid="stMetric"] {
    border-radius: 8px;
    padding: 12px 16px !important;
}
/* tighten spacing */
[data-testid="stVerticalBlockBorderWrapper"] > div {
    gap: 0.6rem !important;
}
.stExpander { border-radius: 8px !important; }
"""

_DARK_COLORS = """
:root { color-scheme: dark; }
.stApp, [data-testid="stAppViewContainer"] {
    background-color: #0B1120 !important; color: #E0E6ED !important;
}
[data-testid="stSidebar"] { background-color: #101D32 !important; }
[data-testid="stHeader"] { background-color: #0B1120 !important; }
h1,h2,h3,h4,h5,h6,p,span,label,.stMarkdown,
[data-testid="stMetricValue"],[data-testid="stMetricLabel"],
.stSelectbox label,.stTextInput label,.stCheckbox label,
.stNumberInput label, .stTextArea label {
    color: #E0E6ED !important;
}
.stButton>button[kind="primary"],.stDownloadButton>button[kind="primary"] {
    background-color: #F0C430 !important; color: #0B1120 !important; border:none !important;
    font-weight:600 !important;
}
.stButton>button[kind="primary"]:hover,.stDownloadButton>button[kind="primary"]:hover {
    background-color: #D4AB20 !important;
}
.stButton>button:not([kind="primary"]) {
    border-color: #1F3A5F !important; color: #E0E6ED !important;
}
.stTabs [data-baseweb="tab"] { color: #E0E6ED !important; }
.stTabs [aria-selected="true"] {
    border-bottom-color: #F0C430 !important; color: #F0C430 !important;
}
[data-testid="stMetric"] { background-color: #111B2E !important; }
.stExpander { border-color: #1A2D4A !important; }
[data-testid="stExpander"] details { border-color: #1A2D4A !important; }
a { color: #F0C430 !important; }
.stCaption,.stCaption p { color: #7A8BA0 !important; }
hr { border-color: #1A2D4A !important; }
/* detail card */
.detail-card {
    background: #111B2E; border: 1px solid #1A2D4A; border-radius: 10px;
    padding: 1.5rem; margin-top: 0.5rem;
}
"""

_LIGHT_COLORS = """
:root { color-scheme: light; }
.stApp, [data-testid="stAppViewContainer"] {
    background-color: #F6F8FB !important; color: #1A1A2E !important;
}
[data-testid="stSidebar"] { background-color: #E8ECF4 !important; }
[data-testid="stHeader"] { background-color: #F6F8FB !important; }
h1,h2,h3,h4,h5,h6,p,span,label,.stMarkdown,
[data-testid="stMetricValue"],[data-testid="stMetricLabel"],
.stSelectbox label,.stTextInput label,.stCheckbox label,
.stNumberInput label, .stTextArea label {
    color: #1A1A2E !important;
}
.stButton>button[kind="primary"],.stDownloadButton>button[kind="primary"] {
    background-color: #102A43 !important; color: #F0C430 !important; border:none !important;
    font-weight:600 !important;
}
.stButton>button[kind="primary"]:hover,.stDownloadButton>button[kind="primary"]:hover {
    background-color: #1A3A5C !important;
}
.stButton>button:not([kind="primary"]) {
    border-color: #102A43 !important; color: #102A43 !important;
}
.stTabs [data-baseweb="tab"] { color: #1A1A2E !important; }
.stTabs [aria-selected="true"] {
    border-bottom-color: #102A43 !important; color: #102A43 !important;
}
[data-testid="stMetric"] { background-color: #E8ECF4 !important; }
.stExpander { border-color: #D0D5E0 !important; }
[data-testid="stExpander"] details { border-color: #D0D5E0 !important; }
a { color: #102A43 !important; }
.stCaption,.stCaption p { color: #6B7280 !important; }
hr { border-color: #D0D5E0 !important; }
.detail-card {
    background: #FFFFFF; border: 1px solid #D0D5E0; border-radius: 10px;
    padding: 1.5rem; margin-top: 0.5rem;
}
"""

_theme_css = _DARK_COLORS if st.session_state.dark_mode else _LIGHT_COLORS
st.markdown(f"<style>{_FONTS}\n{_BASE_CSS}\n{_theme_css}</style>", unsafe_allow_html=True)

# ---------------------------------------------------------------- init store
leads_store.init()

# ---------------------------------------------------------------- chromium
@st.cache_resource
def ensure_chromium_installed():
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

# ---------------------------------------------------------------- constants
AI_VERDICT_ORDER = ["Pursue", "Manual review", "Maybe", "Skip"]
VERDICT_ICON = {"Pursue": "🟢", "Maybe": "🟡", "Manual review": "🟠", "Skip": "⚪"}
EXAMPLE_CSV = (
    "Company Name,Website\n"
    "Hawks Cay Resort,https://www.hawkscay.com/\n"
    "Majesty Fishing,https://www.majestyfishing.com/\n"
    "FishEye Sportfishing,https://www.fisheyesportfishing.com/\n"
)

# ---------------------------------------------------------------- helpers
def get_groq_key() -> str:
    try:
        if "GROQ_API_KEY" in st.secrets:
            return st.secrets["GROQ_API_KEY"]
    except FileNotFoundError:
        pass
    return os.environ.get("GROQ_API_KEY", "")


def get_psi_key() -> str:
    try:
        if "GOOGLE_PSI_API_KEY" in st.secrets:
            return st.secrets["GOOGLE_PSI_API_KEY"]
    except FileNotFoundError:
        pass
    return os.environ.get("GOOGLE_PSI_API_KEY", "")


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def process_batch(leads, niche_key, check_speed, screenshot_dir, groq_key, progress_cb, *, skip_cache=False):
    os.environ["GOOGLE_PSI_API_KEY"] = get_psi_key()
    groq_client = Groq(api_key=groq_key)
    rows = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            for idx, lead in enumerate(leads, start=1):
                company = str(lead.get("Company Name", "")).strip()
                website = str(lead.get("Website", "")).strip()

                if not skip_cache:
                    cached = leads_store.lookup(website)
                    if cached and cached.get("last_scraped_at"):
                        progress_cb(idx, len(leads), f"{company} (cached)")
                        rows.append(cached)
                        continue

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
                leads_store.upsert_pipeline_result(row)
                rows.append(row)
        finally:
            await browser.close()
    return rows


def _svg_logo_base64() -> str:
    svg_path = ASSETS / "logo.svg"
    if svg_path.exists():
        return base64.b64encode(svg_path.read_bytes()).decode()
    return ""


# ================================================================ SIDEBAR
with st.sidebar:
    # ---- logo
    favicon_path = ASSETS / "favicon.png"
    if favicon_path.exists():
        st.image(str(favicon_path), width=48)

    # ---- appearance
    st.subheader("Appearance")
    dark_toggle = st.toggle("Dark mode", value=st.session_state.dark_mode, key="dark_toggle")
    if dark_toggle != st.session_state.dark_mode:
        st.session_state.dark_mode = dark_toggle
        st.rerun()

    # ---- pipeline settings (collapsed)
    st.subheader("Pipeline Settings")
    with st.expander("API keys & options", expanded=False):
        niche_key = st.selectbox(
            "Niche profile",
            options=list(NICHE_PROFILES.keys()),
            format_func=lambda k: NICHE_PROFILES[k].label,
            index=list(NICHE_PROFILES.keys()).index(DEFAULT_NICHE),
            help="Scoring weights and outreach language change per niche.",
        )
        check_speed = st.checkbox(
            "Check page speed (PSI)",
            value=False,
            help="Adds ~10-20s per lead. Needs GOOGLE_PSI_API_KEY.",
        )
        groq_key_input = st.text_input(
            "Groq API key",
            value=get_groq_key(),
            type="password",
            help="Stored in st.secrets on Cloud, or paste here for local runs.",
        )
        st.caption("Free key → console.groq.com/keys")

    # ---- lead store
    st.subheader("Lead Store")
    stored_count = leads_store.count()
    st.caption(f"{stored_count} lead(s) saved")
    if st.button("Clear stored leads", type="secondary", use_container_width=True):
        leads_store.clear()
        st.session_state.selected_website = None
        st.rerun()

    st.divider()
    st.caption(
        "Processes leads one at a time to stay under Streamlit Cloud's "
        "1 GB free-tier RAM limit."
    )


# ================================================================ MAIN AREA
# ---- branded header
logo_b64 = _svg_logo_base64()
if logo_b64:
    st.markdown(
        f'<img src="data:image/svg+xml;base64,{logo_b64}" '
        f'style="height:56px; margin-bottom:4px;" alt="Digital Deckhand">',
        unsafe_allow_html=True,
    )
st.caption("Internal Lead CRM — scrape, score, manage, close.")

# ================================================================ ACTION TABS
action_tab_upload, action_tab_add, action_tab_sync = st.tabs([
    "Upload & Run", "+ Add Lead", "Sync",
])

# ---- Upload & Run --------------------------------------------------
with action_tab_upload:
    col_up, col_ex = st.columns([5, 1])
    with col_up:
        uploaded = st.file_uploader(
            "Upload leads CSV (Company Name + Website columns)",
            type="csv",
        )
    with col_ex:
        st.download_button(
            "Example CSV",
            data=EXAMPLE_CSV,
            file_name="raw_leads_example.csv",
            mime="text/csv",
        )

    leads_df = None
    if uploaded is not None:
        leads_df = pd.read_csv(uploaded)
        missing = {"Company Name", "Website"} - set(leads_df.columns)
        if missing:
            st.error(f"Missing column(s): {', '.join(missing)}")
            leads_df = None
        else:
            st.success(f"Loaded {len(leads_df)} lead(s).")
            st.dataframe(leads_df.head(8), use_container_width=True, hide_index=True)

    run_clicked = st.button(
        "Run pipeline",
        type="primary",
        disabled=leads_df is None or not groq_key_input,
    )
    if leads_df is not None and not groq_key_input:
        st.warning("Add a Groq API key in the sidebar.")

    if run_clicked and leads_df is not None:
        leads = leads_df.to_dict("records")
        prog = st.progress(0.0)
        stat = st.empty()
        def _cb(i, t, c):
            prog.progress(i / t)
            stat.text(f"[{i}/{t}] {c}")
        with st.spinner("Running pipeline…"):
            run_async(process_batch(
                leads, niche_key, check_speed,
                Path(st.session_state.screenshot_dir), groq_key_input, _cb,
            ))
        stat.text(f"Done — {len(leads)} lead(s) processed.")
        st.rerun()

# ---- + Add Lead -----------------------------------------------------
with action_tab_add:
    with st.form("add_lead_form", clear_on_submit=True):
        st.caption("Add a lead manually. Pipeline Status starts at 'New' — run the pipeline on it later from the detail panel.")
        al_cols = st.columns(2)
        al_company = al_cols[0].text_input("Company Name")
        al_website = al_cols[1].text_input("Website")
        al_niche = st.selectbox(
            "Niche",
            options=list(NICHE_PROFILES.keys()),
            format_func=lambda k: NICHE_PROFILES[k].label,
            key="add_lead_niche",
        )
        al_notes = st.text_area("Notes", height=80)
        submitted = st.form_submit_button("Add lead", type="primary")
        if submitted:
            if not al_company or not al_website:
                st.error("Company Name and Website are required.")
            else:
                leads_store.insert_manual_lead(
                    al_company, al_website,
                    NICHE_PROFILES[al_niche].label, al_notes,
                )
                st.success(f"Added {al_company}.")
                st.rerun()

# ---- Sync -----------------------------------------------------------
with action_tab_sync:
    sync_export, sync_import = st.columns(2)

    with sync_export:
        st.markdown("**Export**")
        all_for_export = leads_store.load_all()
        if all_for_export:
            buf = io.StringIO()
            pd.DataFrame(all_for_export).to_csv(buf, index=False)
            st.download_button(
                f"Export all ({len(all_for_export)} leads)",
                data=buf.getvalue(),
                file_name="reviewed_leads.csv",
                mime="text/csv",
                type="primary",
                use_container_width=True,
            )
        else:
            st.caption("No leads in store yet.")

    with sync_import:
        st.markdown("**Import**")
        import_file = st.file_uploader("CSV to import", type="csv", key="sync_import_csv")
        if import_file is not None:
            import_df = pd.read_csv(import_file)
            if "Website" not in import_df.columns:
                st.error("CSV needs a 'Website' column.")
            else:
                import_rows = import_df.to_dict("records")
                new_rows, update_rows = leads_store.diff_import(import_rows)
                st.info(f"{len(new_rows)} new · {len(update_rows)} updates")

                if new_rows:
                    with st.expander(f"Preview — {len(new_rows)} new lead(s)"):
                        st.dataframe(
                            pd.DataFrame(new_rows)[["Company Name", "Website"]].head(20),
                            hide_index=True, use_container_width=True,
                        )
                if update_rows:
                    with st.expander(f"Preview — {len(update_rows)} existing lead(s) to update"):
                        st.dataframe(
                            pd.DataFrame(update_rows)[["Company Name", "Website"]].head(20),
                            hide_index=True, use_container_width=True,
                        )

                if st.button("Confirm import", type="primary", key="confirm_import"):
                    leads_store.upsert_many(import_rows)
                    st.success(f"Imported {len(import_rows)} lead(s).")
                    st.rerun()


# ================================================================ LEADS TABLE
st.divider()

all_leads = leads_store.load_all()

if not all_leads:
    st.info("No leads yet. Upload a CSV, add one manually, or import from the Sync tab.")
    st.stop()

leads_df_full = pd.DataFrame(all_leads)

# ---- stale re-run controls
stale_cols = st.columns([2, 1, 3])
with stale_cols[0]:
    stale_days = st.number_input("Re-check leads older than (days)", min_value=1, value=14, step=1, key="stale_days")
with stale_cols[1]:
    stale_leads = leads_store.load_stale(stale_days)
    st.caption(f"{len(stale_leads)} stale")
    if st.button("Re-check stale", disabled=not stale_leads or not groq_key_input):
        prog = st.progress(0.0)
        stat = st.empty()
        def _stale_cb(i, t, c):
            prog.progress(i / t)
            stat.text(f"[{i}/{t}] {c}")
        with st.spinner("Re-running stale leads…"):
            run_async(process_batch(
                [{"Company Name": l["Company Name"], "Website": l["Website"]} for l in stale_leads],
                niche_key, check_speed,
                Path(st.session_state.screenshot_dir), groq_key_input, _stale_cb,
                skip_cache=True,
            ))
        stat.text(f"Done — {len(stale_leads)} lead(s) refreshed.")
        st.rerun()

# ---- pipeline status filter
status_filter = st.multiselect(
    "Pipeline Status filter",
    options=PIPELINE_STATUSES,
    default=["New", "Reviewing", "Approved", "Contacted"],
    key="pipeline_status_filter",
)

display_df = leads_df_full.copy()
if status_filter:
    display_df = display_df[display_df["pipeline_status"].isin(status_filter)]

if display_df.empty:
    st.caption("No leads match this filter.")
    st.stop()

# ---- AI verdict metrics
verdict_counts = display_df["Lead Status"].value_counts()
mcols = st.columns(len(AI_VERDICT_ORDER))
for mc, v in zip(mcols, AI_VERDICT_ORDER):
    mc.metric(f"{VERDICT_ICON.get(v,'')} {v}", int(verdict_counts.get(v, 0)))

# ---- table
TABLE_COLS = [
    "Company Name", "Website", "Lead Status", "pipeline_status",
    "Overall Score", "Main Issue", "Email Found", "last_scraped_at",
]
visible_cols = [c for c in TABLE_COLS if c in display_df.columns]
show_df = display_df[visible_cols].copy()
show_df.rename(columns={
    "pipeline_status": "Pipeline Status",
    "last_scraped_at": "Last Scraped",
    "Lead Status": "AI Verdict",
}, inplace=True)

st.dataframe(show_df, use_container_width=True, hide_index=True)

# ---- lead selector
lead_options = display_df["Website"].tolist()
lead_labels = [
    f"{row['Company Name']}  —  {row['Website']}"
    for _, row in display_df.iterrows()
]

default_idx = 0
if st.session_state.selected_website in lead_options:
    default_idx = lead_options.index(st.session_state.selected_website)

selected_label = st.selectbox(
    "Select lead to view details",
    options=lead_labels,
    index=default_idx,
    key="lead_selector",
)
if selected_label:
    selected_website = lead_options[lead_labels.index(selected_label)]
    st.session_state.selected_website = selected_website


# ================================================================ DETAIL PANEL
if st.session_state.selected_website:
    lead = leads_store.lookup(st.session_state.selected_website)
    if lead is None:
        st.warning("Lead not found in store.")
        st.stop()

    st.markdown('<div class="detail-card">', unsafe_allow_html=True)
    st.subheader(f"{lead['Company Name']}")
    st.caption(lead["Website"])

    # ---- top row: status + scores
    dc1, dc2, dc3 = st.columns(3)
    with dc1:
        new_status = st.selectbox(
            "Pipeline Status",
            options=PIPELINE_STATUSES,
            index=PIPELINE_STATUSES.index(lead["pipeline_status"]) if lead["pipeline_status"] in PIPELINE_STATUSES else 0,
            key="detail_pipeline_status",
        )
        if new_status != lead["pipeline_status"]:
            leads_store.update_fields(lead["Website"], pipeline_status=new_status)
            st.rerun()

    with dc2:
        ai_verdict = lead.get("Lead Status", "")
        if ai_verdict:
            st.metric("AI Verdict", f"{VERDICT_ICON.get(ai_verdict, '')} {ai_verdict}")
        else:
            st.caption("No AI verdict yet — run the pipeline first.")

    with dc3:
        score = lead.get("Overall Score", "")
        if score:
            st.metric("Overall Score", score)

    # ---- notes
    current_notes = lead.get("notes", "")
    notes_val = st.text_area("Notes", value=current_notes, height=80, key="detail_notes")
    if st.button("Save notes", key="save_notes"):
        leads_store.update_fields(lead["Website"], notes=notes_val)
        st.success("Notes saved.")

    # ---- run pipeline on single lead
    if st.button(
        "Run / re-run pipeline on this lead",
        type="primary",
        disabled=not groq_key_input,
        key="run_single",
    ):
        prog = st.progress(0.0)
        stat = st.empty()
        def _single_cb(i, t, c):
            prog.progress(i / t)
            stat.text(f"Processing {c}…")
        with st.spinner("Running pipeline…"):
            run_async(process_batch(
                [{"Company Name": lead["Company Name"], "Website": lead["Website"]}],
                niche_key, check_speed,
                Path(st.session_state.screenshot_dir), groq_key_input, _single_cb,
                skip_cache=True,
            ))
        stat.text("Done.")
        st.rerun()

    # ---- analysis details (only if pipeline has run)
    if lead.get("Main Issue"):
        st.divider()

        info_cols = st.columns(3)
        info_cols[0].markdown(f"**Main Issue** — {lead['Main Issue']}")
        info_cols[1].markdown(f"**Outreach Angle** — {lead['Best Outreach Angle']}")
        info_cols[2].markdown(f"**Offer** — {lead['Recommended Offer']}")

        # ---- sub-scores
        with st.expander("Sub-scores"):
            sc = st.columns(4)
            for i, (label, key) in enumerate([
                ("Visual", "Visual Quality Score"),
                ("Inquiry Flow", "Inquiry Flow Score"),
                ("Mobile", "Mobile Usability Score"),
                ("Trust/Proof", "Trust/Social Proof Score"),
            ]):
                sc[i].metric(label, lead.get(key, "—"))
            sc2 = st.columns(4)
            for i, (label, key) in enumerate([
                ("Local SEO", "Local SEO Score"),
                ("Technical", "Technical Score"),
                ("Commercial", "Commercial Opportunity Score"),
                ("Niche", "Niche Profile"),
            ]):
                sc2[i].metric(label, lead.get(key, "—"))

        # ---- contact info
        with st.expander("Contact info"):
            ci = st.columns(3)
            ci[0].markdown(f"**Email:** {lead.get('Email Found', '—')}")
            ci[1].markdown(f"**Phone:** {lead.get('Phone Found', '—')}")
            ci[2].markdown(f"**Form:** {lead.get('Contact Form URL', '—')}")
            if lead.get("Social Links"):
                st.caption(f"Social: {lead['Social Links']}")
            if lead.get("Detected Tech"):
                st.caption(f"Tech: {lead['Detected Tech']}")
            if lead.get("Page Speed Summary"):
                st.caption(f"Speed: {lead['Page Speed Summary']}")

        # ---- email draft
        st.divider()
        st.markdown("**Outreach Email**")

        display_email = lead.get("edited_email_draft", "") or lead.get("Email Draft", "")
        email_val = st.text_area(
            "Email draft",
            value=display_email,
            height=180,
            key="detail_email",
            label_visibility="collapsed",
        )
        email_btns = st.columns(3)
        with email_btns[0]:
            if st.button("Save email", key="save_email"):
                leads_store.update_fields(lead["Website"], edited_email_draft=email_val)
                st.success("Email saved.")
        with email_btns[1]:
            if st.button(
                "Regenerate email",
                disabled=not groq_key_input,
                key="regen_email",
            ):
                with st.spinner("Regenerating…"):
                    niche_for_regen = niche_key
                    new_draft = regenerate_email(
                        Groq(api_key=groq_key_input),
                        lead["Company Name"],
                        lead.get("Main Issue", ""),
                        lead.get("Best Outreach Angle", ""),
                        lead.get("Recommended Offer", ""),
                        niche_for_regen,
                        notes=lead.get("notes", ""),
                    )
                leads_store.update_fields(
                    lead["Website"],
                    **{"Email Draft": new_draft, "edited_email_draft": ""},
                )
                st.success("New draft generated.")
                st.rerun()
        if lead.get("edited_email_draft"):
            with email_btns[2]:
                if st.button("Revert to AI draft", key="revert_email"):
                    leads_store.update_fields(lead["Website"], edited_email_draft="")
                    st.rerun()

        # ---- video talking points
        try:
            talking_points = json.loads(lead.get("Video Talking Points") or "[]")
        except json.JSONDecodeError:
            talking_points = []
        if talking_points:
            st.markdown("**Loom talking points**")
            for pt in talking_points:
                st.markdown(f"- {pt}")

        # ---- screenshots
        desktop_path = lead.get("Desktop Screenshot Path", "")
        mobile_path = lead.get("Mobile Screenshot Path", "")
        if (desktop_path and Path(desktop_path).exists()) or (mobile_path and Path(mobile_path).exists()):
            st.divider()
            shot_cols = st.columns(2)
            if desktop_path and Path(desktop_path).exists():
                shot_cols[0].image(desktop_path, caption="Desktop")
            if mobile_path and Path(mobile_path).exists():
                shot_cols[1].image(mobile_path, caption="Mobile")

        # ---- warnings / errors
        if lead.get("Verification Warnings"):
            st.warning(lead["Verification Warnings"])
        if lead.get("Error"):
            st.error(lead["Error"])

    st.markdown('</div>', unsafe_allow_html=True)
