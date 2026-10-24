#!/usr/bin/env python3
"""
FloatConvert — Radial Neon Floating Drag & Drop Image Format Converter
======================================================================
A frameless, always-on-top circular desktop UI with glowing neon accents.
Drag and drop one or more images directly onto any radial format button
(ICO, GIF, WEBP, JPG, PNG, PDF) to convert them immediately in their
original folder.

Features:
1. Direct Per-Button Drag & Drop (ICO, GIF, WEBP, JPG, PNG, PDF).
2. File-Size Saved Readout (e.g., "-78% • 1.4 MB saved") in the center well.
3. Clipboard Paste (Ctrl+V) & Auto-Copy converted files to clipboard.
4. Multi-Image -> Single Merged PDF when dropping 2+ images onto PDF.
5. Quick Resolution Scaling ("Original", "1080p", "50%") via center badge or menu.
6. Instant 0ms Native Win32 Hotkey (Ctrl+Alt+C) & System Tray mode.

Requirements:
    pip install PyQt6 Pillow

Usage:
    pythonw image_converter_app.py
"""

from __future__ import annotations

import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageOps
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
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QGuiApplication,
    QIcon,
    QImage,
    QKeyEvent,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QRadialGradient,
    QWheelEvent,
)
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

SINGLE_INSTANCE_KEY = "FloatConvert_Radial_SingleInstance_Server"

SUPPORTED_INPUT_EXTS = {
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

# (Label, Extension, Pillow Format, Angle in degrees [0=Right, 90=Bottom, 180=Left, 270=Top])
RADIAL_FORMATS = [
    ("ICO", ".ico", "ICO", 140.0),
    ("GIF", ".gif", "GIF", 178.0),
    ("WEBP", ".webp", "WEBP", 216.0),
    ("JPG", ".jpg", "JPEG", 254.0),
    ("PNG", ".png", "PNG", 292.0),
    ("PDF", ".pdf", "PDF", 330.0),
]

SCALE_PRESETS = ["Original", "1080p", "50%"]


class GlobalHotkeyThread(QThread):
    """
    Listens for Ctrl + Alt + C directly via the Windows Win32 kernel API
    (RegisterHotKey) with 0% CPU usage and <1ms response time.
    """

    hotkey_pressed = pyqtSignal()

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

            if not user32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("C")):
                return

            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == WM_HOTKEY:
                    self.hotkey_pressed.emit()

            user32.UnregisterHotKey(None, 1)
        except Exception:  # noqa: BLE001
            pass


def create_neon_tray_icon() -> QIcon:
    """Generate a crisp circular neon icon in memory for the Windows System Tray."""
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    grad = QRadialGradient(QPointF(32, 32), 28)
    grad.setColorAt(0.0, QColor(192, 132, 252))
    grad.setColorAt(0.55, QColor(109, 40, 217))
    grad.setColorAt(1.0, QColor(15, 23, 42))

    painter.setBrush(grad)
    painter.setPen(QPen(QColor(56, 189, 248), 4.0))
    painter.drawEllipse(QPointF(32, 32), 26, 26)

    painter.setBrush(QColor(15, 23, 42))
    painter.setPen(QPen(QColor(216, 180, 254), 2.0))
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
    """Flatten RGBA/palette transparency onto a white RGB background."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[3])
        return background
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def _unique_output_path(parent_dir: Path, stem: str, target_ext: str) -> Path:
    candidate = parent_dir / f"{stem}{target_ext}"
    counter = 1
    while candidate.exists():
        candidate = parent_dir / f"{stem}_{counter}{target_ext}"
        counter += 1
    return candidate


def convert_pil_image_to_path(
    img: Image.Image,
    output_path: Path,
    pil_format: str,
    quality: int = 85,
    scale_preset: str = "Original",
) -> Path:
    """Save an in-memory PIL Image to `output_path` with scaling and format rules."""
    img = ImageOps.exif_transpose(img)
    img = apply_resolution_preset(img, scale_preset)

    save_kwargs: dict = {}
    if pil_format in {"JPEG", "BMP", "PDF"}:
        img = flatten_to_rgb(img)
    elif pil_format == "ICO":
        img = img.convert("RGBA")
        save_kwargs["sizes"] = [(min(img.width, 256), min(img.height, 256))]
    elif pil_format in {"PNG", "WEBP", "TIFF"}:
        if img.mode == "P":
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
    Convert `source_path` to `pil_format` in the exact same directory.
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
    scale_preset: str = "Original",
    replace_original: bool = False,
) -> Path:
    """Combine 2 or more images into a single multi-page PDF in the first image's folder."""
    first = source_paths[0]
    parent_dir = first.parent
    out_path = _unique_output_path(parent_dir, f"{first.stem}_merged", ".pdf")

    rgb_pages: list[Image.Image] = []
    try:
        for src in source_paths:
            with Image.open(src) as img:
                page = ImageOps.exif_transpose(img)
                page = apply_resolution_preset(page, scale_preset)
                page = flatten_to_rgb(page).copy()
                rgb_pages.append(page)

        rgb_pages[0].save(
            out_path,
            format="PDF",
            save_all=True,
            append_images=rgb_pages[1:],
        )
    finally:
        for page in rgb_pages:
            page.close()

    if replace_original:
        for src in source_paths:
            if src.exists() and src.resolve() != out_path.resolve():
                try:
                    src.unlink()
                except OSError:
                    pass

    return out_path


class RadialImageConverter(QWidget):
    """
    Circular frameless floating desktop UI with 3D neon format tiles and
    a curved bottom quality dial.
    """

    WINDOW_SIZE = 460
    CENTER = WINDOW_SIZE / 2.0
    OUTER_RADIUS = 204.0
    RING_RADIUS = 152.0
    INNER_BEZEL_OUTER = 102.0
    INNER_WELL_RADIUS = 82.0
    TILE_SIZE = 64.0

    # Bottom quality arc angles (screen degrees: 0=Right, 90=Bottom, 180=Left)
    ARC_START_DEG = 114.0  # 0% / min end (bottom-left)
    ARC_END_DEG = 18.0     # 100% / max end (bottom-right)

    def __init__(self) -> None:
        super().__init__()
        self.quality: int = 85
        self.scale_idx: int = 0  # 0="Original", 1="1080p", 2="50%"
        self.default_paste_idx: int = 2  # Default Ctrl+V format: WEBP (index 2)
        self.replace_original: bool = False
        self.auto_copy_clipboard: bool = True
        self.merge_pdf_enabled: bool = True
        self.is_pinned: bool = True

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
        self._status_timer.timeout.connect(self._clear_status)

        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._clear_flash)

        self._configure_window()
        self._position_top_right()
        self._setup_tray_and_hotkey()

    @property
    def current_scale_preset(self) -> str:
        return SCALE_PRESETS[self.scale_idx]

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
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(self.WINDOW_SIZE, self.WINDOW_SIZE)

    def _position_top_right(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen:
            geom = screen.availableGeometry()
            self.move(geom.right() - self.width() - 24, geom.top() + 36)

    def _setup_tray_and_hotkey(self) -> None:
        self.tray_icon = QSystemTrayIcon(create_neon_tray_icon(), self)
        self.tray_icon.setToolTip("FloatConvert (Ctrl+Alt+C to Show/Hide)")

        tray_menu = QMenu()
        show_action = tray_menu.addAction("Show / Hide (Ctrl+Alt+C)")
        show_action.triggered.connect(self.toggle_visibility)
        paste_action = tray_menu.addAction("Paste & Convert Clipboard (Ctrl+V)")
        paste_action.triggered.connect(self.convert_from_clipboard)
        tray_menu.addSeparator()
        quit_action = tray_menu.addAction("Quit Completely")
        quit_action.triggered.connect(QApplication.instance().quit)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

        self.hotkey_thread = GlobalHotkeyThread(self)
        self.hotkey_thread.hotkey_pressed.connect(self.toggle_visibility)
        self.hotkey_thread.start()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.toggle_visibility()

    def toggle_visibility(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.bring_to_front()

    def bring_to_front(self) -> None:
        self.show()
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def _show_temporary_status(self, title: str, subtitle: str = "", duration_ms: int = 3200) -> None:
        self._status_text = title
        self._status_subtext = subtitle
        self._status_timer.start(duration_ms)
        self.update()

    def _clear_status(self) -> None:
        self._status_text = ""
        self._status_subtext = ""
        self.update()

    def _clear_flash(self) -> None:
        self.active_flash_idx = None
        self.update()

    def _cycle_scale_preset(self) -> None:
        self.scale_idx = (self.scale_idx + 1) % len(SCALE_PRESETS)
        descriptions = {
            "Original": "100% Native Dimensions",
            "1080p": "Max 1920px Longest Side",
            "50%": "Half Width & Height",
        }
        preset = self.current_scale_preset
        self._show_temporary_status(f"📐 SCALE: {preset.upper()}", descriptions[preset], 2200)

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
        # Clickable resolution preset pill tucked at the bottom of the inner well
        return QRectF(self.CENTER - 38, self.CENTER + self.INNER_WELL_RADIUS - 28, 76, 20)

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
            rect = self._tile_rect(idx).adjusted(-8, -8, 8, 8)
            if rect.contains(pos):
                return idx

        if snap_nearest:
            dx = pos.x() - self.CENTER
            dy = pos.y() - self.CENTER
            dist = math.hypot(dx, dy)
            if 65.0 <= dist <= self.OUTER_RADIUS + 18.0:
                best_idx = None
                best_dist = 95.0
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
    # Custom Neon Radial Painting
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
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
        bezel_glow = QRadialGradient(center_pt, self.INNER_BEZEL_OUTER + 10)
        bezel_glow.setColorAt(0.65, QColor(0, 0, 0, 0))
        bezel_glow.setColorAt(0.88, QColor(139, 92, 246, 85))
        bezel_glow.setColorAt(1.0, QColor(56, 189, 248, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bezel_glow)
        painter.drawEllipse(center_pt, self.INNER_BEZEL_OUTER + 10, self.INNER_BEZEL_OUTER + 10)

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
        painter.setPen(QPen(QColor(168, 85, 247, 110), 1.5))
        painter.drawEllipse(center_pt, self.INNER_BEZEL_OUTER, self.INNER_BEZEL_OUTER)

        well_grad = QRadialGradient(
            QPointF(self.CENTER - 18, self.CENTER - 18), self.INNER_WELL_RADIUS * 1.25
        )
        well_grad.setColorAt(0.0, QColor(20, 25, 37, 252))
        well_grad.setColorAt(0.7, QColor(11, 15, 24, 254))
        well_grad.setColorAt(1.0, QColor(6, 9, 15, 255))
        painter.setBrush(well_grad)
        painter.setPen(QPen(QColor(99, 102, 241, 90), 1.2))
        painter.drawEllipse(center_pt, self.INNER_WELL_RADIUS, self.INNER_WELL_RADIUS)

        # 4. Draw Curved Quality Dial & Arc Track at Bottom
        self._draw_quality_arc_and_dial(painter, center_pt)

        # 5. Draw Each Radial Format Button
        for idx in range(len(RADIAL_FORMATS)):
            self._draw_format_tile(painter, idx)

        # 6. Draw Close Button, Quick Scale Preset Pill & Transient Status Readout
        self._draw_center_overlay(painter, center_pt)

    def _draw_format_tile(self, painter: QPainter, idx: int) -> None:
        label, _, _, _ = RADIAL_FORMATS[idx]
        rect = self._tile_rect(idx)
        center = rect.center()

        is_drag_target = self.drag_target_idx == idx
        is_hovered = self.hovered_tile_idx == idx
        is_flashed = self.active_flash_idx == idx
        is_highlighted = is_drag_target or is_hovered or is_flashed
        is_paste_default = self.default_paste_idx == idx

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
        painter.drawRoundedRect(base_rect, 16.0, 16.0)

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
        painter.drawRoundedRect(body_rect, 14.0, 14.0)

        # D. Inner Beveled Cap
        inner_rect = body_rect.adjusted(5.5, 5.5, -5.5, -5.5)
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
        painter.drawRoundedRect(inner_rect, 10.0, 10.0)

        # Small neon indicator dot on the active Ctrl+V clipboard target format
        if is_paste_default:
            dot_pt = QPointF(inner_rect.center().x(), inner_rect.bottom() - 5.5)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(56, 189, 248, 230))
            painter.drawEllipse(dot_pt, 2.2, 2.2)

        # E. Crisp Format Label
        font = QFont("Segoe UI", 11)
        font.setBold(True)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
        painter.setFont(font)

        painter.setPen(QColor(0, 0, 0, 140))
        painter.drawText(inner_rect.adjusted(0, 1, 0, 1), Qt.AlignmentFlag.AlignCenter, label)

        painter.setPen(QColor(255, 255, 255, 255 if is_highlighted else 235))
        painter.drawText(inner_rect, Qt.AlignmentFlag.AlignCenter, label)

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

    def _draw_center_overlay(self, painter: QPainter, center_pt: QPointF) -> None:
        painter.save()

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
        if self.hovered_scale_badge or is_scaled:
            painter.setBrush(
                QColor(109, 40, 217, 165) if is_scaled else QColor(51, 65, 85, 160)
            )
            painter.setPen(
                QPen(
                    QColor(192, 132, 252, 210)
                    if is_scaled
                    else QColor(148, 163, 184, 120),
                    1.0,
                )
            )
            painter.drawRoundedRect(scale_rect, 9.0, 9.0)

        scale_font = QFont("Segoe UI", 7)
        scale_font.setBold(True)
        painter.setFont(scale_font)
        painter.setPen(
            QColor(233, 213, 255, 240)
            if (self.hovered_scale_badge or is_scaled)
            else QColor(148, 163, 184, 115)
        )
        painter.drawText(
            scale_rect,
            Qt.AlignmentFlag.AlignCenter,
            f"📐 {self.current_scale_preset.upper()}",
        )

        # 3. Transient Status & File-Size Saved Readout inside the center well
        if self.is_dragging_files and self.drag_target_idx is not None:
            fmt_label = RADIAL_FORMATS[self.drag_target_idx][0]
            f1 = QFont("Segoe UI", 11)
            f1.setBold(True)
            painter.setFont(f1)
            painter.setPen(QColor(233, 213, 255, 245))
            painter.drawText(
                QRectF(self.CENTER - 72, self.CENTER - 20, 144, 20),
                Qt.AlignmentFlag.AlignCenter,
                f"DROP → {fmt_label}",
            )
            f2 = QFont("Segoe UI", 8)
            painter.setFont(f2)
            painter.setPen(QColor(148, 163, 184, 215))
            painter.drawText(
                QRectF(self.CENTER - 72, self.CENTER + 0, 144, 16),
                Qt.AlignmentFlag.AlignCenter,
                f"{self.current_scale_preset} • Q:{self.quality}%",
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

        painter.restore()

    # ------------------------------------------------------------------
    # Keyboard (Ctrl + V Clipboard Paste), Mouse & Context Menu
    # ------------------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.matches(Qt.Key.Key_Paste) or (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier
            and event.key() == Qt.Key.Key_V
        ):
            target_idx = (
                self.hovered_tile_idx
                if self.hovered_tile_idx is not None
                else self.default_paste_idx
            )
            self.convert_from_clipboard(target_idx)
            event.accept()
            return
        super().keyPressEvent(event)

    def convert_from_clipboard(self, target_idx: int | None = None) -> None:
        """Convert either copied image files or a raw screenshot from the Windows clipboard."""
        if target_idx is None or not isinstance(target_idx, int):
            target_idx = (
                self.hovered_tile_idx
                if self.hovered_tile_idx is not None
                else self.default_paste_idx
            )

        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()
        if mime is None:
            return

        # Case 1: User copied image file(s) in File Explorer and pressed Ctrl+V
        if mime.hasUrls():
            files = self._collect_image_files(mime.urls())
            if files:
                self._run_conversion_batch(files, target_idx)
                return

        # Case 2: User took a screenshot (Win+Shift+S / PrtScn) and pressed Ctrl+V
        qimg: QImage = clipboard.image()
        if not qimg.isNull():
            label, target_ext, pil_format, _ = RADIAL_FORMATS[target_idx]
            self.active_flash_idx = target_idx
            self._flash_timer.start(900)

            try:
                # Convert QImage to PIL Image via RGBA buffer
                qimg_rgba = qimg.convertToFormat(QImage.Format.Format_RGBA8888)
                width, height = qimg_rgba.width(), qimg_rgba.height()
                ptr = qimg_rgba.bits()
                ptr.setsize(height * qimg_rgba.bytesPerLine())
                pil_img = Image.frombuffer(
                    "RGBA",
                    (width, height),
                    bytes(ptr),
                    "raw",
                    "RGBA",
                    qimg_rgba.bytesPerLine(),
                    1,
                )

                # Save screenshot in Pictures/FloatConvert (or Desktop fallback)
                save_dir = Path.home() / "Pictures" / "FloatConvert"
                try:
                    save_dir.mkdir(parents=True, exist_ok=True)
                except OSError:
                    save_dir = Path.home() / "Desktop"

                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                out_path = _unique_output_path(save_dir, f"clipboard_{stamp}", target_ext)

                convert_pil_image_to_path(
                    img=pil_img,
                    output_path=out_path,
                    pil_format=pil_format,
                    quality=self.quality,
                    scale_preset=self.current_scale_preset,
                )

                self._copy_files_to_clipboard([out_path])
                new_size = out_path.stat().st_size if out_path.exists() else 0
                self._show_temporary_status(
                    f"📋 → {label} COPIED",
                    f"{format_bytes(new_size)} • Ready to Ctrl+V",
                    3200,
                )
            except Exception as exc:  # noqa: BLE001
                self._show_temporary_status("❌ PASTE ERR", str(exc)[:22], 3000)
            return

        self._show_temporary_status("📋 CLIPBOARD EMPTY", "Copy an image first", 2200)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        if event.button() == Qt.MouseButton.LeftButton:
            if self._close_button_rect().contains(pos):
                self.hide()
                return

            if self._scale_badge_rect().contains(pos):
                self._cycle_scale_preset()
                return

            if self._hit_test_quality_arc(pos):
                self.is_adjusting_quality = True
                self._update_quality_from_pos(pos)
                return

            clicked_tile = self._hit_test_tile(pos, snap_nearest=False)
            if clicked_tile is not None:
                # Clicking a format tile sets it as the active Ctrl+V clipboard target
                self.default_paste_idx = clicked_tile
                fmt_label = RADIAL_FORMATS[clicked_tile][0]
                self._show_temporary_status(
                    f"📋 CTRL+V → {fmt_label}",
                    "Press Ctrl+V to paste & convert",
                    2000,
                )
                self.update()
                return

            self._window_drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()

        if self.is_adjusting_quality and (event.buttons() & Qt.MouseButton.LeftButton):
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
        delta = event.angleDelta().y()
        if delta != 0:
            step = 5 if delta > 0 else -5
            self.quality = max(5, min(100, self.quality + step))
            self.update()

    def contextMenuEvent(self, event) -> None:
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

        paste_fmt = RADIAL_FORMATS[self.default_paste_idx][0]
        paste_act = menu.addAction(f"📋 Paste & Convert to {paste_fmt} (Ctrl+V)")

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
            "✓ Merge Multiple Images into 1 PDF"
            if self.merge_pdf_enabled
            else "Merge Multiple Images into 1 PDF"
        )
        del_action = menu.addAction(
            "✓ Delete Original After Convert"
            if self.replace_original
            else "Delete Original After Convert"
        )
        pin_action = menu.addAction(
            "✓ Always on Top" if self.is_pinned else "Always on Top"
        )
        menu.addSeparator()
        hide_action = menu.addAction("Hide Widget (Ctrl+Alt+C)")
        quit_action = menu.addAction("Quit Completely")

        chosen = menu.exec(event.globalPos())
        if chosen == paste_act:
            self.convert_from_clipboard(self.default_paste_idx)
        elif chosen in scale_actions:
            self.scale_idx = scale_actions[chosen]
            self._show_temporary_status(
                f"📐 SCALE: {self.current_scale_preset.upper()}",
                "Updated resize preset",
                2000,
            )
        elif chosen == copy_act:
            self.auto_copy_clipboard = not self.auto_copy_clipboard
            state = "ON" if self.auto_copy_clipboard else "OFF"
            self._show_temporary_status("📋 AUTO-COPY", f"Clipboard Copy: {state}", 1800)
        elif chosen == merge_pdf_act:
            self.merge_pdf_enabled = not self.merge_pdf_enabled
            state = "Merged PDF" if self.merge_pdf_enabled else "Separate PDFs"
            self._show_temporary_status("📄 PDF MODE", state, 1800)
        elif chosen == del_action:
            self.replace_original = not self.replace_original
            mode_txt = "Replace Original: ON" if self.replace_original else "Keep Original: ON"
            self._show_temporary_status("⚙️ MODE", mode_txt, 1800)
        elif chosen == pin_action:
            self.is_pinned = not self.is_pinned
            flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
            if self.is_pinned:
                flags |= Qt.WindowType.WindowStaysOnTopHint
            self.setWindowFlags(flags)
            self.show()
        elif chosen == hide_action:
            self.hide()
        elif chosen == quit_action:
            QApplication.instance().quit()

    # ------------------------------------------------------------------
    # Direct Per-Button Drag & Drop Conversion
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.is_dragging_files = True
            self.drag_target_idx = self._hit_test_tile(event.position(), snap_nearest=True)
            self.update()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasUrls():
            target_idx = self._hit_test_tile(event.position(), snap_nearest=True)
            if target_idx != self.drag_target_idx:
                self.drag_target_idx = target_idx
                self.update()
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self.is_dragging_files = False
        self.drag_target_idx = None
        self.update()

    def dropEvent(self, event: QDropEvent) -> None:
        self.is_dragging_files = False
        target_idx = self._hit_test_tile(event.position(), snap_nearest=True)
        self.drag_target_idx = None

        if not event.mimeData().hasUrls() or target_idx is None:
            self.update()
            return

        event.acceptProposedAction()
        self.default_paste_idx = target_idx

        files = self._collect_image_files(event.mimeData().urls())
        if not files:
            self._show_temporary_status("⚠️ NO IMAGES", "Unsupported file type", 2400)
            return

        self._run_conversion_batch(files, target_idx)

    def _run_conversion_batch(self, files: list[Path], target_idx: int) -> None:
        label, target_ext, pil_format, _ = RADIAL_FORMATS[target_idx]
        self.active_flash_idx = target_idx
        self._flash_timer.start(900)

        # Measure original file sizes before conversion (in case replace_original deletes them)
        orig_bytes = sum(f.stat().st_size for f in files if f.exists())

        # Special Case: Merge 2+ images dropped onto PDF into one multi-page PDF
        if pil_format == "PDF" and len(files) >= 2 and self.merge_pdf_enabled:
            try:
                merged_out = convert_images_to_merged_pdf(
                    source_paths=files,
                    scale_preset=self.current_scale_preset,
                    replace_original=self.replace_original,
                )
                new_bytes = merged_out.stat().st_size if merged_out.exists() else 0
                self._copy_files_to_clipboard([merged_out])
                delta_str = format_size_delta(orig_bytes, new_bytes)
                self._show_temporary_status(
                    f"✓ {len(files)} PAGES MERGED",
                    delta_str or merged_out.name[:22],
                    3400,
                )
            except Exception as exc:  # noqa: BLE001
                self._show_temporary_status("❌ PDF FAILED", str(exc)[:22], 3000)
            return

        converted_paths: list[Path] = []
        errors: list[str] = []

        for file_path in files:
            try:
                out_path = convert_single_image(
                    source_path=file_path,
                    target_ext=target_ext,
                    pil_format=pil_format,
                    quality=self.quality,
                    scale_preset=self.current_scale_preset,
                    replace_original=self.replace_original,
                )
                converted_paths.append(out_path)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{file_path.name}: {exc}")

        if converted_paths and not errors:
            new_bytes = sum(p.stat().st_size for p in converted_paths if p.exists())
            delta_str = format_size_delta(orig_bytes, new_bytes)
            self._copy_files_to_clipboard(converted_paths)

            if len(converted_paths) == 1:
                self._show_temporary_status(
                    f"✓ {label} SAVED",
                    delta_str or converted_paths[0].name[:22],
                    3400,
                )
            else:
                self._show_temporary_status(
                    f"✓ {len(converted_paths)} → {label}",
                    delta_str or "Saved & copied",
                    3400,
                )
        elif converted_paths and errors:
            self._show_temporary_status(
                f"⚠️ {len(converted_paths)} OK / {len(errors)} ERR", errors[0][:20], 3000
            )
        else:
            self._show_temporary_status("❌ FAILED", errors[0][:22], 3000)

    def _collect_image_files(self, urls: Iterable[QUrl]) -> list[Path]:
        collected: list[Path] = []
        for url in urls:
            local_str = url.toLocalFile()
            if not local_str:
                continue
            path = Path(local_str)
            if path.is_file() and path.suffix.lower() in SUPPORTED_INPUT_EXTS:
                collected.append(path)
            elif path.is_dir():
                for child in sorted(path.iterdir()):
                    if child.is_file() and child.suffix.lower() in SUPPORTED_INPUT_EXTS:
                        collected.append(child)
        return collected


def main() -> None:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont("Segoe UI", 10))

    socket = QLocalSocket()
    socket.connectToServer(SINGLE_INSTANCE_KEY)
    if socket.waitForConnected(200):
        socket.write(b"SHOW")
        socket.waitForBytesWritten(200)
        socket.disconnectFromServer()
        sys.exit(0)

    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    server = QLocalServer()
    server.listen(SINGLE_INSTANCE_KEY)

    converter = RadialImageConverter()
    server.newConnection.connect(converter.bring_to_front)
    converter.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()