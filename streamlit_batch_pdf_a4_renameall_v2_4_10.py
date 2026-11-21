#!/usr/bin/env python3
"""
Batch PDF Rename-All (Moderated Files Replace Originals) - Web App (Streamlit Cloud Edition - v2.4.10)
Vishal Ramnath, ramnav@unisa.ac.za - 21 November 2026
Copyright Unisa 2026. Intended for the exclusive use of Unisa lecturers,
internal moderators, and external moderators only.

Upload ALL the PDFs for a module (originals plus moderated versions):

    student1.pdf                      (Lecturer / original)
    student1_int_mod.pdf              (Internal Moderator)
    student1_int_mod_ext_mod.pdf      (Internal + External Moderator)
    student1_ext_mod.pdf              (External Moderator only)

Rule (highest level wins):  external moderated  >  internal moderated  >  original.
The app returns one ZIP containing a single file per student, carrying the ORIGINAL file
name but the content of the final moderated version. A browser cannot change files in your
folder, so extract the ZIP into an empty folder (or over the old folder after backing it up).
"""

import hmac
import io
import os
import re
import zipfile
from pathlib import Path

import streamlit as st

# =====================================================================
# SETTINGS
# =====================================================================
OUTPUT_FOLDER_NAME = "Final_Moderated"   # folder name inside the downloaded ZIP

# Suffix (before ".pdf") -> priority. Higher number wins.
SUFFIX_PRIORITY = {
    "": 0,                    # original / lecturer
    "_int_mod": 1,            # internal moderator
    "_ext_mod": 2,            # external moderator only
    "_int_mod_ext_mod": 3,    # internal then external moderator
}
SUFFIX_LABEL = {
    "": "Original (Lecturer)",
    "_int_mod": "Internal Moderator",
    "_ext_mod": "External Moderator",
    "_int_mod_ext_mod": "External Moderator (on internal)",
}

_NAME_RE = re.compile(r"^(?P<base>.+?)(?P<sfx>(?:_int_mod)?(?:_ext_mod)?)$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Unisa Staff Username & Passcode Gate (same as PDF Marker)
# ---------------------------------------------------------------------------
def get_configured_credentials() -> tuple[str, str]:
    """Read STAFF_USERNAME and STAFF_PASSCODE from Streamlit Secrets (or env vars)."""
    username = None
    passcode = None
    try:
        if "STAFF_USERNAME" in st.secrets:
            username = str(st.secrets["STAFF_USERNAME"]).strip()
        if "STAFF_PASSCODE" in st.secrets:
            passcode = str(st.secrets["STAFF_PASSCODE"]).strip()
    except Exception:
        pass

    if not username:
        username = os.environ.get("STAFF_USERNAME", "").strip()
    if not passcode:
        passcode = os.environ.get("STAFF_PASSCODE", "").strip()

    return username, passcode


def show_logo_or_banner(subtitle_size="14px", title_size="28px"):
    logo_path = Path(__file__).parent / "unisa_logo.png"
    if logo_path.exists():
        st.image(str(logo_path), use_container_width=True)
    else:
        st.markdown(
            f"""
            <div style="background-color:#002f6c; color:white; padding:18px 22px; border-radius:8px; text-align:center; margin-bottom:16px;">
                <div style="font-size:{title_size}; font-weight:800; letter-spacing:2px;">UNISA</div>
                <div style="font-size:{subtitle_size}; opacity:0.92; margin-top:4px;">College of Science, Engineering and Technology</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def check_staff_authentication() -> bool:
    """Require both Unisa staff username and passcode before exposing the workspace."""
    if st.session_state.get("authenticated", False):
        return True

    st.markdown(
        """
        <style>
        .block-container { padding-top: 3.5rem !important; max-width: 560px !important; }
        div[data-testid="stDecoration"], #MainMenu, footer { display: none !important; }
        header[data-testid="stHeader"] { background: transparent !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    show_logo_or_banner()

    st.subheader("Batch PDF Rename-All v2.4.10 — Restricted Access")
    st.caption(
        "Intended for the exclusive use of Unisa lecturers, internal moderators, "
        "and external moderators only."
    )

    with st.form("unisa_passcode_form", clear_on_submit=False):
        entered_user = st.text_input(
            "Staff / Moderator Username",
            placeholder="Enter username...",
        )
        entered_code = st.text_input(
            "Staff / Moderator Passcode",
            type="password",
            placeholder="Enter passcode...",
        )
        submitted = st.form_submit_button("Unlock Rename-All", type="primary", use_container_width=True)

    if submitted:
        expected_user, expected_code = get_configured_credentials()
        if not expected_user or not expected_code:
            st.error(
                "Access is not configured. Set STAFF_USERNAME and STAFF_PASSCODE "
                "in the app's Streamlit Secrets."
            )
            return False
        user_ok = bool(entered_user) and hmac.compare_digest(entered_user.strip(), expected_user)
        pass_ok = bool(entered_code) and hmac.compare_digest(entered_code.strip(), expected_code)
        if user_ok and pass_ok:
            st.session_state["authenticated"] = True
            st.session_state["authenticated_user"] = entered_user.strip()
            st.rerun()
        else:
            st.error("Invalid username or passcode. Please verify credentials with the module lecturer.")

    return False


# ---------------------------------------------------------------------------
# Core logic (same rules as the desktop version) - decides what replaces what
# ---------------------------------------------------------------------------
def parse_pdf_name(filename: str):
    """Return (base_name, suffix_lowercase) for a PDF file name, or None if not a PDF."""
    stem, ext = os.path.splitext(filename)
    if ext.lower() != ".pdf":
        return None
    m = _NAME_RE.match(stem)
    return m.group("base"), m.group("sfx").lower()


def build_plan(filenames):
    """
    Group files by original name and decide the final file for each group.
    Returns (plan, warnings). Each plan item is a dict with:
      base, final_name, source, source_suffix, action ('unchanged' | 'replace' | 'create'),
      all_files (every file in the group), remove (superseded files).
    """
    groups = {}
    warnings = []
    for name in sorted(filenames, key=str.lower):
        parsed = parse_pdf_name(name)
        if parsed is None:
            continue
        base, sfx = parsed
        g = groups.setdefault(base.lower(), {"base": base, "files": {}})
        if sfx in g["files"]:
            warnings.append(f"Duplicate name pattern ignored: {name} (already have {g['files'][sfx]})")
            continue
        g["files"][sfx] = name

    plan = []
    for _, g in sorted(groups.items()):
        files = g["files"]
        best = max(files, key=lambda s: SUFFIX_PRIORITY[s])
        source = files[best]
        all_files = list(files.values())
        if best == "":
            plan.append({
                "base": g["base"], "final_name": source, "source": source, "source_suffix": best,
                "action": "unchanged", "all_files": all_files, "remove": [],
            })
            continue
        if "" in files:
            final_name = files[""]
            action = "replace"
        else:
            final_name = g["base"] + ".pdf"
            action = "create"
        remove = [n for n in all_files if n != source and n != final_name]
        plan.append({
            "base": g["base"], "final_name": final_name, "source": source, "source_suffix": best,
            "action": action, "all_files": all_files, "remove": remove,
        })
    return plan, warnings


def plan_table_rows(plan):
    rows = []
    for p in plan:
        superseded = [n for n in p["all_files"] if n != p["source"]]
        rows.append({
            "Final file name": p["final_name"],
            "Content taken from": p["source"],
            "Level used": SUFFIX_LABEL[p["source_suffix"]],
            "Superseded (not in ZIP)": ", ".join(superseded) if superseded else "—",
        })
    return rows


def build_final_zip(plan, file_map, progress_bar=None):
    """Write one final PDF per student (original name, final content) into a ZIP."""
    zip_buf = io.BytesIO()
    log_lines = []
    ok = 0
    fail = 0
    total = len(plan)
    # PDFs are already compressed, so the ZIP just stores them
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_STORED) as zf:
        for idx, p in enumerate(plan, start=1):
            if progress_bar is not None:
                progress_bar.progress((idx - 1) / max(1, total))
            try:
                data = file_map[p["source"]].getvalue()
                zf.writestr(f"{OUTPUT_FOLDER_NAME}/{p['final_name']}", data)
                ok += 1
                if p["action"] == "unchanged":
                    log_lines.append(f"[OK]   {p['final_name']}  (original only)")
                else:
                    log_lines.append(f"[OK]   {p['final_name']}  <-  {p['source']}")
            except Exception as exc:
                fail += 1
                log_lines.append(f"[FAIL] {p['final_name']} -> {exc}")
    if progress_bar is not None:
        progress_bar.progress(1.0)
    return zip_buf.getvalue() if ok else None, "\n".join(log_lines), ok, fail


# ---------------------------------------------------------------------------
# Session State & Dialogs
# ---------------------------------------------------------------------------
def init_session_state():
    defaults = {
        "authenticated": False,
        "authenticated_user": "",
        "results": None,
        "results_sig": None,
        "uploader_nonce": 0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


@st.dialog("About Batch PDF Rename-All")
def show_about_dialog():
    show_logo_or_banner(subtitle_size="13px", title_size="26px")
    st.markdown(
        "**Copyright Unisa 2026, Vishal Ramnath, 21 November 2026. Version 2.4.10.**\n\n"
        "This program is intended for the exclusive use of Unisa lecturers, "
        "internal moderators, and external moderators only."
    )


def clear_work():
    st.session_state.results = None
    st.session_state.results_sig = None
    st.session_state.uploader_nonce += 1


# ---------------------------------------------------------------------------
# Main Streamlit UI
# ---------------------------------------------------------------------------
def main():
    st.set_page_config(
        page_title="Batch PDF Rename-All v2.4.10 | UNISA CSET",
        page_icon="📄",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    init_session_state()

    if not check_staff_authentication():
        return

    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 3.75rem !important;
            padding-bottom: 2.5rem !important;
        }
        div[data-testid="stDecoration"] {
            display: none !important;
        }
        div[data-testid="stToolbar"] {
            visibility: hidden !important;
            height: 0px !important;
        }
        #MainMenu, footer {
            visibility: hidden !important;
        }
        header[data-testid="stHeader"] {
            background: transparent !important;
        }
        div[data-testid="stSidebarUserContent"] {
            padding-top: 1.25rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # ---------------- Sidebar ----------------
    with st.sidebar:
        st.markdown("### Batch PDF Rename-All v2.4.10")
        st.caption(f"Signed in as: **{st.session_state.authenticated_user}**")
        st.divider()
        b1, b2 = st.columns(2)
        if b1.button("About", use_container_width=True):
            show_about_dialog()
        if b2.button("Lock App", use_container_width=True):
            st.session_state["authenticated"] = False
            st.session_state["authenticated_user"] = ""
            clear_work()
            st.rerun()

    # ---------------- Main area ----------------
    st.markdown("#### Replace Original PDFs by Moderated PDFs (original file names kept)")
    st.caption(
        "Upload ALL the PDFs for the module: originals plus the _int_mod, _ext_mod and "
        "_int_mod_ext_mod versions. The highest level wins (external > internal > original), "
        f"and you get one ZIP (folder '{OUTPUT_FOLDER_NAME}') with a single file per student "
        "under its original file name."
    )

    uploaded = st.file_uploader(
        "Select all PDF files",
        type=["pdf"],
        accept_multiple_files=True,
        key=f"rename_uploader_{st.session_state.uploader_nonce}",
    )

    if not uploaded:
        st.info("Upload the module's PDF files above to see what will replace what.")
        return

    # First upload wins if the same file name is uploaded twice
    file_map = {}
    dup_names = []
    for f in uploaded:
        nm = Path(f.name).name
        if nm in file_map:
            dup_names.append(nm)
        else:
            file_map[nm] = f

    plan, warnings = build_plan(list(file_map.keys()))
    for nm in dup_names:
        warnings.append(f"Uploaded twice - only the first copy of {nm} is used.")

    changes = [p for p in plan if p["action"] != "unchanged"]
    n_int = sum(1 for p in changes if p["source_suffix"] == "_int_mod")
    n_ext = sum(1 for p in changes if p["source_suffix"] in ("_ext_mod", "_int_mod_ext_mod"))
    n_unchanged = len(plan) - len(changes)
    n_created = sum(1 for p in changes if p["action"] == "create")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Students", len(plan))
    m2.metric("From internal moderator", n_int)
    m3.metric("From external moderator", n_ext)
    m4.metric("Original only", n_unchanged)

    for w in warnings:
        st.warning(w)
    if n_created:
        st.warning(
            f"{n_created} student(s) have a moderated file but no original file; "
            "the moderated file will be given the original-style name (name.pdf)."
        )

    with st.expander("Preview: what will be in the ZIP", expanded=True):
        st.dataframe(plan_table_rows(plan), use_container_width=True, hide_index=True)

    if not changes:
        st.info("No _int_mod or _ext_mod files were found, so every file would stay as it is.")

    sig = tuple(sorted((nm, f.size) for nm, f in file_map.items()))
    start_clicked = st.button(
        f"Build ZIP of {len(plan)} final PDF(s)",
        type="primary",
        use_container_width=True,
    )
    if st.button("Clear"):
        clear_work()
        st.rerun()

    if start_clicked:
        progress_bar = st.progress(0.0)
        with st.spinner("Building ZIP..."):
            zip_bytes, log_text, ok, fail = build_final_zip(plan, file_map, progress_bar)
        progress_bar.empty()
        st.session_state.results = {
            "zip_bytes": zip_bytes,
            "log": log_text,
            "ok": ok,
            "fail": fail,
            "summary": f"Done! Final files: {ok} | Failed: {fail}",
        }
        st.session_state.results_sig = sig

    res = st.session_state.results
    if res and st.session_state.results_sig == sig:
        if res["fail"] == 0:
            st.success(res["summary"])
        elif res["ok"] > 0:
            st.warning(res["summary"])
        else:
            st.error(res["summary"])

        if res["zip_bytes"]:
            st.download_button(
                label=f"💾 Download final PDFs ({OUTPUT_FOLDER_NAME}.zip)",
                data=res["zip_bytes"],
                file_name=f"{OUTPUT_FOLDER_NAME}.zip",
                mime="application/zip",
                type="primary",
                use_container_width=True,
            )
            st.caption(
                "Extract the ZIP into an EMPTY folder, or over your old folder after backing it up. "
                "A web app cannot delete the old _int_mod / _ext_mod files on your computer."
            )

        with st.expander("Processing log", expanded=(res["fail"] > 0)):
            st.code(res["log"], language=None)


if __name__ == "__main__":
    main()
