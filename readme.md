# ⚡ FloatConvert — Smart Drag-Activated Radial Neon Image Converter

**FloatConvert** is a zero-latency, frameless floating desktop utility for Windows built with **Python**, **PyQt6**, **Pillow**, and **Win32 API (`ctypes`)**. It stays completely invisible in stealth background mode until you start dragging an image in File Explorer or on your Desktop, pops up a circular neon radial UI in the center of your screen (`0ms`), converts dropped images directly inside their original folder, and automatically disappears once the conversion finishes.

## ✨ Key Features

- **Zero-Latency Stealth Drag-Sense Mode**: Runs silently in the background with `0%` idle CPU usage and pre-mapped GPU memory (`WS_EX_LAYERED | WS_EX_TRANSPARENT`). Hovering or clicking to select files never triggers the UI—it only appears in the center of your screen when you actively hold and drag an image (`>= 180ms` hold and `>= 45px` drag distance).
- **Direct Per-Button Drag & Drop**: Six 3D beveled radial format tiles (**ICO**, **GIF**, **WEBP**, **JPG**, **PNG**, **PDF**) act as individual drop targets. Dropping one or more images onto a tile converts them in place inside the source folder and auto-hides the wheel.
- **Two Ways to Adjust Compression Quality & Resolution Scale**:
  - **Center Well "Hold & Tweak" Mode**: Drop an image inside the center circle instead of on a format tile to stage the file and keep the wheel open. Use your mouse to drag the curved bottom **Quality Dial (`5%–100%`)** or click the **`📐 Scale` badge (`Original`, `1080p`, `50%`)**, then click any format button to convert and auto-close.
  - **Mid-Drag Keyboard Shortcuts**: While dragging an image over the wheel, tap **`Space`** to cycle resolution scaling (`Original → 1080p → 50%`) or tap **`Up / Down Arrow`** to adjust quality (`±5%`) on the fly before releasing the mouse button.
- **Full iPhone `.HEIC` / `.HEIF` Support**: Powered by `pillow-heif`, allowing direct drag-and-drop conversion of iPhone `.heic` photos into `JPG`, `PNG`, `WEBP`, `ICO`, `GIF`, or `PDF`.
- **Multi-Image to Single Merged PDF**: Dropping 2 or more images onto the **PDF** tile automatically merges them into a single multi-page `<first_image>_merged.pdf` file in the same folder.
- **File-Size Saved Readout & Auto-Clipboard Copy**: Displays the exact percentage and megabytes/kilobytes saved (e.g., `-78% • 1.4 MB saved`) in the center well and automatically copies the converted file (`CF_HDROP`) to the Windows Clipboard for immediate pasting (`Ctrl + V`) into WhatsApp, Discord, or video editors.

## 🎮 Controls, Hotkeys & Interactions

| Action / Shortcut | Function |
| :--- | :--- |
| **`Ctrl + Alt + C`** | **Activate (Arm)** Smart Drag Mode silently in the background (System Tray icon glows neon purple/cyan). |
| **`Ctrl + Alt + D`** | **Disable (Disarm)** Smart Drag Mode completely so dragging files never triggers the UI (System Tray icon turns dim gray). |
| **Drag Image → Format Tile** | Immediately converts the image(s) to that format in the same folder, flashes the size-saved badge, and auto-hides. |
| **Drag Image → Center Well** | Stages the image(s) in **Hold & Tweak** mode and keeps the wheel open so you can adjust Quality and Scale with your mouse before clicking a format tile. |
| **`Space` (While Dragging)** | Cycles resolution scaling presets (`Original` → `1080p` → `50%`) live during a drag. |
| **`↑` / `↓` Arrows (While Dragging)** | Increases or decreases compression quality (`±5%`, range `5%–100%`) live during a drag. |
| **Mouse Scroll Wheel** | Adjusts the curved bottom Quality Dial in `5%` increments when hovering over the wheel. |
| **Left-Click System Tray Icon** | Manually pins/unpins the wheel on screen anytime you want to adjust settings without dragging a file. |
| **Right-Click on Wheel / Tray Icon** | Opens the quick settings menu (Resolution Scale, Auto-Copy to Clipboard, Merged vs. Separate PDF, Delete Original After Convert, Quit). |

## 🖼️ Supported Formats

| Direction | Formats Supported |
| :--- | :--- |
| **Input Formats** | `.heic`, `.heif`, `.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`, `.gif`, `.tiff`, `.tif`, `.ico`, `.ppm`, `.pgm`, `.jfif`, `.avif` |
| **Output Formats (Radial Tiles)** | **WEBP** (`.webp`), **PNG** (`.png`), **JPG** (`.jpg`), **ICO** (`.ico`), **GIF** (`.gif`), **PDF** (`.pdf` — single or multi-page merged) |

## 🛠️ Installation & Local Development

### 1. Prerequisites
- **OS**: Windows 10 or Windows 11
- **Python**: Python 3.10+

### 2. Install Dependencies
```powershell
pip install PyQt6 Pillow pillow-heif pyinstaller
```

### 3. Run from Source
```powershell
python image_converter_app.py
```

## 📦 Building the Fast Standalone Executable (`--onedir`)

To avoid the startup unpacking delay of `--onefile`, build FloatConvert using PyInstaller's `--onedir` mode and exclude unused heavy scientific libraries:

```powershell
cd "C:\Personal projects\image_converter_app"
taskkill /F /IM image_converter_app.exe /T 2>$null

pyinstaller --noconfirm --noconsole --onedir --collect-all pillow_heif --exclude-module numpy --exclude-module pandas --exclude-module matplotlib --exclude-module torch --exclude-module scipy image_converter_app.py
```

The compiled application is generated inside `dist\image_converter_app\image_converter_app.exe` alongside its `_internal\` dependencies folder.

## 🚀 Windows Startup & Shortcut Setup

Run this PowerShell snippet once to register **FloatConvert** in the Windows Start Menu and set it to launch automatically in Stealth Armed Mode when you sign in to Windows (with `$Shortcut.Hotkey = ""` so Windows Explorer never overrides the native `<1ms` Win32 hotkey):

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
$Shortcut.Description = "FloatConvert - Smart Drag-Activated Radial Image Converter"
$Shortcut.Save()

# Copy to Windows Startup Folder for automatic background launch on boot
Copy-Item $StartMenuPath "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\FloatConvert.lnk" -Force
```

## 🏗️ Project Architecture & Technical Documentation

```text
C:\Personal projects\image_converter_app\
├── image_converter_app.py        # Complete application source code (UI, Win32 hooks, conversion engine)
├── README.md                     # Project documentation
└── dist\
    └── image_converter_app\
        ├── _internal\            # Pre-extracted Qt6, Pillow, and libheif runtime binaries
        └── image_converter_app.exe  # Fast-launching Windows executable
```

### Internal Architecture Breakdown
1. **Single-Instance IPC Guard (`QLocalServer` / `QLocalSocket`)**:
   - Ensures only one background process of FloatConvert can run at any time using the named pipe `FloatConvert_Radial_SingleInstance_Server`. Launching a second instance signals the existing instance to arm silently and exits cleanly.
2. **Kernel-Level Hotkey Thread (`GlobalHotkeyThread`)**:
   - Runs a dedicated daemon `QThread` calling `ctypes.windll.user32.RegisterHotKey` and `GetMessageW` for **`Ctrl + Alt + C`** (Activate) and **`Ctrl + Alt + D`** (Disable). Because `GetMessageW` blocks at the OS kernel level, it consumes `0%` CPU while responding in `< 1ms`.
3. **Zero-Reload Stealth Window Management (`_set_wheel_visible` & `_set_win32_click_through`)**:
   - Calling standard `hide()` and `show()` on translucent windows forces Windows DWM to deallocate and recreate the GPU surface. FloatConvert initializes at `0.0` opacity prior to `show()`, keeps the window mapped permanently in VRAM, and toggles between `setWindowOpacity(0.0)` with Win32 extended style `WS_EX_LAYERED | WS_EX_TRANSPARENT` (`force=True` synced after DWM handle creation so it never flashes on first boot) and `setWindowOpacity(1.0)` centered on the active monitor.
4. **Smart Drag-Sense Poller (`_poll_mouse_drag_state`)**:
   - A lightweight `30ms` `QTimer` monitors `GetAsyncKeyState(VK_LBUTTON)` and checks if the mouse press originated inside a Windows Explorer or Desktop window (`CabinetWClass`, `ExploreWClass`, `Progman`, `WorkerW`, `#32770`).
   - To prevent false triggers when hovering or clicking to select files, the wheel only appears after the left mouse button is held continuously for `>= 180ms` and dragged `>= 45px`.
   - While the wheel is visible on screen, `_poll_mid_drag_shortcuts` reads edge-triggered `VK_SPACE`, `VK_UP`, and `VK_DOWN` states via `GetAsyncKeyState` so the user can change resolution scale and compression quality mid-drag even while File Explorer holds keyboard focus.
5. **Image Conversion & PDF Merging Engine (`convert_single_image`, `convert_images_to_merged_pdf`)**:
   - Registers `pillow_heif.register_heif_opener()` at startup for seamless `.heic` / `.heif` decoding.
   - Applies EXIF orientation correction (`ImageOps.exif_transpose`), optional Lanczos downscaling (`1080p` max dimension or `50%` dimensions), and automatic alpha-channel flattening onto a white RGB canvas when exporting transparent images to `JPG` or `PDF`.
   - Protects original files from accidental overwrite collisions by writing to temporary files or incrementing suffixes (`_1`, `_2`) unless **Delete Original After Convert** is explicitly enabled.

## 👤 Author

**Zeeshan Khan**
