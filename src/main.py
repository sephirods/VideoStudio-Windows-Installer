#!/usr/bin/env python3
"""
VideoStudio Pro — Windows Desktop Native Entrypoint.

Modes:
  1. Normal launch (`VideoStudio.exe`): Starts local FastAPI backend on 127.0.0.1:<free_port>,
     opens native Windows Edge WebView2 window via `pywebview`, and registers a System Tray icon.
  2. Embedded CLI Script Runner (`VideoStudio.exe --run-script <script.py> [args...]`):
     Executes bundled CLI Python scripts offline without requiring external Python on the user's PC!
  3. Headless Check (`VideoStudio.exe --self-test`): Runs fast boot & health check for CI / installer verification.
"""
from __future__ import annotations

import os
from pathlib import Path
import runpy
import socket
import sys
import threading
import time
import webbrowser

# Ensure UTF-8 streams on Windows even in windowed/noconsole mode
for _stream_name in ("stdout", "stderr"):
    _st = getattr(sys, _stream_name, None)
    if _st is not None and hasattr(_st, "reconfigure"):
        try:
            _st.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _handle_embedded_script_mode() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] == "--run-script":
        from src.backend.app_paths import configure_bundled_binaries_path
        configure_bundled_binaries_path()

        script_file = Path(sys.argv[2]).resolve()
        script_dir = str(script_file.parent)
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)
        sys.argv = [str(script_file)] + sys.argv[3:]
        runpy.run_path(str(script_file), run_name="__main__")
        sys.exit(0)


_handle_embedded_script_mode()

import uvicorn  # noqa: E402
from src.backend.app_paths import bootstrap_workspace, get_resource_root, get_version_info, load_app_settings  # noqa: E402
from src.backend.api import app as fastapi_app  # noqa: E402


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_server_ready(port: int, timeout_sec: float = 8.0) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _start_tray_icon(url: str, window_ref: list) -> None:
    try:
        import pystray
        from PIL import Image, ImageDraw

        ico_path = get_resource_root() / "assets" / "videostudio.ico"
        if ico_path.exists():
            icon_img = Image.open(ico_path)
        else:
            icon_img = Image.new("RGBA", (64, 64), (15, 23, 42, 255))
            d = ImageDraw.Draw(icon_img)
            d.rounded_rectangle((8, 8, 56, 56), radius=14, fill=(99, 102, 241, 255))
            d.polygon([(26, 20), (26, 44), (46, 32)], fill=(255, 255, 255, 255))

        def _open_studio(icon, item):
            if window_ref:
                try:
                    window_ref[0].show()
                    window_ref[0].restore()
                    return
                except Exception:
                    pass
            webbrowser.open(url)

        def _quit_app(icon, item):
            icon.stop()
            os._exit(0)

        menu = pystray.Menu(
            pystray.MenuItem("Abrir VideoStudio Pro", _open_studio, default=True),
            pystray.MenuItem("Salir por completo", _quit_app),
        )
        tray = pystray.Icon("VideoStudioPro", icon_img, "VideoStudio Pro", menu)
        threading.Thread(target=tray.run, name="VideoStudioTray", daemon=True).start()
    except Exception:
        pass


def main() -> int:
    if "--self-test" in sys.argv:
        info = bootstrap_workspace(force_sync=True)
        ver = get_version_info()
        msg = (
            f"SELF_TEST_OK version={ver.get('version')} "
            f"offline_ffmpeg={info['binaries'].get('offline_bundled')} "
            f"ffmpeg={info['binaries'].get('ffmpeg_path')}"
        )
        st_file = os.environ.get("VIDEOSTUDIO_SELFTEST_FILE")
        if st_file:
            Path(st_file).write_text(msg, encoding="utf-8")
        if sys.stdout is not None:
            print(msg, flush=True)
        return 0

    bootstrap_workspace(force_sync=False)
    ver = get_version_info()
    port = int(os.environ.get("VIDEOSTUDIO_PORT") or _find_free_port())
    url = f"http://127.0.0.1:{port}"

    # Ensure static UI is mounted even if resource root resolved after import
    ui_dir = get_resource_root() / "src" / "ui"
    has_ui_mount = any(getattr(r, "name", "") == "ui" for r in fastapi_app.routes)
    if not has_ui_mount and ui_dir.exists():
        from fastapi.staticfiles import StaticFiles
        fastapi_app.mount("/", StaticFiles(directory=str(ui_dir), html=True), name="ui")

    server_cfg = uvicorn.Config(fastapi_app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(server_cfg)
    srv_thread = threading.Thread(target=server.run, name="VideoStudioAPIServer", daemon=True)
    srv_thread.start()
    _wait_server_ready(port)

    if "--headless-server" in sys.argv:
        print(f"SERVER_READY {url}", flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return 0

    window_holder: list = []
    _start_tray_icon(url, window_holder)

    try:
        import webview

        title = f"{ver.get('app_name', 'VideoStudio Pro')} v{ver.get('version', '1.0.0')}"
        win = webview.create_window(
            title=title,
            url=url,
            width=1360,
            height=860,
            min_size=(1060, 700),
            background_color="#090D16",
            text_select=True,
        )
        window_holder.append(win)

        def _on_closing():
            settings = load_app_settings()
            if settings.get("minimize_to_tray", False) and "--allow-tray-hide" in sys.argv:
                win.hide()
                return False
            return True

        win.events.closing += _on_closing
        webview.start(gui="edgechromium")
    except Exception:
        webbrowser.open(url)
        try:
            while srv_thread.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
