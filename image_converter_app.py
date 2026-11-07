#!/usr/bin/env python3
"""
FloatConvert — Smart Drag-Activated Radial Neon Image & Document Converter
==========================================================================
A frameless, always-on-top circular desktop UI with glowing neon accents,
zero-latency stealth activation, integrated 1:1 PDF ⇄ Word conversion,
real-time percentage circular loading indicator, and built-in Gumroad /
Offline License Key verification for commercial distribution.

How It Works:
1. Inactive by Default on Startup:
   When you open your laptop or launch the app, FloatConvert starts silently in
   Inactive Mode so it never triggers unexpectedly.
2. Press Ctrl + Alt + C to Enable (Auto-Off After 5 Minutes Idle):
   Activates Smart Drag Mode and starts a 5-minute inactivity countdown (resets
   on every use; automatically deactivates after 5 minutes of idle time).
   Press Ctrl + Alt + D to disable manually at any time.
3. Drag & Drop Supported Files Directly onto the Radial Wheel:
   When active, dragging a supported image (.jpg, .png, .webp, .heic, .gif,
   .bmp, .tiff, .ico, .avif) OR document (.pdf, .docx, .doc) pops up the
   circular neon UI in the center of your screen:
   - Drop an Image onto `ICO`, `GIF`, `WEBP`, `JPG`, `PNG`, or `PDF` to convert.
   - Drop a `.pdf` onto `WORD` to convert PDF → Editable Word (`.docx`) with
     1:1 layout, font, spacing, bullet, horizontal line, table, margin, and
     hyperlink preservation.
   - Drop a `.docx` / `.doc` onto `PDF` to convert Word → Print-Ready `.pdf`.
   - Drop a `.pdf` onto `JPG` / `PNG` / `WEBP` to export PDF pages as images.
4. Real-Time Numbered Percentage Circular Loading Indicator:
   During conversion, the center well displays a rotating neon progress ring
   with a live `0% – 100%` percentage counter, then automatically copies the
   converted file to your clipboard and hides the wheel when complete.

Requirements:
    pip install PyQt6 Pillow pillow-heif PyMuPDF pdf2docx python-docx pypdf

Usage:
    pythonw image_converter_app.py
"""

from __future__ import annotations

import html
import io
import json
import logging
import math
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Callable, Iterable

# Prevent crashes in PyInstaller `--noconsole` (`pythonw`) builds where
# `sys.stdout` and `sys.stderr` are `None` (libraries like `pdf2docx` write
# progress logs to `sys.stdout` and crash if it is `None`).
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

from PIL import Image, ImageOps

# Enable iPhone .HEIC / .HEIF support across all output formats (including PDF)
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:
    pass

from PyQt6.QtCore import (
    QMimeData,
    QPoint,
    QPointF,
    QRectF,
    Qt,
    QThread,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QConicalGradient,
    QCursor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QGuiApplication,
    QIcon,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QRadialGradient,
    QWheelEvent,
)
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

SINGLE_INSTANCE_KEY = "FloatConvert_Radial_SingleInstance_Server"

# ==============================================================================
# COMMERCIAL LICENSING SETTINGS (Gumroad + Offline Master Key)
# ==============================================================================
# Set to True when compiling the public version for customers on Gumroad.
# Keep False on your own machine if you want all Pro features unlocked by default.
ENFORCE_PRO_LICENSE = False

# Your Gumroad product permalink or Product ID (from your Gumroad product settings)
GUMROAD_PRODUCT_PERMALINK = "floatconvert"

# Master offline key for testing or VIP giveaways
MASTER_OFFLINE_KEYS = {"FLOAT-PRO-2026", "ZEESHAN-PRO-VIP"}

LICENSE_FILE_PATH = Path.home() / ".floatconvert_license.json"
PRO_ONLY_FORMATS = {"ICO", "GIF", "PDF", "WORD"}

# Auto-deactivate Smart Drag Mode after 5 minutes (300,000 ms) of inactivity
INACTIVITY_TIMEOUT_MS = 5 * 60 * 1000

# ISO A4 physical dimensions in millimeters (210mm x 297mm) and uniform margin (15mm)
A4_SHORT_MM = 210.0
A4_LONG_MM = 297.0
A4_MARGIN_MM = 15.0

# Image input extensions (including iPhone .heic / .heif)
IMAGE_INPUT_EXTS = {
    ".heic",
    ".heif",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".gif",
    ".tiff",
    ".tif",
    ".ico",
    ".ppm",
    ".pgm",
    ".jfif",
    ".avif",
}

# Document input extensions supported directly in the radial UI
WORD_INPUT_EXTS = {".docx", ".doc"}
PDF_INPUT_EXTS = {".pdf"}

# All supported input extensions that trigger the radial wheel on drag
SUPPORTED_INPUT_EXTS = IMAGE_INPUT_EXTS | WORD_INPUT_EXTS | PDF_INPUT_EXTS

# 7 Radial Format Tiles arranged around the upper ring (evenly spaced by 33°):
# (Label, Extension, Target Format Key, Angle in degrees [0=Right, 90=Bottom, 180=Left, 270=Top])
RADIAL_FORMATS = [
    ("ICO", ".ico", "ICO", 138.0),
    ("GIF", ".gif", "GIF", 171.0),
    ("WEBP", ".webp", "WEBP", 204.0),
    ("JPG", ".jpg", "JPEG", 237.0),
    ("PNG", ".png", "PNG", 270.0),
    ("PDF", ".pdf", "PDF", 303.0),
    ("WORD", ".docx", "DOCX", 336.0),
]

SCALE_PRESETS = ["Original", "1080p", "50%"]

# Windows Explorer & Desktop window class names where file drags originate
EXPLORER_WINDOW_CLASSES = {
    "CabinetWClass",
    "ExploreWClass",
    "Progman",
    "WorkerW",
    "#32770",
}


# ----------------------------------------------------------------------
# License Verification & Persistence Helpers
# ----------------------------------------------------------------------
def load_saved_license() -> bool:
    """Return True if Pro Mode is unlocked locally or ENFORCE_PRO_LICENSE is False."""
    if not ENFORCE_PRO_LICENSE:
        return True
    try:
        if LICENSE_FILE_PATH.exists():
            data = json.loads(LICENSE_FILE_PATH.read_text(encoding="utf-8"))
            return bool(data.get("is_pro", False) and data.get("license_key"))
    except Exception:  # noqa: BLE001
        pass
    return False


def verify_and_save_license_key(license_key: str) -> tuple[bool, str]:
    """
    Verify `license_key` against master offline keys or Gumroad's License API.
    Saves activation state to `~/.floatconvert_license.json`.
    """
    cleaned = license_key.strip()
    if not cleaned:
        return False, "Please enter a license key."

    if cleaned.upper() in MASTER_OFFLINE_KEYS:
        _save_license_file(cleaned.upper(), "offline_master")
        return True, "Pro License activated! All features unlocked."

    try:
        payload = urllib.parse.urlencode(
            {
                "product_permalink": GUMROAD_PRODUCT_PERMALINK,
                "license_key": cleaned,
                "increment_uses_count": "true",
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            "https://api.gumroad.com/v2/licenses/verify",
            data=payload,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if body.get("success") and not body.get("purchase", {}).get("refunded", False):
                _save_license_file(cleaned, "gumroad")
                return True, "Gumroad Pro License verified & activated!"
            return False, body.get("message", "Invalid or refunded license key.")
    except Exception as exc:  # noqa: BLE001
        return False, f"Verification error: {exc}"


def _save_license_file(key: str, source: str) -> None:
    try:
        LICENSE_FILE_PATH.write_text(
            json.dumps({"is_pro": True, "license_key": key, "source": source}, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


class LicenseActivationDialog(QDialog):
    """Dark neon dialog for activating a FloatConvert Pro license key."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Activate FloatConvert Pro")
        self.setFixedSize(380, 210)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setStyleSheet(
            """
            QDialog {
                background-color: #0F172A;
                color: #F8FAFC;
            }
            QLabel#Header {
                color: #F8FAFC;
                font-size: 14px;
                font-weight: 700;
            }
            QLabel#Sub {
                color: #94A3B8;
                font-size: 11px;
            }
            QLineEdit {
                background-color: #1E293B;
                color: #F8FAFC;
                border: 1px solid #475569;
                border-radius: 7px;
                padding: 8px 10px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid #A855F7;
            }
            QPushButton#ActivateBtn {
                background-color: #6D28D9;
                color: #FFFFFF;
                border: 1px solid #A855F7;
                border-radius: 7px;
                padding: 7px 16px;
                font-size: 12px;
                font-weight: 700;
            }
            QPushButton#ActivateBtn:hover {
                background-color: #7C3AED;
            }
            QPushButton#CancelBtn {
                background-color: #1E293B;
                color: #CBD5E1;
                border: 1px solid #334155;
                border-radius: 7px;
                padding: 7px 14px;
                font-size: 12px;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        header = QLabel("⚡ Unlock FloatConvert Pro")
        header.setObjectName("Header")
        layout.addWidget(header)

        sub = QLabel(
            "Enter your Gumroad license key to unlock PDF ⇄ Word conversion, "
            "multi-page PDF merging, iPhone .HEIC support, and 1080p/50% scaling."
        )
        sub.setObjectName("Sub")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("XXXX-XXXX-XXXX-XXXX (or FLOAT-PRO-2026)")
        layout.addWidget(self.key_input)

        self.feedback_label = QLabel("")
        self.feedback_label.setObjectName("Sub")
        layout.addWidget(self.feedback_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("CancelBtn")
        cancel_btn.clicked.connect(self.reject)

        activate_btn = QPushButton("Activate Pro")
        activate_btn.setObjectName("ActivateBtn")
        activate_btn.clicked.connect(self._on_activate_clicked)

        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(activate_btn)
        layout.addLayout(btn_row)

    def _on_activate_clicked(self) -> None:
        ok, msg = verify_and_save_license_key(self.key_input.text())
        if ok:
            self.accept()
        else:
            self.feedback_label.setStyleSheet("color: #F87171; font-size: 11px;")
            self.feedback_label.setText(msg)


# ----------------------------------------------------------------------
# Global Hotkeys (Ctrl+Alt+C to Activate, Ctrl+Alt+D to Disable)
# ----------------------------------------------------------------------
class GlobalHotkeyThread(QThread):
    """
    Listens for native Windows Win32 hotkeys with 0% CPU usage and <1ms latency:
    - Hotkey 1 (Ctrl + Alt + C): Activate (Arm) Smart Drag Mode
    - Hotkey 2 (Ctrl + Alt + D): Disable Smart Drag Mode
    """

    activate_pressed = pyqtSignal()
    disable_pressed = pyqtSignal()

    def run(self) -> None:
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            MOD_ALT = 0x0001
            MOD_CONTROL = 0x0002
            MOD_NOREPEAT = 0x4000
            WM_HOTKEY = 0x0312
            mods = MOD_CONTROL | MOD_ALT | MOD_NOREPEAT

            user32.RegisterHotKey(None, 1, mods, ord("C"))
            user32.RegisterHotKey(None, 2, mods, ord("D"))

            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == WM_HOTKEY:
                    hk_id = msg.wParam
                    if hk_id == 1:
                        self.activate_pressed.emit()
                    elif hk_id == 2:
                        self.disable_pressed.emit()

            user32.UnregisterHotKey(None, 1)
            user32.UnregisterHotKey(None, 2)
        except Exception:  # noqa: BLE001
            pass


# ----------------------------------------------------------------------
# System Tray Icon & Formatting Helpers
# ----------------------------------------------------------------------
def create_neon_tray_icon(armed: bool = False) -> QIcon:
    """Generate a crisp circular icon for the System Tray (Neon when Armed, Dim when Inactive)."""
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    grad = QRadialGradient(QPointF(32, 32), 28)
    if armed:
        grad.setColorAt(0.0, QColor(192, 132, 252))
        grad.setColorAt(0.55, QColor(109, 40, 217))
        grad.setColorAt(1.0, QColor(15, 23, 42))
        ring_color = QColor(56, 189, 248)
        inner_border = QColor(216, 180, 254)
    else:
        grad.setColorAt(0.0, QColor(100, 116, 139))
        grad.setColorAt(0.55, QColor(51, 65, 85))
        grad.setColorAt(1.0, QColor(15, 23, 42))
        ring_color = QColor(71, 85, 105)
        inner_border = QColor(148, 163, 184)

    painter.setBrush(grad)
    painter.setPen(QPen(ring_color, 4.0))
    painter.drawEllipse(QPointF(32, 32), 26, 26)

    painter.setBrush(QColor(15, 23, 42))
    painter.setPen(QPen(inner_border, 2.0))
    painter.drawEllipse(QPointF(32, 32), 12, 12)
    painter.end()
    return QIcon(pix)


def format_bytes(num_bytes: int) -> str:
    """Format byte count as KB or MB."""
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    return f"{max(1, round(num_bytes / 1024))} KB"


def format_size_delta(orig_bytes: int, new_bytes: int) -> str:
    """Return a concise size-reduction readout such as '-78% • 1.4 MB saved'."""
    if orig_bytes <= 0 or new_bytes <= 0:
        return ""
    saved = orig_bytes - new_bytes
    if saved > 0:
        pct = int(round((saved / orig_bytes) * 100))
        return f"-{pct}% • {format_bytes(saved)} saved"
    return f"Size: {format_bytes(new_bytes)}"


def apply_resolution_preset(img: Image.Image, scale_preset: str) -> Image.Image:
    """Resize image according to the active preset ('Original', '1080p', '50%')."""
    if scale_preset == "1080p":
        max_dim = max(img.width, img.height)
        if max_dim > 1920:
            scale = 1920.0 / max_dim
            new_w = max(1, int(round(img.width * scale)))
            new_h = max(1, int(round(img.height * scale)))
            return img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    elif scale_preset == "50%":
        new_w = max(1, img.width // 2)
        new_h = max(1, img.height // 2)
        return img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    return img


def flatten_to_rgb(img: Image.Image) -> Image.Image:
    """Flatten RGBA/palette/HDR transparency onto a standard 8-bit white RGB background."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[3])
        return background
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def get_a4_pdf_dpi(scale_preset: str) -> float:
    """Return the target print DPI for ISO A4 PDF generation based on `scale_preset`."""
    if scale_preset == "1080p":
        return 200.0
    if scale_preset == "50%":
        return 150.0
    return 300.0


def compose_a4_pdf_page(img: Image.Image, scale_preset: str = "Original") -> tuple[Image.Image, float]:
    """
    Place `img` onto a clean, uniform ISO A4 page (210mm x 297mm):
    - Automatically selects Portrait (height >= width) or Landscape (width > height)
      orientation to match the image.
    - Maintains uniform 15mm margins on all four sides.
    - Preserves exact image aspect ratio (no stretching, no cropping, no overflow).
    - Centers the image cleanly on a crisp white RGB A4 canvas.
    Returns `(a4_page_image, dpi)`.
    """
    img = ImageOps.exif_transpose(img)
    rgb = flatten_to_rgb(img)

    dpi = get_a4_pdf_dpi(scale_preset)
    short_px = int(round((A4_SHORT_MM / 25.4) * dpi))
    long_px = int(round((A4_LONG_MM / 25.4) * dpi))
    margin_px = int(round((A4_MARGIN_MM / 25.4) * dpi))

    if rgb.width > rgb.height:
        page_w, page_h = long_px, short_px
    else:
        page_w, page_h = short_px, long_px

    avail_w = max(1, page_w - 2 * margin_px)
    avail_h = max(1, page_h - 2 * margin_px)

    fit_scale = min(avail_w / max(1, rgb.width), avail_h / max(1, rgb.height))
    target_w = max(1, min(avail_w, int(round(rgb.width * fit_scale))))
    target_h = max(1, min(avail_h, int(round(rgb.height * fit_scale))))

    if (target_w, target_h) != rgb.size:
        fitted = rgb.resize((target_w, target_h), Image.Resampling.LANCZOS)
    else:
        fitted = rgb

    page = Image.new("RGB", (page_w, page_h), (255, 255, 255))
    paste_x = margin_px + (avail_w - target_w) // 2
    paste_y = margin_px + (avail_h - target_h) // 2
    page.paste(fitted, (paste_x, paste_y))
    return page, dpi


def _unique_output_path(parent_dir: Path, stem: str, target_ext: str) -> Path:
    candidate = parent_dir / f"{stem}{target_ext}"
    counter = 1
    while candidate.exists():
        candidate = parent_dir / f"{stem}_{counter}{target_ext}"
        counter += 1
    return candidate


# ----------------------------------------------------------------------
# 1:1 Precision PDF ⇄ Word Conversion Engine (Fonts, Lines, Bullets, Tables)
# ----------------------------------------------------------------------
_SUBSET_FONT_RE = re.compile(r"^[A-Z]{6}\+")
_PDF2DOCX_STAGE_RE = re.compile(r"\((\d+)/4\)\s*Page\s*(\d+)", re.IGNORECASE)
_BULLET_CHARS = {"•", "●", "▪", "◦", "‣", "⁃", "–", "-"}


def _clean_font_and_style(raw_font: str | None, flags: int = 0) -> tuple[str, bool, bool]:
    """
    Map embedded PDF font names (e.g. `BCDEEE+Calibri-Bold`, `TimesNewRomanPSMT`)
    and MuPDF flags to clean Word font families and `(is_bold, is_italic)` flags.
    """
    is_bold = bool(flags & 16)
    is_italic = bool(flags & 2)
    if not raw_font:
        return "Calibri", is_bold, is_italic

    cleaned = _SUBSET_FONT_RE.sub("", raw_font).strip()
    lower = cleaned.lower()
    if any(k in lower for k in ("bold", "black", "heavy", "demi", "semibold")):
        is_bold = True
    if any(k in lower for k in ("italic", "oblique")):
        is_italic = True

    if "calibri" in lower:
        family = "Calibri"
    elif "arial" in lower or "helvetica" in lower:
        family = "Arial"
    elif "times" in lower:
        family = "Times New Roman"
    elif "segoe" in lower:
        family = "Segoe UI"
    elif "cambria" in lower:
        family = "Cambria"
    elif "georgia" in lower:
        family = "Georgia"
    elif "garamond" in lower:
        family = "Garamond"
    elif "verdana" in lower:
        family = "Verdana"
    elif "tahoma" in lower:
        family = "Tahoma"
    elif "consolas" in lower or "courier" in lower:
        family = "Consolas"
    else:
        family = (
            re.sub(
                r"[-,](BoldItalic|Bold|Italic|Regular|Medium|Light|PSMT|MT).*$",
                "",
                cleaned,
                flags=re.IGNORECASE,
            )
            or "Calibri"
        )
    return family, is_bold, is_italic


def _norm_color_to_rgb(c) -> tuple[int, int, int]:
    """Convert PDF color (int sRGB, float greyscale, or float RGB tuple) to `(R, G, B)` 0..255."""
    if c is None:
        return (0, 0, 0)
    if isinstance(c, int):
        # PyMuPDF span color is a 24-bit integer 0xRRGGBB
        if c > 1:
            return ((c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF)
        v = max(0, min(255, int(round(c * 255))))
        return (v, v, v)
    if isinstance(c, float):
        v = max(0, min(255, int(round(c * 255))))
        return (v, v, v)
    if isinstance(c, (tuple, list)):
        if len(c) == 1:
            v = max(0, min(255, int(round(float(c[0]) * 255))))
            return (v, v, v)
        if len(c) >= 3:
            if any(isinstance(x, float) and x <= 1.0 for x in c[:3]) and max(c[:3]) <= 1.0:
                return tuple(max(0, min(255, int(round(float(x) * 255)))) for x in c[:3])
            return tuple(max(0, min(255, int(round(float(x))))) for x in c[:3])
    return (0, 0, 0)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def _add_paragraph_bottom_border(p, hex_color: str, height_pt: float, space_pt: int = 2) -> None:
    """Attach a crisp OpenXML full-width bottom border (`<w:pBdr><w:bottom .../>`) to paragraph `p`."""
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    sz = max(4, min(18, int(round(height_pt * 8))))
    pPr = p._p.get_or_add_pPr()
    for existing in pPr.findall(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pBdr"
    ):
        pPr.remove(existing)
    pBdr = parse_xml(
        f'<w:pBdr {nsdecls("w")}>'
        f'<w:bottom w:val="single" w:sz="{sz}" w:space="{space_pt}" w:color="{hex_color}"/>'
        f"</w:pBdr>"
    )
    pPr.append(pBdr)


def _extract_page_layout_fitz(pdf_path: Path) -> list[dict]:
    """
    Extract exact per-page geometry, visual horizontal text lines, spans, thin
    horizontal divider rules, link underlines, and embedded images using `PyMuPDF` (`fitz`).
    Also detects if a page contains a multi-cell grid table.
    """
    import fitz

    pages_data: list[dict] = []
    with fitz.open(str(pdf_path)) as doc:
        for page in doc:
            pw = float(page.rect.width)
            ph = float(page.rect.height)

            hrules: list[dict] = []
            underlines: list[dict] = []
            v_segments = 0

            # 1. Inspect vector drawings for section divider lines, underlines, and table grids
            for d in page.get_drawings():
                rect = d.get("rect")
                if not rect:
                    continue
                rw = float(rect.width)
                rh = float(rect.height)
                col = _norm_color_to_rgb(d.get("fill") or d.get("color"))
                if rh <= 3.8 and rw >= 130.0:
                    hrules.append(
                        {
                            "x0": float(rect.x0),
                            "x1": float(rect.x1),
                            "top": float(rect.y0),
                            "bottom": float(rect.y1),
                            "width": rw,
                            "height": max(0.5, rh),
                            "hex": _rgb_to_hex(col),
                        }
                    )
                elif rh <= 2.2 and 14.0 <= rw < 130.0:
                    underlines.append(
                        {
                            "x0": float(rect.x0),
                            "x1": float(rect.x1),
                            "top": float(rect.y0),
                            "bottom": float(rect.y1),
                            "hex": _rgb_to_hex(col),
                        }
                    )
                elif rw <= 3.0 and rh >= 18.0:
                    v_segments += 1

            # Also check PDF hyperlink annotations as underlined regions
            for lnk in page.get_links():
                lrect = lnk.get("from")
                if lrect:
                    underlines.append(
                        {
                            "x0": float(lrect.x0),
                            "x1": float(lrect.x1),
                            "top": float(lrect.y1) - 1.0,
                            "bottom": float(lrect.y1),
                            "hex": "1F3864",
                        }
                    )

            # 2. Extract all text spans and cluster into visual horizontal lines by Y-midpoint
            raw_spans: list[dict] = []
            image_blocks: list[dict] = []
            text_dict = page.get_text("dict")
            for b in text_dict.get("blocks", []):
                btype = b.get("type", 0)
                if btype == 0:
                    for line in b.get("lines", []):
                        for sp in line.get("spans", []):
                            txt = sp.get("text", "")
                            if not txt or not txt.strip():
                                continue
                            bbox = sp.get("bbox", (0, 0, 0, 0))
                            sx0, stop, sx1, sbot = (
                                float(bbox[0]),
                                float(bbox[1]),
                                float(bbox[2]),
                                float(bbox[3]),
                            )
                            fam, bold, italic = _clean_font_and_style(
                                sp.get("font"), int(sp.get("flags", 0))
                            )
                            sz = round(float(sp.get("size", 10.0)) * 2) / 2.0
                            rgb = _norm_color_to_rgb(sp.get("color", 0))
                            is_ul = any(
                                (u["x0"] - 4.0 <= (sx0 + sx1) / 2.0 <= u["x1"] + 4.0)
                                and (abs(u["top"] - sbot) <= 4.5)
                                for u in underlines
                            )
                            raw_spans.append(
                                {
                                    "key": (fam, sz, bold, italic, rgb, is_ul),
                                    "x0": sx0,
                                    "x1": sx1,
                                    "top": stop,
                                    "bottom": sbot,
                                    "ymid": (stop + sbot) / 2.0,
                                    "text": txt,
                                }
                            )
                elif btype == 1 and b.get("image"):
                    bbox = b.get("bbox", (0, 0, 100, 100))
                    image_blocks.append(
                        {
                            "x0": float(bbox[0]),
                            "top": float(bbox[1]),
                            "x1": float(bbox[2]),
                            "bottom": float(bbox[3]),
                            "width": max(12.0, float(bbox[2]) - float(bbox[0])),
                            "image": b.get("image"),
                        }
                    )

            # Cluster spans whose vertical centers are within 3.5pt into single visual lines
            raw_spans.sort(key=lambda s: (round(s["ymid"] / 3.0), s["x0"]))
            visual_lines: list[list[dict]] = []
            for sp in sorted(raw_spans, key=lambda s: s["ymid"]):
                placed = False
                for vline in visual_lines:
                    avg_ymid = sum(x["ymid"] for x in vline) / len(vline)
                    if abs(sp["ymid"] - avg_ymid) <= 3.5:
                        vline.append(sp)
                        placed = True
                        break
                if not placed:
                    visual_lines.append([sp])

            for vline in visual_lines:
                vline.sort(key=lambda s: s["x0"])

            visual_lines.sort(key=lambda vl: min(s["top"] for s in vl))

            pages_data.append(
                {
                    "width": pw,
                    "height": ph,
                    "hrules": sorted(hrules, key=lambda r: r["top"]),
                    "visual_lines": visual_lines,
                    "images": image_blocks,
                    "has_grid_table": v_segments >= 6,
                }
            )
    return pages_data


def _extract_page_layout_pdfplumber(pdf_path: Path) -> list[dict]:
    """Fallback extractor using `pdfplumber` if `fitz` is not installed."""
    import pdfplumber

    pages_data: list[dict] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            pw = float(page.width)
            ph = float(page.height)
            lines = page.extract_text_lines(
                extra_attrs=["fontname", "size", "non_stroking_color"]
            )
            rects = page.rects or []
            plines = page.lines or []

            hrules: list[dict] = []
            underlines: list[dict] = []
            v_segments = 0
            for r in rects + plines:
                rw = float(r.get("width", abs(r.get("x1", 0) - r.get("x0", 0))))
                rh = float(r.get("height", abs(r.get("bottom", 0) - r.get("top", 0))))
                col = _norm_color_to_rgb(
                    r.get("non_stroking_color") or r.get("stroking_color")
                )
                if rh <= 3.8 and rw >= 130.0:
                    hrules.append(
                        {
                            "x0": float(r["x0"]),
                            "x1": float(r["x1"]),
                            "top": float(r["top"]),
                            "bottom": float(r["bottom"]),
                            "width": rw,
                            "height": max(0.5, rh),
                            "hex": _rgb_to_hex(col),
                        }
                    )
                elif rh <= 2.2 and 14.0 <= rw < 130.0:
                    underlines.append(
                        {
                            "x0": float(r["x0"]),
                            "x1": float(r["x1"]),
                            "top": float(r["top"]),
                            "bottom": float(r["bottom"]),
                            "hex": _rgb_to_hex(col),
                        }
                    )
                elif rw <= 3.0 and rh >= 18.0:
                    v_segments += 1

            visual_lines: list[list[dict]] = []
            for ln in lines:
                chars = ln.get("chars", [])
                if not chars:
                    continue
                spans: list[dict] = []
                for ch in chars:
                    txt = ch.get("text", "")
                    if not txt:
                        continue
                    fam, bold, italic = _clean_font_and_style(ch.get("fontname"))
                    sz = round(float(ch.get("size", 10.0)) * 2) / 2.0
                    rgb = _norm_color_to_rgb(ch.get("non_stroking_color"))
                    cx0, cx1 = float(ch["x0"]), float(ch["x1"])
                    ctop, cbot = float(ch["top"]), float(ch["bottom"])
                    is_ul = any(
                        (u["x0"] - 3.0 <= (cx0 + cx1) / 2.0 <= u["x1"] + 3.0)
                        and (abs(u["top"] - cbot) <= 4.0)
                        for u in underlines
                    )
                    key = (fam, sz, bold, italic, rgb, is_ul)
                    if not spans:
                        spans.append(
                            {
                                "key": key,
                                "x0": cx0,
                                "x1": cx1,
                                "top": ctop,
                                "bottom": cbot,
                                "text": txt,
                            }
                        )
                    else:
                        prev = spans[-1]
                        gap = cx0 - prev["x1"]
                        if (
                            prev["text"].strip() in _BULLET_CHARS and gap > 3.0
                        ) or gap >= 28.0:
                            spans.append(
                                {
                                    "key": key,
                                    "x0": cx0,
                                    "x1": cx1,
                                    "top": ctop,
                                    "bottom": cbot,
                                    "text": txt,
                                }
                            )
                        elif prev["key"] == key:
                            if (
                                gap > sz * 0.18
                                and not prev["text"].endswith(" ")
                                and txt != " "
                            ):
                                prev["text"] += " "
                            prev["text"] += txt
                            prev["x1"] = cx1
                        else:
                            if (
                                gap > sz * 0.18
                                and not prev["text"].endswith(" ")
                                and txt != " "
                            ):
                                prev["text"] += " "
                            spans.append(
                                {
                                    "key": key,
                                    "x0": cx0,
                                    "x1": cx1,
                                    "top": ctop,
                                    "bottom": cbot,
                                    "text": txt,
                                }
                            )
                if spans:
                    visual_lines.append(spans)

            pages_data.append(
                {
                    "width": pw,
                    "height": ph,
                    "hrules": sorted(hrules, key=lambda r: r["top"]),
                    "visual_lines": visual_lines,
                    "images": [],
                    "has_grid_table": v_segments >= 6,
                }
            )
    return pages_data


def _build_precision_docx_from_pages(
    pages_data: list[dict],
    out_docx: Path,
    progress_cb: Callable[[int], None] | None = None,
) -> None:
    """
    Construct a 1:1 formatted Word `.docx` from extracted PDF page layout data:
    - Exact page width, height, and margins.
    - Exact fonts, sizes, bold/italic/underline styles, and RGB text colors.
    - Full-width horizontal section divider rules (`<w:pBdr><w:bottom .../>`).
    - True hanging-indent bullet lists (`left_indent` + negative `first_line_indent` + tab stop).
    - Multi-stop tab alignment when a line has left + right columns (e.g. Role + Date).
    - Compensated vertical paragraph spacing so single-page documents never spill onto page 2.
    """
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
    from docx.shared import Pt, RGBColor

    doc = Document()
    for p in list(doc.paragraphs):
        p._element.getparent().remove(p._element)

    total_pages = max(1, len(pages_data))

    for page_idx, pinfo in enumerate(pages_data):
        pw = pinfo["width"]
        ph = pinfo["height"]
        hrules = pinfo["hrules"]
        vlines = pinfo["visual_lines"]

        all_x0 = [sp["x0"] for vl in vlines for sp in vl] + [r["x0"] for r in hrules]
        all_x1 = [sp["x1"] for vl in vlines for sp in vl] + [r["x1"] for r in hrules]
        all_top = [sp["top"] for vl in vlines for sp in vl]
        all_bot = [sp["bottom"] for vl in vlines for sp in vl]

        left_m = max(18.0, min(all_x0) if all_x0 else 36.0)
        right_m = max(18.0, (pw - max(all_x1)) if all_x1 else 36.0)
        top_m = max(18.0, min(all_top) if all_top else 36.0)
        bot_m = max(18.0, (ph - max(all_bot)) if all_bot else 36.0)

        section = doc.sections[0] if page_idx == 0 else doc.add_section()
        section.page_width = Pt(pw)
        section.page_height = Pt(ph)
        section.left_margin = Pt(left_m)
        section.right_margin = Pt(right_m)
        section.top_margin = Pt(top_m)
        section.bottom_margin = Pt(bot_m)

        body_width = max(100.0, pw - left_m - right_m)

        parsed_lines: list[dict] = []
        for vl in vlines:
            # Merge adjacent spans with identical formatting unless separated by a bullet or large column gap
            merged_spans: list[dict] = []
            tab_stops_on_line: list[tuple[float, str]] = []

            for sp in vl:
                txt = sp["text"]
                if not merged_spans:
                    merged_spans.append(dict(sp))
                    continue

                prev = merged_spans[-1]
                gap = sp["x0"] - prev["x1"]
                sz = sp["key"][1]

                if prev["text"].strip() in _BULLET_CHARS and gap > 2.0:
                    merged_spans.append(dict(sp))
                elif gap >= 28.0:
                    # Large horizontal gap on same line -> insert tab stop for multi-column alignment
                    prev["text"] = prev["text"].rstrip() + "\t"
                    is_right_col = sp["x1"] >= (pw - right_m - 18.0)
                    if is_right_col:
                        tab_stops_on_line.append((body_width, "RIGHT"))
                    else:
                        tab_stops_on_line.append((max(0.0, sp["x0"] - left_m), "LEFT"))
                    merged_spans.append(dict(sp))
                elif prev["key"] == sp["key"]:
                    if (
                        gap > sz * 0.16
                        and not prev["text"].endswith(" ")
                        and not txt.startswith(" ")
                    ):
                        prev["text"] += " "
                    prev["text"] += txt
                    prev["x1"] = max(prev["x1"], sp["x1"])
                else:
                    if (
                        gap > sz * 0.16
                        and not prev["text"].endswith(" ")
                        and not txt.startswith(" ")
                    ):
                        prev["text"] += " "
                    merged_spans.append(dict(sp))

            lx0 = min(s["x0"] for s in merged_spans)
            lx1 = max(s["x1"] for s in merged_spans)
            ltop = min(s["top"] for s in merged_spans)
            lbot = max(s["bottom"] for s in merged_spans)

            first_txt = merged_spans[0]["text"].strip()
            is_bullet = first_txt in _BULLET_CHARS or (
                len(first_txt) > 1
                and first_txt[0] in _BULLET_CHARS
                and first_txt[1] in (" ", "\t")
            )
            if is_bullet and first_txt not in _BULLET_CHARS:
                # Split leading bullet char from text if they were in the same PDF span
                bchar = first_txt[0]
                rest_txt = merged_spans[0]["text"].lstrip()[1:].lstrip()
                b_span = dict(merged_spans[0])
                b_span["text"] = bchar
                t_span = dict(merged_spans[0])
                t_span["text"] = rest_txt
                t_span["x0"] = lx0 + 13.0
                merged_spans = [b_span, t_span] + merged_spans[1:]

            bullet_text_x0 = (
                merged_spans[1]["x0"]
                if (is_bullet and len(merged_spans) > 1)
                else (lx0 + 13.0 if is_bullet else lx0)
            )

            l_gap = lx0 - left_m
            r_gap = (pw - right_m) - lx1
            is_centered = (
                (l_gap >= 35.0)
                and (abs(l_gap - r_gap) <= 15.0)
                and not is_bullet
                and not tab_stops_on_line
            )

            parsed_lines.append(
                {
                    "x0": lx0,
                    "x1": lx1,
                    "top": ltop,
                    "bottom": lbot,
                    "spans": merged_spans,
                    "is_bullet": is_bullet,
                    "bullet_text_x0": bullet_text_x0,
                    "is_centered": is_centered,
                    "tab_stops": tab_stops_on_line,
                    "max_size": max(s["key"][1] for s in merged_spans),
                    "any_bold": any(s["key"][2] for s in merged_spans),
                }
            )

        # Group wrapped continuation lines into natural editable paragraphs
        paragraphs: list[dict] = []
        used_hrules: set[int] = set()

        for pl in parsed_lines:
            if paragraphs:
                prev_p = paragraphs[-1]
                for hi, hr in enumerate(hrules):
                    if (
                        hi not in used_hrules
                        and prev_p["bottom"] - 2.0 <= hr["top"] <= pl["top"] + 2.0
                    ):
                        prev_p["bottom_border"] = hr
                        used_hrules.add(hi)

                v_gap = pl["top"] - prev_p["bottom"]
                prev_reached_right = prev_p["last_x1"] >= (left_m + body_width * 0.72)
                same_cont_x0 = abs(pl["x0"] - prev_p["cont_x0"]) <= 4.0
                same_font_size = abs(pl["max_size"] - prev_p["max_size"]) <= 0.6

                if (
                    "bottom_border" not in prev_p
                    and not prev_p["is_centered"]
                    and not pl["is_centered"]
                    and not pl["is_bullet"]
                    and not prev_p["tab_stops"]
                    and not pl["tab_stops"]
                    and not (pl["any_bold"] and not prev_p["any_bold"])
                    and v_gap <= 3.4
                    and prev_reached_right
                    and same_cont_x0
                    and same_font_size
                ):
                    if prev_p["spans"] and not prev_p["spans"][-1]["text"].endswith(" "):
                        prev_p["spans"][-1]["text"] += " "
                    prev_p["spans"].extend(pl["spans"])
                    prev_p["bottom"] = pl["bottom"]
                    prev_p["last_x1"] = pl["x1"]
                    prev_p["line_count"] += 1
                    prev_p["line_leading_sum"] += pl["top"] - prev_p["last_top"]
                    prev_p["last_top"] = pl["top"]
                    continue

            paragraphs.append(
                {
                    "x0": pl["x0"],
                    "cont_x0": pl["bullet_text_x0"] if pl["is_bullet"] else pl["x0"],
                    "last_x1": pl["x1"],
                    "top": pl["top"],
                    "last_top": pl["top"],
                    "bottom": pl["bottom"],
                    "spans": list(pl["spans"]),
                    "is_bullet": pl["is_bullet"],
                    "is_centered": pl["is_centered"],
                    "tab_stops": list(pl["tab_stops"]),
                    "max_size": pl["max_size"],
                    "any_bold": pl["any_bold"],
                    "line_count": 1,
                    "line_leading_sum": 0.0,
                }
            )

        if paragraphs:
            for hi, hr in enumerate(hrules):
                if hi not in used_hrules and hr["top"] >= paragraphs[-1]["bottom"] - 2.0:
                    paragraphs[-1]["bottom_border"] = hr
                    used_hrules.add(hi)

        # Emit Word paragraphs
        prev_bottom = top_m
        num_paras = max(1, len(paragraphs))
        for pi, pdata in enumerate(paragraphs):
            if progress_cb and pi % 4 == 0:
                page_base = (page_idx / total_pages) * 85.0
                page_frac = ((pi + 1) / num_paras) * (85.0 / total_pages)
                progress_cb(min(95, int(round(10 + page_base + page_frac))))

            p = doc.add_paragraph()
            pf = p.paragraph_format

            # Subtract Word's internal font leading (~0.22 * font_size) from raw bbox gap
            # so multi-section single-page resumes/documents fit on the exact same page count
            raw_gap = (
                max(0.0, (pdata["top"] - prev_bottom) - (0.22 * pdata["max_size"]))
                if pi > 0
                else 0.0
            )
            pf.space_before = Pt(round(raw_gap * 2) / 2.0)
            pf.space_after = Pt(0)

            if pdata["line_count"] > 1:
                avg_leading = pdata["line_leading_sum"] / (pdata["line_count"] - 1)
                pf.line_spacing = Pt(round(avg_leading * 2) / 2.0)
            else:
                pf.line_spacing = Pt(round(pdata["max_size"] * 1.12 * 2) / 2.0)

            if pdata["is_centered"]:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                pf.left_indent = Pt(0)
                pf.right_indent = Pt(0)
                pf.first_line_indent = Pt(0)
            elif pdata["is_bullet"]:
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                bullet_x = max(0.0, pdata["x0"] - left_m)
                text_x = max(bullet_x + 11.0, pdata["cont_x0"] - left_m)
                pf.left_indent = Pt(round(text_x * 2) / 2.0)
                pf.right_indent = Pt(0)
                pf.first_line_indent = Pt(-round((text_x - bullet_x) * 2) / 2.0)
                pf.tab_stops.add_tab_stop(
                    Pt(round(text_x * 2) / 2.0), WD_TAB_ALIGNMENT.LEFT
                )
            else:
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                indent_x = max(0.0, pdata["x0"] - left_m)
                pf.left_indent = (
                    Pt(round(indent_x * 2) / 2.0) if indent_x >= 3.5 else Pt(0)
                )
                pf.right_indent = Pt(0)
                pf.first_line_indent = Pt(0)

            for ts_pos, ts_align in pdata["tab_stops"]:
                align_enum = (
                    WD_TAB_ALIGNMENT.RIGHT
                    if ts_align == "RIGHT"
                    else WD_TAB_ALIGNMENT.LEFT
                )
                pf.tab_stops.add_tab_stop(Pt(round(ts_pos * 2) / 2.0), align_enum)

            if "bottom_border" in pdata:
                hr = pdata["bottom_border"]
                space_pt = max(1, min(6, int(round(hr["top"] - pdata["bottom"]))))
                _add_paragraph_bottom_border(
                    p, hr["hex"], hr["height"], space_pt=space_pt
                )
                prev_bottom = hr["bottom"]
            else:
                prev_bottom = pdata["bottom"]

            for si, sp in enumerate(pdata["spans"]):
                fam, sz, bold, italic, rgb, is_ul = sp["key"]
                txt = sp["text"]
                if pdata["is_bullet"] and si == 0 and txt.strip() in _BULLET_CHARS:
                    txt = txt.strip() + "\t"
                run = p.add_run(txt)
                run.font.name = fam
                run.font.size = Pt(sz)
                run.bold = bold
                run.italic = italic
                run.underline = is_ul
                run.font.color.rgb = RGBColor(rgb[0], rgb[1], rgb[2])

        # Append any embedded images on the page
        for img_item in pinfo.get("images", []):
            try:
                p_img = doc.add_paragraph()
                p_img.add_run().add_picture(
                    io.BytesIO(img_item["image"]),
                    width=Pt(min(body_width, img_item["width"])),
                )
            except Exception:  # noqa: BLE001
                pass

    doc.save(str(out_docx))


def _repair_pdf2docx_xml(docx_path: Path, pages_data: list[dict] | None = None) -> None:
    """
    Repair OpenXML defects in `pdf2docx` output (used when converting complex grid tables):
    1. Unwraps invalid `<w:r><w:hyperlink>...</w:hyperlink></w:r>` so links are visible.
    2. Strips artificial right indents (`w:right`) on paragraphs so short lines don't wrap.
    3. Zeroes `w:left`/`w:right` on centered paragraphs and fixes false-centered bullets.
    4. Strips 6-letter PDF subset font prefixes (`BCDEEE+Calibri` -> `Calibri`).
    """
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Pt

        doc = Document(str(docx_path))
        W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

        for p in doc.paragraphs:
            # 1. Unwrap nested <w:hyperlink> inside <w:r>
            for r_elem in list(p._p.findall(f"{W_NS}r")):
                hl_elem = r_elem.find(f"{W_NS}hyperlink")
                if hl_elem is not None:
                    outer_rPr = r_elem.find(f"{W_NS}rPr")
                    for inner_r in hl_elem.findall(f"{W_NS}r"):
                        if outer_rPr is not None:
                            inner_rPr = inner_r.find(f"{W_NS}rPr")
                            if inner_rPr is not None:
                                inner_r.remove(inner_rPr)
                            inner_r.insert(0, deepcopy(outer_rPr))
                    idx = list(p._p).index(r_elem)
                    p._p.insert(idx, hl_elem)
                    p._p.remove(r_elem)

            # 2. Fix indents and false centering
            pf = p.paragraph_format
            txt_stripped = p.text.strip()
            if txt_stripped and txt_stripped[0] in _BULLET_CHARS:
                if p.alignment == WD_ALIGN_PARAGRAPH.CENTER:
                    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            elif p.alignment == WD_ALIGN_PARAGRAPH.CENTER:
                pf.left_indent = Pt(0)
                pf.right_indent = Pt(0)
                pf.first_line_indent = Pt(0)

            if pf.right_indent is not None and pf.right_indent > Pt(12):
                pf.right_indent = Pt(0)

            for run in p.runs:
                if run.font and run.font.name and _SUBSET_FONT_RE.match(run.font.name):
                    run.font.name = _SUBSET_FONT_RE.sub("", run.font.name)

        doc.save(str(docx_path))
    except Exception:  # noqa: BLE001
        pass


class _Pdf2DocxProgressHandler(logging.Handler):
    """Intercepts `pdf2docx` log messages and translates them into `0% - 100%` callbacks."""

    def __init__(self, total_pages: int, progress_cb: Callable[[int], None] | None) -> None:
        super().__init__()
        self.total_pages = max(1, total_pages)
        self.progress_cb = progress_cb

    def emit(self, record: logging.LogRecord) -> None:
        if self.progress_cb is None:
            return
        try:
            msg = record.getMessage()
            match = _PDF2DOCX_STAGE_RE.search(msg)
            if match:
                stage = int(match.group(1))
                page_num = int(match.group(2))
                stage_weights = {1: 0.05, 2: 0.30, 3: 0.65, 4: 0.88}
                base = stage_weights.get(stage, 0.5)
                span = 0.22 / self.total_pages
                frac = base + min(self.total_pages, page_num) * span
                pct = max(8, min(95, int(round(frac * 100))))
                self.progress_cb(pct)
        except Exception:  # noqa: BLE001
            pass


def convert_pdf_to_word_docx(
    source_pdf: Path,
    replace_original: bool = False,
    progress_cb: Callable[[int], None] | None = None,
) -> Path:
    """
    Convert `source_pdf` (.pdf) into a 1:1 formatted, editable Word `.docx`:
    - Uses the ultra-fast Precision Layout Engine (`_extract_page_layout_fitz` /
      `_extract_page_layout_pdfplumber` + `_build_precision_docx_from_pages`) for
      text-based PDFs (resumes, letters, reports, documentation) to preserve exact
      fonts, colors, centered headers, hyperlinks, full-width horizontal divider
      lines, hanging-indent bullets, and single-page vertical spacing in ~0.2s.
    - Automatically routes pages with multi-cell grid tables through `pdf2docx` +
      OpenXML repair (`_repair_pdf2docx_xml`).
    """
    out_docx = _unique_output_path(source_pdf.parent, source_pdf.stem, ".docx")
    conversion_succeeded = False
    last_error = ""

    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()

    if progress_cb:
        progress_cb(8)

    # Extract page layout geometry (via PyMuPDF fitz or pdfplumber)
    pages_data: list[dict] = []
    try:
        pages_data = _extract_page_layout_fitz(source_pdf)
    except Exception:  # noqa: BLE001
        try:
            pages_data = _extract_page_layout_pdfplumber(source_pdf)
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)

    has_any_text = any(bool(p.get("visual_lines")) for p in pages_data)
    has_grid_table = any(bool(p.get("has_grid_table")) for p in pages_data)

    # Path A: Fast 1:1 Precision Reconstruction for Resumes & Text/Image PDFs
    if has_any_text and not has_grid_table:
        try:
            if progress_cb:
                progress_cb(25)
            _build_precision_docx_from_pages(
                pages_data=pages_data,
                out_docx=out_docx,
                progress_cb=progress_cb,
            )
            if out_docx.exists() and out_docx.stat().st_size > 0:
                conversion_succeeded = True
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)

    # Path B: Grid-Table PDFs or Fallback -> `pdf2docx` + OpenXML Repair
    if not conversion_succeeded:
        try:
            from pdf2docx import Converter

            total_pages = max(1, len(pages_data))
            handler = _Pdf2DocxProgressHandler(total_pages, progress_cb)
            root_logger = logging.getLogger()
            p2d_logger = logging.getLogger("pdf2docx")
            root_logger.addHandler(handler)
            p2d_logger.addHandler(handler)
            try:
                cv = Converter(str(source_pdf))
                try:
                    cv.convert(
                        str(out_docx),
                        start=0,
                        end=None,
                        multi_processing=False,
                        delete_end_line_hyphen=False,
                    )
                finally:
                    cv.close()
            finally:
                root_logger.removeHandler(handler)
                p2d_logger.removeHandler(handler)

            if out_docx.exists() and out_docx.stat().st_size > 0:
                if progress_cb:
                    progress_cb(94)
                _repair_pdf2docx_xml(out_docx, pages_data)
                conversion_succeeded = True
        except Exception as exc:  # noqa: BLE001
            last_error = last_error or str(exc)

    # Path C: Fallback to Precision Builder even if grid-table flag was set
    if not conversion_succeeded and has_any_text:
        try:
            _build_precision_docx_from_pages(
                pages_data=pages_data,
                out_docx=out_docx,
                progress_cb=progress_cb,
            )
            if out_docx.exists() and out_docx.stat().st_size > 0:
                conversion_succeeded = True
        except Exception as exc:  # noqa: BLE001
            last_error = last_error or str(exc)

    if not conversion_succeeded or not out_docx.exists():
        raise RuntimeError(
            last_error or "Install PyMuPDF & python-docx (`pip install PyMuPDF python-docx`)."
        )

    if progress_cb:
        progress_cb(100)

    if replace_original and source_pdf.exists() and source_pdf.resolve() != out_docx.resolve():
        try:
            source_pdf.unlink()
        except OSError:
            pass

    return out_docx


def convert_word_to_pdf_file(
    source_word: Path,
    replace_original: bool = False,
    progress_cb: Callable[[int], None] | None = None,
) -> Path:
    """
    Convert `source_word` (.docx / .doc) into a clean, print-ready `.pdf`
    using 100% background-thread-safe engines with live percentage progress:
    - Tier 1: Microsoft Word native PDF export (`ExportAsFixedFormat($dst, 17)` in `-STA`).
    - Tier 2: Pure-Python thread-safe `python-docx` + `PyMuPDF` (`fitz`) multi-page A4 renderer.
    """
    out_pdf = _unique_output_path(source_word.parent, source_word.stem, ".pdf")
    conversion_succeeded = False
    last_error = ""

    if progress_cb:
        progress_cb(15)

    if sys.platform == "win32":
        try:
            if progress_cb:
                progress_cb(35)
            src_escaped = str(source_word.resolve()).replace("'", "''")
            dst_escaped = str(out_pdf.resolve()).replace("'", "''")
            ps_script = (
                "$ErrorActionPreference = 'Stop'; "
                "$word = New-Object -ComObject Word.Application; "
                "$word.Visible = $false; "
                "$word.DisplayAlerts = 0; "
                "try { "
                f"  $doc = $word.Documents.Open('{src_escaped}', $false, $true); "
                f"  $doc.ExportAsFixedFormat('{dst_escaped}', 17); "
                "  $doc.Close($false); "
                "} finally { "
                "  $word.Quit(); "
                "}"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-STA", "-Command", ps_script],
                check=True,
                capture_output=True,
                text=True,
                timeout=90,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            )
            if out_pdf.exists() and out_pdf.stat().st_size > 0:
                conversion_succeeded = True
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)

    if not conversion_succeeded:
        try:
            import fitz
            from docx import Document

            if progress_cb:
                progress_cb(50)

            doc = Document(str(source_word))
            html_parts = [
                "<html><head><style>"
                "body { font-family: sans-serif; font-size: 11pt; color: #0F172A; line-height: 1.45; }"
                "h1 { font-size: 18pt; font-weight: bold; margin-top: 10pt; margin-bottom: 6pt; }"
                "h2 { font-size: 14pt; font-weight: bold; margin-top: 8pt; margin-bottom: 5pt; }"
                "h3 { font-size: 12pt; font-weight: bold; margin-top: 6pt; margin-bottom: 4pt; }"
                "p { margin-top: 0pt; margin-bottom: 6pt; }"
                "table { border-collapse: collapse; width: 100%; margin-top: 6pt; margin-bottom: 6pt; }"
                "td, th { border: 1px solid #64748B; padding: 4pt 6pt; font-size: 10pt; }"
                "</style></head><body>"
            ]

            for para in doc.paragraphs:
                style_name = (para.style.name if para.style else "").lower()
                tag = "p"
                if "heading 1" in style_name or style_name == "title":
                    tag = "h1"
                elif "heading 2" in style_name:
                    tag = "h2"
                elif "heading 3" in style_name:
                    tag = "h3"

                run_fragments: list[str] = []
                for run in para.runs:
                    txt = html.escape(run.text).replace("\n", "<br/>")
                    if not txt:
                        continue
                    if run.bold:
                        txt = f"<b>{txt}</b>"
                    if run.italic:
                        txt = f"<i>{txt}</i>"
                    if run.underline:
                        txt = f"<u>{txt}</u>"
                    run_fragments.append(txt)

                inner_html = "".join(run_fragments) if run_fragments else html.escape(para.text)
                if inner_html.strip():
                    html_parts.append(f"<{tag}>{inner_html}</{tag}>")

            for table in doc.tables:
                html_parts.append("<table>")
                for row in table.rows:
                    html_parts.append("<tr>")
                    for cell in row.cells:
                        cell_txt = "<br/>".join(
                            html.escape(p.text) for p in cell.paragraphs if p.text.strip()
                        )
                        html_parts.append(f"<td>{cell_txt}</td>")
                    html_parts.append("</tr>")
                html_parts.append("</table>")

            html_parts.append("</body></html>")
            full_html = "".join(html_parts)

            if progress_cb:
                progress_cb(80)

            a4_w, a4_h = 595.28, 841.89
            margin_pt = 42.52
            content_rect = fitz.Rect(margin_pt, margin_pt, a4_w - margin_pt, a4_h - margin_pt)

            if hasattr(fitz, "Story"):
                story = fitz.Story(html=full_html)
                writer = fitz.DocumentWriter(str(out_pdf))
                mediabox = fitz.Rect(0, 0, a4_w, a4_h)
                more = 1
                while more:
                    device = writer.begin_page(mediabox)
                    more, _ = story.place(content_rect)
                    story.draw(device)
                    writer.end_page()
                writer.close()
            else:
                pdf_out = fitz.open()
                page = pdf_out.new_page(width=a4_w, height=a4_h)
                page.insert_htmlbox(content_rect, full_html)
                pdf_out.save(str(out_pdf))
                pdf_out.close()

            if out_pdf.exists() and out_pdf.stat().st_size > 0:
                conversion_succeeded = True
        except Exception as exc:  # noqa: BLE001
            last_error = last_error or str(exc)

    if not conversion_succeeded or not out_pdf.exists():
        raise RuntimeError(last_error or "Could not convert Word document to PDF.")

    if progress_cb:
        progress_cb(100)

    if replace_original and source_word.exists() and source_word.resolve() != out_pdf.resolve():
        try:
            source_word.unlink()
        except OSError:
            pass

    return out_pdf


def convert_pdf_to_images(
    source_pdf: Path,
    target_ext: str,
    pil_format: str,
    quality: int = 85,
    scale_preset: str = "Original",
    replace_original: bool = False,
    progress_cb: Callable[[int], None] | None = None,
) -> list[Path]:
    """Render `.pdf` pages to image files (`.jpg`, `.png`, `.webp`, etc.) if dropped on an image tile."""
    import fitz

    dpi = int(get_a4_pdf_dpi(scale_preset))
    pdf_doc = fitz.open(str(source_pdf))
    outputs: list[Path] = []
    try:
        total_pages = max(1, len(pdf_doc))
        for idx in range(total_pages):
            if progress_cb:
                progress_cb(int(round(((idx + 0.5) / total_pages) * 95)))
            page = pdf_doc[idx]
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            stem = source_pdf.stem if total_pages == 1 else f"{source_pdf.stem}_page{idx + 1}"
            out_path = _unique_output_path(source_pdf.parent, stem, target_ext)
            convert_pil_image_to_path(
                img=img,
                output_path=out_path,
                pil_format=pil_format,
                quality=quality,
                scale_preset="Original",
            )
            outputs.append(out_path)
    finally:
        pdf_doc.close()

    if progress_cb:
        progress_cb(100)

    if replace_original and outputs and source_pdf.exists():
        try:
            source_pdf.unlink()
        except OSError:
            pass
    return outputs


def convert_image_to_word_docx(
    source_img: Path,
    scale_preset: str = "Original",
    replace_original: bool = False,
) -> Path:
    """Embed an image cleanly inside an editable A4 Word `.docx` if dropped onto `WORD`."""
    from docx import Document
    from docx.shared import Inches

    out_docx = _unique_output_path(source_img.parent, source_img.stem, ".docx")
    doc = Document()
    for section in doc.sections:
        section.top_margin = Inches(0.6)
        section.bottom_margin = Inches(0.6)
        section.left_margin = Inches(0.6)
        section.right_margin = Inches(0.6)

    with Image.open(source_img) as img:
        transposed = ImageOps.exif_transpose(img)
        scaled = apply_resolution_preset(transposed, scale_preset)
        rgb = flatten_to_rgb(scaled)
        buf = io.BytesIO()
        rgb.save(buf, format="PNG")
        buf.seek(0)
        doc.add_picture(buf, width=Inches(6.0))

    doc.save(str(out_docx))
    if replace_original and source_img.exists() and source_img.resolve() != out_docx.resolve():
        try:
            source_img.unlink()
        except OSError:
            pass
    return out_docx


# ----------------------------------------------------------------------
# Image Conversion Helpers
# ----------------------------------------------------------------------
def convert_pil_image_to_path(
    img: Image.Image,
    output_path: Path,
    pil_format: str,
    quality: int = 85,
    scale_preset: str = "Original",
) -> Path:
    """Save an in-memory PIL Image (including decoded .HEIC) to `output_path`."""
    if pil_format == "PDF":
        a4_page, dpi = compose_a4_pdf_page(img, scale_preset=scale_preset)
        a4_page.save(
            output_path,
            format="PDF",
            resolution=dpi,
            quality=max(5, min(100, quality)),
        )
        a4_page.close()
        return output_path

    img = ImageOps.exif_transpose(img)
    img = apply_resolution_preset(img, scale_preset)

    save_kwargs: dict = {}
    if pil_format in {"JPEG", "BMP"}:
        img = flatten_to_rgb(img)
    elif pil_format == "ICO":
        img = img.convert("RGBA")
        save_kwargs["sizes"] = [(min(img.width, 256), min(img.height, 256))]
    elif pil_format in {"PNG", "WEBP", "TIFF", "GIF"}:
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")

    if pil_format in {"JPEG", "WEBP"}:
        save_kwargs["quality"] = max(1, min(100, quality))
        if pil_format == "JPEG":
            save_kwargs["optimize"] = True
        elif pil_format == "WEBP":
            save_kwargs["method"] = 4
    elif pil_format == "PNG":
        save_kwargs["optimize"] = True

    img.save(output_path, format=pil_format, **save_kwargs)
    return output_path


def convert_single_image(
    source_path: Path,
    target_ext: str,
    pil_format: str,
    quality: int = 85,
    scale_preset: str = "Original",
    replace_original: bool = False,
) -> Path:
    """
    Convert `source_path` (including .HEIC) to `pil_format` in the exact same folder.
    Returns the output Path.
    """
    parent_dir = source_path.parent
    stem = source_path.stem
    candidate_out = parent_dir / f"{stem}{target_ext}"

    if candidate_out.resolve() == source_path.resolve():
        if replace_original:
            temp_out = parent_dir / f".{stem}_tmp_convert{target_ext}"
        else:
            candidate_out = _unique_output_path(parent_dir, f"{stem}_converted", target_ext)
            temp_out = None
    else:
        temp_out = None
        if not replace_original and candidate_out.exists():
            candidate_out = _unique_output_path(parent_dir, stem, target_ext)

    write_target = temp_out if temp_out is not None else candidate_out

    with Image.open(source_path) as img:
        convert_pil_image_to_path(
            img=img,
            output_path=write_target,
            pil_format=pil_format,
            quality=quality,
            scale_preset=scale_preset,
        )

    if temp_out is not None:
        temp_out.replace(candidate_out)
    elif replace_original and source_path.exists() and source_path.resolve() != candidate_out.resolve():
        try:
            source_path.unlink()
        except OSError:
            pass

    return candidate_out


def convert_images_to_merged_pdf(
    source_paths: list[Path],
    quality: int = 85,
    scale_preset: str = "Original",
    replace_original: bool = False,
    progress_cb: Callable[[int], None] | None = None,
) -> Path:
    """
    Combine 2 or more images (including .HEIC) into a single multi-page ISO A4 PDF.
    Each image is placed on its own A4 page (auto Portrait/Landscape) with uniform
    margins, centered alignment, and preserved aspect ratio.
    """
    first = source_paths[0]
    parent_dir = first.parent
    out_path = _unique_output_path(parent_dir, f"{first.stem}_merged", ".pdf")

    a4_pages: list[Image.Image] = []
    target_dpi = get_a4_pdf_dpi(scale_preset)
    total = max(1, len(source_paths))
    try:
        for idx, src in enumerate(source_paths):
            if progress_cb:
                progress_cb(int(round(((idx + 0.5) / total) * 85)))
            with Image.open(src) as img:
                page, dpi = compose_a4_pdf_page(img, scale_preset=scale_preset)
                target_dpi = dpi
                a4_pages.append(page)

        if progress_cb:
            progress_cb(94)
        a4_pages[0].save(
            out_path,
            format="PDF",
            save_all=True,
            append_images=a4_pages[1:],
            resolution=target_dpi,
            quality=max(5, min(100, quality)),
        )
        if progress_cb:
            progress_cb(100)
    finally:
        for page in a4_pages:
            page.close()

    if replace_original:
        for src in source_paths:
            if src.exists() and src.resolve() != out_path.resolve():
                try:
                    src.unlink()
                except OSError:
                    pass

    return out_path


# ----------------------------------------------------------------------
# Unified Background Worker Thread with Real-Time Percentage Progress
# ----------------------------------------------------------------------
class ConversionWorkerThread(QThread):
    """
    Executes image, PDF-to-Word, and Word-to-PDF conversions on a background
    thread while emitting real-time percentage progress (`0% – 100%`).
    """

    progress_updated = pyqtSignal(int)
    batch_finished = pyqtSignal(list, list, str, int, int)

    def __init__(
        self,
        files: list[Path],
        target_idx: int,
        quality: int,
        scale_preset: str,
        replace_original: bool,
        merge_pdf_enabled: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.files = files
        self.target_idx = target_idx
        self.quality = quality
        self.scale_preset = scale_preset
        self.replace_original = replace_original
        self.merge_pdf_enabled = merge_pdf_enabled

    def run(self) -> None:
        label, target_ext, pil_format, _ = RADIAL_FORMATS[self.target_idx]
        orig_bytes = sum(f.stat().st_size for f in self.files if f.exists())
        converted_paths: list[Path] = []
        errors: list[str] = []

        self.progress_updated.emit(5)

        image_files = [f for f in self.files if f.suffix.lower() in IMAGE_INPUT_EXTS]
        pdf_files = [f for f in self.files if f.suffix.lower() in PDF_INPUT_EXTS]
        word_files = [f for f in self.files if f.suffix.lower() in WORD_INPUT_EXTS]

        # Case 1: Multiple images dropped onto PDF -> Merged Multi-Page A4 PDF
        if (
            pil_format == "PDF"
            and len(image_files) >= 2
            and not pdf_files
            and not word_files
            and self.merge_pdf_enabled
        ):
            try:
                merged_out = convert_images_to_merged_pdf(
                    source_paths=image_files,
                    quality=self.quality,
                    scale_preset=self.scale_preset,
                    replace_original=self.replace_original,
                    progress_cb=self.progress_updated.emit,
                )
                converted_paths.append(merged_out)
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
            self.batch_finished.emit(
                converted_paths, errors, f"{len(image_files)} A4 PAGES", orig_bytes, self.target_idx
            )
            return

        # Case 2: Process each file with per-file and intra-file percentage reporting
        total_files = max(1, len(self.files))
        for file_idx, file_path in enumerate(self.files):
            ext = file_path.suffix.lower()

            def _scaled_progress(sub_pct: int, idx: int = file_idx) -> None:
                overall = int(round(((idx + (sub_pct / 100.0)) / total_files) * 100))
                self.progress_updated.emit(max(5, min(99, overall)))

            try:
                if ext in PDF_INPUT_EXTS:
                    if pil_format in {"DOCX", "PDF"}:
                        out_path = convert_pdf_to_word_docx(
                            source_pdf=file_path,
                            replace_original=self.replace_original,
                            progress_cb=_scaled_progress,
                        )
                        converted_paths.append(out_path)
                        label = "WORD"
                    else:
                        out_imgs = convert_pdf_to_images(
                            source_pdf=file_path,
                            target_ext=target_ext,
                            pil_format=pil_format,
                            quality=self.quality,
                            scale_preset=self.scale_preset,
                            replace_original=self.replace_original,
                            progress_cb=_scaled_progress,
                        )
                        converted_paths.extend(out_imgs)
                elif ext in WORD_INPUT_EXTS:
                    if pil_format in {"PDF", "DOCX"}:
                        out_path = convert_word_to_pdf_file(
                            source_word=file_path,
                            replace_original=self.replace_original,
                            progress_cb=_scaled_progress,
                        )
                        converted_paths.append(out_path)
                        label = "PDF"
                    else:
                        errors.append("Drop Word files on PDF")
                elif ext in IMAGE_INPUT_EXTS:
                    _scaled_progress(35)
                    if pil_format == "DOCX":
                        out_path = convert_image_to_word_docx(
                            source_img=file_path,
                            scale_preset=self.scale_preset,
                            replace_original=self.replace_original,
                        )
                        converted_paths.append(out_path)
                    else:
                        out_path = convert_single_image(
                            source_path=file_path,
                            target_ext=target_ext,
                            pil_format=pil_format,
                            quality=self.quality,
                            scale_preset=self.scale_preset,
                            replace_original=self.replace_original,
                        )
                        converted_paths.append(out_path)
                    _scaled_progress(100)
                else:
                    errors.append(f"Unsupported: {file_path.name}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{file_path.name}: {exc}")

        self.progress_updated.emit(100)
        self.batch_finished.emit(converted_paths, errors, label, orig_bytes, self.target_idx)


# ----------------------------------------------------------------------
# Main Circular Neon Radial UI (Images + PDF ⇄ Word All-in-One)
# ----------------------------------------------------------------------
class RadialImageConverter(QWidget):
    """
    Circular frameless floating desktop UI that:
    1. Starts INACTIVE by default when you open your laptop—never triggers until
       you manually enable it (Ctrl + Alt + C) and automatically deactivates
       after 5 minutes of inactivity.
    2. Uses an imperceptible (alpha=2/255) OLE drop-target surface under the cursor
       when Armed so the UI ONLY appears when you drag a supported image, PDF, or
       Word file (staying completely hidden for unsupported files or selection boxes).
    3. Integrates `WORD` and `PDF` right alongside `ICO`, `GIF`, `WEBP`, `JPG`, `PNG`
       and displays a rotating circular neon loading indicator with a live
       numbered percentage (`0% – 100%`) during conversion.
    """

    WINDOW_SIZE = 460
    CENTER = WINDOW_SIZE / 2.0
    OUTER_RADIUS = 204.0
    RING_RADIUS = 152.0
    INNER_BEZEL_OUTER = 102.0
    INNER_WELL_RADIUS = 82.0
    TILE_SIZE = 60.0

    # Bottom quality arc angles (screen degrees: 0=Right, 90=Bottom, 180=Left)
    ARC_START_DEG = 114.0  # 0% / min end (bottom-left)
    ARC_END_DEG = 18.0     # 100% / max end (bottom-right)

    # Drag threshold so normal single-clicks / selecting a file never triggers the UI
    DRAG_MIN_DISTANCE_PX = 45.0
    DRAG_MIN_HOLD_SECONDS = 0.18
    PROBE_MAX_MOVE_TICKS = 10

    def __init__(self) -> None:
        super().__init__()
        self.is_pro: bool = load_saved_license()
        self.quality: int = 85
        self.scale_idx: int = 0  # 0="Original", 1="1080p", 2="50%"
        self.replace_original: bool = False
        self.auto_copy_clipboard: bool = True
        self.merge_pdf_enabled: bool = True
        self.is_pinned: bool = True

        # 1. Inactive by default on laptop startup! Only activates on manual enable (Ctrl+Alt+C)
        self.is_armed: bool = False
        self._wheel_shown: bool = False
        self._manual_pin_visible: bool = False
        self._staged_files: list[Path] = []
        self._is_dragging_over_center: bool = False
        self._conversion_just_finished: bool = False

        # Background conversion & numbered percentage circular loading spinner state
        self.is_converting: bool = False
        self._spinner_angle: int = 0
        self._conversion_progress_pct: int = 0
        self._target_progress_pct: int = 0
        self._loading_title: str = ""
        self._loading_subtitle: str = ""
        self._worker: ConversionWorkerThread | None = None

        # Mouse drag & imperceptible OLE format probe state
        self._mouse_was_down: bool = False
        self._mouse_down_pos: QPoint = QPoint(0, 0)
        self._mouse_down_time: float = 0.0
        self._drag_origin_is_explorer: bool = False
        self._is_probing_drag: bool = False
        self._probe_move_ticks: int = 0
        self._last_probe_pos: QPoint = QPoint(0, 0)
        self._drag_rejected_unsupported: bool = False

        # Edge-triggered key state tracking for Option 3 mid-drag shortcuts
        self._key_was_down: dict[int, bool] = {}

        self.hovered_tile_idx: int | None = None
        self.drag_target_idx: int | None = None
        self.active_flash_idx: int | None = None
        self.is_dragging_files: bool = False
        self.is_adjusting_quality: bool = False
        self.hovered_close: bool = False
        self.hovered_scale_badge: bool = False

        self._window_drag_offset: QPoint | None = None
        self._status_text: str = ""
        self._status_subtext: str = ""

        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._on_status_timeout)

        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._clear_flash)

        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self._auto_hide_after_drag)

        # Smooth 30ms circular loading spinner + percentage counter timer
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(30)
        self._spinner_timer.timeout.connect(self._tick_loading_spinner)
        self._spinner_tick_count: int = 0

        # 5-minute auto-deactivation timer when Armed
        self._inactivity_timer = QTimer(self)
        self._inactivity_timer.setSingleShot(True)
        self._inactivity_timer.timeout.connect(self._on_inactivity_timeout)

        # 30ms lightweight poller (runs ONLY when manually Armed)
        self._drag_watch_timer = QTimer(self)
        self._drag_watch_timer.setInterval(30)
        self._drag_watch_timer.timeout.connect(self._poll_mouse_drag_state)

        self._configure_window()
        self._position_center()
        self._setup_tray_and_hotkey()

    @property
    def current_scale_preset(self) -> str:
        return SCALE_PRESETS[self.scale_idx]

    @property
    def has_staged_files(self) -> bool:
        return len(self._staged_files) > 0

    def _on_worker_progress(self, pct: int) -> None:
        self._target_progress_pct = max(self._target_progress_pct, min(100, pct))
        if self._conversion_progress_pct < self._target_progress_pct:
            self._conversion_progress_pct = self._target_progress_pct
        self.update()

    def _tick_loading_spinner(self) -> None:
        self._spinner_angle = (self._spinner_angle - 12) % 360
        self._spinner_tick_count += 1
        if self._conversion_progress_pct < self._target_progress_pct:
            self._conversion_progress_pct = min(
                self._target_progress_pct, self._conversion_progress_pct + 2
            )
        elif self._spinner_tick_count % 3 == 0 and self._conversion_progress_pct < 94:
            self._conversion_progress_pct += 1
        self.update()

    def _configure_window(self) -> None:
        self.setWindowTitle("FloatConvert")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFixedSize(self.WINDOW_SIZE, self.WINDOW_SIZE)
        self.setWindowOpacity(0.0)

    def _position_center(self) -> None:
        """Center the circular UI on the primary screen."""
        screen = QGuiApplication.primaryScreen()
        if screen:
            geom = screen.availableGeometry()
            x = geom.left() + (geom.width() - self.width()) // 2
            y = geom.top() + (geom.height() - self.height()) // 2
            self.move(x, y)

    def start_in_stealth_armed_mode(self) -> None:
        """
        Initialize the window surface in GPU memory at 0.0 opacity with Win32
        click-through enabled, keeping Smart Drag Mode INACTIVE by default on startup
        until the user manually presses Ctrl + Alt + C (or enables from Tray).
        """
        self.is_armed = False
        self.setWindowOpacity(0.0)
        self.show()
        self._set_wheel_visible(False, force=True)
        QTimer.singleShot(60, lambda: self._set_wheel_visible(False, force=True))
        self._update_tray_status()

    def _reset_inactivity_timer(self) -> None:
        """Restart the 5-minute auto-deactivation countdown whenever Armed."""
        if self.is_armed:
            self._inactivity_timer.start(INACTIVITY_TIMEOUT_MS)
        else:
            self._inactivity_timer.stop()

    def _on_inactivity_timeout(self) -> None:
        """Automatically deactivate Smart Drag Mode after 5 minutes of inactivity."""
        if self.is_armed and not self.is_converting:
            self.disable_armed_mode()

    def _set_win32_click_through(self, click_through: bool) -> None:
        """Toggle Win32 WS_EX_TRANSPARENT so an invisible 0-opacity window never blocks clicks."""
        if sys.platform != "win32":
            return
        try:
            import ctypes

            user32 = ctypes.windll.user32
            hwnd = int(self.winId())
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if click_through:
                new_style = style | WS_EX_LAYERED | WS_EX_TRANSPARENT
            else:
                new_style = (style | WS_EX_LAYERED) & ~WS_EX_TRANSPARENT
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_style)
        except Exception:  # noqa: BLE001
            pass

    def _start_invisible_drag_probe(self, cur_pos: QPoint) -> None:
        """
        Position the widget under the cursor with an imperceptible alpha=2/255 surface
        (while SourceConstantAlpha=1.0 so Windows `WindowFromPoint` and `DoDragDrop`
        hit-test it immediately) to let `dragEnterEvent` verify the file format
        before ever displaying the wheel.
        """
        self._is_probing_drag = True
        self._probe_move_ticks = 0
        self._last_probe_pos = cur_pos
        self.move(cur_pos.x() - self.width() // 2, cur_pos.y() - self.height() // 2)
        self._set_win32_click_through(False)
        self.setWindowOpacity(1.0)
        self.raise_()
        self.repaint()

    def _abort_invisible_drag_probe(self) -> None:
        """Restore click-through at 0.0 opacity when a drag is unsupported or non-file."""
        self._is_probing_drag = False
        self._probe_move_ticks = 0
        if not self._wheel_shown:
            self.setWindowOpacity(0.0)
            self._set_win32_click_through(True)
            self._position_center()
            self.repaint()

    def _set_wheel_visible(self, visible: bool, force: bool = False) -> None:
        """Switch between 0ms invisible click-through stealth state and centered visible state."""
        self._is_probing_drag = False
        self._probe_move_ticks = 0
        if not force and visible == self._wheel_shown:
            if not visible:
                self.setWindowOpacity(0.0)
                self._set_win32_click_through(True)
            return

        self._wheel_shown = visible
        if visible:
            self._reset_inactivity_timer()
            self._position_center()
            self._set_win32_click_through(False)
            self.setWindowOpacity(1.0)
            self.raise_()
            self.repaint()
        else:
            self.is_dragging_files = False
            self._is_dragging_over_center = False
            self.drag_target_idx = None
            self.hovered_tile_idx = None
            self._staged_files.clear()
            self.setWindowOpacity(0.0)
            self._set_win32_click_through(True)
            self._position_center()
            self.repaint()

    # ------------------------------------------------------------------
    # Smart Drag-Sense Detection & Option 3 Mid-Drag Keyboard Shortcuts
    # ------------------------------------------------------------------
    def _is_explorer_or_desktop_under_cursor(self, pt: QPoint) -> bool:
        if sys.platform != "win32":
            return True
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            GA_ROOT = 2

            wpt = wintypes.POINT(pt.x(), pt.y())
            hwnd = user32.WindowFromPoint(wpt)
            if not hwnd:
                return False
            root_hwnd = user32.GetAncestor(hwnd, GA_ROOT) or hwnd

            buf = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(root_hwnd, buf, 64)
            if buf.value in EXPLORER_WINDOW_CLASSES:
                return True

            fg_hwnd = user32.GetForegroundWindow()
            if fg_hwnd:
                user32.GetClassNameW(fg_hwnd, buf, 64)
                if buf.value in EXPLORER_WINDOW_CLASSES:
                    return True
            return False
        except Exception:  # noqa: BLE001
            return False

    def _check_edge_key_press(self, user32, vk_code: int) -> bool:
        """Return True once per key-down press using Win32 GetAsyncKeyState."""
        is_down = (user32.GetAsyncKeyState(vk_code) & 0x8000) != 0
        was_down = self._key_was_down.get(vk_code, False)
        self._key_was_down[vk_code] = is_down
        return is_down and not was_down

    def _poll_mid_drag_shortcuts(self, user32) -> None:
        if self.is_converting:
            return
        VK_SPACE = 0x20
        VK_UP = 0x26
        VK_DOWN = 0x28

        if self._check_edge_key_press(user32, VK_SPACE):
            self._reset_inactivity_timer()
            self._cycle_scale_preset()

        if self._check_edge_key_press(user32, VK_UP):
            self._reset_inactivity_timer()
            self.quality = min(100, self.quality + 5)
            self.update()

        if self._check_edge_key_press(user32, VK_DOWN):
            self._reset_inactivity_timer()
            self.quality = max(5, self.quality - 5)
            self.update()

    def _poll_mouse_drag_state(self) -> None:
        if sys.platform != "win32" or not self.is_armed or self.is_converting:
            return
        try:
            import ctypes

            user32 = ctypes.windll.user32
            lbutton_down = (user32.GetAsyncKeyState(0x01) & 0x8000) != 0
            cur_pos = QCursor.pos()

            if self._wheel_shown:
                self._poll_mid_drag_shortcuts(user32)

            if lbutton_down and not self._mouse_was_down:
                self._mouse_was_down = True
                self._mouse_down_pos = cur_pos
                self._mouse_down_time = time.monotonic()
                self._drag_origin_is_explorer = self._is_explorer_or_desktop_under_cursor(cur_pos)
                self._drag_rejected_unsupported = False
                self._is_probing_drag = False
                self._probe_move_ticks = 0
            elif lbutton_down and self._mouse_was_down:
                if (
                    self._drag_origin_is_explorer
                    and not self._wheel_shown
                    and not self._conversion_just_finished
                    and not self._drag_rejected_unsupported
                ):
                    held_sec = time.monotonic() - self._mouse_down_time
                    dx = cur_pos.x() - self._mouse_down_pos.x()
                    dy = cur_pos.y() - self._mouse_down_pos.y()
                    if (
                        held_sec >= self.DRAG_MIN_HOLD_SECONDS
                        and math.hypot(dx, dy) >= self.DRAG_MIN_DISTANCE_PX
                    ):
                        if not self._is_probing_drag:
                            self._auto_hide_timer.stop()
                            self._start_invisible_drag_probe(cur_pos)
                        else:
                            if cur_pos != self._last_probe_pos:
                                self._last_probe_pos = cur_pos
                                self._probe_move_ticks += 1
                                self.move(
                                    cur_pos.x() - self.width() // 2,
                                    cur_pos.y() - self.height() // 2,
                                )
                            if self._probe_move_ticks > self.PROBE_MAX_MOVE_TICKS:
                                self._drag_rejected_unsupported = True
                                self._abort_invisible_drag_probe()
            elif not lbutton_down and self._mouse_was_down:
                self._mouse_was_down = False
                self._drag_origin_is_explorer = False
                self._drag_rejected_unsupported = False
                if self._is_probing_drag:
                    self._abort_invisible_drag_probe()
                if (
                    self._wheel_shown
                    and not self._manual_pin_visible
                    and not self.has_staged_files
                    and not self._conversion_just_finished
                    and not self.is_converting
                ):
                    self._auto_hide_timer.start(350)
        except Exception:  # noqa: BLE001
            pass

    def _auto_hide_after_drag(self) -> None:
        if (
            not self._manual_pin_visible
            and not self.has_staged_files
            and not self._conversion_just_finished
            and not self._mouse_was_down
            and not self.is_converting
        ):
            self._set_wheel_visible(False)

    # ------------------------------------------------------------------
    # Hotkeys (Ctrl+Alt+C to Activate, Ctrl+Alt+D to Disable) & System Tray
    # ------------------------------------------------------------------
    def _setup_tray_and_hotkey(self) -> None:
        self.tray_icon = QSystemTrayIcon(create_neon_tray_icon(armed=False), self)
        self.tray_icon.setToolTip(
            "FloatConvert: INACTIVE (Press Ctrl+Alt+C to Activate)"
        )

        self.tray_menu = QMenu()
        self.arm_tray_action = self.tray_menu.addAction("Activate Smart Drag Mode (Ctrl+Alt+C)")
        self.arm_tray_action.triggered.connect(self.activate_armed_mode_silently)

        self.disable_tray_action = self.tray_menu.addAction("Disable Smart Drag Mode (Ctrl+Alt+D)")
        self.disable_tray_action.triggered.connect(self.disable_armed_mode)

        self.tray_menu.addSeparator()
        self.license_tray_action = self.tray_menu.addAction(
            "✓ FloatConvert Pro Activated" if self.is_pro else "🔑 Activate FloatConvert Pro..."
        )
        self.license_tray_action.triggered.connect(self.open_license_dialog)

        self.tray_menu.addSeparator()
        quit_action = self.tray_menu.addAction("Quit Completely")
        quit_action.triggered.connect(QApplication.instance().quit)

        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

        self.hotkey_thread = GlobalHotkeyThread(self)
        self.hotkey_thread.activate_pressed.connect(self.activate_armed_mode_silently)
        self.hotkey_thread.disable_pressed.connect(self.disable_armed_mode)
        self.hotkey_thread.start()

    def open_license_dialog(self) -> None:
        dlg = LicenseActivationDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.is_pro = True
            self.license_tray_action.setText("✓ FloatConvert Pro Activated")
            if self._wheel_shown:
                self._show_temporary_status("⚡ PRO UNLOCKED", "All features active!", 2200)

    def _update_tray_status(self) -> None:
        self.tray_icon.setIcon(create_neon_tray_icon(armed=self.is_armed))
        if self.is_armed:
            self.arm_tray_action.setText("✓ Active — Auto-Off in 5m (Ctrl+Alt+C)")
            self.tray_icon.setToolTip(
                "FloatConvert: ACTIVE (Auto-deactivates after 5m idle • Ctrl+Alt+D Disable)"
            )
        else:
            self.arm_tray_action.setText("Activate Smart Drag Mode (Ctrl+Alt+C)")
            self.tray_icon.setToolTip("FloatConvert: INACTIVE (Press Ctrl+Alt+C to Activate)")

    def activate_armed_mode_silently(self) -> None:
        """Manually enable Smart Drag Mode and start the 5-minute inactivity timer."""
        self.is_armed = True
        self._manual_pin_visible = False
        self._drag_rejected_unsupported = False
        self._is_probing_drag = False
        if not self.is_converting:
            self._set_wheel_visible(False, force=True)
        if not self._drag_watch_timer.isActive():
            self._drag_watch_timer.start()
        self._reset_inactivity_timer()
        self._update_tray_status()

    def disable_armed_mode(self) -> None:
        """Deactivate Smart Drag Mode (manually or after 5 minutes of inactivity)."""
        self.is_armed = False
        self._manual_pin_visible = False
        self._is_probing_drag = False
        self._drag_rejected_unsupported = False
        self._inactivity_timer.stop()
        self._drag_watch_timer.stop()
        if not self.is_converting:
            self._set_wheel_visible(False, force=True)
        self._update_tray_status()

    def toggle_manual_pin_wheel(self) -> None:
        if self._wheel_shown and self._manual_pin_visible and not self.is_converting:
            self._manual_pin_visible = False
            self._set_wheel_visible(False, force=True)
        else:
            self.is_armed = True
            if not self._drag_watch_timer.isActive():
                self._drag_watch_timer.start()
            self._reset_inactivity_timer()
            self._update_tray_status()
            self._manual_pin_visible = True
            self._set_wheel_visible(True, force=True)
            self.activateWindow()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.toggle_manual_pin_wheel()

    def _show_temporary_status(
        self,
        title: str,
        subtitle: str = "",
        duration_ms: int = 1100,
        hide_wheel_on_finish: bool = False,
    ) -> None:
        self._status_text = title
        self._status_subtext = subtitle
        self._conversion_just_finished = hide_wheel_on_finish
        self._status_timer.start(duration_ms)
        self.update()

    def _on_status_timeout(self) -> None:
        self._status_text = ""
        self._status_subtext = ""
        if self._conversion_just_finished:
            self._conversion_just_finished = False
            if not self._manual_pin_visible and not self.has_staged_files and not self.is_converting:
                self._set_wheel_visible(False, force=True)
                return
        self.update()

    def _clear_flash(self) -> None:
        self.active_flash_idx = None
        self.update()

    def _cycle_scale_preset(self) -> None:
        if not self.is_pro:
            self._show_temporary_status("🔒 PRO FEATURE", "Right-click to unlock Scale", 1800)
            return
        self.scale_idx = (self.scale_idx + 1) % len(SCALE_PRESETS)
        descriptions = {
            "Original": "100% Native / 300 DPI A4",
            "1080p": "Max 1920px / 200 DPI A4",
            "50%": "Half Size / 150 DPI A4",
        }
        preset = self.current_scale_preset
        if not self.has_staged_files:
            self._show_temporary_status(f"📐 SCALE: {preset.upper()}", descriptions[preset], 1400)
        else:
            self.update()

    def _copy_files_to_clipboard(self, paths: list[Path]) -> None:
        if not self.auto_copy_clipboard or not paths:
            return
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(p.resolve())) for p in paths])
        QApplication.clipboard().setMimeData(mime)

    # ------------------------------------------------------------------
    # Geometry & Hit-Testing Helpers
    # ------------------------------------------------------------------
    def _tile_center(self, angle_deg: float) -> QPointF:
        rad = math.radians(angle_deg)
        x = self.CENTER + self.RING_RADIUS * math.cos(rad)
        y = self.CENTER + self.RING_RADIUS * math.sin(rad)
        return QPointF(x, y)

    def _tile_rect(self, idx: int) -> QRectF:
        _, _, _, angle_deg = RADIAL_FORMATS[idx]
        c = self._tile_center(angle_deg)
        half = self.TILE_SIZE / 2.0
        return QRectF(c.x() - half, c.y() - half, self.TILE_SIZE, self.TILE_SIZE)

    def _close_button_rect(self) -> QRectF:
        return QRectF(self.CENTER - 12, self.CENTER - self.INNER_WELL_RADIUS + 8, 24, 24)

    def _scale_badge_rect(self) -> QRectF:
        return QRectF(self.CENTER - 38, self.CENTER + self.INNER_WELL_RADIUS - 28, 76, 20)

    def _is_inside_center_well(self, pos: QPointF) -> bool:
        """Return True if `pos` is inside the central well (Option 1 Hold & Tweak zone)."""
        return math.hypot(pos.x() - self.CENTER, pos.y() - self.CENTER) <= (
            self.INNER_BEZEL_OUTER - 4.0
        )

    def _quality_angle_deg(self) -> float:
        t = max(0.0, min(1.0, self.quality / 100.0))
        return self.ARC_START_DEG - t * (self.ARC_START_DEG - self.ARC_END_DEG)

    def _quality_knob_center(self) -> QPointF:
        rad = math.radians(self._quality_angle_deg())
        return QPointF(
            self.CENTER + self.RING_RADIUS * math.cos(rad),
            self.CENTER + self.RING_RADIUS * math.sin(rad),
        )

    def _hit_test_tile(self, pos: QPointF, snap_nearest: bool = False) -> int | None:
        for idx in range(len(RADIAL_FORMATS)):
            rect = self._tile_rect(idx).adjusted(-6, -6, 6, 6)
            if rect.contains(pos):
                return idx

        if snap_nearest:
            dx = pos.x() - self.CENTER
            dy = pos.y() - self.CENTER
            dist = math.hypot(dx, dy)
            if (self.INNER_BEZEL_OUTER - 4.0) < dist <= self.OUTER_RADIUS + 18.0:
                best_idx = None
                best_dist = 88.0
                for idx, (_, _, _, angle_deg) in enumerate(RADIAL_FORMATS):
                    tc = self._tile_center(angle_deg)
                    d = math.hypot(pos.x() - tc.x(), pos.y() - tc.y())
                    if d < best_dist:
                        best_dist = d
                        best_idx = idx
                return best_idx
        return None

    def _hit_test_quality_arc(self, pos: QPointF) -> bool:
        knob = self._quality_knob_center()
        if math.hypot(pos.x() - knob.x(), pos.y() - knob.y()) <= 30.0:
            return True

        dx = pos.x() - self.CENTER
        dy = pos.y() - self.CENTER
        dist = math.hypot(dx, dy)
        if not (self.RING_RADIUS - 26.0 <= dist <= self.RING_RADIUS + 26.0):
            return False

        angle = math.degrees(math.atan2(dy, dx))
        if angle < 0:
            angle += 360.0
        return (self.ARC_END_DEG - 8.0) <= angle <= (self.ARC_START_DEG + 8.0)

    def _update_quality_from_pos(self, pos: QPointF) -> None:
        dx = pos.x() - self.CENTER
        dy = pos.y() - self.CENTER
        angle = math.degrees(math.atan2(dy, dx))
        if angle < 0:
            angle += 360.0

        if angle > 220.0:
            angle = self.ARC_END_DEG
        clamped = max(self.ARC_END_DEG, min(self.ARC_START_DEG, angle))
        t = (self.ARC_START_DEG - clamped) / (self.ARC_START_DEG - self.ARC_END_DEG)
        new_q = int(round(t * 100))
        self.quality = max(5, min(100, new_q))
        self.update()

    # ------------------------------------------------------------------
    # Custom Neon Radial Painting + Numbered Percentage Loading Ring
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:
        painter = QPainter(self)

        # During the <15ms OLE format probe, paint a uniform alpha=2/255 surface:
        # 100% imperceptible to the human eye, yet solid to Windows `WindowFromPoint` / `DoDragDrop`!
        if self._is_probing_drag and not self._wheel_shown:
            painter.fillRect(self.rect(), QColor(0, 0, 0, 2))
            painter.end()
            return

        if not self._wheel_shown:
            painter.end()
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        center_pt = QPointF(self.CENTER, self.CENTER)

        # 1. Soft Outer Ambient Shadow / Glow around entire circular disc
        ambient = QRadialGradient(center_pt, self.OUTER_RADIUS + 22)
        ambient.setColorAt(0.0, QColor(15, 23, 42, 0))
        ambient.setColorAt(0.78, QColor(15, 23, 42, 160))
        ambient.setColorAt(0.90, QColor(88, 28, 135, 95))
        ambient.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ambient)
        painter.drawEllipse(center_pt, self.OUTER_RADIUS + 22, self.OUTER_RADIUS + 22)

        # 2. Main Dark Glass Circular Disc
        disc_grad = QLinearGradient(
            self.CENTER - self.OUTER_RADIUS,
            self.CENTER - self.OUTER_RADIUS,
            self.CENTER + self.OUTER_RADIUS,
            self.CENTER + self.OUTER_RADIUS,
        )
        disc_grad.setColorAt(0.0, QColor(28, 35, 52, 240))
        disc_grad.setColorAt(0.5, QColor(17, 22, 35, 245))
        disc_grad.setColorAt(1.0, QColor(10, 14, 24, 248))

        painter.setBrush(disc_grad)
        painter.setPen(QPen(QColor(148, 163, 184, 75), 1.6))
        painter.drawEllipse(center_pt, self.OUTER_RADIUS, self.OUTER_RADIUS)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(56, 189, 248, 45), 1.0))
        painter.drawEllipse(center_pt, self.OUTER_RADIUS - 2.5, self.OUTER_RADIUS - 2.5)

        # 3. Recessed Central Torus Bezel & Clean Dark Center Well
        center_active = self._is_dragging_over_center or self.has_staged_files or self.is_converting
        bezel_glow = QRadialGradient(center_pt, self.INNER_BEZEL_OUTER + 12)
        bezel_glow.setColorAt(0.60, QColor(0, 0, 0, 0))
        bezel_glow.setColorAt(
            0.86,
            QColor(56, 189, 248, 175) if center_active else QColor(139, 92, 246, 85),
        )
        bezel_glow.setColorAt(1.0, QColor(56, 189, 248, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bezel_glow)
        painter.drawEllipse(center_pt, self.INNER_BEZEL_OUTER + 12, self.INNER_BEZEL_OUTER + 12)

        bezel_grad = QLinearGradient(
            self.CENTER,
            self.CENTER - self.INNER_BEZEL_OUTER,
            self.CENTER,
            self.CENTER + self.INNER_BEZEL_OUTER,
        )
        bezel_grad.setColorAt(0.0, QColor(51, 65, 85, 245))
        bezel_grad.setColorAt(0.5, QColor(22, 28, 42, 250))
        bezel_grad.setColorAt(1.0, QColor(15, 20, 32, 252))
        painter.setBrush(bezel_grad)
        painter.setPen(
            QPen(
                QColor(56, 189, 248, 220) if center_active else QColor(168, 85, 247, 110),
                1.8 if center_active else 1.5,
            )
        )
        painter.drawEllipse(center_pt, self.INNER_BEZEL_OUTER, self.INNER_BEZEL_OUTER)

        well_grad = QRadialGradient(
            QPointF(self.CENTER - 18, self.CENTER - 18), self.INNER_WELL_RADIUS * 1.25
        )
        well_grad.setColorAt(
            0.0, QColor(26, 38, 58, 252) if center_active else QColor(20, 25, 37, 252)
        )
        well_grad.setColorAt(0.7, QColor(11, 15, 24, 254))
        well_grad.setColorAt(1.0, QColor(6, 9, 15, 255))
        painter.setBrush(well_grad)
        painter.setPen(
            QPen(
                QColor(56, 189, 248, 190) if center_active else QColor(99, 102, 241, 90),
                1.5 if center_active else 1.2,
            )
        )
        painter.drawEllipse(center_pt, self.INNER_WELL_RADIUS, self.INNER_WELL_RADIUS)

        # 4. Draw Curved Quality Dial & Arc Track at Bottom
        self._draw_quality_arc_and_dial(painter, center_pt)

        # 5. Draw Each Radial Format Button (ICO, GIF, WEBP, JPG, PNG, PDF, WORD)
        for idx in range(len(RADIAL_FORMATS)):
            self._draw_format_tile(painter, idx)

        # 6. Draw Close Button, Quick Scale Preset Pill, Numbered % Loading Spinner & Status Readout
        self._draw_center_overlay(painter, center_pt)

    def _draw_format_tile(self, painter: QPainter, idx: int) -> None:
        label, _, _, _ = RADIAL_FORMATS[idx]
        rect = self._tile_rect(idx)
        center = rect.center()

        is_drag_target = self.drag_target_idx == idx
        is_hovered = self.hovered_tile_idx == idx
        is_flashed = self.active_flash_idx == idx
        is_highlighted = is_drag_target or is_hovered or is_flashed

        painter.save()

        # A. Neon Underglow / Halo
        glow_radius = self.TILE_SIZE * (0.98 if is_highlighted else 0.76)
        glow_center = QPointF(center.x(), center.y() + 4.0)
        halo = QRadialGradient(glow_center, glow_radius)
        if is_highlighted:
            halo.setColorAt(0.0, QColor(192, 132, 252, 235))
            halo.setColorAt(0.45, QColor(147, 51, 234, 165))
            halo.setColorAt(0.78, QColor(99, 102, 241, 65))
            halo.setColorAt(1.0, QColor(99, 102, 241, 0))
        else:
            halo.setColorAt(0.0, QColor(56, 189, 248, 165))
            halo.setColorAt(0.50, QColor(37, 99, 235, 90))
            halo.setColorAt(1.0, QColor(37, 99, 235, 0))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(glow_center, glow_radius, glow_radius)

        # B. 3D Lower Pedestal / Neon Rim Base
        base_rect = rect.adjusted(-2.0, 3.5, 2.0, 5.5)
        base_grad = QLinearGradient(base_rect.topLeft(), base_rect.bottomLeft())
        if is_highlighted:
            base_grad.setColorAt(0.0, QColor(168, 85, 247, 220))
            base_grad.setColorAt(1.0, QColor(232, 121, 249, 255))
            rim_pen = QPen(QColor(240, 171, 252, 255), 2.0)
        else:
            base_grad.setColorAt(0.0, QColor(30, 58, 95, 210))
            base_grad.setColorAt(1.0, QColor(125, 211, 252, 235))
            rim_pen = QPen(QColor(125, 211, 252, 210), 1.5)

        painter.setBrush(base_grad)
        painter.setPen(rim_pen)
        painter.drawRoundedRect(base_rect, 15.0, 15.0)

        # C. Main 3D Glass Tile Body
        y_shift = -2.0 if is_highlighted else 0.0
        body_rect = rect.adjusted(0.0, y_shift, 0.0, y_shift)
        body_grad = QLinearGradient(body_rect.topLeft(), body_rect.bottomRight())
        if is_highlighted:
            body_grad.setColorAt(0.0, QColor(126, 34, 206, 248))
            body_grad.setColorAt(0.55, QColor(88, 28, 135, 248))
            body_grad.setColorAt(1.0, QColor(59, 7, 100, 252))
            body_border = QPen(QColor(216, 180, 254, 245), 1.8)
        else:
            body_grad.setColorAt(0.0, QColor(51, 65, 90, 242))
            body_grad.setColorAt(0.55, QColor(30, 41, 62, 245))
            body_grad.setColorAt(1.0, QColor(19, 27, 44, 250))
            body_border = QPen(QColor(148, 163, 184, 135), 1.3)

        painter.setBrush(body_grad)
        painter.setPen(body_border)
        painter.drawRoundedRect(body_rect, 13.0, 13.0)

        # D. Inner Beveled Cap
        inner_rect = body_rect.adjusted(5.0, 5.0, -5.0, -5.0)
        inner_grad = QLinearGradient(inner_rect.topLeft(), inner_rect.bottomRight())
        if is_highlighted:
            inner_grad.setColorAt(0.0, QColor(147, 51, 234, 220))
            inner_grad.setColorAt(1.0, QColor(76, 29, 149, 235))
            inner_pen = QPen(QColor(233, 213, 255, 190), 1.1)
        else:
            inner_grad.setColorAt(0.0, QColor(62, 78, 108, 210))
            inner_grad.setColorAt(1.0, QColor(27, 37, 57, 230))
            inner_pen = QPen(QColor(255, 255, 255, 65), 1.0)

        painter.setBrush(inner_grad)
        painter.setPen(inner_pen)
        painter.drawRoundedRect(inner_rect, 9.0, 9.0)

        # E. Crisp Format Label
        font_pt = 9 if len(label) >= 4 else 11
        font = QFont("Segoe UI", font_pt)
        font.setBold(True)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
        painter.setFont(font)

        display_label = f"🔒{label}" if (not self.is_pro and label in PRO_ONLY_FORMATS) else label

        painter.setPen(QColor(0, 0, 0, 140))
        painter.drawText(inner_rect.adjusted(0, 1, 0, 1), Qt.AlignmentFlag.AlignCenter, display_label)

        painter.setPen(QColor(255, 255, 255, 255 if is_highlighted else 235))
        painter.drawText(inner_rect, Qt.AlignmentFlag.AlignCenter, display_label)

        painter.restore()

    def _draw_quality_arc_and_dial(self, painter: QPainter, center_pt: QPointF) -> None:
        painter.save()

        arc_rect = QRectF(
            self.CENTER - self.RING_RADIUS,
            self.CENTER - self.RING_RADIUS,
            self.RING_RADIUS * 2.0,
            self.RING_RADIUS * 2.0,
        )

        qt_start_angle = int(-self.ARC_START_DEG * 16)
        qt_total_span = int((self.ARC_START_DEG - self.ARC_END_DEG) * 16)

        rim_pen = QPen(QColor(100, 116, 139, 75), 10.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(rim_pen)
        painter.drawArc(arc_rect, qt_start_angle, qt_total_span)

        groove_pen = QPen(QColor(10, 15, 28, 230), 8.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(groove_pen)
        painter.drawArc(arc_rect, qt_start_angle, qt_total_span)

        q_angle = self._quality_angle_deg()
        qt_active_span = int((self.ARC_START_DEG - q_angle) * 16)

        bloom_pen = QPen(QColor(139, 92, 246, 110), 13.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(bloom_pen)
        painter.drawArc(arc_rect, qt_start_angle, qt_active_span)

        active_grad = QConicalGradient(center_pt, -self.ARC_START_DEG)
        active_grad.setColorAt(0.0, QColor(56, 189, 248))
        active_grad.setColorAt(0.15, QColor(129, 140, 248))
        active_grad.setColorAt(0.30, QColor(192, 132, 252))
        active_grad.setColorAt(1.0, QColor(56, 189, 248))

        active_pen = QPen(active_grad, 6.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(active_pen)
        painter.drawArc(arc_rect, qt_start_angle, qt_active_span)

        tick_font = QFont("Segoe UI", 7)
        tick_font.setBold(True)
        painter.setFont(tick_font)

        num_ticks = 20
        for i in range(num_ticks + 1):
            frac = i / num_ticks
            ang_deg = self.ARC_START_DEG - frac * (self.ARC_START_DEG - self.ARC_END_DEG)
            rad = math.radians(ang_deg)
            is_major = i % 4 == 0

            r_in = self.RING_RADIUS + 14.0
            r_out = self.RING_RADIUS + (20.0 if is_major else 17.5)

            p1 = QPointF(self.CENTER + r_in * math.cos(rad), self.CENTER + r_in * math.sin(rad))
            p2 = QPointF(self.CENTER + r_out * math.cos(rad), self.CENTER + r_out * math.sin(rad))

            painter.setPen(
                QPen(
                    QColor(148, 163, 184, 155 if is_major else 85),
                    1.3 if is_major else 0.9,
                )
            )
            painter.drawLine(p1, p2)

            if is_major:
                pct_val = int(round(frac * 100))
                r_lbl = self.RING_RADIUS + 31.0
                lx = self.CENTER + r_lbl * math.cos(rad)
                ly = self.CENTER + r_lbl * math.sin(rad)
                lbl_rect = QRectF(lx - 18, ly - 8, 36, 16)
                painter.setPen(QColor(148, 163, 184, 175))
                painter.drawText(lbl_rect, Qt.AlignmentFlag.AlignCenter, f"{pct_val}%")

        knob_pt = self._quality_knob_center()
        knob_radius = 27.0

        knob_glow = QRadialGradient(knob_pt, knob_radius + 14.0)
        knob_glow.setColorAt(0.0, QColor(168, 85, 247, 200))
        knob_glow.setColorAt(0.6, QColor(56, 189, 248, 110))
        knob_glow.setColorAt(1.0, QColor(56, 189, 248, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(knob_glow)
        painter.drawEllipse(knob_pt, knob_radius + 14.0, knob_radius + 14.0)

        knob_grad = QLinearGradient(
            knob_pt.x() - knob_radius,
            knob_pt.y() - knob_radius,
            knob_pt.x() + knob_radius,
            knob_pt.y() + knob_radius,
        )
        knob_grad.setColorAt(0.0, QColor(45, 55, 78, 248))
        knob_grad.setColorAt(0.5, QColor(23, 30, 48, 252))
        knob_grad.setColorAt(1.0, QColor(15, 20, 34, 255))

        painter.setBrush(knob_grad)
        painter.setPen(QPen(QColor(167, 139, 250, 235), 2.0))
        painter.drawEllipse(knob_pt, knob_radius, knob_radius)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(56, 189, 248, 140), 1.0))
        painter.drawEllipse(knob_pt, knob_radius - 4.0, knob_radius - 4.0)

        val_font = QFont("Segoe UI", 10)
        val_font.setBold(True)
        painter.setFont(val_font)
        painter.setPen(QColor(255, 255, 255, 250))
        top_text_rect = QRectF(knob_pt.x() - 24, knob_pt.y() - 13, 48, 16)
        painter.drawText(top_text_rect, Qt.AlignmentFlag.AlignCenter, f"{self.quality}%")

        sub_font = QFont("Segoe UI", 7)
        painter.setFont(sub_font)
        painter.setPen(QColor(196, 181, 253, 220))
        sub_text_rect = QRectF(knob_pt.x() - 24, knob_pt.y() + 1, 48, 13)
        painter.drawText(sub_text_rect, Qt.AlignmentFlag.AlignCenter, "Quality")

        painter.restore()

    def _draw_circular_loading_spinner(self, painter: QPainter, center_pt: QPointF) -> None:
        """
        Draw a circular neon progress ring + rotating glow sweep + large numbered
        percentage indicator (`0% – 100%`) inside the Center Well.
        """
        painter.save()

        spin_radius = self.INNER_WELL_RADIUS - 9.0
        spin_rect = QRectF(
            self.CENTER - spin_radius,
            self.CENTER - spin_radius,
            spin_radius * 2.0,
            spin_radius * 2.0,
        )

        # 1. Background track ring
        track_pen = QPen(
            QColor(51, 65, 85, 130), 6.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap
        )
        painter.setPen(track_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center_pt, spin_radius, spin_radius)

        # 2. Proportional percentage progress arc (starts at top 90° and fills clockwise)
        pct = max(1, min(100, self._conversion_progress_pct))
        span_deg = -(pct / 100.0) * 360.0

        bloom_pen = QPen(
            QColor(168, 85, 247, 115),
            11.0,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
        )
        painter.setPen(bloom_pen)
        painter.drawArc(spin_rect, int(90 * 16), int(span_deg * 16))

        prog_grad = QLinearGradient(spin_rect.topLeft(), spin_rect.bottomRight())
        prog_grad.setColorAt(0.0, QColor(56, 189, 248, 255))
        prog_grad.setColorAt(0.5, QColor(129, 140, 248, 255))
        prog_grad.setColorAt(1.0, QColor(192, 132, 252, 255))

        prog_pen = QPen(prog_grad, 5.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(prog_pen)
        painter.drawArc(spin_rect, int(90 * 16), int(span_deg * 16))

        # 3. Rotating active neon comet highlight
        comet_pen = QPen(
            QColor(255, 255, 255, 190), 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap
        )
        painter.setPen(comet_pen)
        painter.drawArc(spin_rect, int(self._spinner_angle * 16), int(48 * 16))

        # 4. Large Numbered Percentage Readout in the Center ("68%")
        pct_font = QFont("Segoe UI", 16)
        pct_font.setBold(True)
        painter.setFont(pct_font)
        painter.setPen(QColor(255, 255, 255, 252))
        painter.drawText(
            QRectF(self.CENTER - 64, self.CENTER - 30, 128, 28),
            Qt.AlignmentFlag.AlignCenter,
            f"{self._conversion_progress_pct}%",
        )

        # 5. Conversion Mode & Subtitle Below Percentage
        f1 = QFont("Segoe UI", 8)
        f1.setBold(True)
        painter.setFont(f1)
        painter.setPen(QColor(56, 189, 248, 250))
        painter.drawText(
            QRectF(self.CENTER - 68, self.CENTER - 1, 136, 16),
            Qt.AlignmentFlag.AlignCenter,
            self._loading_title or "CONVERTING...",
        )

        f2 = QFont("Segoe UI", 7)
        painter.setFont(f2)
        painter.setPen(QColor(203, 213, 225, 220))
        painter.drawText(
            QRectF(self.CENTER - 68, self.CENTER + 14, 136, 14),
            Qt.AlignmentFlag.AlignCenter,
            self._loading_subtitle or "Preserving 1:1 layout",
        )

        painter.restore()

    def _draw_center_overlay(self, painter: QPainter, center_pt: QPointF) -> None:
        painter.save()

        # If actively converting in background, show the Numbered % Circular Loading Indicator!
        if self.is_converting:
            self._draw_circular_loading_spinner(painter, center_pt)
            painter.restore()
            return

        # 1. Subtle top close button inside the center well
        close_rect = self._close_button_rect()
        if self.hovered_close:
            painter.setBrush(QColor(239, 68, 68, 175))
            painter.setPen(QPen(QColor(252, 165, 165, 220), 1.0))
            painter.drawEllipse(close_rect)

        close_font = QFont("Segoe UI", 8)
        close_font.setBold(True)
        painter.setFont(close_font)
        painter.setPen(QColor(255, 255, 255, 230 if self.hovered_close else 75))
        painter.drawText(close_rect, Qt.AlignmentFlag.AlignCenter, "✕")

        # 2. Quick Resolution Scaling Pill at the bottom of the inner well ("Original", "1080p", "50%")
        scale_rect = self._scale_badge_rect()
        is_scaled = self.scale_idx != 0
        if self.hovered_scale_badge or is_scaled or self.has_staged_files:
            painter.setBrush(
                QColor(109, 40, 217, 185) if is_scaled else QColor(51, 65, 85, 175)
            )
            painter.setPen(
                QPen(
                    QColor(192, 132, 252, 220)
                    if is_scaled
                    else QColor(148, 163, 184, 140),
                    1.0,
                )
            )
            painter.drawRoundedRect(scale_rect, 9.0, 9.0)

        scale_font = QFont("Segoe UI", 7)
        scale_font.setBold(True)
        painter.setFont(scale_font)
        painter.setPen(
            QColor(233, 213, 255, 245)
            if (self.hovered_scale_badge or is_scaled or self.has_staged_files)
            else QColor(148, 163, 184, 130)
        )
        painter.drawText(
            scale_rect,
            Qt.AlignmentFlag.AlignCenter,
            f"📐 {self.current_scale_preset.upper()}",
        )

        # 3. Center Well Status: Option 1 (Hold & Tweak) / Option 3 (Mid-Drag Keys) / Saved Readout
        if self.is_dragging_files and self._is_dragging_over_center:
            f1 = QFont("Segoe UI", 9)
            f1.setBold(True)
            painter.setFont(f1)
            painter.setPen(QColor(56, 189, 248, 250))
            painter.drawText(
                QRectF(self.CENTER - 74, self.CENTER - 22, 148, 18),
                Qt.AlignmentFlag.AlignCenter,
                "HOLD & TWEAK",
            )
            f2 = QFont("Segoe UI", 7)
            painter.setFont(f2)
            painter.setPen(QColor(203, 213, 225, 225))
            painter.drawText(
                QRectF(self.CENTER - 76, self.CENTER - 3, 152, 15),
                Qt.AlignmentFlag.AlignCenter,
                "Drop here to stage file",
            )
            painter.setPen(QColor(148, 163, 184, 180))
            painter.drawText(
                QRectF(self.CENTER - 76, self.CENTER + 11, 152, 14),
                Qt.AlignmentFlag.AlignCenter,
                f"{self.current_scale_preset} • Q:{self.quality}%",
            )
        elif self.is_dragging_files and self.drag_target_idx is not None:
            fmt_label = RADIAL_FORMATS[self.drag_target_idx][0]
            f1 = QFont("Segoe UI", 11)
            f1.setBold(True)
            painter.setFont(f1)
            painter.setPen(QColor(233, 213, 255, 245))
            painter.drawText(
                QRectF(self.CENTER - 72, self.CENTER - 22, 144, 20),
                Qt.AlignmentFlag.AlignCenter,
                f"DROP → {fmt_label}",
            )
            f2 = QFont("Segoe UI", 8)
            f2.setBold(True)
            painter.setFont(f2)
            painter.setPen(QColor(56, 189, 248, 235))
            painter.drawText(
                QRectF(self.CENTER - 72, self.CENTER - 3, 144, 16),
                Qt.AlignmentFlag.AlignCenter,
                f"{self.current_scale_preset} • Q:{self.quality}%",
            )
            f3 = QFont("Segoe UI", 6)
            painter.setFont(f3)
            painter.setPen(QColor(148, 163, 184, 175))
            painter.drawText(
                QRectF(self.CENTER - 76, self.CENTER + 12, 152, 13),
                Qt.AlignmentFlag.AlignCenter,
                "Space: Scale • ↑↓: Quality",
            )
        elif self._status_text:
            f1 = QFont("Segoe UI", 9)
            f1.setBold(True)
            painter.setFont(f1)
            painter.setPen(QColor(56, 189, 248, 250))
            painter.drawText(
                QRectF(self.CENTER - 74, self.CENTER - 20, 148, 18),
                Qt.AlignmentFlag.AlignCenter,
                self._status_text,
            )
            if self._status_subtext:
                f2 = QFont("Segoe UI", 8)
                f2.setBold(True)
                painter.setFont(f2)
                painter.setPen(QColor(192, 132, 252, 245))
                painter.drawText(
                    QRectF(self.CENTER - 76, self.CENTER - 1, 152, 18),
                    Qt.AlignmentFlag.AlignCenter,
                    self._status_subtext,
                )
        elif self.has_staged_files:
            count = len(self._staged_files)
            title = (
                f"📌 {self._staged_files[0].name[:15]}"
                if count == 1
                else f"📌 {count} FILES READY"
            )
            f1 = QFont("Segoe UI", 8)
            f1.setBold(True)
            painter.setFont(f1)
            painter.setPen(QColor(56, 189, 248, 250))
            painter.drawText(
                QRectF(self.CENTER - 74, self.CENTER - 22, 148, 16),
                Qt.AlignmentFlag.AlignCenter,
                title,
            )
            f2 = QFont("Segoe UI", 8)
            f2.setBold(True)
            painter.setFont(f2)
            painter.setPen(QColor(233, 213, 255, 240))
            painter.drawText(
                QRectF(self.CENTER - 76, self.CENTER - 5, 152, 16),
                Qt.AlignmentFlag.AlignCenter,
                f"{self.current_scale_preset} • Q:{self.quality}%",
            )
            f3 = QFont("Segoe UI", 7)
            painter.setFont(f3)
            painter.setPen(QColor(148, 163, 184, 210))
            painter.drawText(
                QRectF(self.CENTER - 76, self.CENTER + 10, 152, 14),
                Qt.AlignmentFlag.AlignCenter,
                "Click any format to convert",
            )

        painter.restore()

    # ------------------------------------------------------------------
    # Mouse & Context Menu Interaction
    # ------------------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self.is_converting:
            return
        self._reset_inactivity_timer()
        pos = event.position()
        if event.button() == Qt.MouseButton.LeftButton:
            if self._close_button_rect().contains(pos):
                self._staged_files.clear()
                self._manual_pin_visible = False
                self._set_wheel_visible(False, force=True)
                return

            if self._scale_badge_rect().contains(pos):
                self._cycle_scale_preset()
                return

            if self._hit_test_quality_arc(pos):
                self.is_adjusting_quality = True
                self._update_quality_from_pos(pos)
                return

            clicked_tile = self._hit_test_tile(pos, snap_nearest=False)
            if clicked_tile is not None and self.has_staged_files:
                files_to_convert = list(self._staged_files)
                self._staged_files.clear()
                self._run_conversion_batch(files_to_convert, clicked_tile)
                return

            self._window_drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.is_converting:
            return
        pos = event.position()

        if self.is_adjusting_quality and (event.buttons() & Qt.MouseButton.LeftButton):
            self._reset_inactivity_timer()
            self._update_quality_from_pos(pos)
            return

        if self._window_drag_offset is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._window_drag_offset)
            event.accept()
            return

        new_hover = self._hit_test_tile(pos, snap_nearest=False)
        new_close = self._close_button_rect().contains(pos)
        new_scale = self._scale_badge_rect().contains(pos)

        if (
            new_hover != self.hovered_tile_idx
            or new_close != self.hovered_close
            or new_scale != self.hovered_scale_badge
        ):
            self.hovered_tile_idx = new_hover
            self.hovered_close = new_close
            self.hovered_scale_badge = new_scale
            if (
                new_hover is not None
                or new_close
                or new_scale
                or self._hit_test_quality_arc(pos)
            ):
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.is_adjusting_quality = False
        self._window_drag_offset = None

    def leaveEvent(self, event) -> None:
        self.hovered_tile_idx = None
        self.hovered_close = False
        self.hovered_scale_badge = False
        self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self.is_converting:
            return
        self._reset_inactivity_timer()
        delta = event.angleDelta().y()
        if delta != 0:
            step = 5 if delta > 0 else -5
            self.quality = max(5, min(100, self.quality + step))
            self.update()

    def contextMenuEvent(self, event) -> None:
        if self.is_converting:
            return
        self._reset_inactivity_timer()
        menu = QMenu(self)
        menu.setStyleSheet(
            """
            QMenu {
                background-color: #0F172A;
                color: #F8FAFC;
                border: 1px solid #475569;
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 18px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #6D28D9;
            }
            """
        )

        pro_act = menu.addAction(
            "✓ FloatConvert Pro Activated"
            if self.is_pro
            else "🔑 Activate FloatConvert Pro..."
        )
        menu.addSeparator()

        scale_menu = menu.addMenu(f"📐 Resolution Scale ({self.current_scale_preset})")
        scale_actions = {}
        for idx, preset in enumerate(SCALE_PRESETS):
            prefix = "✓ " if idx == self.scale_idx else "   "
            act = scale_menu.addAction(f"{prefix}{preset}")
            scale_actions[act] = idx

        menu.addSeparator()
        copy_act = menu.addAction(
            "✓ Auto-Copy Converted File to Clipboard"
            if self.auto_copy_clipboard
            else "Auto-Copy Converted File to Clipboard"
        )
        merge_pdf_act = menu.addAction(
            "✓ Merge Multiple Images into 1 A4 PDF"
            if self.merge_pdf_enabled
            else "Merge Multiple Images into 1 A4 PDF"
        )
        del_action = menu.addAction(
            "✓ Delete Original After Convert"
            if self.replace_original
            else "Delete Original After Convert"
        )
        menu.addSeparator()
        hide_action = menu.addAction("Hide Back to Stealth Armed Mode")
        disable_action = menu.addAction("Disable Smart Drag Mode (Ctrl+Alt+D)")
        quit_action = menu.addAction("Quit Completely")

        chosen = menu.exec(event.globalPos())
        if chosen == pro_act and not self.is_pro:
            self.open_license_dialog()
        elif chosen in scale_actions:
            if not self.is_pro and scale_actions[chosen] != 0:
                self.open_license_dialog()
            else:
                self.scale_idx = scale_actions[chosen]
                self.update()
        elif chosen == copy_act:
            self.auto_copy_clipboard = not self.auto_copy_clipboard
            state = "ON" if self.auto_copy_clipboard else "OFF"
            self._show_temporary_status("📋 AUTO-COPY", f"Clipboard Copy: {state}", 1600)
        elif chosen == merge_pdf_act:
            self.merge_pdf_enabled = not self.merge_pdf_enabled
            state = "Merged A4 PDF" if self.merge_pdf_enabled else "Separate A4 PDFs"
            self._show_temporary_status("📄 PDF MODE", state, 1600)
        elif chosen == del_action:
            self.replace_original = not self.replace_original
            mode_txt = "Replace Original: ON" if self.replace_original else "Keep Original: ON"
            self._show_temporary_status("⚙️ MODE", mode_txt, 1600)
        elif chosen == hide_action:
            self._staged_files.clear()
            self._manual_pin_visible = False
            self._set_wheel_visible(False, force=True)
        elif chosen == disable_action:
            self.disable_armed_mode()
        elif chosen == quit_action:
            QApplication.instance().quit()

    # ------------------------------------------------------------------
    # Direct Per-Button Drag & Drop OR Center-Well "Hold & Tweak" Drop
    # ------------------------------------------------------------------
    def _update_drag_hover_state(self, pos: QPointF) -> None:
        if self._is_inside_center_well(pos):
            self._is_dragging_over_center = True
            self.drag_target_idx = None
        else:
            self._is_dragging_over_center = False
            self.drag_target_idx = self._hit_test_tile(pos, snap_nearest=True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self.is_converting:
            event.ignore()
            return

        if not event.mimeData().hasUrls():
            event.ignore()
            self._drag_rejected_unsupported = True
            if self._is_probing_drag:
                self._abort_invisible_drag_probe()
            return

        files = self._collect_supported_files(event.mimeData().urls())
        if not files:
            event.ignore()
            self._drag_rejected_unsupported = True
            if self._is_probing_drag or not self._manual_pin_visible:
                self._abort_invisible_drag_probe()
                if self._wheel_shown and not self._manual_pin_visible and not self.has_staged_files:
                    self._set_wheel_visible(False, force=True)
            return

        self._auto_hide_timer.stop()
        self._reset_inactivity_timer()

        if not self._wheel_shown or self._is_probing_drag:
            self._set_wheel_visible(True, force=True)

        event.acceptProposedAction()
        local_pt = self.mapFromGlobal(QCursor.pos())
        if self.rect().contains(local_pt):
            self.is_dragging_files = True
            self._update_drag_hover_state(QPointF(local_pt))
        else:
            self.is_dragging_files = False
            self._is_dragging_over_center = False
            self.drag_target_idx = None
        self.update()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self.is_converting or not event.mimeData().hasUrls():
            event.ignore()
            return

        files = self._collect_supported_files(event.mimeData().urls())
        if not files:
            event.ignore()
            return

        self._auto_hide_timer.stop()
        self._reset_inactivity_timer()
        self.is_dragging_files = True
        prev_center = self._is_dragging_over_center
        prev_idx = self.drag_target_idx
        self._update_drag_hover_state(event.position())
        if (
            self._is_dragging_over_center != prev_center
            or self.drag_target_idx != prev_idx
        ):
            self.update()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self.is_dragging_files = False
        self._is_dragging_over_center = False
        self.drag_target_idx = None
        self.update()

    def dropEvent(self, event: QDropEvent) -> None:
        if self.is_converting:
            event.ignore()
            return

        self.is_dragging_files = False
        pos = event.position()
        dropped_in_center = self._is_inside_center_well(pos)
        target_idx = None if dropped_in_center else self._hit_test_tile(pos, snap_nearest=True)

        self._is_dragging_over_center = False
        self.drag_target_idx = None

        if not event.mimeData().hasUrls():
            self.update()
            return

        files = self._collect_supported_files(event.mimeData().urls())
        if not files:
            event.ignore()
            if not self._manual_pin_visible:
                self._set_wheel_visible(False, force=True)
            return

        event.acceptProposedAction()
        self._auto_hide_timer.stop()
        self._reset_inactivity_timer()

        if dropped_in_center:
            self._staged_files = files
            self._status_text = ""
            self._status_subtext = ""
            self.activateWindow()
            self.update()
            return

        if target_idx is None:
            self.update()
            return

        self._staged_files.clear()
        self._run_conversion_batch(files, target_idx)

    def _run_conversion_batch(self, files: list[Path], target_idx: int) -> None:
        if self.is_converting:
            return
        self._reset_inactivity_timer()
        label, _, pil_format, _ = RADIAL_FORMATS[target_idx]

        if not self.is_pro:
            has_heic_or_doc = any(
                f.suffix.lower() in {".heic", ".heif", ".pdf", ".docx", ".doc"}
                for f in files
            )
            if label in PRO_ONLY_FORMATS or has_heic_or_doc:
                self.open_license_dialog()
                if not self.is_pro:
                    self._show_temporary_status(
                        "🔒 PRO REQUIRED",
                        "Unlock Pro for PDF/WORD/HEIC",
                        1500,
                        hide_wheel_on_finish=True,
                    )
                    return

        exts = {f.suffix.lower() for f in files}
        if exts.issubset(PDF_INPUT_EXTS) and pil_format in {"DOCX", "PDF"}:
            self._loading_title = "PDF → WORD"
            self._loading_subtitle = "Preserving 1:1 layout"
        elif exts.issubset(WORD_INPUT_EXTS):
            self._loading_title = "WORD → PDF"
            self._loading_subtitle = "Rendering A4 PDF"
        else:
            self._loading_title = f"CONVERTING → {label}"
            self._loading_subtitle = f"{len(files)} file(s)"

        self.is_converting = True
        self.active_flash_idx = target_idx
        self._spinner_angle = 0
        self._spinner_tick_count = 0
        self._conversion_progress_pct = 5
        self._target_progress_pct = 10
        self._spinner_timer.start()
        self.update()

        self._worker = ConversionWorkerThread(
            files=list(files),
            target_idx=target_idx,
            quality=self.quality,
            scale_preset=self.current_scale_preset,
            replace_original=self.replace_original,
            merge_pdf_enabled=self.merge_pdf_enabled,
            parent=self,
        )
        self._worker.progress_updated.connect(self._on_worker_progress)
        self._worker.batch_finished.connect(self._on_worker_batch_finished)
        self._worker.start()

    def _on_worker_batch_finished(
        self,
        converted_paths: list[Path],
        errors: list[str],
        label: str,
        orig_bytes: int,
        target_idx: int,
    ) -> None:
        self._conversion_progress_pct = 100
        self._target_progress_pct = 100
        self.is_converting = False
        self._spinner_timer.stop()
        self._reset_inactivity_timer()

        self.active_flash_idx = target_idx
        self._flash_timer.start(850)

        if converted_paths and not errors:
            new_bytes = sum(p.stat().st_size for p in converted_paths if p.exists())
            delta_str = format_size_delta(orig_bytes, new_bytes)
            self._copy_files_to_clipboard(converted_paths)

            if len(converted_paths) == 1:
                self._show_temporary_status(
                    f"✓ {label} SAVED (100%)",
                    delta_str or converted_paths[0].name[:22],
                    950,
                    hide_wheel_on_finish=True,
                )
            else:
                self._show_temporary_status(
                    f"✓ {len(converted_paths)} → {label} (100%)",
                    delta_str or "Saved & copied",
                    950,
                    hide_wheel_on_finish=True,
                )
        elif converted_paths and errors:
            self._copy_files_to_clipboard(converted_paths)
            self._show_temporary_status(
                f"⚠️ {len(converted_paths)} OK / {len(errors)} ERR",
                errors[0][:20],
                1600,
                hide_wheel_on_finish=True,
            )
        else:
            self._show_temporary_status(
                "❌ FAILED",
                (errors[0] if errors else "Conversion error")[:22],
                1600,
                hide_wheel_on_finish=True,
            )

    def _collect_supported_files(self, urls: Iterable[QUrl]) -> list[Path]:
        """
        Return local `Path`s only if ALL dragged items have a supported extension
        (`SUPPORTED_INPUT_EXTS`: images, `.pdf`, `.docx`, `.doc`). If any dragged
        item is an unsupported format or a folder, return `[]` so the UI stays hidden.
        """
        collected: list[Path] = []
        for url in urls:
            local_str = url.toLocalFile()
            if not local_str:
                return []
            path = Path(local_str)
            if path.suffix.lower() in SUPPORTED_INPUT_EXTS and not path.is_dir():
                collected.append(path)
            else:
                return []
        return collected


def main() -> None:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont("Segoe UI", 10))

    socket = QLocalSocket()
    socket.connectToServer(SINGLE_INSTANCE_KEY)
    if socket.waitForConnected(200):
        socket.write(b"ARM")
        socket.waitForBytesWritten(200)
        socket.disconnectFromServer()
        sys.exit(0)

    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    server = QLocalServer()
    server.listen(SINGLE_INSTANCE_KEY)

    converter = RadialImageConverter()
    server.newConnection.connect(converter.activate_armed_mode_silently)
    converter.start_in_stealth_armed_mode()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()