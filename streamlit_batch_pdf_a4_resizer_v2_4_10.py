#!/usr/bin/env python3
"""
Batch PDF to A4 Portrait Resizer - Web App (Streamlit Cloud Edition - v2.4.10)
Vishal Ramnath, ramnav@unisa.ac.za - 21 November 2026
Copyright Unisa 2026. Intended for the exclusive use of Unisa lecturers,
internal moderators, and external moderators only.

Resizes uploaded PDFs to exact ISO A4 Portrait dimensions:
21.0 cm x 29.7 cm (595.28 x 841.89 PDF points at 72 DPI), properly handling
page rotation metadata (/Rotate), CropBox boundaries, and arbitrary phone/scanner DPIs.
All resized files are returned in a single ZIP (folder "A4_Resized").
"""

import hmac
import io
import os
import zipfile
from pathlib import Path

import pymupdf
import streamlit as st

# =====================================================================
# SETTINGS
# =====================================================================
# Exact ISO A4 portrait dimensions in PDF points (1 inch = 72 pt, 1 inch = 2.54 cm)
# 21.0 cm = 595.2756 pt | 29.7 cm = 841.8898 pt
A4_WIDTH_PT = 21.0 / 2.54 * 72.0    # 595.28 pt
A4_HEIGHT_PT = 29.7 / 2.54 * 72.0   # 841.89 pt
OUTPUT_FOLDER_NAME = "A4_Resized"   # folder name inside the downloaded ZIP
DEFAULT_AUTO_ROTATE = True          # rotate landscape pages to portrait by default


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

    st.subheader("Batch PDF A4 Resizer v2.4.10 — Restricted Access")
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
        submitted = st.form_submit_button("Unlock Batch Resizer", type="primary", use_container_width=True)

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
# Core A4 resizing logic (same algorithm as desktop v2.4.10)
# ---------------------------------------------------------------------------
def resize_pdf_bytes_to_a4(pdf_bytes: bytes, auto_rotate_landscape: bool = True) -> bytes:
    """
    Scales and centres each visible page of a PDF proportionally onto an exact
    A4 portrait page (21.0 cm x 29.7 cm), respecting /Rotate and CropBox.
    Returns the resized PDF as bytes.
    """
    src_doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    out_doc = pymupdf.open()

    try:
        if getattr(src_doc, "needs_pass", False):
            raise ValueError("PDF is password-protected")

        for page_num in range(len(src_doc)):
            src_page = src_doc[page_num]
            # page.rect already accounts for both CropBox and /Rotate metadata
            vis_rect = src_page.rect
            orig_w = float(vis_rect.width)
            orig_h = float(vis_rect.height)

            if orig_w <= 0 or orig_h <= 0:
                continue

            # Optionally rotate landscape pages by 90 deg so phone scans stand upright
            extra_rotate = 0
            if auto_rotate_landscape and orig_w > orig_h:
                extra_rotate = 90
                eff_w, eff_h = orig_h, orig_w
            else:
                eff_w, eff_h = orig_w, orig_h

            # Proportional scale factor to fit cleanly within A4 portrait without clipping
            scale = min(A4_WIDTH_PT / eff_w, A4_HEIGHT_PT / eff_h)
            scaled_w = eff_w * scale
            scaled_h = eff_h * scale

            # Centre the scaled content on the A4 portrait canvas
            offset_x = (A4_WIDTH_PT - scaled_w) / 2.0
            offset_y = (A4_HEIGHT_PT - scaled_h) / 2.0

            target_rect = pymupdf.Rect(
                offset_x,
                offset_y,
                offset_x + scaled_w,
                offset_y + scaled_h,
            )

            a4_page = out_doc.new_page(width=A4_WIDTH_PT, height=A4_HEIGHT_PT)
            a4_page.show_pdf_page(
                target_rect,
                src_doc,
                page_num,
                rotate=extra_rotate,
                keep_proportion=True,
            )

        if len(out_doc) == 0:
            raise ValueError("PDF has no usable pages")

        return out_doc.tobytes(garbage=4, deflate=True)
    finally:
        out_doc.close()
        src_doc.close()


def unique_name(name: str, used: set) -> str:
    """Avoid overwriting when two uploaded files share the same name."""
    if name not in used:
        used.add(name)
        return name
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 2
    while f"{stem}_{n}{suffix}" in used:
        n += 1
    new_name = f"{stem}_{n}{suffix}"
    used.add(new_name)
    return new_name


def process_uploads(uploaded_files, auto_rotate: bool, progress_bar, status_box) -> dict:
    """Resize every uploaded PDF, one at a time, writing each result straight into a ZIP."""
    files = sorted(uploaded_files, key=lambda f: f.name.lower())
    total = len(files)
    zip_buf = io.BytesIO()
    used_names: set = set()
    ok_names = []
    log_lines = [
        f"Files received: {total}",
        f"Output folder:  {OUTPUT_FOLDER_NAME}/ (inside the ZIP)",
        "Target size:    A4 Portrait (21.0 cm x 29.7 cm / 595.28 x 841.89 pt)",
        "-" * 58,
    ]
    success_count = 0
    error_count = 0

    # PDFs are already compressed, so the ZIP just stores them (faster, less memory)
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_STORED) as zf:
        for idx, f in enumerate(files, start=1):
            filename = Path(f.name).name
            status_box.write(f"Processing ({idx}/{total}): {filename}")
            progress_bar.progress((idx - 1) / total)
            try:
                resized = resize_pdf_bytes_to_a4(f.getvalue(), auto_rotate_landscape=auto_rotate)
                arc_name = unique_name(filename, used_names)
                zf.writestr(f"{OUTPUT_FOLDER_NAME}/{arc_name}", resized)
                ok_names.append((arc_name, resized if total == 1 else None))
                success_count += 1
                log_lines.append(f"[OK]   {filename}")
            except Exception as exc:
                error_count += 1
                log_lines.append(f"[FAIL] {filename} -> {exc}")

    progress_bar.progress(1.0)
    summary = f"Done! Resized to A4: {success_count} | Failed: {error_count}"
    log_lines.append("-" * 58)
    log_lines.append(summary)

    single_pdf = None
    if total == 1 and success_count == 1:
        single_pdf = (ok_names[0][0], ok_names[0][1])

    return {
        "zip_bytes": zip_buf.getvalue() if success_count else None,
        "log": "\n".join(log_lines),
        "summary": summary,
        "ok": success_count,
        "fail": error_count,
        "single_pdf": single_pdf,
    }


# ---------------------------------------------------------------------------
# Session State & Dialogs
# ---------------------------------------------------------------------------
def init_session_state():
    defaults = {
        "authenticated": False,
        "authenticated_user": "",
        "auto_rotate": DEFAULT_AUTO_ROTATE,
        "results": None,
        "uploader_nonce": 0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


@st.dialog("About Batch PDF A4 Resizer")
def show_about_dialog():
    show_logo_or_banner(subtitle_size="13px", title_size="26px")
    st.markdown(
        "**Copyright Unisa 2026, Vishal Ramnath, 21 November 2026. Version 2.4.10.**\n\n"
        "This program is intended for the exclusive use of Unisa lecturers, "
        "internal moderators, and external moderators only."
    )


def clear_work():
    st.session_state.results = None
    st.session_state.uploader_nonce += 1


# ---------------------------------------------------------------------------
# Main Streamlit UI
# ---------------------------------------------------------------------------
def main():
    st.set_page_config(
        page_title="Batch PDF A4 Resizer v2.4.10 | UNISA CSET",
        page_icon="📄",
        layout="centered",
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
        st.markdown("### Batch PDF A4 Resizer v2.4.10")
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
    st.markdown("#### Batch Resize PDFs to A4 Portrait (21.0 cm × 29.7 cm)")
    st.caption(
        "Upload one or more student PDFs. Resized A4 files are returned in a single ZIP "
        f"(folder '{OUTPUT_FOLDER_NAME}'), keeping the original file names."
    )

    st.session_state.auto_rotate = st.checkbox(
        "Auto-rotate landscape pages to portrait (recommended for phone/CamScanner scans)",
        value=st.session_state.auto_rotate,
    )

    uploaded = st.file_uploader(
        "Select PDF files to resize",
        type=["pdf"],
        accept_multiple_files=True,
        key=f"batch_uploader_{st.session_state.uploader_nonce}",
    )

    c1, c2 = st.columns([3, 1])
    start_clicked = c1.button(
        f"Resize {len(uploaded) if uploaded else ''} PDF(s) to A4".replace("  ", " "),
        type="primary",
        use_container_width=True,
        disabled=not uploaded,
    )
    if c2.button("Clear", use_container_width=True):
        clear_work()
        st.rerun()

    if start_clicked and uploaded:
        st.session_state.results = None
        progress_bar = st.progress(0.0)
        status_box = st.empty()
        with st.spinner("Resizing..."):
            st.session_state.results = process_uploads(
                uploaded,
                st.session_state.auto_rotate,
                progress_bar,
                status_box,
            )
        progress_bar.empty()
        status_box.empty()

    res = st.session_state.results
    if res:
        if res["fail"] == 0:
            st.success(res["summary"])
        elif res["ok"] > 0:
            st.warning(res["summary"])
        else:
            st.error(res["summary"])

        if res["zip_bytes"]:
            st.download_button(
                label=f"💾 Download resized PDFs ({OUTPUT_FOLDER_NAME}.zip)",
                data=res["zip_bytes"],
                file_name=f"{OUTPUT_FOLDER_NAME}.zip",
                mime="application/zip",
                type="primary",
                use_container_width=True,
            )
            if res["single_pdf"]:
                single_name, single_bytes = res["single_pdf"]
                st.download_button(
                    label=f"Download {single_name} only",
                    data=single_bytes,
                    file_name=single_name,
                    mime="application/pdf",
                    use_container_width=True,
                )

        with st.expander("Processing log", expanded=(res["fail"] > 0)):
            st.code(res["log"], language=None)

        st.caption(
            "Tip: Enable 'Ask where to save each file' in your browser to choose a target folder."
        )
    elif not uploaded:
        st.info("Upload student PDF scripts above, then click **Resize PDF(s) to A4**.")


if __name__ == "__main__":
    main()
