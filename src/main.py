#!/usr/bin/env python3
"""
VideoStudio Pro — Windows Desktop Native Entrypoint.

CRITICAL WINDOWS GUI GUARANTEES:
  1. Redirects `sys.stdout` and `sys.stderr` BEFORE any imports when running in PyInstaller
     `--windowed` mode (where both are `None`), preventing `uvicorn` / `logging` `.isatty()` crashes.
  2. Sets explicit Windows `AppUserModelID` + Win32 `WM_SETICON` so the taskbar, window titlebar,
     and shortcuts always display the official VideoStudio Pro icon.
  3. Supports `--smoke-gui` to verify full end-to-end startup (FastAPI + Uvicorn + Edge WebView2 DOM render)
     on the actual compiled `.exe` before releasing any installer.
"""
from __future__ import annotations

import ctypes
import io
import os
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser

_IS_EMBEDDED_SCRIPT = len(sys.argv) >= 3 and sys.argv[1] == "--run-script"


def _install_silent_windows_subprocesses() -> None:
    """
    Suppresses 100% of flashing black CMD/conhost windows on Windows whenever VideoStudio Pro
    or any `--run-script` child worker invokes console tools (ffmpeg, ffprobe, yt-dlp, nvidia-smi,
    schtasks, Playwright driver node.exe, etc.).

    Win32 `CREATE_NO_WINDOW` (0x08000000) ONLY affects console-subsystem binaries and is ignored
    by Windows for GUI-subsystem binaries (Explorer, Chromium login window, Inno Setup updater),
    and must not be combined with `DETACHED_PROCESS` or `CREATE_NEW_CONSOLE`.
    """
    if not sys.platform.startswith("win"):
        return
    if getattr(subprocess.Popen, "_vs_silent_patched", False):
        return

    _orig_popen_init = subprocess.Popen.__init__
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    create_new_console = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010)
    detached_process = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)

    def _silent_popen_init(self, *args, **kwargs):
        flags = int(kwargs.get("creationflags") or 0)
        if not (flags & (create_new_console | detached_process)):
            kwargs["creationflags"] = flags | create_no_window
            if kwargs.get("stdin") is None:
                kwargs["stdin"] = subprocess.DEVNULL
        _orig_popen_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _silent_popen_init  # type: ignore[method-assign]
    subprocess.Popen._vs_silent_patched = True  # type: ignore[attr-defined]


_install_silent_windows_subprocesses()


def _ensure_safe_stdio() -> Path:
    """
    In PyInstaller --windowed mode on Windows, sys.stdout and sys.stderr are None.
    Attach a real UTF-8 log file stream (whose .isatty() returns False) BEFORE any 3rd-party imports.
    """
    roaming = os.environ.get("VIDEOSTUDIO_APPDATA_DIR") or os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    log_dir = Path(roaming) / ("logs" if os.environ.get("VIDEOSTUDIO_APPDATA_DIR") else "VideoStudio/logs")
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "videostudio.log"
        stream = open(log_file, "a", encoding="utf-8", errors="replace", buffering=1)
    except Exception:
        log_file = Path("videostudio.log")
        stream = io.StringIO()  # type: ignore[assignment]

    if sys.stdin is None:
        try:
            sys.stdin = open(os.devnull, "r", encoding="utf-8")
        except Exception:
            sys.stdin = io.StringIO("")  # type: ignore[assignment]

    if sys.stdout is None:
        sys.stdout = stream
    elif hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if sys.stderr is None:
        sys.stderr = stream
    elif hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    return log_file


_APP_LOG_FILE = _ensure_safe_stdio()


def _install_friendly_crash_dialog() -> None:
    def _hook(exc_type, exc_val, exc_tb):
        details = "".join(traceback.format_exception(exc_type, exc_val, exc_tb))
        try:
            if sys.stderr:
                sys.stderr.write(f"\n[CRASH] {details}\n")
                sys.stderr.flush()
        except Exception:
            pass
        if (
            sys.platform.startswith("win")
            and not _IS_EMBEDDED_SCRIPT
            and "--smoke-gui" not in sys.argv
            and "--self-test" not in sys.argv
            and "--smoke-scripts" not in sys.argv
        ):
            msg = (
                "Ocurrió un problema inesperado al iniciar VideoStudio Pro.\n\n"
                f"Detalle técnico registrado en:\n{_APP_LOG_FILE}\n\n"
                f"Resumen: {exc_val}"
            )
            ctypes.windll.user32.MessageBoxW(0, msg, "VideoStudio Pro — Aviso", 0x10)

    sys.excepthook = _hook


if not _IS_EMBEDDED_SCRIPT:
    _install_friendly_crash_dialog()


def _set_windows_app_id() -> None:
    if sys.platform.startswith("win"):
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("VideoStudio.Pro.Desktop.1.0")
        except Exception:
            pass


def _handle_embedded_script_mode() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] == "--run-script":
        exit_code = 0
        try:
            from src.backend.app_paths import configure_bundled_binaries_path
            configure_bundled_binaries_path()

            script_file = Path(sys.argv[2]).resolve()
            script_dir = str(script_file.parent)
            if script_dir not in sys.path:
                sys.path.insert(0, script_dir)
            sys.argv = [str(script_file)] + sys.argv[3:]
            runpy.run_path(str(script_file), run_name="__main__")
        except SystemExit as se:
            exit_code = se.code if isinstance(se.code, int) else (1 if se.code else 0)
        except BaseException:
            traceback.print_exc(file=sys.stderr)
            exit_code = 1
        finally:
            try:
                if sys.stdout:
                    sys.stdout.flush()
                if sys.stderr:
                    sys.stderr.flush()
            except Exception:
                pass
        os._exit(exit_code)


_handle_embedded_script_mode()
_set_windows_app_id()

import uvicorn  # noqa: E402
from src.backend.app_paths import (  # noqa: E402
    bootstrap_workspace,
    get_appdata_dir,
    get_install_root,
    get_resource_root,
    get_version_info,
    load_app_settings,
)
from src.backend.api import app as fastapi_app  # noqa: E402


def _locate_icon_path() -> Path | None:
    candidates = [
        get_install_root() / "videostudio.ico",
        get_install_root() / "assets" / "videostudio.ico",
        get_resource_root() / "assets" / "videostudio.ico",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _apply_win32_window_icon(title_text: str, ico_path: Path | None) -> None:
    if not sys.platform.startswith("win") or not ico_path or not ico_path.exists():
        return
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, title_text)
        if not hwnd:
            return
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        hicon_big = user32.LoadImageW(None, str(ico_path), IMAGE_ICON, 64, 64, LR_LOADFROMFILE)
        hicon_small = user32.LoadImageW(None, str(ico_path), IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        if hicon_big:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
        if hicon_small:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
    except Exception:
        pass


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_server_ready(port: int, timeout_sec: float = 10.0) -> bool:
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

        ico_path = _locate_icon_path()
        if ico_path and ico_path.exists():
            icon_img = Image.open(ico_path)
        else:
            icon_img = Image.new("RGBA", (64, 64), (67, 56, 202, 255))
            d = ImageDraw.Draw(icon_img)
            d.polygon([(24, 18), (24, 46), (46, 32)], fill=(255, 255, 255, 255))

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
            pystray.MenuItem("Cerrar aplicación", _quit_app),
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
        print(msg, flush=True)
        return 0

    bootstrap_workspace(force_sync=False)
    ver = get_version_info()
    port = int(os.environ.get("VIDEOSTUDIO_PORT") or _find_free_port())
    url = f"http://127.0.0.1:{port}"

    ui_dir = get_resource_root() / "src" / "ui"
    has_ui_mount = any(getattr(r, "name", "") == "ui" for r in fastapi_app.routes)
    if not has_ui_mount and ui_dir.exists():
        from fastapi.staticfiles import StaticFiles
        fastapi_app.mount("/", StaticFiles(directory=str(ui_dir), html=True), name="ui")

    # CRITICAL: log_config=None guarantees Uvicorn never calls DefaultFormatter / sys.stderr.isatty()
    server_cfg = uvicorn.Config(
        fastapi_app,
        host="127.0.0.1",
        port=port,
        log_config=None,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(server_cfg)
    srv_thread = threading.Thread(target=server.run, name="VideoStudioAPIServer", daemon=True)
    srv_thread.start()
    if not _wait_server_ready(port):
        raise RuntimeError(f"El servidor local no pudo iniciar en el puerto {port}.")

    if "--headless-server" in sys.argv:
        print(f"SERVER_READY {url}", flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return 0

    is_smoke_gui = "--smoke-gui" in sys.argv
    window_holder: list = []
    if not is_smoke_gui:
        _start_tray_icon(url, window_holder)

    ico_path = _locate_icon_path()
    title = f"{ver.get('app_name', 'VideoStudio Pro')} v{ver.get('version', '1.0.0')}"

    try:
        import webview

        win = webview.create_window(
            title=title,
            url=url,
            width=1400,
            height=880,
            min_size=(1100, 720),
            background_color="#070B14",
            text_select=True,
            hidden=is_smoke_gui,
        )
        window_holder.append(win)

        def _on_shown():
            time.sleep(0.15)
            _apply_win32_window_icon(title, ico_path)

        win.events.shown += _on_shown

        if is_smoke_gui:
            def _smoke_runner():
                # Wait for real HTML + JS bootstrap to finish inside Edge WebView2!
                deadline = time.time() + 12.0
                rendered_title = ""
                has_wizard = False
                while time.time() < deadline:
                    try:
                        rendered_title = win.evaluate_js("document.title") or ""
                        has_wizard = bool(win.evaluate_js("!!document.getElementById('topVersionBadge') && document.getElementById('topVersionBadge').textContent.includes('v')"))
                        if rendered_title and has_wizard:
                            break
                    except Exception:
                        pass
                    time.sleep(0.25)

                out_path = os.environ.get("VIDEOSTUDIO_SMOKE_GUI_FILE")
                if out_path and rendered_title and has_wizard:
                    Path(out_path).write_text(
                        f"SMOKE_GUI_OK title={rendered_title} icon={ico_path is not None}",
                        encoding="utf-8",
                    )
                time.sleep(0.3)
                win.destroy()

            webview_storage = get_appdata_dir() / "webview_cache"
            webview_storage.mkdir(parents=True, exist_ok=True)
            webview.start(
                func=_smoke_runner,
                gui="edgechromium",
                private_mode=False,
                storage_path=str(webview_storage),
                icon=str(ico_path) if ico_path else None,
            )
            return 0

        webview_storage = get_appdata_dir() / "webview_cache"
        webview_storage.mkdir(parents=True, exist_ok=True)
        webview.start(
            gui="edgechromium",
            private_mode=False,
            storage_path=str(webview_storage),
            icon=str(ico_path) if ico_path else None,
        )
    except Exception as e:
        if is_smoke_gui:
            raise RuntimeError(f"Fallo al abrir ventana nativa Edge WebView2: {e}") from e
        webbrowser.open(url)
        try:
            while srv_thread.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
