#!/usr/bin/env python3
"""
PDF Marker Web App (Streamlit Cloud Edition - Baseline v2.4.8)
Vishal Ramnath, ramnav@unisa.ac.za - 20 November 2026
Copyright Unisa 2026. Intended for the exclusive use of Unisa lecturers,
internal moderators, and external moderators only.
"""

import hmac
import io
import os
import re
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
import pymupdf
from PIL import Image, ImageDraw, ImageFont
import streamlit as st
from streamlit_image_coordinates import streamlit_image_coordinates

# Standard A4 dimensions in PDF points (72 DPI): 595 x 842 pt
A4_REF_DIAGONAL = (595.0 ** 2 + 842.0 ** 2) ** 0.5

COLOUR_MAP = {
    "Red": "#ff0000",
    "Green": "#008000",
    "Blue": "#0000ff",
}

ROLE_COLOUR_MAP = {
    "Lecturer": "Red",
    "Internal Moderator": "Green",
    "External Moderator": "Blue",
}

ROLE_SUFFIX_MAP = {
    "Lecturer": "_marked",
    "Internal Moderator": "_int_mod",
    "External Moderator": "_ext_mod",
}


# ---------------------------------------------------------------------------
# Unisa Staff Passcode Gate
# ---------------------------------------------------------------------------
def get_configured_passcode() -> str:
    """Read STAFF_PASSCODE from Streamlit Secrets (or env var), defaulting to UNISA2026."""
    try:
        if "STAFF_PASSCODE" in st.secrets:
            return str(st.secrets["STAFF_PASSCODE"]).strip()
    except Exception:
        pass
    return os.environ.get("STAFF_PASSCODE", "UNISA2026").strip()


def check_staff_authentication() -> bool:
    """Require a Unisa staff passcode before exposing the marking workspace."""
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

    logo_path = Path(__file__).parent / "unisa_logo.png"
    if logo_path.exists():
        st.image(str(logo_path), use_container_width=True)
    else:
        st.markdown(
            """
            <div style="background-color:#002f6c; color:white; padding:18px 22px; border-radius:8px; text-align:center; margin-bottom:16px;">
                <div style="font-size:28px; font-weight:800; letter-spacing:2px;">UNISA</div>
                <div style="font-size:14px; opacity:0.92; margin-top:4px;">College of Science, Engineering and Technology</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.subheader("PDF Marker v2.4.8 — Restricted Access")
    st.caption(
        "Intended for the exclusive use of Unisa lecturers, internal moderators, "
        "and external moderators only."
    )

    with st.form("unisa_passcode_form", clear_on_submit=False):
        entered_code = st.text_input(
            "Enter Unisa Staff / Moderator Passcode",
            type="password",
            placeholder="Enter passcode...",
        )
        submitted = st.form_submit_button("Unlock PDF Marker", type="primary", use_container_width=True)

    if submitted:
        expected_code = get_configured_passcode()
        if entered_code and hmac.compare_digest(entered_code.strip(), expected_code):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Invalid passcode. Please verify the passcode with the module lecturer.")

    return False


# ---------------------------------------------------------------------------
# Geometry & Scaling Helpers (Preserved from v2.4.8)
# ---------------------------------------------------------------------------
def get_page_scale_ratio(page):
    rect = page.rect
    diag = (rect.width ** 2 + rect.height ** 2) ** 0.5
    if diag <= 0:
        return 1.0
    return diag / A4_REF_DIAGONAL


def transform_point_for_rotation(x, y, old_w, old_h, delta_deg):
    delta = delta_deg % 360
    if delta == 90:
        return old_h - y, x
    elif delta == 270:
        return y, old_w - x
    elif delta == 180:
        return old_w - x, old_h - y
    return x, y


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def hex_to_rgba(h, alpha=255):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


def load_arial_like_font(size_px):
    candidates = [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "arialbd.ttf",
        "Arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=max(10, int(round(size_px))))
        except Exception:
            continue
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Matplotlib LaTeX + Plain-Text Transparent PNG Renderer (Preserved from v2.4.8)
# ---------------------------------------------------------------------------
def tokenize_with_latex(paragraph):
    cleaned = re.sub(r"\$\$(.+?)\$\$", r"$\1$", paragraph)
    parts = re.split(r"(\$[^$]+?\$)", cleaned)
    tokens = []
    for part in parts:
        if not part:
            continue
        if part.startswith("$") and part.endswith("$") and len(part) >= 2:
            tokens.append(part)
        else:
            for word in part.split(" "):
                if word:
                    tokens.append(word)
    return tokens


def measure_mpl_text(fig, renderer, text_str, fontsize_pt):
    t = fig.text(
        0.0,
        0.0,
        text_str,
        fontsize=fontsize_pt,
        fontfamily="sans-serif",
        fontname="Arial",
    )
    bbox = t.get_window_extent(renderer=renderer)
    t.remove()
    return max(1.0, bbox.width), max(1.0, bbox.height)


def wrap_mpl_lines(fig, renderer, text, fontsize_pt, max_pixel_width):
    wrapped = []
    for paragraph in (text.splitlines() or [text]):
        if not paragraph.strip():
            wrapped.append("")
            continue
        tokens = tokenize_with_latex(paragraph)
        current_line = ""
        for tok in tokens:
            candidate = tok if not current_line else f"{current_line} {tok}"
            try:
                w_px, _ = measure_mpl_text(fig, renderer, candidate, fontsize_pt)
            except Exception:
                safe_tok = tok.replace("$", r"\$")
                candidate = safe_tok if not current_line else f"{current_line} {safe_tok}"
                w_px, _ = measure_mpl_text(fig, renderer, candidate, fontsize_pt)

            if w_px <= max_pixel_width or not current_line:
                current_line = candidate
            else:
                wrapped.append(current_line)
                current_line = tok
        if current_line:
            wrapped.append(current_line)
    return wrapped or [text]


def render_matplotlib_text_block(text, hex_colour, fontsize_pt, dpi, max_box_width_pt=None):
    fig = Figure(figsize=(8, 4), dpi=dpi)
    fig.patch.set_alpha(0.0)
    canvas = FigureCanvasAgg(fig)
    renderer = canvas.get_renderer()

    with matplotlib.rc_context({
        "mathtext.fontset": "dejavusans",
        "mathtext.default": "regular",
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "DejaVu Sans", "Liberation Sans"],
    }):
        pad_px = max(4, int(round(5 * (dpi / 72.0))))
        if max_box_width_pt is not None:
            max_px = max(40.0, max_box_width_pt * (dpi / 72.0) - 2 * pad_px)
            lines = wrap_mpl_lines(fig, renderer, text, fontsize_pt, max_px)
        else:
            lines = text.splitlines() or [text]

        safe_lines = []
        line_metrics = []
        for ln in lines:
            display_ln = ln if ln else " "
            try:
                w_px, h_px = measure_mpl_text(fig, renderer, display_ln, fontsize_pt)
                safe_lines.append(ln)
                line_metrics.append((w_px, h_px))
            except Exception:
                escaped_ln = ln.replace("$", r"\$")
                w_px, h_px = measure_mpl_text(
                    fig, renderer, escaped_ln if escaped_ln else " ", fontsize_pt
                )
                safe_lines.append(escaped_ln)
                line_metrics.append((w_px, h_px))

        line_gap_px = max(2.0, 3.0 * (dpi / 72.0))
        content_w = max((m[0] for m in line_metrics), default=20.0)
        content_h = sum(m[1] for m in line_metrics) + line_gap_px * max(0, len(line_metrics) - 1)

        total_w_px = int(round(content_w + 2 * pad_px + 6))
        total_h_px = int(round(content_h + 2 * pad_px + 6))

        fig.set_size_inches(total_w_px / dpi, total_h_px / dpi)
        canvas = FigureCanvasAgg(fig)
        renderer = canvas.get_renderer()

        y_cursor_px = total_h_px - pad_px - 2
        for ln, (_, h_px) in zip(safe_lines, line_metrics):
            if ln:
                fig.text(
                    (pad_px + 2) / total_w_px,
                    y_cursor_px / total_h_px,
                    ln,
                    fontsize=fontsize_pt,
                    color=hex_colour,
                    ha="left",
                    va="top",
                    fontfamily="sans-serif",
                    fontname="Arial",
                )
            y_cursor_px -= (h_px + line_gap_px)

        canvas.draw()
        buf = canvas.buffer_rgba()
        raw_img = Image.frombuffer(
            "RGBA",
            canvas.get_width_height(),
            bytes(buf),
            "raw",
            "RGBA",
            0,
            1,
        ).copy()

    alpha_bbox = raw_img.getbbox()
    if alpha_bbox:
        crop_pad = max(3, int(round(4 * (dpi / 72.0))))
        x0 = max(0, alpha_bbox[0] - crop_pad)
        y0 = max(0, alpha_bbox[1] - crop_pad)
        x1 = min(raw_img.width, alpha_bbox[2] + crop_pad)
        y1 = min(raw_img.height, alpha_bbox[3] + crop_pad)
        raw_img = raw_img.crop((x0, y0, x1, y1))

    return raw_img


@st.cache_data(show_spinner=False)
def create_transparent_text_png_bytes(
    text,
    hex_colour,
    base_fontsize=14.0,
    scale=1.0,
    max_box_width_pt=None,
    max_box_height_pt=None,
):
    dpi = max(72.0, 72.0 * scale)
    effective_fontsize = float(base_fontsize)

    while True:
        img = render_matplotlib_text_block(
            text=text,
            hex_colour=hex_colour,
            fontsize_pt=effective_fontsize,
            dpi=dpi,
            max_box_width_pt=max_box_width_pt,
        )
        if (
            max_box_height_pt is not None
            and (img.height / scale) > max_box_height_pt
            and effective_fontsize > 6.0
        ):
            effective_fontsize = max(6.0, effective_fontsize * 0.85)
            continue
        break

    alpha = img.getchannel("A")
    alpha = alpha.point(lambda p: int(round(p * 0.5)))
    img.putalpha(alpha)

    rgb = tuple(int(hex_colour.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    border_rgba = (rgb[0], rgb[1], rgb[2], 90)
    draw = ImageDraw.Draw(img)
    draw.rectangle(
        [0, 0, img.width - 1, img.height - 1],
        outline=border_rgba,
        width=max(1, int(round(scale))),
    )

    out_buf = io.BytesIO()
    img.save(out_buf, format="PNG")
    return out_buf.getvalue()


# ---------------------------------------------------------------------------
# Page Preview & Marked PDF Export Builders
# ---------------------------------------------------------------------------
def build_annotated_page_preview(pdf_bytes, page_idx, zoom_factor, page_rotations, annotations):
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    total_pages = len(doc)
    page_idx = max(0, min(page_idx, total_pages - 1))
    page = doc[page_idx]

    delta_deg = page_rotations.get(page_idx, 0) % 360
    if delta_deg != 0:
        page.set_rotation((page.rotation + delta_deg) % 360)

    page_scale = get_page_scale_ratio(page)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom_factor, zoom_factor))
    base_img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples).convert("RGBA")
    draw = ImageDraw.Draw(base_img, "RGBA")

    scaled_mark_px = max(12, int(round(16 * page_scale * zoom_factor)))
    mark_font = load_arial_like_font(scaled_mark_px)

    for a in annotations:
        if a["page"] != page_idx:
            continue
        px = a["x"] * zoom_factor
        py = a["y"] * zoom_factor
        if a.get("kind") == "text_png":
            png_bytes = create_transparent_text_png_bytes(
                a["text"],
                a["colour"],
                base_fontsize=a.get("fontsize", 14) * page_scale,
                scale=zoom_factor,
                max_box_width_pt=a.get("max_w_pt"),
                max_box_height_pt=a.get("max_h_pt"),
            )
            note_img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
            base_img.alpha_composite(note_img, (int(round(px)), int(round(py))))
        else:
            rgba = hex_to_rgba(a["colour"], 235)
            draw.text((px, max(0.0, py - scaled_mark_px * 0.65)), a["text"], fill=rgba, font=mark_font)

    doc.close()
    return base_img.convert("RGB")


def generate_marked_pdf_bytes(
    pdf_bytes,
    page_rotations,
    annotations,
    max_marks,
    signature_role,
    annotation_colour_name,
    signature_bytes=None,
):
    out_doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")

    for page_idx, delta_deg in page_rotations.items():
        if delta_deg % 360 != 0 and 0 <= page_idx < len(out_doc):
            p = out_doc[page_idx]
            p.set_rotation((p.rotation + delta_deg) % 360)

    for a in annotations:
        page = out_doc[a["page"]]
        page_scale = get_page_scale_ratio(page)
        if a.get("kind") == "text_png":
            render_scale = 2.0
            png_bytes = create_transparent_text_png_bytes(
                a["text"],
                a["colour"],
                base_fontsize=a.get("fontsize", 14) * page_scale,
                scale=render_scale,
                max_box_width_pt=a.get("max_w_pt"),
                max_box_height_pt=a.get("max_h_pt"),
            )
            note_pil = Image.open(io.BytesIO(png_bytes))
            w_pt = note_pil.width / render_scale
            h_pt = note_pil.height / render_scale

            pw = page.rect.width
            ph = page.rect.height
            x0 = max(0.0, min(a["x"], pw - w_pt))
            y0 = max(0.0, min(a["y"], ph - h_pt))
            rect = pymupdf.Rect(x0, y0, x0 + w_pt, y0 + h_pt)
            page.insert_image(rect, stream=png_bytes)
        else:
            scaled_pdf_fontsize = max(8.0, 14.0 * page_scale)
            page.insert_text(
                (a["x"], a["y"]),
                a["text"],
                fontsize=scaled_pdf_fontsize,
                color=hex_to_rgb(a["colour"]),
            )

    score = sum(a["points"] for a in annotations)
    maxm = max(1, int(max_marks))
    pct = 100.0 * score / maxm

    first = out_doc[0]
    pw = first.rect.width
    ph = first.rect.height
    first_scale = get_page_scale_ratio(first)
    summary_colour = hex_to_rgb(COLOUR_MAP[annotation_colour_name])

    role = signature_role
    if role == "Lecturer":
        summary_x = 40 * first_scale
        summary_y = 40 * first_scale
    elif role == "Internal Moderator":
        summary_x = pw - 260 * first_scale
        summary_y = 40 * first_scale
    else:  # External Moderator
        summary_x = pw - 260 * first_scale
        summary_y = ph - 120 * first_scale

    first.insert_text(
        (summary_x, summary_y),
        f"Final Mark: {score}/{maxm}",
        fontsize=18 * first_scale,
        color=summary_colour,
    )
    first.insert_text(
        (summary_x, summary_y + 25 * first_scale),
        f"Percentage: {pct:.2f}%",
        fontsize=18 * first_scale,
        color=summary_colour,
    )
    first.insert_text(
        (summary_x, summary_y + 50 * first_scale),
        datetime.now().strftime("Marked: %Y-%m-%d %H:%M:%S"),
        fontsize=12 * first_scale,
        color=summary_colour,
    )

    if signature_bytes:
        sig_img = Image.open(io.BytesIO(signature_bytes)).convert("RGBA")
        alpha = sig_img.getchannel("A")
        alpha = alpha.point(lambda p: int(p * 0.5))
        sig_img.putalpha(alpha)
        sig_buf = io.BytesIO()
        sig_img.save(sig_buf, format="PNG")
        sig_50_bytes = sig_buf.getvalue()

        if role == "Lecturer":
            rect = pymupdf.Rect(
                40 * first_scale,
                130 * first_scale,
                220 * first_scale,
                220 * first_scale,
            )
        elif role == "Internal Moderator":
            rect = pymupdf.Rect(
                pw - 220 * first_scale,
                130 * first_scale,
                pw - 40 * first_scale,
                220 * first_scale,
            )
        else:  # External Moderator
            rect = pymupdf.Rect(
                pw - 220 * first_scale,
                ph - 260 * first_scale,
                pw - 40 * first_scale,
                ph - 170 * first_scale,
            )

        first.insert_image(rect, stream=sig_50_bytes)

        if role == "Lecturer":
            role_x = 50 * first_scale
            role_y = 235 * first_scale
        elif role == "Internal Moderator":
            role_x = pw - 210 * first_scale
            role_y = 235 * first_scale
        else:
            role_x = pw - 210 * first_scale
            role_y = ph - 155 * first_scale

        first.insert_text(
            (role_x, role_y),
            role,
            fontsize=12 * first_scale,
            color=summary_colour,
        )

    result_bytes = out_doc.tobytes()
    out_doc.close()
    return result_bytes


# ---------------------------------------------------------------------------
# Session State & Dialogs
# ---------------------------------------------------------------------------
def init_session_state():
    defaults = {
        "authenticated": False,
        "pdf_bytes": None,
        "pdf_filename": None,
        "total_pages": 0,
        "current_page": 0,
        "zoom_factor": 1.35,
        "annotations": [],
        "page_rotations": {},
        "current_tool": ("tick", 1),
        "pending_text_note": "",
        "pending_text_fontsize": 14,
        "default_note_fontsize": 14,
        "signature_bytes": None,
        "signature_name": None,
        "signature_role": "Lecturer",
        "annotation_colour": "Red",
        "max_marks": 35,
        "canvas_nonce": 0,
        "consumed_click": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


@st.dialog("About PDF Marker")
def show_about_dialog():
    logo_path = Path(__file__).parent / "unisa_logo.png"
    if logo_path.exists():
        st.image(str(logo_path), use_container_width=True)
    else:
        st.markdown(
            """
            <div style="background-color:#002f6c; color:white; padding:16px 20px; border-radius:6px; text-align:center; margin-bottom:12px;">
                <div style="font-size:26px; font-weight:800; letter-spacing:2px;">UNISA</div>
                <div style="font-size:13px; opacity:0.92; margin-top:4px;">College of Science, Engineering and Technology</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown(
        "**Copyright Unisa 2026, Vishal Ramnath, 20 November 2026.**\n\n"
        "This program is intended for the exclusive use of Unisa lecturers, "
        "internal moderators, and external moderators only."
    )


def rotate_current_page(delta_deg):
    if not st.session_state.pdf_bytes:
        return
    p_idx = st.session_state.current_page
    doc = pymupdf.open(stream=st.session_state.pdf_bytes, filetype="pdf")
    page = doc[p_idx]
    cur_rot = st.session_state.page_rotations.get(p_idx, 0) % 360
    if cur_rot != 0:
        page.set_rotation((page.rotation + cur_rot) % 360)

    old_w = page.rect.width
    old_h = page.rect.height
    doc.close()

    st.session_state.page_rotations[p_idx] = (cur_rot + delta_deg) % 360

    for a in st.session_state.annotations:
        if a["page"] == p_idx:
            nx, ny = transform_point_for_rotation(a["x"], a["y"], old_w, old_h, delta_deg)
            if a.get("kind") == "text_png":
                bw = a.get("box_w", 0)
                bh = a.get("box_h", 0)
                if delta_deg % 360 == 90:
                    nx = max(0.0, nx - bh)
                elif delta_deg % 360 == 270:
                    ny = max(0.0, ny - bw)
            a["x"] = nx
            a["y"] = ny

    st.session_state.canvas_nonce += 1


# ---------------------------------------------------------------------------
# Main Streamlit UI
# ---------------------------------------------------------------------------
def main():
    st.set_page_config(
        page_title="PDF Marker v2.4.8 | UNISA CSET",
        page_icon="✓",
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

    # ---------------- Sidebar: Save, Role, Signature, Tools & Score ----------------
    with st.sidebar:
        st.markdown("### PDF Marker v2.4.8")
        st.caption("Vishal Ramnath · ramnav@unisa.ac.za")

        # 0. Prominent Save Marked PDF button in Sidebar
        if st.session_state.pdf_bytes is not None:
            role = st.session_state.signature_role
            suffix = ROLE_SUFFIX_MAP.get(role, "_marked")
            stem = Path(st.session_state.pdf_filename).stem
            out_filename = f"{stem}{suffix}.pdf"

            marked_bytes = generate_marked_pdf_bytes(
                pdf_bytes=st.session_state.pdf_bytes,
                page_rotations=st.session_state.page_rotations,
                annotations=st.session_state.annotations,
                max_marks=st.session_state.max_marks,
                signature_role=role,
                annotation_colour_name=st.session_state.annotation_colour,
                signature_bytes=st.session_state.signature_bytes,
            )
            st.download_button(
                label=f"💾 Save Marked PDF\n({out_filename})",
                data=marked_bytes,
                file_name=out_filename,
                mime="application/pdf",
                type="primary",
                use_container_width=True,
            )
        else:
            st.button(
                "💾 Save Marked PDF",
                disabled=True,
                use_container_width=True,
                help="Open a PDF script first to enable saving.",
            )

        st.divider()

        # 1. Role & Signature PNG
        st.markdown("#### 1. Role & Signature")
        roles = ["Lecturer", "Internal Moderator", "External Moderator"]
        chosen_role = st.selectbox(
            "Active Role",
            options=roles,
            index=roles.index(st.session_state.signature_role),
        )
        if chosen_role != st.session_state.signature_role:
            st.session_state.signature_role = chosen_role
            st.session_state.annotation_colour = ROLE_COLOUR_MAP[chosen_role]
            st.rerun()

        sig_upload = st.file_uploader(
            "Load Signature PNG (optional)",
            type=["png"],
            key="sig_uploader",
        )
        if sig_upload is not None:
            st.session_state.signature_bytes = sig_upload.getvalue()
            st.session_state.signature_name = sig_upload.name
            st.success(f"Signature loaded ({st.session_state.signature_role})")

        # 2. Annotation Colour
        colour_options = ["Red", "Green", "Blue"]
        st.session_state.annotation_colour = st.radio(
            "Annotation Colour",
            options=colour_options,
            index=colour_options.index(st.session_state.annotation_colour),
            horizontal=True,
        )

        st.divider()

        # 3. Marking Tools
        st.markdown("#### 2. Marking Tools")
        c1, c2, c3 = st.columns(3)
        if c1.button("✓ 1pt", use_container_width=True):
            st.session_state.current_tool = ("tick", 1)
        if c2.button("✓ 2pt", use_container_width=True):
            st.session_state.current_tool = ("tick", 2)
        if c3.button("✓ 3pt", use_container_width=True):
            st.session_state.current_tool = ("tick", 3)

        c4, c5, c6 = st.columns(3)
        if c4.button("✓ 5pt", use_container_width=True):
            st.session_state.current_tool = ("tick", 5)
        if c5.button("✓ 10pt", use_container_width=True):
            st.session_state.current_tool = ("tick", 10)
        if c6.button("✗ Cross", use_container_width=True):
            st.session_state.current_tool = ("cross", 0)

        # Text & LaTeX Note Box
        with st.expander("Add Text & LaTeX Note", expanded=(st.session_state.current_tool[0] == "text")):
            st.caption(r"Wrap LaTeX math in `$ ... $` (e.g., `$F = m\frac{d^2x}{dt^2}$`).")
            note_font_size = st.selectbox(
                "Font (Arial) Size",
                options=[8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32],
                index=[8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32].index(
                    st.session_state.default_note_fontsize
                ),
            )
            note_input = st.text_area(
                "Note Content",
                value=st.session_state.pending_text_note,
                height=95,
                placeholder="Type feedback or $LaTeX$ formula...",
            )
            if st.button("Arm Note Tool (Click PDF to Place)", use_container_width=True):
                if not note_input.strip():
                    st.warning("Please enter annotation text first.")
                else:
                    st.session_state.default_note_fontsize = note_font_size
                    st.session_state.pending_text_fontsize = note_font_size
                    st.session_state.pending_text_note = note_input.strip()
                    st.session_state.current_tool = ("text", 0)
                    st.rerun()

        kind, pts = st.session_state.current_tool
        if kind == "tick":
            st.info(f"**Active Tool:** ✓ {pts}pt ({st.session_state.annotation_colour})")
        elif kind == "cross":
            st.info(f"**Active Tool:** ✗ Cross ({st.session_state.annotation_colour})")
        else:
            st.warning(
                f"**Active Tool:** Click PDF to place note ({st.session_state.pending_text_fontsize}pt)"
            )

        u1, u2 = st.columns(2)
        if u1.button("Undo", use_container_width=True):
            if st.session_state.annotations:
                st.session_state.annotations.pop()
                st.session_state.canvas_nonce += 1
                st.rerun()
        if u2.button("Reset Score", use_container_width=True):
            if st.session_state.annotations:
                st.session_state.annotations.clear()
                st.session_state.consumed_click = None
                st.session_state.canvas_nonce += 1
                st.rerun()

        st.divider()

        # 4. Score Summary
        score = sum(a["points"] for a in st.session_state.annotations)
        maxm = max(1, int(st.session_state.max_marks))
        pct = 100.0 * score / maxm
        st.metric("Marks", f"{score} / {maxm}", f"{pct:.2f}%")

        b1, b2 = st.columns(2)
        if b1.button("About", use_container_width=True):
            show_about_dialog()
        if b2.button("Lock App", use_container_width=True):
            st.session_state["authenticated"] = False
            st.rerun()

    # ---------------- Top Bar: File Upload, Assessment Total, Navigation, Rotate & Zoom ----------------
    top_cols = st.columns([2.8, 1.2, 1.5, 1.5, 1.5])

    with top_cols[0]:
        uploaded_pdf = st.file_uploader(
            "Open PDF Script",
            type=["pdf"],
            label_visibility="collapsed",
        )
        if uploaded_pdf is not None:
            file_id = f"{uploaded_pdf.name}_{uploaded_pdf.size}"
            if st.session_state.get("loaded_file_id") != file_id:
                raw_bytes = uploaded_pdf.getvalue()
                doc_check = pymupdf.open(stream=raw_bytes, filetype="pdf")
                st.session_state.loaded_file_id = file_id
                st.session_state.pdf_bytes = raw_bytes
                st.session_state.pdf_filename = uploaded_pdf.name
                st.session_state.total_pages = len(doc_check)
                st.session_state.current_page = 0
                st.session_state.annotations = []
                st.session_state.page_rotations = {}
                st.session_state.consumed_click = None
                st.session_state.canvas_nonce += 1
                doc_check.close()
                st.rerun()

    with top_cols[1]:
        st.session_state.max_marks = st.number_input(
            "Assessment Total",
            min_value=1,
            max_value=1000,
            value=int(st.session_state.max_marks),
            step=5,
            label_visibility="collapsed",
            help="Assessment Total Marks",
        )

    with top_cols[2]:
        nav1, nav2 = st.columns(2)
        if nav1.button("◀ Prev", use_container_width=True, disabled=(st.session_state.current_page <= 0)):
            st.session_state.current_page -= 1
            st.session_state.consumed_click = None
            st.session_state.canvas_nonce += 1
            st.rerun()
        if nav2.button(
            "Next ▶",
            use_container_width=True,
            disabled=(
                st.session_state.pdf_bytes is None
                or st.session_state.current_page >= st.session_state.total_pages - 1
            ),
        ):
            st.session_state.current_page += 1
            st.session_state.consumed_click = None
            st.session_state.canvas_nonce += 1
            st.rerun()

    with top_cols[3]:
        rot1, rot2 = st.columns(2)
        if rot1.button("↺ 90°", use_container_width=True, help="Rotate Counter-Clockwise"):
            rotate_current_page(-90)
            st.rerun()
        if rot2.button("↻ 90°", use_container_width=True, help="Rotate Clockwise"):
            rotate_current_page(90)
            st.rerun()

    with top_cols[4]:
        zm1, zm2 = st.columns(2)
        if zm1.button("Zoom -", use_container_width=True):
            st.session_state.zoom_factor = max(0.5, round(st.session_state.zoom_factor / 1.2, 2))
            st.session_state.canvas_nonce += 1
            st.rerun()
        if zm2.button("Zoom +", use_container_width=True):
            st.session_state.zoom_factor = min(3.0, round(st.session_state.zoom_factor * 1.2, 2))
            st.session_state.canvas_nonce += 1
            st.rerun()

    # ---------------- Interactive PDF Canvas Area ----------------
    if st.session_state.pdf_bytes is None:
        st.info(
            "Upload a student PDF script using **Open PDF Script** above to start marking. "
            "Click directly anywhere on the rendered PDF page to place ticks, crosses, or LaTeX notes."
        )
        return

    status_cols = st.columns([2, 2, 3])
    status_cols[0].caption(
        f"**File:** {st.session_state.pdf_filename} · "
        f"**Page {st.session_state.current_page + 1}/{st.session_state.total_pages}**"
    )
    status_cols[1].caption(
        f"**Role:** {st.session_state.signature_role} · "
        f"**Zoom:** {int(round(st.session_state.zoom_factor * 100))}%"
    )
    status_cols[2].caption("Tip: Enable 'Ask where to save each file' in your browser to choose a target folder.")

    preview_img = build_annotated_page_preview(
        pdf_bytes=st.session_state.pdf_bytes,
        page_idx=st.session_state.current_page,
        zoom_factor=st.session_state.zoom_factor,
        page_rotations=st.session_state.page_rotations,
        annotations=st.session_state.annotations,
    )

    # Fresh key per annotation/page/zoom forces streamlit_image_coordinates to reset
    # its cached click value to None after every click (eliminating runaway mark loops).
    canvas_key = (
        f"pdf_canvas_p{st.session_state.current_page}"
        f"_z{st.session_state.zoom_factor}"
        f"_n{st.session_state.canvas_nonce}"
    )
    coords = streamlit_image_coordinates(preview_img, key=canvas_key)

    if coords is not None and "x" in coords and "y" in coords:
        click_sig = (canvas_key, coords["x"], coords["y"])
        if click_sig != st.session_state.consumed_click:
            st.session_state.consumed_click = click_sig
            st.session_state.canvas_nonce += 1

            doc = pymupdf.open(stream=st.session_state.pdf_bytes, filetype="pdf")
            page = doc[st.session_state.current_page]
            cur_rot = st.session_state.page_rotations.get(st.session_state.current_page, 0) % 360
            if cur_rot != 0:
                page.set_rotation((page.rotation + cur_rot) % 360)

            pw = page.rect.width
            ph = page.rect.height
            page_scale = get_page_scale_ratio(page)
            doc.close()

            zoom = st.session_state.zoom_factor
            pdf_x = max(0.0, min(pw, coords["x"] / zoom))
            pdf_y = max(0.0, min(ph, coords["y"] / zoom))
            kind, pts = st.session_state.current_tool

            if kind == "text":
                role_colour_name = ROLE_COLOUR_MAP.get(st.session_state.signature_role, "Red")
                st.session_state.annotation_colour = role_colour_name
                colour = COLOUR_MAP[role_colour_name]

                margin = 10.0 * page_scale
                min_box_w = min(pw - 2 * margin, max(120.0 * page_scale, pw * 0.35))
                if pdf_x + min_box_w > pw - margin:
                    pdf_x = max(margin, pw - margin - min_box_w)

                max_w_pt = max(40.0, pw - pdf_x - margin)
                max_h_pt = max(30.0, ph - pdf_y - margin)

                test_png_bytes = create_transparent_text_png_bytes(
                    st.session_state.pending_text_note,
                    colour,
                    base_fontsize=st.session_state.pending_text_fontsize * page_scale,
                    scale=2.0,
                    max_box_width_pt=max_w_pt,
                    max_box_height_pt=max_h_pt,
                )
                test_pil = Image.open(io.BytesIO(test_png_bytes))
                box_w_pt = test_pil.width / 2.0
                box_h_pt = test_pil.height / 2.0

                if pdf_x + box_w_pt > pw - margin:
                    pdf_x = max(margin, pw - margin - box_w_pt)
                if pdf_y + box_h_pt > ph - margin:
                    pdf_y = max(margin, ph - margin - box_h_pt)

                st.session_state.annotations.append({
                    "kind": "text_png",
                    "page": st.session_state.current_page,
                    "x": pdf_x,
                    "y": pdf_y,
                    "text": st.session_state.pending_text_note,
                    "fontsize": st.session_state.pending_text_fontsize,
                    "max_w_pt": max_w_pt,
                    "max_h_pt": max_h_pt,
                    "box_w": box_w_pt,
                    "box_h": box_h_pt,
                    "points": 0,
                    "colour": colour,
                })
                st.session_state.pending_text_note = ""
                st.session_state.current_tool = ("tick", 1)
                st.rerun()
            else:
                selected_colour = COLOUR_MAP[st.session_state.annotation_colour]
                if kind == "tick":
                    text = f"✓{pts}"
                else:
                    text = "✗"
                    pts = 0

                st.session_state.annotations.append({
                    "kind": kind,
                    "page": st.session_state.current_page,
                    "x": pdf_x,
                    "y": pdf_y,
                    "text": text,
                    "points": pts,
                    "colour": selected_colour,
                })
                st.rerun()


if __name__ == "__main__":
    main()
