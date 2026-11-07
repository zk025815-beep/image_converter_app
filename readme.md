# ⚡ FloatConvert — Smart Drag-Activated Radial Neon Image & Document Converter

**FloatConvert** is a zero-latency, frameless floating desktop utility for Windows built with **Python**, **PyQt6**, **Pillow**, **PyMuPDF (`fitz`)**, **python-docx**, and **Win32 API (`ctypes`)**. It launches silently in **Inactive Mode** on startup, activates on demand with **`Ctrl + Alt + C`** (auto-deactivating after 5 minutes of idle time), pops up a circular neon radial UI in the center of your screen **only when you drag a supported image, PDF, or Word file**, and converts files in place with a live **`0% – 100%` circular neon progress indicator**.

## ✨ Key Features

* **Inactive by Default & 5-Minute Auto-Deactivation**: Starts silently in **Inactive Mode** when you boot your laptop so it never triggers unexpectedly. Pressing **`Ctrl + Alt + C`** manually enables Smart Drag Mode and starts a 5-minute inactivity countdown (`INACTIVITY_TIMEOUT_MS = 300,000 ms`) that resets on every conversion and automatically deactivates the tool after 5 minutes of idle time.
* **Supported-Format-Only Drag Probe**: Uses an imperceptible (`alpha = 2/255`) Win32 OLE drop-target probe under the cursor when a drag gesture starts (`>= 180ms` hold and `>= 45px` movement) in File Explorer or on the Desktop. The circular neon UI **only** appears if the dragged selection consists of supported image, `.pdf`, or `.docx`/`.doc` files—staying completely hidden when dragging unsupported files (`.mp4`, `.zip`, `.exe`, `.txt`, folders) or empty selection boxes.
* **7 Integrated Radial Format Tiles (`ICO`, `GIF`, `WEBP`, `JPG`, `PNG`, `PDF`, `WORD`)**:
  * **Image Conversion**: Drop one or more images onto `ICO`, `GIF`, `WEBP`, `JPG`, `PNG`, or `PDF`.
  * **1:1 PDF → Editable Word (`.docx`)**: Drop any `.pdf` onto **`WORD`** to reconstruct a fully editable Word document that preserves original fonts, sizes, colors, centered headers, underlined links, full-width horizontal section divider lines (`<w:pBdr>`), native hanging-indent bullet points, multi-column tab stops, tables, images, and single-page vertical spacing.
  * **Word → Print-Ready PDF (`.pdf`)**: Drop any `.docx` or `.doc` file onto **`PDF`** to generate a print-ready PDF using native Word COM (`ExportAsFixedFormat`) or the built-in thread-safe `PyMuPDF` multi-page ISO A4 vector PDF renderer.
  * **PDF → High-DPI Images**: Drop any `.pdf` onto `JPG`, `PNG`, or `WEBP` to export its pages as crisp images.
* **Print-Grade ISO A4 Image-to-PDF Layout (`compose_a4_pdf_page`)**: Converting single or multiple images to **PDF** places each image onto a standardized **ISO A4 page (`210 mm × 297 mm`)**, automatically selects **Portrait** (`height >= width`) or **Landscape** (`width > height`) orientation per image after EXIF rotation, maintains uniform **`15 mm` white margins** on all four sides, and scales proportionally (`LANCZOS`) without stretching, cropping, or overflowing.
* **Live Numbered Percentage Circular Loading Indicator (`0% – 100%`)**: All conversions run asynchronously on a background `QThread` (`ConversionWorkerThread`) while the Center Well displays a proportional neon progress ring, rotating comet highlight, and live **`0% – 100%` numeric counter**.
* **Two Ways to Adjust Compression Quality & Resolution Scale**:
  * **Center Well "Hold & Tweak" Mode**: Drop files inside the center circle instead of on a format tile to stage them and keep the wheel open. Adjust the curved bottom **Quality Dial (`5%–100%`)** or click the **`📐 Scale` badge (`Original`, `1080p`, `50%`)**, then click any format tile to convert and auto-close.
  * **Mid-Drag Keyboard Shortcuts**: While dragging files over the wheel, tap **`Space`** to cycle resolution scaling (`Original → 1080p → 50%`) or tap **`Up / Down Arrow`** to adjust quality (`±5%`) on the fly before dropping.
* **Full iPhone `.HEIC` / `.HEIF` Support**: Powered by `pillow-heif`, enabling direct conversion of iPhone `.heic` photos into `JPG`, `PNG`, `WEBP`, `ICO`, `GIF`, `PDF`, or `WORD`.
* **File-Size Saved Readout & Auto-Clipboard Copy**: Displays the exact percentage and size reduction (e.g., `-78% • 1.4 MB saved`) and automatically copies converted output files (`CF_HDROP`) to the Windows Clipboard for immediate pasting (`Ctrl + V`).
* **Built-In Gumroad / Offline Pro Licensing**: Includes `LicenseActivationDialog` and `verify_and_save_license_key()` (`ENFORCE_PRO_LICENSE` toggle + Gumroad `/v2/licenses/verify` API + offline master keys) for commercial distribution.

## 🎮 Controls, Hotkeys & Interactions

| Action / Shortcut | Function |
| :--- | :--- |
| **`Ctrl + Alt + C`** | **Activate (Arm)** Smart Drag Mode silently and start the 5-minute inactivity countdown (System Tray icon glows neon purple/cyan). |
| **`Ctrl + Alt + D`** | **Disable (Disarm)** Smart Drag Mode immediately (System Tray icon turns dim gray; also triggers automatically after 5 minutes idle). |
| **Drag Supported File → Format Tile** | Converts the dragged image, `.pdf`, or `.docx`/`.doc` to the target format in the same folder with a live `0%–100%` progress ring, copies to clipboard, and auto-hides. |
| **Drag Supported File → Center Well** | Stages the file(s) in **Hold & Tweak** mode and keeps the wheel open so you can adjust Quality and Scale with your mouse before clicking a format tile. |
| **`Space` (While Dragging)** | Cycles resolution scaling presets (`Original` → `1080p` → `50%`) live during a drag. |
| **`↑` / `↓` Arrows (While Dragging)** | Increases or decreases compression quality (`±5%`, range `5%–100%`) live during a drag. |
| **Mouse Scroll Wheel** | Adjusts the curved bottom Quality Dial in `5%` increments when hovering over the wheel. |
| **Left-Click System Tray Icon** | Manually opens/pins or hides the radial wheel on screen at any time. |
| **Right-Click on Wheel / Tray Icon** | Opens the settings menu (Pro License Activation, Resolution Scale, Auto-Copy to Clipboard, Merged vs. Separate A4 PDF, Delete Original After Convert, Disable, Quit). |

## 🖼️ Supported Formats

| Direction | Formats Supported |
| :--- | :--- |
| **Supported Input Formats** | **Images**: `.heic`, `.heif`, `.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`, `.gif`, `.tiff`, `.tif`, `.ico`, `.ppm`, `.pgm`, `.jfif`, `.avif`<br>**Documents**: `.pdf`, `.docx`, `.doc` |
| **Output Formats (7 Radial Tiles)** | **ICO** (`.ico`), **GIF** (`.gif`), **WEBP** (`.webp`), **JPG** (`.jpg`), **PNG** (`.png`), **PDF** (`.pdf` — ISO A4 single/merged images or Word-to-PDF), **WORD** (`.docx` — 1:1 editable PDF-to-Word or Image-to-Word) |

## 🛠️ Installation & Local Development

### 1. Prerequisites

* **OS**: Windows 10 or Windows 11
* **Python**: Python 3.10+ (Python 3.12 recommended)

### 2. Install Dependencies

```powershell
pip install PyQt6 Pillow pillow-heif PyMuPDF pdf2docx python-docx pdfplumber pypdf pyinstaller
```

### 3. Run from Source

```powershell
python image_converter_app.py
```

## 📦 Building the Fast Standalone Executable (`--onedir`)

To avoid the startup unpacking delay of `--onefile`, build FloatConvert using PyInstaller's `--onedir` mode in your Python 3.12 environment:

```powershell
cd "C:\Personal projects\image_converter_app"
Stop-Process -Name "image_converter_app" -Force -ErrorAction SilentlyContinue

& "C:\Users\Ghulam-Hur\AppData\Local\Programs\Python\Python312\python.exe" -m pip install PyQt6 Pillow pillow-heif PyMuPDF pdf2docx python-docx pdfplumber pypdf pyinstaller

& "C:\Users\Ghulam-Hur\AppData\Local\Programs\Python\Python312\python.exe" -m PyInstaller --noconfirm --noconsole --onedir --clean --collect-all pillow_heif --collect-all docx --collect-all pdf2docx --collect-all fitz --exclude-module matplotlib --exclude-module pandas --exclude-module scipy --exclude-module torch --exclude-module IPython --exclude-module pytest image_converter_app.py

Start-Process "C:\Personal projects\image_converter_app\dist\image_converter_app\image_converter_app.exe"
```

The compiled application is generated inside `dist\image_converter_app\image_converter_app.exe` alongside its `_internal\` dependencies folder.

## 🚀 Windows Startup & Shortcut Setup

Run this PowerShell snippet once to register **FloatConvert** in the Windows Start Menu and launch it automatically in **Inactive Stealth Mode** when you sign in to Windows:

```powershell
$TargetExe = "C:\Personal projects\image_converter_app\dist\image_converter_app\image_converter_app.exe"
$WorkDir   = "C:\Personal projects\image_converter_app\dist\image_converter_app"
$WshShell  = New-Object -ComObject WScript.Shell

# Create Start Menu Shortcut
$StartMenuPath = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\FloatConvert.lnk"
$Shortcut = $WshShell.CreateShortcut($StartMenuPath)
$Shortcut.TargetPath = $TargetExe
$Shortcut.WorkingDirectory = $WorkDir
$Shortcut.Hotkey = ""
$Shortcut.Description = "FloatConvert - Smart Drag-Activated Radial Image & Document Converter"
$Shortcut.Save()

# Copy to Windows Startup Folder for automatic background launch on boot (starts Inactive by default)
Copy-Item $StartMenuPath "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\FloatConvert.lnk" -Force
```

## 🏗️ Project Architecture & Technical Documentation

```text
C:\Personal projects\image_converter_app\
├── image_converter_app.py        # Complete application source code (UI, Win32 hooks, A4 PDF & 1:1 Word engines)
├── FloatConvert_Installer.iss    # Inno Setup script for building FloatConvert_Setup_v1.0.exe
├── README.md                     # Project documentation
└── dist\
    └── image_converter_app\
        ├── _internal\            # Pre-extracted Qt6, Pillow, PyMuPDF, python-docx & libheif binaries
        └── image_converter_app.exe  # Fast-launching Windows executable
```

### Internal Architecture Breakdown

1. **Single-Instance IPC Guard (`QLocalServer` / `QLocalSocket`)**:
   * Ensures only one background process of FloatConvert runs at any time via `FloatConvert_Radial_SingleInstance_Server`.
2. **Inactive-on-Boot Lifecycle & 5-Minute Auto-Off Timer (`_inactivity_timer`)**:
   * Starts with `self.is_armed = False` and `_drag_watch_timer` stopped (`0%` CPU). Pressing `Ctrl + Alt + C` arms the poller and starts a 5-minute `QTimer` that resets on every user interaction and automatically calls `disable_armed_mode()` after 5 minutes idle.
3. **Imperceptible OLE Format Probe (`_start_invisible_drag_probe`)**:
   * Because Windows 11 DWM skips `0.0`-opacity windows during `DoDragDrop` hit-testing, FloatConvert paints an imperceptible `alpha = 2/255` (`0.7%` opacity) probe surface under the cursor for a single frame once a drag exceeds `180ms` and `45px`.
   * When `dragEnterEvent` fires (`< 15ms`), `_collect_supported_files` verifies that all dragged items belong to `SUPPORTED_INPUT_EXTS`. Supported files snap the wheel to the center of the screen at `100%` opacity; unsupported files abort the probe immediately so the wheel stays hidden.
4. **1:1 Precision PDF-to-Word Reconstruction Engine (`convert_pdf_to_word_docx`)**:
   * Extracts exact page dimensions, margins, visual horizontal text lines (clustered by vertical midpoint `ymid`), font families, point sizes, RGB colors, hyperlink underlines, and full-width horizontal vector rules (`_extract_page_layout_fitz` / `_extract_page_layout_pdfplumber`).
   * Reconstructs native Word paragraphs (`_build_precision_docx_from_pages`) with full-width bottom borders (`<w:pBdr><w:bottom .../>`), true hanging-indent bullets (`left_indent` + negative `first_line_indent` + tab stops), multi-column tab stops, and compensated vertical leading (`0.22 × font_size`) so single-page resumes and documents fit on a single page in Word.
   * Automatically routes multi-cell grid tables through `pdf2docx` followed by `_repair_pdf2docx_xml` (which unwraps nested `<w:r><w:hyperlink>` tags and removes artificial right indents).
5. **ISO A4 PDF Composer & Thread-Safe Word-to-PDF Engine (`compose_a4_pdf_page`, `convert_word_to_pdf_file`)**:
   * Normalizes all image-to-PDF conversions onto `210 mm × 297 mm` ISO A4 canvases (auto Portrait/Landscape) with `15 mm` uniform margins and centered `LANCZOS` scaling.
   * Converts Word documents to PDF on a background `QThread` using `powershell -STA` Word COM (`ExportAsFixedFormat`) or `PyMuPDF` (`fitz.Story` / `insert_htmlbox`) with zero main-thread blocking.

## 👤 Author

**Zeeshan Khan**