"""
Streamlit GUI for the job-search agent.

Run with:  streamlit run app.py

Prerequisites this GUI does NOT change or work around:
- `config/settings.py` reads GROQ_API_KEY and CEREBRAS_API_KEY via
  `os.environ["..."]` (not `.get`), so it will raise at import time if
  those aren't in your .env even if you only use Gemini/Ollama. Add
  dummy values to .env or relax those two lines if you hit that.
- If GeminiProvider/GroqProvider need a real key to construct without
  erroring, make sure at least one of GEMINI_API_KEY / GROQ_API_KEY is set.
"""

from __future__ import annotations

import streamlit as st

from pydantic import ValidationError

from src.models import CandidateProfile, PersonalInformation
from src.matchers.matcher import CandidatePreferences
from src.models_job import EmploymentType, WorkArrangement
from src.candidate_identity import MissingCandidateContactInfoError
from src.pipeline import run_pipeline_for_candidate  
from config.settings import Settings

import gui_utils as gu

st.set_page_config(page_title="Job Search Agent", layout="wide")
gu.ensure_dirs()
gu.register_all_scrapers()

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
st.session_state.setdefault("cv_filename", None)
st.session_state.setdefault("candidate_profile", None)

st.title("🧭 Job Search Agent")

tab_cv, tab_prefs, tab_run, tab_matches, tab_apps = st.tabs(
    ["1. CV & Profile", "2. Preferences & Logins", "3. Run Agent", "4. Matches", "5. Applications"]
)

# ---------------------------------------------------------------------------
# TAB 1 -- CV upload + editable extracted profile
# ---------------------------------------------------------------------------
with tab_cv:
    st.subheader("Choose a CV")
    manifest = gu.list_uploaded_cvs()

    if manifest:
        options = [e["stored_filename"] for e in manifest]
        labels = {e["stored_filename"]: gu.cv_display_label(e) for e in manifest}
        selected = st.selectbox(
            "Previously uploaded CVs (most recent first)",
            options, index=0, format_func=lambda k: labels[k],
        )
        if selected != st.session_state.cv_filename:
            st.session_state.cv_filename = selected
            st.session_state.candidate_profile = gu.load_cached_profile(selected)  # None if never extracted
    else:
        st.caption("No CVs uploaded yet -- upload one below.")

    st.divider()
    st.subheader("Upload a new CV")
    uploaded = st.file_uploader("CV file (PDF, PNG, JPG)", type=["pdf", "png", "jpg", "jpeg"])
    if uploaded is not None and st.button("Save this CV"):
        filename = gu.save_uploaded_cv(uploaded)
        st.session_state.cv_filename = filename
        st.session_state.candidate_profile = None
        st.rerun()  # refresh the selector above so the new file shows up, selected

    if st.session_state.cv_filename:
        st.divider()
        col_a, col_b = st.columns(2)
        if col_a.button("🔍 Extract / re-extract profile from selected CV", type="primary"):
            with st.spinner("Parsing CV and extracting structured profile (local LLM)..."):
                llm = gu.build_cv_llm()
                profile = gu.extract_candidate_profile(st.session_state.cv_filename, llm)
                profile = gu.save_profile(profile, st.session_state.cv_filename)
            st.session_state.candidate_profile = profile
            st.success(f"Extracted profile for candidate_id={profile.candidate_id}")

        if col_b.button("↩️ Discard edits (reload saved profile)"):
            cached = gu.load_cached_profile(st.session_state.cv_filename)
            if cached:
                st.session_state.candidate_profile = cached
                st.info("Reloaded previously saved profile.")
            else:
                st.warning("No cached profile found for this CV yet -- run extraction first.")

    profile: CandidateProfile | None = st.session_state.candidate_profile
    if profile is None:
        st.info("Select or upload a CV above, then click **Extract profile** to continue.")
    else:
        st.divider()
        st.subheader("Review & correct the extracted profile")
        st.caption("Fix anything the extractor got wrong or missed, then click **Save profile** at the bottom.")

        with st.expander("Personal information", expanded=True):
            pi = profile.personal_information
            c1, c2 = st.columns(2)
            full_name = c1.text_input("Full name", pi.full_name or "")
            email = c2.text_input("Email *", pi.email or "", help="Required before matching/applying.")
            if not email.strip():
                c2.caption("⚠️ Required before you can run matching/applying (tab 3).")
            country_code = c1.text_input("Country code", pi.country_code or "")
            phone = c2.text_input("Phone", pi.phone or "")
            location = c1.text_input("Location (city, region, ...)", getattr(pi, "location", None) or "")
            linkedin_url = c2.text_input("LinkedIn URL", pi.linkedin or "")
            github_url = c1.text_input("GitHub URL", pi.github or "")

        professional_summary = st.text_area("Professional summary", profile.professional_summary or "", height=80)

        with st.expander(f"Education ({len(profile.education)})", expanded=False):
            from src.models_job import DegreeLevel
            edu_df = st.data_editor(
                gu.education_to_df(profile.education),
                num_rows="dynamic", use_container_width=True, key="edu_editor",
                column_config={
                    "degree_level": st.column_config.SelectboxColumn(
                        options=[d.value for d in DegreeLevel], required=False
                    ),
                },
            )

        with st.expander(f"Experience ({len(profile.experience)})", expanded=False):
            st.caption("`responsibilities` and `technologies`: separate multiple entries with ` | `")
            exp_df = st.data_editor(
                gu.experience_to_df(profile.experience),
                num_rows="dynamic", use_container_width=True, key="exp_editor",
            )

        with st.expander(f"Projects ({len(profile.projects)})", expanded=False):
            st.caption("`highlights` and `technologies`: separate multiple entries with ` | `")
            proj_df = st.data_editor(
                gu.projects_to_df(profile.projects),
                num_rows="dynamic", use_container_width=True, key="proj_editor",
            )

        with st.expander(f"Skills ({len(profile.skills)})", expanded=False):
            from src.models_job import SkillCategory
            skills_df = st.data_editor(
                gu.skills_to_df(profile.skills),
                num_rows="dynamic", use_container_width=True, key="skills_editor",
                column_config={
                    "category": st.column_config.SelectboxColumn(
                        options=[c.value for c in SkillCategory], required=False
                    ),
                },
            )

        with st.expander(f"Certifications ({len(profile.certifications)})", expanded=False):
            cert_df = st.data_editor(
                gu.certifications_to_df(profile.certifications),
                num_rows="dynamic", use_container_width=True, key="cert_editor",
            )

        with st.expander(f"Spoken languages ({len(profile.spoken_languages)})", expanded=False):
            lang_df = st.data_editor(
                gu.spoken_languages_to_df(profile.spoken_languages),
                num_rows="dynamic", use_container_width=True, key="lang_editor",
            )

        if st.button("💾 Save profile", type="primary"):
            try:
                updated = CandidateProfile(
                    candidate_id=profile.candidate_id,
                    personal_information=PersonalInformation(
                        full_name=full_name or None, email=email or None,
                        country_code=country_code or None, phone=phone or None,
                        location=location or None,
                        linkedin=linkedin_url or None, github=github_url or None,
                    ),
                    professional_summary=professional_summary or None,
                    education=gu.df_to_education(edu_df),
                    experience=gu.df_to_experience(exp_df),
                    projects=gu.df_to_projects(proj_df),
                    skills=gu.df_to_skills(skills_df),
                    certifications=gu.df_to_certifications(cert_df),
                    spoken_languages=gu.df_to_spoken_languages(lang_df),
                )
            except ValidationError as e:
                st.error("Couldn't save the profile -- please fix the fields below:")
                for msg in gu.format_validation_errors(e):
                    st.error(msg)
            else:
                updated = gu.save_profile(updated, st.session_state.cv_filename)
                st.session_state.candidate_profile = updated
                st.success("Profile saved.")
                if not updated.personal_information.email:
                    st.warning("No email set yet -- you can save without one, but matching/applying will refuse to run until it's filled in.")

# ---------------------------------------------------------------------------
# TAB 2 -- Preferences & credentials
# ---------------------------------------------------------------------------
with tab_prefs:
    if st.session_state.candidate_profile is None:
        st.info("Extract a profile in tab 1 first.")
    else:
        st.subheader("Job preferences")
        c1, c2 = st.columns(2)
        preferred_employment_types = c1.multiselect(
            "Preferred employment types (empty = no restriction)",
            [e.value for e in EmploymentType],
        )
        preferred_work_arrangements = c2.multiselect(
            "Preferred work arrangements (empty = no restriction)",
            [w.value for w in WorkArrangement],
        )
        willing_to_relocate = st.checkbox("Willing to relocate", value=False)
        c3, c4, c5 = st.columns(3)
        country = c3.text_input("Country *", "Tunisia")
        if not country.strip():
            c3.caption("⚠️ Required -- used for the on-site/relocation filter.")
        governorate = c4.text_input("Governorate (optional)", "")
        max_commute = c5.number_input(
            "Max commute distance (km, 0 = no limit)", min_value=0, value=0
        )

        st.divider()
        st.subheader("Job board logins")
        st.caption("Stored only in memory for this session and written to `Settings` at run time.")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**TanitJobs**")
            tanit_email = st.text_input("TanitJobs email", Settings.TANITJOBS_EMAIL, key="tanit_email")
            tanit_password = st.text_input("TanitJobs password", Settings.TANITJOBS_PASSWORD, type="password", key="tanit_password")
        with c2:
            st.markdown("**LinkedIn**")
            linkedin_email = st.text_input("LinkedIn email", Settings.LINKEDIN_EMAIL, key="linkedin_email")
            linkedin_password = st.text_input("LinkedIn password", Settings.LINKEDIN_PASSWORD, type="password", key="linkedin_password")

        if st.button("Save preferences & logins", type="primary"):
            try:
                preferences = CandidatePreferences(
                    preferred_employment_types=[EmploymentType(v) for v in preferred_employment_types],
                    preferred_work_arrangements=[WorkArrangement(v) for v in preferred_work_arrangements],
                    willing_to_relocate=willing_to_relocate,
                    country=country,
                    governorate=governorate or None,
                    max_commute_distance_km=max_commute or None,
                )
            except ValidationError as e:
                st.error("Couldn't save preferences -- please fix the fields below:")
                for msg in gu.format_validation_errors(e):
                    st.error(msg)
            else:
                st.session_state.preferences = preferences
                Settings.TANITJOBS_EMAIL = tanit_email
                Settings.TANITJOBS_PASSWORD = tanit_password
                Settings.LINKEDIN_EMAIL = linkedin_email
                Settings.LINKEDIN_PASSWORD = linkedin_password
                st.success("Saved for this session.")

# ---------------------------------------------------------------------------
# TAB 3 -- Run the agent
# ---------------------------------------------------------------------------
with tab_run:
    if st.session_state.candidate_profile is None:
        st.info("Extract a profile in tab 1 first.")
    elif "preferences" not in st.session_state:
        st.info("Fill in preferences in tab 2 first.")
    else:
        st.subheader("Run a search")
        keyword = st.text_input("Job title / keyword to search for", "")
        board_labels = st.multiselect(
            "Job boards to search", list(gu.BOARD_DOMAINS.keys()), default=list(gu.BOARD_DOMAINS.keys())
        )
        c1, c2, c3 = st.columns(3)
        dry_run = c1.checkbox("Dry run (don't actually submit applications)", value=True)
        high_threshold = c2.slider("Auto-apply score threshold", 0.0, 1.0, 0.75, 0.05)
        # mid_threshold = c3.slider("Ask-to-confirm score threshold", 0.0, 1.0, 0.5, 0.05)

        run_disabled = not keyword or not board_labels
        if st.button("🚀 Run agent", type="primary", disabled=run_disabled):
            candidate = st.session_state.candidate_profile
            preferences = st.session_state.preferences
            board_domains = [gu.BOARD_DOMAINS[b] for b in board_labels]

            log_box = st.empty()
            buffer = []

            class _StreamlitLog:
                def write(self, text):
                    if text.strip():
                        buffer.append(text)
                        log_box.code("".join(buffer[-400:]))
                def flush(self):
                    pass

            import contextlib
            try:
                with st.spinner("Running agent (this opens real browser windows for scraping/applying)..."):
                    fallback_llm = gu.build_fallback_llm()
                    job_offer_extractor = gu.JobOfferExtractor(
                        llm=fallback_llm, output_path=gu.JOB_OFFERS_OUTPUT_PATH
                    )
                    cv_path = str(gu.CV_DIR / st.session_state.cv_filename)
                    with contextlib.redirect_stdout(_StreamlitLog()):
                        result = run_pipeline_for_candidate(
                            candidate=candidate,
                            keyword=keyword,
                            preferences=preferences,
                            llm=fallback_llm,
                            job_offer_extractor=job_offer_extractor,
                            matches_output_path=gu.MATCHES_OUTPUT_PATH,
                            applications_log_path=gu.DEFAULT_APPLICATIONS_LOG_PATH,
                            cv_path=cv_path,
                            board_domains=board_domains,
                            dry_run=dry_run,
                            high_score_threshold=high_threshold,
                            # mid_score_threshold=mid_threshold,
                        )
                auto_applied = result["auto_applied"]
                to_confirm = result["to_confirm"]
                discarded = result["discarded"]
                st.success(
                    f"Run finished: {len(auto_applied)} auto-applied, "
                    f"{len(to_confirm)} to confirm, {len(discarded)} discarded. "
                    "Full history is in the Matches / Applications tabs."
                )
 
                if auto_applied:
                    st.write(f"**Auto-applied this run ({len(auto_applied)})**")
                    st.dataframe(
                        [{"job_url": l.job_url, "submitted": l.submitted, "dry_run": l.dry_run,
                          "cover_letter_source": l.cover_letter_source} for l in auto_applied],
                        use_container_width=True, hide_index=True,
                    )
                if to_confirm:
                    print(f"**Awaiting your confirmation ({len(to_confirm)})** -- mid-tier matches, not auto-applied")
                    # st.write(f"**Awaiting your confirmation ({len(to_confirm)})** -- mid-tier matches, not auto-applied")
                    # st.dataframe(gu.matches_to_df(to_confirm), use_container_width=True, hide_index=True)
            except MissingCandidateContactInfoError:
                st.error("Candidate email is missing -- fill it in on tab 1 (Personal information) and save.")
            except Exception as e:
                st.error(f"Run failed: {e}")
                st.exception(e)


# ---------------------------------------------------------------------------
# TAB 4 -- Matches
# ---------------------------------------------------------------------------
with tab_matches:
    if st.session_state.candidate_profile is None:
        st.info("Extract a profile in tab 1 first.")
    else:
        candidate_id = st.session_state.candidate_profile.candidate_id
        if st.button("🔄 Refresh matches"):
            st.rerun()
        results, rejected = gu.load_matches(candidate_id)
        st.subheader(f"Scored matches ({len(results)})")
        if results:
            st.dataframe(gu.matches_to_df(results), use_container_width=True, hide_index=True)
        else:
            st.caption("No scored matches yet -- run the agent in tab 3.")

        with st.expander(f"Rejected by hard filters ({len(rejected)})"):
            if rejected:
                st.dataframe(gu.rejected_to_df(rejected), use_container_width=True, hide_index=True)
            else:
                st.caption("Nothing filtered out yet.")

# ---------------------------------------------------------------------------
# TAB 5 -- Application history
# ---------------------------------------------------------------------------
with tab_apps:
    if st.session_state.candidate_profile is None:
        st.info("Extract a profile in tab 1 first.")
    else:
        candidate_id = st.session_state.candidate_profile.candidate_id
        if st.button("🔄 Refresh applications"):
            st.rerun()
        apps_df = gu.load_all_applications(candidate_id)
        st.subheader(f"Application history ({len(apps_df)})")
        if not apps_df.empty:
            st.dataframe(apps_df, use_container_width=True, hide_index=True)
        else:
            st.caption("No applications logged yet.")